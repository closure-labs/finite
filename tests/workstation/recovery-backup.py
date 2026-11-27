#!/usr/bin/env python3
"""Exercise backup boundaries and a real tar permissions/credential restore."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('backup', ROOT / 'scripts/workstation/recovery-backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class RecoveryBackup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.work = self.home / 'private'
        self.destination = self.home / 'Nextcloud/finite-backup'
        for name in ['.ssh', '.gnupg', '.password-store', '.config/home-manager']:
            path = self.home / name
            path.mkdir(mode=0o700, parents=True)
            (path / 'fixture').write_text('private fixture')
            (path / 'fixture').chmod(0o600)
        (self.home / 'notes.txt').write_text('preserved document')
        (self.home / '.cache').mkdir()
        (self.home / '.cache/omit-me').write_text('cache')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        # age and credentials are stubs; GNU tar and the complete workflow are
        # real. These tests make no claim about age's cryptography.
        scripts = {
            'age': '''import shutil,sys
if '--output' in sys.argv:
 with open(sys.argv[sys.argv.index('--output')+1], 'xb') as stream: shutil.copyfileobj(sys.stdin.buffer,stream)
else:
 with open(sys.argv[-1],'rb') as stream: shutil.copyfileobj(stream,sys.stdout.buffer)
''',
            'gpg': '''import sys,os,pathlib
if '--export-ownertrust' in sys.argv: print('# trust fixture')
else: assert pathlib.Path(os.environ['GNUPGHOME'],'fixture').read_text()=='private fixture'
''',
            'pass': '''import os,pathlib,sys
assert pathlib.Path(os.environ['PASSWORD_STORE_DIR'],'fixture').read_text()=='private fixture'
assert pathlib.Path(os.environ['GNUPGHOME'],'fixture').exists()
print('SECRET-MUST-NOT-BE-PRINTED')
sys.exit(1 if os.environ.get('FAIL_PASS') else 0)
''',
            'gpgconf': 'pass\n',
        }
        import sys
        for name, content in scripts.items():
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\n' + content)
            path.chmod(0o755)
        self.env = patch.dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'])
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tty = patch.object(backup.os, 'isatty', return_value=True)
        self.tty.start()
        self.addCleanup(self.tty.stop)
        self.out = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.out)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        backup.inventory(argparse.Namespace(home=self.home, work=self.work, destination=self.destination,
                                           include=[self.home / 'notes.txt']))

    def create(self):
        backup.create(argparse.Namespace(inventory=self.work / 'inventory.json', work=self.work))

    def verify(self):
        backup.verify(argparse.Namespace(work=self.work, pass_entry='fixture'))

    def test_inventory_includes_herdr_config_and_excludes_rotating_session_snapshots(self):
        herdr = self.home / '.config/herdr'
        snapshots = herdr / 'session-snapshots'
        snapshots.mkdir(parents=True)
        (snapshots / 'session.json').touch()
        config = herdr / 'config.toml'
        config.touch()
        (self.work / 'inventory.json').unlink()
        backup.inventory(argparse.Namespace(home=self.home, work=self.work, destination=self.destination, include=[]))
        plan = backup.read_plan(self.work / 'inventory.json')
        self.assertIn(str(config), plan['include'])
        self.assertIn(str(snapshots), plan['exclude'])
        self.assertFalse(any(Path(path).is_relative_to(snapshots) for path in plan['include']))

    def test_round_trip_preserves_modes_and_tests_restored_credentials(self):
        self.create()
        self.verify()
        result = json.loads((self.work / 'verified.json').read_text())
        self.assertTrue(result['passwordStoreDecrypted'])
        self.assertTrue(result['uploadAssumedByOperator'])
        self.assertEqual(len(list(self.destination.iterdir())), 1)
        self.assertNotIn('SECRET-MUST-NOT-BE-PRINTED', self.out.getvalue())
        self.assertFalse(list(self.work.glob('restore-*')))
        import tarfile
        with tarfile.open(self.work / 'finite-recovery.tar.age') as archive:
            names = archive.getnames()
            self.assertTrue(any(n.endswith('notes.txt') for n in names))
            self.assertFalse(any('omit-me' in n or 'finite-recovery' in n for n in names))

    def test_changed_nextcloud_copy_has_no_verified_receipt(self):
        self.create()
        synced = Path(json.loads((self.work / 'created.json').read_text())['nextcloudFile'])
        synced.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.verify()
        self.assertFalse((self.work / 'verified.json').exists())

    def test_password_decryption_failure_has_no_verified_receipt(self):
        self.create()
        with patch.dict(os.environ, FAIL_PASS='1'):
            with self.assertRaises(subprocess.CalledProcessError):
                self.verify()
        self.assertFalse((self.work / 'verified.json').exists())
        self.assertFalse(list(self.work.glob('restore-*')))

    def test_excluding_private_key_is_rejected_before_archival(self):
        path = self.work / 'inventory.json'
        plan = json.loads(path.read_text())
        plan['exclude'].append(str(self.home / '.ssh/fixture'))
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'essentials'):
            self.create()
        self.assertFalse((self.work / 'finite-recovery.tar.age').exists())

    def test_noninteractive_create_does_not_prompt_or_create_archive(self):
        with patch.object(backup.os, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'local terminal'):
                self.create()
        self.assertFalse((self.work / 'finite-recovery.tar.age').exists())

    def test_insecure_work_directory_is_rejected(self):
        self.work.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            backup.private(self.work)

    def test_credential_link_cannot_verify_against_live_key(self):
        (self.home / '.gnupg/link-to-live-key').symlink_to(self.home / '.gnupg/fixture')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.create()
        self.assertFalse((self.work / 'finite-recovery.tar.age').exists())

    def test_documents_and_installed_dependencies_are_not_selected(self):
        documents = self.home / 'Documents'
        documents.mkdir()
        with (documents / 'large-download').open('wb') as stream:
            stream.truncate(1024**3)
        installed = self.home / '.config/opencode/node_modules/example'
        installed.mkdir(parents=True)
        (installed / 'package.json').write_text('{"installed":true}')
        config = self.home / '.config/opencode/settings.json'
        config.write_text('{"unique":true}')
        work = self.home / 'small-inventory'
        backup.inventory(argparse.Namespace(home=self.home, work=work, destination=self.destination, include=[]))
        plan = backup.read_plan(work / 'inventory.json')
        self.assertIn(str(config), plan['include'])
        self.assertFalse(any('Documents' in p or 'node_modules' in p for p in plan['include']))
        self.assertLess(backup.input_size(plan), 1024**2)

    def test_oversized_input_is_refused_before_encryption(self):
        with patch.object(backup, 'input_size', return_value=backup.MAX_INPUT + 1):
            with self.assertRaisesRegex(ValueError, '512 MiB'):
                self.create()
        self.assertFalse((self.work / 'finite-recovery.tar.age').exists())

    def test_insufficient_restore_space_is_refused_before_encryption(self):
        from collections import namedtuple
        usage = namedtuple('usage', 'total used free')
        with patch.object(backup.shutil, 'disk_usage', return_value=usage(100, 99, 1)):
            with self.assertRaisesRegex(ValueError, 'free space'):
                self.create()
        self.assertFalse((self.work / 'finite-recovery.tar.age').exists())


if __name__ == '__main__':
    unittest.main()
