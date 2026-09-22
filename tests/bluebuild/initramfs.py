#!/usr/bin/env python3
"""Reject missing boot payloads and incomplete encrypted-root initramfs images."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'files/system/usr/libexec/finite/check-initramfs'
RELEASE = '7.2.6-300.fc45.x86_64'
MODULES = ['ostree', 'crypt', 'systemd-cryptsetup', 'fido2']
CONTENTS = f'lrwxrwxrwx 1 root root 23 init -> usr/lib/systemd/systemd\nusr/lib/modules/{RELEASE}/kernel/dm-crypt.ko.xz\n'


class Initramfs(unittest.TestCase):
    def check(self, *, missing=None, empty=False, modules=MODULES, contents=CONTENTS, unreadable=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kernel = root / 'modules' / RELEASE
            kernel.mkdir(parents=True)
            for name in ('vmlinuz', 'initramfs.img'):
                if name != missing:
                    (kernel / name).write_bytes(b'' if empty else b'fixture')
            (root / 'included').write_text('\n'.join(modules) + '\n')
            (root / 'contents').write_text(contents)
            tool = root / 'lsinitrd'
            tool.write_text('#!' + shutil.which('bash') + '\n' + ('exit 1\n' if unreadable else
                            'if [[ $1 == -m ]]; then cat "$FIXTURE/included"; else cat "$FIXTURE/contents"; fi\n'))
            tool.chmod(0o755)
            return subprocess.run(['bash', str(SCRIPT), RELEASE, str(root / 'modules')],
                                  env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                                       'FIXTURE': str(root)}, capture_output=True, text=True)

    def test_complete_boot_payload(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_empty_boot_payload(self):
        for missing in ('vmlinuz', 'initramfs.img'):
            result = self.check(missing=missing)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Missing or empty boot payload', result.stderr)
        self.assertNotEqual(self.check(empty=True).returncode, 0)

    def test_missing_encrypted_root_or_ostree_support(self):
        for missing in MODULES:
            result = self.check(modules=[m for m in MODULES if m != missing])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('required dracut module: ' + missing, result.stderr)

    def test_unreadable_archive_missing_init_and_wrong_kernel(self):
        self.assertNotEqual(self.check(unreadable=True).returncode, 0)
        self.assertNotEqual(self.check(contents=CONTENTS.split('\n', 1)[1]).returncode, 0)
        self.assertNotEqual(self.check(contents=CONTENTS.replace(RELEASE, 'old-kernel')).returncode, 0)


if __name__ == '__main__':
    unittest.main()
