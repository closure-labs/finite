#!/usr/bin/env python3
"""Exercise bounded VM transfer, failure propagation and durable redaction."""
import importlib.util
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('upgrade', ROOT / 'scripts/bluebuild/vm-upgrade.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class Upgrade(unittest.TestCase):
    def exercise(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'private'
            state.mkdir()
            evidence = root / 'evidence'
            (state / 'boot.log').write_text('fixture-secret')
            ssh = root / 'ssh'
            ssh.write_text('''import os, signal, sys, time
if 'bootc' not in sys.argv:
 print('guest memory and disk metrics'); sys.exit(0)
print('transfer fixture-secret', flush=True)
mode = sys.argv[1]
if mode == 'cancel':
 os.kill(os.getppid(), signal.SIGTERM)
if mode in ('hang', 'cancel'):
 time.sleep(30)
sys.exit(17 if mode == 'fail' else 0)
''')
            result = upgrade.supervise(state, evidence, b'fixture-secret', [sys.executable, str(ssh), mode],
                                       'image', limit=0.5, interval=0.1)
            self.assertEqual((state / 'boot.log').read_text(), 'fixture-secret')
            self.assertEqual((evidence / 'boot.log').read_text(), '[REDACTED]')
            for path in evidence.rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'fixture-secret', path.read_bytes())
            self.assertIn('[REDACTED]', (evidence / 'upgrade-transfer.log').read_text())
            return result

    def test_remote_probe_shell_syntax(self):
        command = 'sudo sh -c ' + upgrade.shlex.quote(upgrade.DIAGNOSTICS)
        subprocess.run(['sh', '-n', '-c', command], check=True)

    def test_success(self):
        self.assertEqual(self.exercise('success'), 0)

    def test_failure_is_not_accepted(self):
        self.assertEqual(self.exercise('fail'), 17)

    def test_hang_is_bounded_and_retains_logs(self):
        self.assertEqual(self.exercise('hang'), 124)

    def test_cancellation_retains_logs(self):
        self.assertEqual(self.exercise('cancel'), 143)

    def test_empty_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                upgrade.redactor.snapshot_logs(root, b'', root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
