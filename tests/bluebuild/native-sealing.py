#!/usr/bin/env python3
"""Signed kernel arguments must not weaken or replace the native root binding."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/bluebuild'))
spec = importlib.util.spec_from_file_location('seal_native', ROOT / 'scripts/bluebuild/seal-native.py')
sealer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sealer)


class KernelArguments(unittest.TestCase):
    def arguments(self, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'usr/lib/bootc/kargs.d'
            config.mkdir(parents=True)
            (config / '00-native.toml').write_text(text)
            return sealer.kernel_arguments(root, 'a' * 128)

    def test_strict_native_arguments_include_exact_imported_digest(self):
        self.assertEqual(self.arguments('kargs = ["rw", "quiet"]'),
                         'rw quiet composefs.digest=v1-sha512-12:' + 'a' * 128)

    def test_existing_digest_ostree_readonly_and_unsupported_encoding_are_rejected(self):
        for text in ['kargs = ["ro"]', 'kargs = ["rw", "ro"]',
                     'kargs = ["rw", "ostree=/old"]', 'kargs = ["rw", "composefs=?wrong"]',
                     'kargs = ["rw", "composefs.digest=v1:wrong"]',
                     'kargs = ["rw", "two args"]', 'kargs = "rw"',
                     'kargs = ["rw"]\nunknown = true']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.arguments(text)


if __name__ == '__main__':
    unittest.main()
