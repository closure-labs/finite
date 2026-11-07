"""Offline migration/guest boundaries; native store/NAR behavior is a hosted gate."""
from contextlib import redirect_stdout
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = self.root/'assets'
        self.store = self.root/'store'
        self.profile = self.root/'profile'
        self.bin = self.root/'bin'
        for path in (self.assets/'store', self.store, self.profile/'bin', self.bin):
            path.mkdir(parents=True)
        (self.profile/'manifest.nix').write_text('fixture')
        (self.profile/'CA-certificate').write_text('preserve')
        (self.profile/'etc/ssl/certs').mkdir(parents=True)
        (self.profile/'etc/ssl/certs/ca-bundle.crt').write_text('preserve certificates')
        (self.store/'user-data').write_text('preserve')
        self.runtime = self.store/('a'*32+'-determinate-nix-3.24.1')
        src = self.assets/'store'/self.runtime.name
        (src/'bin').mkdir(parents=True)
        shell = '#!'+shutil.which('bash')+'\nset -euo pipefail\n'
        (src/'bin/nix').write_text(shell+'exit 0\n')
        (src/'bin/nix-store').write_text(shell+'echo "$*" >>"$CALLS"\nif [[ $1 == --load-db ]]; then cat >/dev/null; fi\nif [[ $1 == --verify-path ]]; then exit "${VERIFY_FAIL:-0}"; fi\n')
        (src/'bin/nix-env').write_text(shell+'echo "$*" >>"$CALLS"\nln -sfn "$4/bin/nix" "$2/bin/nix"\n')
        for path in (src/'bin').iterdir(): path.chmod(0o755)
        self.library = self.store/('b'*32+'-library')
        libsrc = self.assets/'store'/self.library.name/'lib'
        libsrc.mkdir(parents=True)
        (libsrc/'libnixstore.so').write_text('library')
        self.manifest = {'schema': 1, 'runtime': str(self.runtime),
            'library': str(self.library/'lib/libnixstore.so'),
            'binarySha256': hashlib.sha256((src/'bin/nix').read_bytes()).hexdigest(),
            'librarySha256': hashlib.sha256((libsrc/'libnixstore.so').read_bytes()).hexdigest()}
        (self.assets/'store-paths').write_text(str(self.runtime)+'\n'+str(self.library)+'\n')
        (self.assets/'registration').write_text('registration fixture')
        self.write_manifest()
        systemctl = self.bin/'systemctl'
        systemctl.write_text(shell+'exit "${DAEMON_STATUS:-3}"\n'); systemctl.chmod(0o755)
        restorecon = self.bin/'restorecon'
        restorecon.write_text(shell+'echo "restorecon $*" >>"$CALLS"\nexit "${RESTORE_FAIL:-0}"\n')
        restorecon.chmod(0o755)
        text = (ROOT/'files/system/usr/libexec/finite/install-native-nix-runtime').read_text()
        for old, new in (('/usr/lib/finite/nix-runtime', self.assets),
                         ('/nix/var/nix/profiles/default', self.profile), ('/nix/store', self.store)):
            text = text.replace(old, str(new))
        self.script = self.root/'migrate'; self.script.write_text(text)
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'], CALLS=str(self.root/'calls'))

    def write_manifest(self):
        (self.assets/'runtime.json').write_text(json.dumps(self.manifest))

    def run_migration(self, **env):
        return subprocess.run(['bash', str(self.script)], env=dict(self.env, **env), capture_output=True, text=True)

    def test_preserves_and_is_idempotent(self):
        for _ in range(2):
            result = self.run_migration(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.profile/'CA-certificate').read_text(), 'preserve')
        self.assertEqual((self.store/'user-data').read_text(), 'preserve')
        calls = (self.root/'calls').read_text().splitlines()
        self.assertEqual(sum('--install' in c for c in calls), 1)
        self.assertEqual(sum('--verify-path' in c for c in calls), 2)
        self.assertEqual(sum(c.startswith('restorecon -RFD -- ') for c in calls), 2)

    def test_active_daemon_blocks_before_copy(self):
        self.assertNotEqual(self.run_migration(DAEMON_STATUS='0').returncode, 0)
        self.assertFalse(self.runtime.exists())

    def test_unknown_profile_blocks_before_copy(self):
        (self.profile/'manifest.json').write_text('{}')
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertFalse(self.runtime.exists())

    def test_invalid_schema_blocks_before_copy(self):
        self.manifest['schema'] = 2; self.write_manifest()
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertFalse(self.runtime.exists())

    def test_nar_verification_failure_blocks_activation(self):
        self.assertNotEqual(self.run_migration(VERIFY_FAIL='1').returncode, 0)
        self.assertFalse((self.profile/'bin/nix').exists())

    def test_selinux_label_failure_blocks_execution_and_activation(self):
        self.assertNotEqual(self.run_migration(RESTORE_FAIL='1').returncode, 0)
        self.assertFalse((self.profile/'bin/nix').exists())
        self.assertNotIn('--load-db', (self.root/'calls').read_text())

    def test_binary_tampering_blocks_activation(self):
        self.manifest['binarySha256'] = '0'*64; self.write_manifest()
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertFalse((self.profile/'bin/nix').exists())

    def test_library_tampering_blocks_activation(self):
        self.manifest['librarySha256'] = '0'*64; self.write_manifest()
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertFalse((self.profile/'bin/nix').exists())

    def test_existing_store_bytes_not_overwritten(self):
        self.runtime.mkdir(); (self.runtime/'marker').write_text('preserve')
        self.assertNotEqual(self.run_migration().returncode, 0)
        self.assertEqual((self.runtime/'marker').read_text(), 'preserve')


class GuestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root/'nix/store'/('a'*32+'-determinate-nix-3.24.1')
        self.binary = self.runtime/'bin/nix'
        self.library = self.root/'nix/store'/('b'*32+'-library/lib/libnixstore.so')
        for path, data in ((self.binary, b'fixed Nix binary'), (self.library, b'fixed library')):
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        self.manifest = {'schema': 1, 'runtime': str(self.runtime), 'library': str(self.library),
            'binarySha256': hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            'librarySha256': hashlib.sha256(self.library.read_bytes()).hexdigest(),
            'sourceRevision': 'c'*40, 'patchedSourceSha256': 'd'*64}
        manifest = self.root/'usr/lib/finite/nix-runtime/runtime.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(self.manifest))
        profile = self.root/'nix/var/nix/profiles/default/bin/nix'
        profile.parent.mkdir(parents=True)
        profile.symlink_to(self.binary)
        self.cgroup = self.root/'sys/fs/cgroup/system.slice/nix-daemon.service/cgroup.procs'
        self.cgroup.parent.mkdir(parents=True)
        self.cgroup.write_text('100\n200\n')
        for pid in ('100', '200'):
            process = self.root/'proc'/pid
            process.mkdir(parents=True)
            (process/'exe').symlink_to(self.binary)
            (process/'maps').write_text(str(self.library)+'\n')
        self.verified = self.root/'var/lib/finite-vm/native-nix-verified'
        self.verified.parent.mkdir(parents=True)
        source = ROOT/'scripts/bluebuild/check-native-nix-guest.py'
        text = source.read_text()
        # Run the actual guest checker against an isolated filesystem fixture.
        for path in ('/usr/lib/finite/nix-runtime/runtime.json', '/nix/var/nix/profiles/default/bin/nix',
                     '/sys/fs/cgroup', '/proc', '/var/home/nix/finite-predecessor-fixture',
                     '/var/lib/finite-vm/native-nix-verified'):
            text = text.replace(repr(path), repr(str(self.root/path.lstrip('/'))))
        self.checker = compile(text, str(source), 'exec')

    def check_output(self, command, **kwargs):
        self.assertEqual(kwargs, {'text': True})
        if command[0] in ('matchpathcon', 'stat'):
            self.assertIn(command[-1], (str(self.binary), str(self.library)))
            return 'system_u:object_r:nix_store_t:s0\n'
        if command == ['systemctl', 'show', '--property=ControlGroup', '--value', 'nix-daemon.service']:
            return '/system.slice/nix-daemon.service\n'
        if command == ['journalctl', '-b', '-u', 'finite-nix-runtime.service', '--output=cat', '--no-pager']:
            return 'Prior native Nix: '+str(self.binary)+'\n'
        self.fail('Unexpected guest command: '+repr(command))

    def run_guest(self, method='read_text', target=None, error=None):
        original = getattr(Path, method)

        def read(path, *args, **kwargs):
            if path == target:
                raise error
            return original(path, *args, **kwargs)

        self.verified.unlink(missing_ok=True)
        self.output = io.StringIO()
        with patch.object(Path, method, read), patch('subprocess.check_output', self.check_output), \
                patch('subprocess.run') as ping, redirect_stdout(self.output):
            exec(self.checker, {'__name__': '__main__'})
        ping.assert_called_once_with([str(self.binary), '--extra-experimental-features',
            'nix-command', '--store', 'daemon', 'store', 'ping'], check=True, capture_output=True, timeout=30)
        receipt = json.loads(self.output.getvalue())
        self.assertEqual(receipt['status'], 'pass')
        self.assertTrue(receipt['runningDaemonMatched'])
        self.assertEqual(receipt['binarySha256'], self.manifest['binarySha256'])
        self.assertEqual(receipt['librarySha256'], self.manifest['librarySha256'])
        self.assertTrue(self.verified.exists())

    def assert_failed(self):
        self.assertEqual(self.output.getvalue(), '')
        self.assertFalse(self.verified.exists())

    def test_live_daemon_passes(self):
        self.run_guest()

    def test_disappearing_member_still_requires_verified_live_daemon(self):
        for method, name in (('resolve', 'exe'), ('read_text', 'maps'), ('read_bytes', 'exe')):
            for code in (errno.ENOENT, errno.ESRCH):
                for pids in ('100\n200\n', '200\n100\n'):
                    with self.subTest(method=method, errno=code, pids=pids):
                        self.cgroup.write_text(pids)
                        self.run_guest(method, self.root/'proc/100'/name, OSError(code, os.strerror(code)))

    def test_all_daemons_disappearing_fails_closed(self):
        self.cgroup.write_text('100\n')
        for code in (errno.ENOENT, errno.ESRCH):
            with self.subTest(errno=code):
                with self.assertRaisesRegex(AssertionError, 'No running fixed Nix daemon'):
                    self.run_guest(target=self.root/'proc/100/maps', error=OSError(code, os.strerror(code)))
                self.assert_failed()

    def test_empty_or_unrelated_cgroup_fails_closed(self):
        executable = self.root/'proc/100/exe'
        executable.unlink()
        executable.symlink_to('/unrelated-program')
        for pids in ('', '100\n'):
            with self.subTest(pids=pids):
                self.cgroup.write_text(pids)
                with self.assertRaisesRegex(AssertionError, 'No running fixed Nix daemon'):
                    self.run_guest()
                self.assert_failed()

    def test_unexpected_proc_errors_fail_even_after_a_verified_daemon(self):
        for method, name in (('resolve', 'exe'), ('read_text', 'maps'), ('read_bytes', 'exe')):
            for code in (errno.EACCES, errno.EIO):
                with self.subTest(method=method, errno=code):
                    with self.assertRaises(OSError) as raised:
                        self.run_guest(method, self.root/'proc/200'/name, OSError(code, os.strerror(code)))
                    self.assertEqual(raised.exception.errno, code)
                    self.assert_failed()

    def test_daemon_library_mismatch_fails_even_with_a_verified_daemon(self):
        (self.root/'proc/200/maps').write_text('/wrong-library\n')
        with self.assertRaises(AssertionError):
            self.run_guest()
        self.assert_failed()

    def test_daemon_binary_mismatch_fails_even_with_a_verified_daemon(self):
        read_bytes = Path.read_bytes

        def tampered(path):
            return b'tampered daemon' if path == self.root/'proc/200/exe' else read_bytes(path)

        with patch.object(Path, 'read_bytes', tampered), self.assertRaises(AssertionError):
            self.run_guest()
        self.assert_failed()


if __name__ == '__main__': unittest.main()
