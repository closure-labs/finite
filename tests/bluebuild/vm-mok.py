#!/usr/bin/env python3
"""Enrollment is a certificate match, independent of mokutil test-key conventions."""
import hashlib
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Enrollment(unittest.TestCase):
    def invoke(self, mode, certificate=b'expected certificate', expected=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'certificate.der'
            source.write_bytes(certificate)
            tool = root / 'mokutil'
            tool.write_text('#!' + shutil.which('bash') + '\n' + '''set -eu
case "$1" in
  --version) echo "mokutil fixture" ;;
  --export)
    case "$MODE" in
      enrolled) cp "$CERTIFICATE" MOK-0001.der ;;
      absent) : ;;
      wrong) printf other >MOK-0001.der ;;
      error) cp "$CERTIFICATE" MOK-0001.der; exit 1 ;;
    esac ;;
  *) echo "Unexpected mokutil command" >&2; exit 99 ;;
esac
''')
            tool.chmod(0o755)
            return subprocess.run(
                ['bash', str(ROOT / 'scripts/bluebuild/check-vm-mok.sh'),
                 expected if expected is not None else hashlib.sha256(certificate).hexdigest()],
                env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                     'MODE': mode, 'CERTIFICATE': str(source)}, capture_output=True, text=True)

    def test_enrolled_certificate_is_accepted_without_test_key(self):
        result = self.invoke('enrolled')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Enrolled MOK certificate SHA-256:', result.stdout)

    def test_absent_wrong_and_failed_exports_are_rejected(self):
        for mode in ('absent', 'wrong', 'error'):
            with self.subTest(mode=mode):
                self.assertNotEqual(self.invoke(mode).returncode, 0)

    def test_malformed_expected_digest_is_rejected(self):
        for digest in ('', 'a' * 63, '../certificate'):
            with self.subTest(digest=digest):
                self.assertNotEqual(self.invoke('enrolled', expected=digest).returncode, 0)


if __name__ == '__main__':
    unittest.main()
