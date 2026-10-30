#!/usr/bin/env python3
"""Small process fixtures for the opt-in DB experiment; no images or network."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / 'scripts/bluebuild/security-scan.py'
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64


def load():
    spec = importlib.util.spec_from_file_location('overlap_scanner', SCANNER)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    return scanner


def until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Fixture condition did not become true')


def running(pid):
    try:
        return Path('/proc/' + str(pid) + '/stat').read_text().split()[2] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        # procfs can report ESRCH if the process exits during open/read.
        return False


GRYPE = r'''
import json, os, pathlib, signal, subprocess, sys, time
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
cache = pathlib.Path(os.environ['GRYPE_DB_CACHE_DIR'])
args = sys.argv[1:]
with (root / 'events').open('a') as stream:
    stream.write(json.dumps({'args': args, 'cache': str(cache),
        'auto': os.environ.get('GRYPE_DB_AUTO_UPDATE'),
        'require': os.environ.get('GRYPE_DB_REQUIRE_UPDATE_CHECK')}) + '\n')
if args[:2] == ['db', 'update']:
    (root / 'update-started').touch()
    if os.environ.get('FIXTURE_CHILD') == 'true':
        child = subprocess.Popen([sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'])
        (root / 'db-child').write_text(str(child.pid))
    if os.environ.get('FIXTURE_FAIL') == 'true':
        sys.exit(17)
    if os.environ.get('FIXTURE_WAIT') == 'true':
        while not (root / 'inventory').exists():
            time.sleep(0.01)
    cache.joinpath('snapshot').write_text('one fresh snapshot')
    (root / 'update-complete').touch()
else:
    assert (root / 'update-complete').exists(), 'read before refresh succeeded'
    assert cache.joinpath('snapshot').read_text() == 'one fresh snapshot'
    assert os.environ['GRYPE_DB_AUTO_UPDATE'] == 'false'
    print('[]' if args[:2] == ['db', 'search'] else '{}')
'''


class ProcessStateTests(unittest.TestCase):
    def test_disappearing_process_is_not_running(self):
        for error in (FileNotFoundError(2, 'gone'), ProcessLookupError(3, 'gone')):
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, 'read_text', side_effect=error):
                    self.assertFalse(running(123))

    def test_other_read_errors_are_not_suppressed(self):
        for error in (PermissionError(13, 'denied'), OSError(5, 'I/O error')):
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, 'read_text', side_effect=error):
                    with self.assertRaises(type(error)):
                        running(123)

    def test_live_and_zombie_states(self):
        for state, expected in (('S', True), ('R', True), ('Z', False)):
            with self.subTest(state=state):
                with patch.object(Path, 'read_text', return_value=f'123 (fixture) {state} 1'):
                    self.assertEqual(running(123), expected)


class DatabaseOverlapTests(unittest.TestCase):
    def setUp(self):
        self.scanner = load()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        tool = self.root / 'grype'
        tool.write_text('#!' + sys.executable + '\n' + GRYPE)
        tool.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            'FIXTURE_ROOT': str(self.root), 'FIXTURE_WAIT': 'false',
            'FIXTURE_FAIL': 'false', 'FIXTURE_CHILD': 'false',
            'FINITE_SCANNER_BOUNDED': 'true', 'GRYPE_DB_AUTO_UPDATE': 'true',
            'GRYPE_DB_CACHE_DIR': str(self.root / 'old-cache'), 'GITHUB_SHA': 'b' * 40}))
        (self.root / 'old-cache').mkdir()
        (self.root / 'old-cache/snapshot').write_text('stale snapshot')

    def overlap(self):
        overlap = self.scanner.DatabaseOverlap(self.root)
        self.addCleanup(overlap.close)
        return overlap

    def events(self):
        return [json.loads(line) for line in (self.root / 'events').read_text().splitlines()]

    def test_one_frozen_private_snapshot_and_parent_environment_unchanged(self):
        overlap = self.overlap()
        overlap.wait()
        overlap.run(['grype', 'db', 'search'], self.root / 'coverage')
        overlap.run(['grype', 'sbom:fixture'], self.root / 'scan')
        events = self.events()
        self.assertEqual([e['args'] for e in events],
                         [['db', 'update'], ['db', 'search'], ['sbom:fixture']])
        self.assertEqual(len({e['cache'] for e in events}), 1)
        self.assertNotEqual(events[0]['cache'], os.environ['GRYPE_DB_CACHE_DIR'])
        self.assertTrue(all(e['auto'] == 'false' and e['require'] == 'true' for e in events))
        self.assertEqual(os.environ['GRYPE_DB_AUTO_UPDATE'], 'true')
        self.assertEqual((self.root / 'old-cache/snapshot').read_text(), 'stale snapshot')
        cache = Path(overlap.temporary.name)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
        overlap.close()
        self.assertFalse(cache.exists())

    def test_update_overlaps_inventory_and_is_joined_before_reads(self):
        os.environ['FIXTURE_WAIT'] = 'true'
        overlap = self.overlap()
        until(lambda: (self.root / 'update-started').exists())
        self.assertFalse(overlap.future.done())
        overlap.command([sys.executable, '-c',
                         'from pathlib import Path; Path(' + repr(str(self.root / 'inventory')) + ').touch()'])
        overlap.wait()
        overlap.run(['grype', 'db', 'search'])
        self.assertTrue((self.root / 'update-complete').exists())
        self.assertGreaterEqual(overlap.wait_seconds, 0)
        phase = next(p for p in self.scanner.PHASES if p['phase'] == 'database-update')
        self.assertTrue(phase['success'])
        self.assertTrue(phase['concurrentWithInventory'])

    def test_failed_update_is_fatal_even_when_old_cache_exists(self):
        os.environ['FIXTURE_FAIL'] = 'true'
        overlap = self.overlap()
        with self.assertRaises(subprocess.CalledProcessError) as error:
            overlap.wait()
        self.assertEqual(error.exception.returncode, 17)
        with self.assertRaises(subprocess.CalledProcessError):
            overlap.run(['grype', 'db', 'search'])
        self.assertEqual(len(self.events()), 1)

    def test_update_timeout_kills_descendant_and_is_not_ignored(self):
        os.environ.update(FIXTURE_WAIT='true', FIXTURE_CHILD='true')
        with patch.object(self.scanner, 'DATABASE_UPDATE_TIMEOUT', 0.3):
            overlap = self.overlap()
            until(lambda: (self.root / 'db-child').exists())
            child = int((self.root / 'db-child').read_text())
            with self.assertRaises(subprocess.TimeoutExpired):
                overlap.wait()
            until(lambda: not running(child))
            self.assertFalse(self.scanner.PHASES[-1]['success'])

    def test_foreground_timeout_kills_descendants(self):
        overlap = self.overlap()
        overlap.wait()
        pidfile = self.root / 'foreground-child'
        command = [sys.executable, '-c',
            'import subprocess,sys,time; from pathlib import Path; '
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"]); '
            'Path(' + repr(str(pidfile)) + ').write_text(str(p.pid)); time.sleep(120)']
        with self.assertRaises(subprocess.TimeoutExpired):
            overlap.command(command, timeout=0.3)
        until(lambda: not running(int(pidfile.read_text())))

    def test_background_failure_aborts_running_inventory_process_group(self):
        os.environ['FIXTURE_WAIT'] = 'true'
        overlap = self.overlap()
        pidfile = self.root / 'foreground-child'
        command = [sys.executable, '-c',
            'import os,signal,subprocess,sys,time; from pathlib import Path; '
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"]); '
            'Path(' + repr(str(pidfile)) + ').write_text(str(p.pid)); '
            'os.kill(' + str(overlap.process.pid) + ', signal.SIGTERM); time.sleep(120)']
        with self.assertRaises(subprocess.CalledProcessError):
            overlap.command(command)
        until(lambda: not running(int(pidfile.read_text())))

    def test_early_inventory_failure_cleans_up_update_and_restores_handlers(self):
        os.environ.update(FIXTURE_WAIT='true', FIXTURE_CHILD='true')
        previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        overlap = self.overlap()
        until(lambda: (self.root / 'db-child').exists())
        with self.assertRaises(subprocess.CalledProcessError):
            overlap.command([sys.executable, '-c', 'raise SystemExit(19)'])
        overlap.close()
        until(lambda: not running(int((self.root / 'db-child').read_text())))
        self.assertEqual({number: signal.getsignal(number) for number in previous}, previous)
        self.assertFalse(json.loads((self.root / 'database-overlap.json').read_text())['updateSucceeded'])

    def invoke_main(self, experimental=True, inventory_error=False):
        directory = self.root / 'evidence'
        argv = [str(SCANNER), IMAGE, str(directory), '--inventory-dir', str(self.root / 'inventory-input')]
        if experimental:
            argv.append('--experimental-database-overlap')
        def copy(_source, destination, _identity):
            if experimental:
                until(lambda: (self.root / 'update-started').exists())
            if inventory_error:
                raise ValueError('invalid inventory')
            (self.root / 'inventory').touch()
            (destination / 'sbom.syft.json').write_text('{}')
        with ExitStack() as context:
            context.enter_context(patch.object(sys, 'argv', argv))
            context.enter_context(patch.object(self.scanner.policy_module, 'load_policy',
                return_value={'mode': 'strict', 'coverageProbePackage': 'openssl'}))
            context.enter_context(patch.object(self.scanner.inventory_module, 'read', return_value={
                'schema': 1, 'status': 'authenticated-inventory-only', 'image': IMAGE,
                'newScanRequired': True, 'validationRevision': 'b' * 40}))
            context.enter_context(patch.object(self.scanner.inventory_module, 'verify', return_value={}))
            context.enter_context(patch.object(self.scanner.inventory_module, 'copy', side_effect=copy))
            context.enter_context(patch.object(self.scanner.policy_module, 'read_manifests', return_value={}))
            context.enter_context(patch.object(self.scanner.policy_module, 'inventory',
                return_value={'effective': 'fedora:44'}))
            policy = context.enter_context(patch.object(self.scanner.subprocess, 'call', return_value=0))
            with self.assertRaises(SystemExit) as status:
                self.scanner.main()
        return status.exception.code, directory, policy

    def test_main_join_precedes_coverage_scan_and_existing_policy(self):
        os.environ['FIXTURE_WAIT'] = 'true'
        code, directory, policy = self.invoke_main()
        self.assertEqual(code, 0)
        policy.assert_called_once()
        events = self.events()
        self.assertEqual(events[0]['args'], ['db', 'update'])
        self.assertEqual(events[1]['args'][:2], ['db', 'search'])
        self.assertTrue(events[2]['args'][0].startswith('sbom:'))
        self.assertEqual(len(events), 3)
        self.assertEqual(len({e['cache'] for e in events}), 1)
        result = json.loads((directory / 'database-overlap.json').read_text())
        self.assertTrue(result['updateSucceeded'])
        self.assertFalse(result['performanceImprovementProven'])

    def test_main_update_failure_never_reaches_policy(self):
        os.environ['FIXTURE_FAIL'] = 'true'
        code, directory, policy = self.invoke_main()
        self.assertEqual(code, 2)
        policy.assert_not_called()
        self.assertEqual(json.loads((directory / 'security-result.json').read_text())['status'], 'scanner-error')
        self.assertEqual(len(self.events()), 1)
        phases = json.loads((directory / 'phase-timings.json').read_text())['phases']
        self.assertTrue(any(p['phase'] == 'database-update' and not p['success'] for p in phases))

    def test_main_inventory_failure_cleans_up_and_never_scans(self):
        os.environ['FIXTURE_WAIT'] = 'true'
        code, directory, policy = self.invoke_main(inventory_error=True)
        self.assertEqual(code, 2)
        policy.assert_not_called()
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertFalse(Path(events[0]['cache']).exists())
        self.assertFalse(json.loads((directory / 'database-overlap.json').read_text())['updateSucceeded'])

    def test_opt_in_requires_bounded_wrapper(self):
        os.environ['FINITE_SCANNER_BOUNDED'] = 'false'
        code, directory, policy = self.invoke_main()
        self.assertEqual(code, 2)
        policy.assert_not_called()
        self.assertFalse((self.root / 'events').exists())
        self.assertIn('bounded hosted', (directory / 'security-result.json').read_text())

    def test_default_does_not_start_overlap(self):
        # Native serial behavior still selects the caller's existing DB cache.
        # Fake update expects auto-update disabled; this fixture records, not enforces it.
        code, directory, policy = self.invoke_main(experimental=False)
        self.assertEqual(code, 0)
        policy.assert_called_once()
        self.assertFalse((directory / 'database-overlap.json').exists())
        self.assertEqual({e['cache'] for e in self.events()}, {str(self.root / 'old-cache')})
        self.assertTrue((self.root / 'inventory').exists())

    def test_first_signal_during_final_cleanup_never_reaches_policy(self):
        original = self.scanner.DatabaseOverlap.close
        def cancel_during_close(overlap):
            if overlap.closed:
                return original(overlap)
            cleanup = overlap.temporary.cleanup
            def cancel_then_clean():
                os.kill(os.getpid(), signal.SIGTERM)
                cleanup()
            with patch.object(overlap.temporary, 'cleanup', side_effect=cancel_then_clean):
                return original(overlap)
        with patch.object(self.scanner.DatabaseOverlap, 'close', cancel_during_close):
            code, directory, policy = self.invoke_main()
        self.assertEqual(code, 2)
        policy.assert_not_called()
        self.assertIn('cancelled by signal', (directory / 'security-result.json').read_text())
        self.assertFalse(Path(self.events()[0]['cache']).exists())

    def test_updater_group_is_cleaned_once_even_after_repeated_close(self):
        with patch.object(self.scanner, 'stop_process_group', wraps=self.scanner.stop_process_group) as stop:
            overlap = self.overlap()
            overlap.wait()
            self.assertEqual(stop.call_count, 1)
            overlap.close()
            overlap.close()
            self.assertEqual(stop.call_count, 1)

    def test_cleanup_error_still_joins_worker_and_restores_signal_handlers(self):
        previous = signal.getsignal(signal.SIGTERM)
        overlap = self.overlap()
        overlap.wait()
        with patch.object(overlap, 'stop_update', side_effect=OSError('cleanup failed')), \
                patch.object(overlap.executor, 'shutdown', wraps=overlap.executor.shutdown) as shutdown:
            with self.assertRaisesRegex(OSError, 'cleanup failed'):
                overlap.close()
            shutdown.assert_called_once_with(wait=True)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.assertFalse(Path(overlap.temporary.name).exists())

    def test_second_update_command_is_rejected(self):
        overlap = self.overlap()
        overlap.wait()
        with self.assertRaisesRegex(ValueError, 'Only coverage and findings'):
            overlap.run(['grype', 'db', 'update'])
        self.assertEqual(len(self.events()), 1)

    def test_first_cancellation_during_foreground_cleanup_is_deferred(self):
        overlap = self.overlap()
        overlap.wait()
        original = self.scanner.stop_process_group
        completed = []
        def cleanup(process):
            os.kill(os.getpid(), signal.SIGTERM)
            original(process)
            completed.append(True)
        with patch.object(self.scanner, 'stop_process_group', side_effect=cleanup):
            with self.assertRaises(InterruptedError):
                overlap.command([sys.executable, '-c', 'pass'])
        self.assertEqual(completed, [True])

    def test_real_signals_stop_children_and_report_failure(self):
        for number in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=number):
                (self.root / 'db-child').unlink(missing_ok=True)
                (self.root / 'signal-ready').unlink(missing_ok=True)
                (self.root / 'cancelled').unlink(missing_ok=True)
                (self.root / 'foreground-pid').unlink(missing_ok=True)
                script = '''import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location('scanner', sys.argv[1])
scanner = importlib.util.module_from_spec(spec); spec.loader.exec_module(scanner)
root = pathlib.Path(sys.argv[2]); overlap = scanner.DatabaseOverlap(root)
try:
    while not (root / 'db-child').exists(): time.sleep(0.01)
    (root / 'signal-ready').touch()
    code = ('import os,signal,time; from pathlib import Path; '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        'Path(' + repr(str(root / 'foreground-pid')) + ').write_text(str(os.getpid())); time.sleep(120)')
    overlap.command([sys.executable, '-c', code])
except InterruptedError:
    (root / 'cancelled').touch()
finally:
    overlap.close()
'''
                process = subprocess.Popen([sys.executable, '-c', script, str(SCANNER), str(self.root)],
                    env={**os.environ, 'FIXTURE_WAIT': 'true', 'FIXTURE_CHILD': 'true'})
                try:
                    until(lambda: (self.root / 'signal-ready').exists() and (self.root / 'foreground-pid').exists())
                    process.send_signal(number)
                    time.sleep(0.05)
                    process.send_signal(number)  # Must not interrupt the one-second reaping grace.
                    self.assertEqual(process.wait(timeout=10), 0)
                    self.assertTrue((self.root / 'cancelled').exists())
                    until(lambda: not running(int((self.root / 'db-child').read_text())))
                    until(lambda: not running(int((self.root / 'foreground-pid').read_text())))
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
