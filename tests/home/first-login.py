#!/usr/bin/env python3
"""Run the real login helper against systemctl's any-active semantics."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FirstLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        binaries = self.root / 'bin'
        binaries.mkdir()
        def executable(name, content):
            path = binaries / name
            path.write_text('#!' + shutil.which('bash') + '\nset -euo pipefail\n' + content)
            path.chmod(0o755)
            return str(path)
        executable('systemctl', '''
printf '%s\\n' "$*" >>"$LOGIN_ROOT/systemctl.log"
[[ $1 == is-active ]] || exit 99
# Deliberately implement systemctl's OR behavior for multiple units.
for unit in "$@"; do
  if [[ $unit == nix-daemon.socket || $unit == determinate-nixd.socket ]]; then
    [[ $ACTIVE == both || $ACTIVE == "$unit" || -f $LOGIN_ROOT/ready ]] && exit 0
  fi
done
exit 3
''')
        executable('sleep', 'touch "$LOGIN_ROOT/slept" "$LOGIN_ROOT/ready"\n')
        executable('zenity', 'touch "$LOGIN_ROOT/diagnostic"\n')
        nix = executable('nix', 'exit 0\n')
        home_init = executable('home-init', 'touch "$LOGIN_ROOT/initialized"\n')
        (self.root / 'seed.yaml').write_text('schema: 2\n')
        (self.root / 'running.json').write_text('{}\n')
        self.env = {**os.environ, 'PATH': str(binaries) + ':' + os.environ['PATH'],
                    'LOGIN_ROOT': str(self.root), 'ACTIVE': 'both', 'FINITE_NIX_COMMAND': nix,
                    'FINITE_HOME_INIT_COMMAND': home_init, 'FINITE_NIX_WAIT_SECONDS': '0',
                    'FINITE_PROVISIONED_PROFILE_PATH': str(self.root / 'seed.yaml'),
                    'FINITE_HOME_PROFILE_PATH': str(self.root / 'absent.json'),
                    'FINITE_HOME_FLAKE_PATH': str(self.root / 'home-manager'),
                    'FINITE_RUNNING_PROFILE_PATH': str(self.root / 'running.json')}

    def run_login(self):
        return subprocess.run(['bash', str(ROOT / 'files/system/usr/libexec/finite/home-first-login')],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_both_active_initializes(self):
        self.assertEqual(self.run_login().returncode, 0)
        self.assertTrue((self.root / 'initialized').exists())
        self.assertFalse((self.root / 'slept').exists())

    def test_either_socket_alone_or_neither_times_out_without_initializing(self):
        for active in ('nix-daemon.socket', 'determinate-nixd.socket', 'neither'):
            self.env['ACTIVE'] = active
            with self.subTest(active=active):
                result = self.run_login()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('did not become ready within 0s', result.stderr)
                self.assertTrue((self.root / 'diagnostic').exists())
                self.assertFalse((self.root / 'initialized').exists())
                self.assertFalse((self.root / 'slept').exists())

    def test_delayed_readiness_waits_for_both(self):
        self.env.update(ACTIVE='determinate-nixd.socket', FINITE_NIX_WAIT_SECONDS='5')
        self.assertEqual(self.run_login().returncode, 0)
        self.assertTrue((self.root / 'slept').exists())
        self.assertTrue((self.root / 'initialized').exists())

    def test_existing_configuration_skips_readiness_and_initialization(self):
        config = self.root / 'home-manager'
        config.mkdir()
        for name in ('flake.nix', 'flake.lock', 'profile.json'):
            (config / name).write_text('{}')
        self.env.update(ACTIVE='neither', FINITE_NIX_WAIT_SECONDS='invalid')
        self.assertEqual(self.run_login().returncode, 0)
        self.assertFalse((self.root / 'systemctl.log').exists())
        self.assertFalse((self.root / 'initialized').exists())


if __name__ == '__main__':
    unittest.main()
