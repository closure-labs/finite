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
        self.assertIn('COPY secure-boot.der', content)
        self.assertNotIn('openssl', content)

    def test_host_converts_pinned_der_and_cleans_context_after_success_or_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / 'files/installer', root / 'files/installer')
            (root / 'sources').mkdir()
            for name in ('bluebuild-installer.json', 'installer-security.json'):
                shutil.copy2(ROOT / 'sources' / name, root / 'sources' / name)
            (root / 'bin').mkdir()
            docker = root / 'bin/docker'
            docker.write_text('#!/usr/bin/env python3\n' + '''
import hashlib,json,os,sys
from pathlib import Path
command=sys.argv[1]
if command=='inspect':
    if '--format' in sys.argv:
        print('sha256:'+'a'*64)
    else:
        pin=json.loads(Path('sources/bluebuild-installer.json').read_text())
        print(json.dumps([{'Config':{'Labels':{'org.opencontainers.image.version':pin['version'],
            'org.opencontainers.image.revision':pin['revision']}}}]))
elif command=='build':
    context=Path(sys.argv[-1])
    assert (context/'install_finite_fstab').is_file() and (context/'Containerfile').is_file()
    digest=hashlib.sha256((context/'secure-boot.der').read_bytes()).hexdigest()
    Path('context-observed.json').write_text(json.dumps({'path':str(context),'sha256':digest}))
    sys.exit(int(os.environ['FINITE_TEST_DOCKER_BUILD_STATUS']))
elif command=='run' and 'sha256sum' in sys.argv:
    if sys.argv[-1].endswith('sb_pubkey.der'):
        digest=json.loads(Path('context-observed.json').read_text())['sha256']
    else:
        digest=hashlib.sha256(Path('files/installer/install_finite_fstab').read_bytes()).hexdigest()
    print(digest+'  '+sys.argv[-1])
''')
            docker.chmod(0o755)
            for status in (42, 0):
                with self.subTest(build_status=status):
                    result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/prepare-installer.sh')],
                        cwd=root, env=dict(os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='closure-labs/finite',
                            GITHUB_SHA='a' * 40, FINITE_TEST_DOCKER_BUILD_STATUS=str(status),
                            PATH=str(root / 'bin') + ':' + os.environ['PATH']), capture_output=True)
                    self.assertEqual(result.returncode, status, result.stderr.decode())
                    observed = json.loads((root / 'context-observed.json').read_text())
                    pin = json.loads((root / 'sources/installer-security.json').read_text())
                    self.assertEqual(observed['sha256'], pin['derSha256'])
                    self.assertFalse(Path(observed['path']).exists())
                    self.assertFalse((root / 'files/installer/secure-boot.der').exists())


if __name__ == '__main__':
    unittest.main()
