#!/usr/bin/env python3
"""Certificate corruption fails before any installer network/container work."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
            docker.write_text('#!' + shutil.which('bash') + '\ntouch docker-called\nexit 99\n')
            docker.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/prepare-installer.sh')],
                cwd=root, env=dict(os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='closure-labs/finite',
                                   PATH=str(root / 'bin') + ':' + os.environ['PATH']), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'docker-called').exists())

    def test_compression_scope_rejection_stops_before_container_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'bin').mkdir()
            docker=root/'bin/docker';docker.write_text('#!'+shutil.which('bash')+'\ntouch docker-called\nexit 99\n');docker.chmod(0o755)
            env=dict(os.environ,GITHUB_ACTIONS='true',GITHUB_REPOSITORY='closure-labs/finite',GITHUB_SHA='a'*40,PATH=str(root/'bin')+':'+os.environ['PATH'])
            for settings in ({'FINITE_INSTALLER_COMPRESSION':'zstd','FINITE_VALIDATION_ONLY':'false','GITHUB_REF':'refs/heads/main'},
                             {'FINITE_INSTALLER_COMPRESSION':'zstd','FINITE_VALIDATION_ONLY':'true','PREVIOUS_DIGEST':''},
                             {'FINITE_INSTALLER_COMPRESSION':'gzip'}):
                with self.subTest(settings=settings):
                    result=subprocess.run(['bash',str(ROOT/'scripts/bluebuild/prepare-installer.sh')],cwd=root,env={**env,**settings},capture_output=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertFalse((root/'docker-called').exists())

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
            docker.write_text('#!' + sys.executable + '\n' + '''
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
    observed={'path':str(context),'sha256':digest,'containerfile':(context/'Containerfile').read_text()}
    if 'finite-installer-compression.py' in observed['containerfile']:
        import runpy
        config=context/'installed-lorax.conf'
        config.write_text('[lorax]'+chr(10)+'logdir = /custom-logs'+chr(10)+'[compression]'+chr(10)+'type = xz'+chr(10)+'args = '+chr(10)+'bcj = on'+chr(10))
        runpy.run_path(str(context/'installer-compression.py'))['merge'](config,context/'lorax-zstd.conf')
        observed['configuration']=config.read_text()
    Path('context-observed.json').write_text(json.dumps(observed))
    sys.exit(int(os.environ['FINITE_TEST_DOCKER_BUILD_STATUS']))
elif command=='run' and 'cat' in sys.argv:
    value=json.loads(Path('context-observed.json').read_text())['configuration']
    if os.environ.get('FINITE_TEST_CORRUPT_COMPRESSION')=='true':value=value.replace('type = zstd','type = xz')
    print(value,end='')
elif command=='run' and 'sha256sum' in sys.argv:
    if sys.argv[-1].endswith('sb_pubkey.der'):
        digest=json.loads(Path('context-observed.json').read_text())['sha256']
    else:
        digest=hashlib.sha256(Path('files/installer/install_finite_fstab').read_bytes()).hexdigest()
    print(digest+'  '+sys.argv[-1])
''')
            docker.chmod(0o755)
            for compression, status, corrupt in [('default',42,False),('default',0,False),('zstd',42,False),('zstd',0,False),('zstd',1,True)]:
                with self.subTest(compression=compression,build_status=status,corrupt=corrupt):
                    result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/prepare-installer.sh')],
                        cwd=root, env=dict(os.environ, GITHUB_ACTIONS='true', GITHUB_REPOSITORY='closure-labs/finite',
                            GITHUB_SHA='a' * 40, FINITE_TEST_DOCKER_BUILD_STATUS=str(0 if corrupt else status),
                            FINITE_INSTALLER_COMPRESSION=compression, FINITE_TEST_CORRUPT_COMPRESSION=str(corrupt).lower(),
                            FINITE_VALIDATION_ONLY='true',PREVIOUS_DIGEST='sha256:'+'e'*64,GITHUB_REF='refs/heads/ci/qualification-benchmark',
                            GITHUB_EVENT_NAME='workflow_dispatch',
                            GITHUB_WORKFLOW_REF='closure-labs/finite/.github/workflows/benchmark-image-tools.yml@refs/heads/ci/qualification-benchmark',
                            PATH=str(root / 'bin') + ':' + os.environ['PATH']), capture_output=True)
                    if corrupt:self.assertNotEqual(result.returncode,0)
                    else:self.assertEqual(result.returncode,status,result.stderr.decode())
                    observed = json.loads((root / 'context-observed.json').read_text())
                    pin = json.loads((root / 'sources/installer-security.json').read_text())
                    self.assertEqual(observed['sha256'], pin['derSha256'])
                    self.assertFalse(Path(observed['path']).exists())
                    self.assertFalse((root / 'files/installer/secure-boot.der').exists())
                    if status==0:
                        installer=json.loads((root/'.bluebuild/iso/installer.json').read_text())
                        if compression=='default':
                            self.assertNotIn('diagnosticCompression',installer)
                            self.assertEqual(observed['containerfile'],(root/'files/installer/Containerfile').read_text())
                        else:
                            self.assertIn('logdir = /custom-logs',observed['configuration'])
                            actual=hashlib.sha256(observed['configuration'].encode()).hexdigest()
                            self.assertEqual(installer['diagnosticCompression']['configurationSha256'],actual)
                            self.assertEqual(installer['diagnosticCompression']['presetSha256'],hashlib.sha256((root/'files/installer/lorax-zstd.conf').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
