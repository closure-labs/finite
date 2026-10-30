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
    def test_cancelled_collector_never_claims_complete_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'key').write_bytes(b'secret')
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/bluebuild/guest-timings.py'),
                str(root / 'timings.json'), '--log', str(root / 'home-init.log'), '--secret', str(root / 'key')],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                process.stdin.write(b'partial secret output\npadding')
                process.stdin.flush()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if (root / 'home-init.log').exists() and (root / 'home-init.log').stat().st_size:
                        break
                    time.sleep(0.01)
                else:
                    self.fail('Collector did not capture partial output')
                process.terminate()
                self.assertEqual(process.wait(timeout=2), -signal.SIGTERM)
                self.assertNotIn(b'secret', (root / 'home-init.log').read_bytes())
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

    def test_log_budget_failure_is_explicit(self):
        with patch.object(guest, 'LOG_LIMIT', 16):
            with self.assertRaisesRegex(ValueError, 'evidence incomplete'):
                list(guest.bounded_lines(io.BytesIO(b'x' * 32), io.BytesIO(), b'secret'))

    def test_pipeline_preserves_producer_exit_and_compressed_sanitized_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'key').write_bytes(b'secret')
            command = ['bash', '-c', 'set -o pipefail; { printf "failure secret\\nFINITE_GUEST_STAGE home-init 1 19\\n"; exit 19; } | "$@"',
                       'fixture', sys.executable, str(ROOT / 'scripts/bluebuild/guest-timings.py'), str(root / 'timings.json'),
                       '--log', str(root / 'home-init.log'), '--secret', str(root / 'key')]
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
                self.assertEqual(gzip.decompress((destination / 'home-init.log.gz').read_bytes()), (root / 'home-init.log').read_bytes())
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
