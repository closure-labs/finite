#!/usr/bin/env python3
"""Versioned diagnostic consumers retain legacy and partial observations."""
from copy import deepcopy
import importlib.util
import io
import gzip
import os
import threading
import signal
import time
import subprocess
from unittest.mock import patch
import json
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import foundation_timings as timings
SPEC = importlib.util.spec_from_file_location('guest_timings', ROOT / 'scripts/bluebuild/guest-timings.py')
guest = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(guest)


def record(stage='nix-activities'):
    return {'schema': 2, 'kind': 'foundation-stage-timing', 'authorizesPublication': False,
            'stage': stage, 'startedAt': '2026-10-27T12:00:00Z', 'seconds': 0,
            'outcome': 'success', 'status': 0, 'details': {
                'logger': 'nix-internal-json-v1', 'evaluation': 'unknown', 'builds': 2, 'substitutions': 3,
                'buildSeconds': 10., 'substitutionSeconds': 8., 'overlapSeconds': 5.,
                'incomplete': False, 'rejectedRecords': 0}}


class BoundedGuestLogs(unittest.TestCase):
    def test_local_host_headroom_scope_and_boundaries(self):
        source = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        function = 'ensure_local_host_space() {' + source.split('ensure_local_host_space() {', 1)[1].split('\nbegin_stage()', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            docker = root / 'bin/docker'
            docker.write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["CALLS"]).write_text(json.dumps(sys.argv[1:]))\nsys.exit(int(os.environ.get("PRUNE_EXIT","0")))\n')
            docker.chmod(0o755)
            df = root / 'bin/df'
            df.write_text('#!' + sys.executable + '\nimport os,sys\nfrom pathlib import Path\nPath(os.environ["DF_CALLED"]).touch()\nprint("Available\\n  "+os.environ["AVAILABLE"])\nsys.exit(int(os.environ.get("DF_EXIT","0")))\n')
            df.chmod(0o755)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'CALLS': str(root / 'calls'), 'DF_CALLED': str(root / 'df-called'),
                   'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                   'GITHUB_REF': 'refs/heads/validation', 'AVAILABLE': '30000000000',
                   'LOCAL_VALIDATION': 'true', 'PRUNE_EXIT': '0', 'DF_EXIT': '0'}
            cases = [({}, True, True), ({'AVAILABLE': '30000000001'}, True, True),
                     ({'AVAILABLE': '29999999999'}, False, True), ({'AVAILABLE': '0'}, False, True),
                     ({'AVAILABLE': 'bad'}, False, True), ({'AVAILABLE': '9' * 30}, False, True),
                     ({'DF_EXIT': '1'}, False, True), ({'PRUNE_EXIT': '1'}, False, True),
                     ({'LOCAL_VALIDATION': 'false', 'GITHUB_REF': 'refs/heads/main'}, True, False),
                     ({'GITHUB_ACTIONS': 'false'}, False, False),
                     ({'GITHUB_REPOSITORY': 'other/repository'}, False, False),
                     ({'GITHUB_REF': ''}, False, False),
                     ({'GITHUB_REF': 'refs/heads/main'}, False, False)]
            for changes, accepted, pruned in cases:
                with self.subTest(changes=changes):
                    (root / 'calls').unlink(missing_ok=True)
                    (root / 'df-called').unlink(missing_ok=True)
                    result = subprocess.run(['bash', '-c', 'set -euo pipefail; ' + function +
                                             '\nlocal_validation=$LOCAL_VALIDATION; state=/tmp/fixture; ensure_local_host_space; echo initialization-reached'],
                                            env={**env, **changes}, text=True, capture_output=True)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    self.assertEqual('initialization-reached' in result.stdout, accepted)
                    self.assertEqual((root / 'calls').exists(), pruned)
                    if pruned:
                        self.assertEqual(json.loads((root / 'calls').read_text()),
                                         ['buildx', 'prune', '--builder', 'bluebuild', '--min-free-space', '30000000000', '--force'])
                    if changes.get('PRUNE_EXIT') == '1':
                        self.assertFalse((root / 'df-called').exists())

    def test_headroom_reclaims_only_completed_validation_builder_before_initialization(self):
        image = yaml.safe_load((ROOT / '.github/workflows/image.yml').read_text())
        builder = next(step for step in image['jobs']['build']['steps'] if step.get('name') == 'Set up the BlueBuild builder')
        self.assertEqual(builder['with']['name'], 'bluebuild')
        acceptance = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        self.assertIn('host_disk_snapshot before-initialize\nensure_local_host_space\nhost_disk_snapshot ready-initialize\nrun_functional initialize', acceptance)
        local = (ROOT / 'scripts/bluebuild/local-vm.sh').read_text()
        self.assertLess(local.index('>SHA256SUMS)'), local.index('rm -f -- "$work/candidate.tar"'))
        self.assertLess(local.index('rm -f -- "$work/candidate.tar"'), local.index('local-vm-acceptance'))

    def test_cancelled_collector_never_claims_complete_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'key').write_bytes(b'secret')
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/bluebuild/guest-timings.py'),
                str(root / 'timings.json'), '--log', str(root / 'home-init.log.gz'), '--secret', str(root / 'key')],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                process.stdin.write(b'partial secret output\npadding')
                process.stdin.flush()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if (root / 'home-init.log.gz').exists() and (root / 'home-init.log.gz').stat().st_size:
                        break
                    time.sleep(0.01)
                else:
                    self.fail('Collector did not capture partial output')
                process.terminate()
                self.assertEqual(process.wait(timeout=2), -signal.SIGTERM)
                self.assertNotIn(b'secret', gzip.decompress((root / 'home-init.log.gz').read_bytes()))
                receipt = root / 'home-init-log.json'
                self.assertTrue(not receipt.exists() or not json.loads(receipt.read_text())['captureComplete'])
            finally:
                process.stdin.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_short_pipe_line_is_available_before_producer_closes(self):
        reader, writer = os.pipe()
        result, ready = [], threading.Event()
        def consume():
            with os.fdopen(reader, 'rb') as stream:
                for line in guest.bounded_lines(stream, io.BytesIO(), b'secret'):
                    result.append(line)
                    ready.set()
        worker = threading.Thread(target=consume)
        worker.start()
        try:
            os.write(writer, b'FINITE_GUEST_STAGE startup-checks 1 0\n' + b'padding')
            self.assertTrue(ready.wait(2), 'Buffered pipe waited for EOF instead of emitting a stage')
            self.assertEqual(result[0], 'FINITE_GUEST_STAGE startup-checks 1 0\n')
        finally:
            os.close(writer)
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())


    def test_large_split_utf8_and_secret_lines_keep_full_sanitized_log(self):
        secret = b'secret-with-boundaries'
        content = b'x' * 65530 + secret + b'\n' + 'café'.encode() + b'\n'
        content += b'@nix ' + b'y' * 1000000 + b'\nFINITE_GUEST_STAGE home-init 1 19\n'
        raw = io.BytesIO()
        lines = list(guest.bounded_lines(io.BytesIO(content), raw, secret))
        self.assertEqual(raw.getvalue(), content.replace(secret, b'[REDACTED]'))
        self.assertTrue(all(len(line.encode()) < 17000 for line in lines))
        self.assertIn('café\n', lines)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'timings.json'
            console = io.StringIO()
            bounded = guest.BoundedConsole(console)
            rows = guest.collect(lines, output, bounded)
            bounded.finish(rows)
            self.assertEqual(rows[0]['status'], 19)
            self.assertNotIn(secret.decode(), console.getvalue())
            self.assertLess(len(console.getvalue()), 43000)

    def test_noisy_console_is_byte_bounded_and_preserves_failure_tail(self):
        console = io.StringIO()
        bounded = guest.BoundedConsole(console, clock=lambda: 0)
        for _ in range(10000):
            bounded.write('@nix progress\n')
            bounded.write('ordinary output\n')
        bounded.write('exact failing command stderr\n')
        bounded.write('@nix ' + json.dumps({'action': 'msg', 'level': 0, 'msg': 'actual Nix error'}) + '\n')
        bounded.finish([])
        self.assertLess(len(console.getvalue().encode()), 42000)
        self.assertNotIn('@nix', console.getvalue())
        self.assertIn('exact failing command stderr', console.getvalue())
        self.assertIn('actual Nix error', console.getvalue())

    def test_compressed_budget_preserves_guest_status_and_drains_stream(self):
        content = os.urandom(65536) + b'\nFINITE_GUEST_STAGE home-init 1 19\n'
        raw = io.BytesIO()
        capture = guest.CompressedCapture(raw, limit=100)
        with tempfile.TemporaryDirectory() as temporary:
            rows = guest.collect(guest.bounded_lines(io.BytesIO(content), capture, b'secret'),
                                 Path(temporary) / 'timings.json', io.StringIO())
        self.assertEqual(rows[-1]['status'], 19)
        self.assertEqual(capture.error, 'compressed-byte-budget')
        self.assertEqual(capture.input_bytes, len(content))
        self.assertLessEqual(len(raw.getvalue()), 100)

    def test_compressed_budget_keeps_valid_prefix_and_rejects_guest_success(self):
        raw = io.BytesIO()
        capture = guest.CompressedCapture(raw, limit=100)
        capture.write(b'first safe line\n')
        capture.write(os.urandom(65536))
        self.assertEqual(gzip.decompress(raw.getvalue()), b'first safe line\n')
        self.assertEqual(capture.error, 'compressed-byte-budget')
        self.assertLessEqual(len(raw.getvalue()), 100)
        script = (ROOT / 'scripts/bluebuild/vm-functional.sh').read_text()
        check = script.split("<<'CAPTURE'\n", 1)[1].split('\nCAPTURE', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'check.py').write_text(check)
            (root / 'receipt.json').write_text(json.dumps({'captureComplete': False, 'homeInitStatus': 0}))
            for guest_status, expected in ((0, 1), (19, 19)):
                result = subprocess.run(['bash', '-c',
                    'set -eo pipefail; (exit "$1") | cat; python3 "$2" "$3"',
                    'fixture', str(guest_status), str(root / 'check.py'), str(root / 'receipt.json')], capture_output=True)
                self.assertEqual(result.returncode, expected)
                if guest_status == 0:
                    self.assertIn(b'diagnostic evidence incomplete', result.stderr)

    def test_compressed_snapshot_redacts_again_and_rejects_partial_member(self):
        spec = importlib.util.spec_from_file_location('redactor', ROOT / 'scripts/bluebuild/redact-vm-logs.py')
        redactor = importlib.util.module_from_spec(spec); spec.loader.exec_module(redactor)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, destination = root / 'state', root / 'evidence'
            state.mkdir()
            path = state / 'home-init.log.gz'
            path.write_bytes(gzip.compress(b'private sec') + gzip.compress(b'ret output\n'))
            redactor.snapshot_logs(state, b'secret', destination)
            target = destination / path.name
            self.assertEqual(gzip.decompress(target.read_bytes()), b'private [REDACTED] output\n')
            target.unlink()
            path.write_bytes(path.read_bytes()[:-4])
            with self.assertRaises(EOFError):
                redactor.snapshot_logs(state, b'secret', destination)
            self.assertFalse(target.exists())
            self.assertFalse(list(destination.glob('*.tmp')))

    def test_capture_io_errors_are_not_suppressed(self):
        class Broken:
            def write(self, data):
                raise OSError('disk failure')
        with self.assertRaisesRegex(OSError, 'disk failure'):
            guest.CompressedCapture(Broken()).write(b'output')

    def test_capture_disk_failure_drains_input_and_retains_guest_verdict(self):
        class Broken:
            def write(self, data):
                raise OSError('disk failure')
        content = b'private secret\nFINITE_GUEST_STAGE home-init 3 19\n'
        source = io.BytesIO(content)
        capture = guest.CompressedCapture(Broken())
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            rows = guest.collect(guest.bounded_lines(source, capture, b'secret'),
                                 Path(temporary) / 'timings.json', guest.BoundedConsole(output))
            self.assertEqual(source.tell(), len(content))
            self.assertEqual(capture.input_bytes, len(content.replace(b'secret', b'[REDACTED]')))
            self.assertEqual(capture.error, 'storage-io-error')
            self.assertEqual(rows[-1]['status'], 19)
            self.assertNotIn('secret', output.getvalue())

    def test_unavailable_capture_fails_closed_after_recording_guest_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'key').write_bytes(b'secret')
            for status in (0, 19):
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/guest-timings.py'),
                                         str(root / 'timings.json'), '--log', str(root / 'absent/home-init.log.gz'),
                                         '--secret', str(root / 'key')],
                                        input=f'private secret\nFINITE_GUEST_STAGE home-init 3 {status}\n',
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, status or 1)
                self.assertNotIn('secret', result.stdout + result.stderr)
                self.assertIn(f'Guest stage home-init: 3s, exit {status}', result.stdout)
                self.assertIn('incomplete', result.stderr)

    def test_timing_storage_error_is_recorded_without_stopping_drain(self):
        class Broken:
            def write_text(self, data):
                raise OSError('disk failure')
        errors = []
        rows = guest.collect(['FINITE_GUEST_STAGE startup-checks 1 0\n',
                              'FINITE_GUEST_STAGE home-init 3 19\n'], Broken(),
                             guest.BoundedConsole(io.StringIO()), errors)
        self.assertEqual(errors, ['timing-storage-io-error'])
        self.assertEqual(rows[-1]['status'], 19)

    def test_disk_snapshots_are_bounded_and_cannot_replace_guest_failure(self):
        acceptance = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        functional = (ROOT / 'scripts/bluebuild/vm-functional.sh').read_text()
        host = acceptance.split('host_disk_snapshot() {', 1)[1].split('\nbegin_stage()', 1)[0]
        host = 'host_disk_snapshot() {' + host
        guest_functions = functional.split('guest_disk_snapshot() {', 1)[1].split('\ntrap guest_exit EXIT', 1)[0]
        guest_functions = 'guest_disk_snapshot() {' + guest_functions
        for script in (host, guest_functions):
            self.assertIn('timeout 5s df -B1', script)
            self.assertIn('timeout 10s sudo -n du -sx -B1', script)
            self.assertIn('head -c 8192', script)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            for name in ('df', 'du'):
                tool = root / 'bin' / name
                tool.write_text('#!/bin/sh\nhead -c 16384 /dev/zero\nexit 1\n')
                tool.chmod(0o755)
            sudo = root / 'bin/sudo'
            sudo.write_text('#!/bin/sh\ntest "$1" = -n && shift\nexec "$@"\n')
            sudo.chmod(0o755)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH']}
            result = subprocess.run(['bash', '-c', 'set -euo pipefail; ' + host +
                                     '\nstate=/absent; artifact=/absent; host_disk_snapshot fixture'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLessEqual(len(result.stdout), 8192)
            result = subprocess.run(['bash', '-c', 'set -euo pipefail; ' + guest_functions +
                                     '\nguest_finish() { echo "verdict:$1"; }; trap guest_exit EXIT; exit 19'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 19, result.stderr)
            self.assertIn('verdict:19', result.stdout)

    def test_more_than_512_mib_progress_is_complete_with_bounded_memory(self):
        import hashlib
        class Generated:
            def __init__(self):
                self.remaining = 8193
                self.total = 0
                self.digest = hashlib.sha256()
            def read(self, size):
                if self.remaining > 0:
                    self.remaining -= 1
                    line = b'@nix {"action":"result","id":1,"type":105,"fields":[1,0,0,0]}'
                    chunk = (line.ljust(255) + b'\n') * 256
                elif self.remaining == 0:
                    self.remaining = -1
                    chunk = b'FINITE_GUEST_STAGE home-init 1 0\n'
                else:
                    return b''
                self.total += len(chunk)
                self.digest.update(chunk)
                return chunk
        source = Generated()
        with tempfile.TemporaryFile() as raw, tempfile.TemporaryDirectory() as temporary:
            capture = guest.CompressedCapture(raw)
            rows = guest.collect(guest.bounded_lines(source, capture, b'secret'),
                                 Path(temporary) / 'timings.json', guest.BoundedConsole(io.StringIO(), clock=lambda: 0))
            self.assertGreater(source.total, 512 * 1024 * 1024)
            self.assertIsNone(capture.error)
            self.assertEqual(rows[-1]['status'], 0)
            self.assertLess(capture.bytes, 16 * 1024 * 1024)
            raw.seek(0)
            digest = hashlib.sha256()
            with gzip.GzipFile(fileobj=raw) as recovered:
                while chunk := recovered.read(65536):
                    digest.update(chunk)
            self.assertEqual(digest.digest(), source.digest.digest())

    def test_pipeline_preserves_producer_exit_and_compressed_sanitized_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'key').write_bytes(b'secret')
            command = ['bash', '-c', 'set -o pipefail; { printf "failure secret\\nFINITE_GUEST_STAGE home-init 1 19\\n"; exit 19; } | "$@"',
                       'fixture', sys.executable, str(ROOT / 'scripts/bluebuild/guest-timings.py'), str(root / 'timings.json'),
                       '--log', str(root / 'home-init.log.gz'), '--secret', str(root / 'key')]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 19, result.stderr)
            self.assertNotIn('secret', result.stdout)
            receipt = json.loads((root / 'home-init-log.json').read_text())
            self.assertTrue(receipt['captureComplete'])
            self.assertEqual(receipt['homeInitStatus'], 19)
            spec = importlib.util.spec_from_file_location('redactor', ROOT / 'scripts/bluebuild/redact-vm-logs.py')
            redactor = importlib.util.module_from_spec(spec); spec.loader.exec_module(redactor)
            destination = root.parent / (root.name + '-evidence')
            try:
                redactor.snapshot_logs(root, b'secret', destination)
                self.assertFalse((destination / 'home-init.log').exists())
                self.assertEqual(gzip.decompress((destination / 'home-init.log.gz').read_bytes()), gzip.decompress((root / 'home-init.log.gz').read_bytes()))
            finally:
                import shutil
                shutil.rmtree(destination, ignore_errors=True)

    def test_streaming_redaction_handles_every_split_and_repeated_secret(self):
        spec = importlib.util.spec_from_file_location('redactor', ROOT / 'scripts/bluebuild/redact-vm-logs.py')
        redactor = importlib.util.module_from_spec(spec); spec.loader.exec_module(redactor)
        content = b'prefix-secretsecret-middle-secret-suffix'
        for size in range(1, 24):
            self.assertEqual(b''.join(redactor.redacted_chunks(io.BytesIO(content), b'secret', size)),
                             content.replace(b'secret', b'[REDACTED]'))


class Diagnostics(unittest.TestCase):
    def test_v2_and_legacy_partial_rows_survive_same_envelope(self):
        legacy = record('activation'); legacy['schema'] = 1; del legacy['details']
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'receipt.json'
            guest.collect(io.StringIO(''.join('FOUNDATION_TIMING ' + json.dumps(row) + '\n'
                                             for row in (legacy, record()))), output, console=io.StringIO())
            value = json.loads(output.read_text())
            self.assertEqual(value['foundation']['stages'], [legacy, record()])
            self.assertLess(output.stat().st_size, 16384)

    def test_malformed_versions_fields_and_overlap_are_rejected(self):
        for change in (lambda v: v.update(schema=True), lambda v: v.update(schema=3),
                       lambda v: v['details'].update(rawArguments='private'),
                       lambda v: v['details'].update(overlapSeconds=11),
                       lambda v: v['details'].update(builds=True),
                       lambda v: v['details'].update(buildSeconds=float('nan')),
                       lambda v: v['details'].update(incomplete=True)):
            value = record(); change(value)
            with self.assertRaises(ValueError): timings.validate(value)

    def test_unknown_intervals_and_separate_resource_scope(self):
        value = record(); value['details'].update(incomplete=True, buildSeconds=None,
                                                 substitutionSeconds=None, overlapSeconds=None)
        timings.validate(value)
        value = record('resource-nix-daemon')
        value['details'] = {'scope': 'shared-daemon', 'memoryCurrentBytes': None,
                            'memoryPeakBytes': None, 'cpuUsageUsec': None, 'available': False}
        timings.validate(value)
        value['details']['scope'] = 'client'
        with self.assertRaises(ValueError): timings.validate(value)

    def test_duplicate_unknown_and_oversize_lines_do_not_discard_valid_rows(self):
        lines = ['FOUNDATION_TIMING ' + json.dumps(record()) + '\n'] * 2
        lines += ['FOUNDATION_TIMING ' + 'x' * 5000 + '\n']
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'receipt.json'
            guest.collect(io.StringIO(''.join(lines)), output, console=io.StringIO())
            value = json.loads(output.read_text())['foundation']
            self.assertEqual(len(value['stages']), 1)
            self.assertEqual(value['rejectedRecords'], 2)


if __name__ == '__main__': unittest.main()
