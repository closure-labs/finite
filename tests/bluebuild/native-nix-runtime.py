"""Offline migration boundaries; native store/NAR behavior is a hosted gate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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


if __name__ == '__main__': unittest.main()
