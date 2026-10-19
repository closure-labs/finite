#!/usr/bin/env python3
"""Exercise bounded VM transfer, failure propagation and durable redaction."""
import importlib.util
import json
import os
import shlex
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
    def test_home_initializer_cannot_consume_following_remote_script_commands(self):
        source = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        command = next(line for line in source.splitlines() if line.startswith('/usr/libexec/finite/home-init --profile'))
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            initializer = home / 'initializer.py'
            initializer.write_text('import pathlib,sys\npathlib.Path.home().joinpath("initializer-input").write_text(sys.stdin.read())\n')
            command = command.replace('/usr/libexec/finite/home-init', shlex.join([sys.executable, str(initializer)]))
            script = command + '\nprintf "created\\n" >"$HOME/following-command"\n'
            subprocess.run(['bash', '-s'], input=script, text=True, check=True, env={**os.environ, 'HOME': str(home)})
            self.assertEqual((home / 'initializer-input').read_text(), '')
            self.assertEqual((home / 'following-command').read_text(), 'created\n')

    def test_marker_is_verified_after_initialization_before_upgrade(self):
        source = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        probe = source.split("<<'HOME_INITIALIZED'\n", 1)[1].split('\nHOME_INITIALIZED', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            sentinel = home / 'nix-marker'
            sentinel.write_text('persistent-nix-state\n')
            configuration = home / '.config/home-manager'
            configuration.mkdir(parents=True)
            for name in ('flake.nix', 'flake.lock', 'profile.json', 'customize.nix'):
                (configuration / name).write_text('existing user fixture\n')
            probe = probe.replace("Path('/var/home/nix/finite-acceptance')", f'Path({str(sentinel)!r})')
            result = subprocess.run([sys.executable, '-c', probe], env={**os.environ, 'HOME': str(home)},
                                    text=True, capture_output=True, check=True)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt['status'], 'pass')
            self.assertTrue(receipt['checks']['nixState'])
            self.assertTrue(receipt['checks']['homeCustomization'])
            self.assertRegex(receipt['customizationSha256'], r'^[0-9a-f]{64}$')
            customization = configuration / 'customize.nix'
            self.assertTrue(customization.read_text().startswith('existing user fixture\n'))
            customization.unlink()
            result = subprocess.run([sys.executable, '-c', probe], env={**os.environ, 'HOME': str(home)},
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('required configuration file: customize.nix', result.stderr)
            self.assertFalse(customization.exists())

    def test_post_upgrade_persistence_receipt_identifies_failures(self):
        source = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        probe = source.split("<<'HOME_PERSISTENCE'\n", 1)[1].split('\nHOME_PERSISTENCE', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            sentinel = home / 'nix-marker'
            customization = home / '.config/home-manager/customize.nix'
            customization.parent.mkdir(parents=True)
            probe = probe.replace("Path('/var/home/nix/finite-acceptance')", f'Path({str(sentinel)!r})')
            for mode in ('pass', 'missing-nix', 'changed-nix', 'missing-customization', 'changed-customization'):
                with self.subTest(mode=mode):
                    sentinel.write_text('persistent-nix-state\n')
                    customization.write_text('# VM acceptance customization\n')
                    if mode == 'missing-nix': sentinel.unlink()
                    if mode == 'changed-nix': sentinel.write_text('fixture-sensitive-data')
                    if mode == 'missing-customization': customization.unlink()
                    if mode == 'changed-customization': customization.write_text('fixture-sensitive-data')
                    result = subprocess.run([sys.executable, '-c', probe], text=True, capture_output=True,
                                            env={**os.environ, 'HOME': str(home)}, check=False)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(result.returncode, int(mode != 'pass'))
                    self.assertEqual(receipt['status'], 'pass' if mode == 'pass' else 'fail')
                    self.assertEqual(receipt['checks']['nixState'], mode not in ('missing-nix', 'changed-nix'))
                    self.assertEqual(receipt['checks']['homeCustomization'], mode not in ('missing-customization', 'changed-customization'))
                    self.assertNotIn('fixture-sensitive-data', result.stdout + result.stderr)
                    if mode != 'pass':
                        self.assertIn('Post-upgrade persistence check failed:', result.stderr)

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
