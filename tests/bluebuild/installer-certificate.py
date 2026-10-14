#!/usr/bin/env python3
"""Certificate corruption fails before any installer network/container work."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallerCertificate(unittest.TestCase):
    def test_certificate_matches_immutable_pin(self):
        lock = json.loads((ROOT / 'sources/installer-security.json').read_text())
        raw = subprocess.check_output(['openssl', 'x509', '-in', str(ROOT / lock['certificate']), '-outform', 'DER'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), lock['derSha256'])
        self.assertRegex(lock['source'], r'/blob/[0-9a-f]{40}/secure_boot\.der$')

    def test_changed_certificate_pin_stops_before_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / 'files/installer', root / 'files/installer')
            (root / 'sources').mkdir()
            for name in ('bluebuild-installer.json', 'installer-security.json'):
                shutil.copy2(ROOT / 'sources' / name, root / 'sources' / name)
            lock = json.loads((root / 'sources/installer-security.json').read_text())
            lock['derSha256'] = 'a' * 64
            (root / 'sources/installer-security.json').write_text(json.dumps(lock))
            (root / 'bin').mkdir()
            docker = root / 'bin/docker'
            docker.write_text('#!/usr/bin/env bash\ntouch docker-called\nexit 99\n')
            docker.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/prepare-installer.sh')],
                cwd=root, env=dict(os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='closure-labs/finite',
                                   PATH=str(root / 'bin') + ':' + os.environ['PATH']), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'docker-called').exists())

    def test_container_has_no_certificate_download_fallback(self):
        content = (ROOT / 'files/installer/Containerfile').read_text()
        self.assertIn("grep -Fq 'curl --fail", content)
        self.assertIn('Pinned Secure Boot certificate missing', content)
        self.assertIn('exit 1', content)
        self.assertIn('COPY secure-boot.pem', content)


if __name__ == '__main__':
    unittest.main()
