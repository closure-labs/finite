#!/usr/bin/env python3
"""Exercise shell diagnostic boundaries with tiny OCI and hosted-service stubs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/ci/diagnose-built-candidate.sh'
PROFILE = 'finite'
REVISION = 'a' * 40
IDENTITY = 'v1:' + 'b' * 64
BASE_DIGEST = 'sha256:' + 'd' * 64


class DiagnoseBuiltCandidate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stubs = self.root / 'stubs'
        self.stubs.mkdir()
        (self.root / 'runner').mkdir()
        evidence = self.root / '.bluebuild'
        evidence.mkdir()
        self.config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.revision': REVISION, 'io.finite.profile': PROFILE,
            'io.finite.build-inputs': IDENTITY, 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.base.name': 'ghcr.io/ublue-os/bluefin:stable@' + BASE_DIGEST,
            'org.opencontainers.image.base.digest': BASE_DIGEST}}, 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'f' * 64]}}
        raw = json.dumps(self.config).encode()
        self.docker_id = 'sha256:' + hashlib.sha256(raw).hexdigest()
        (self.root / 'config.json').write_bytes(raw)
        self.inspected = [{'Id': self.docker_id, 'Os': 'linux', 'Architecture': 'amd64',
                          'Config': self.config['config'], 'RootFS': {'Type': 'layers', 'Layers': ['sha256:' + 'f' * 64]}}]
        (self.root / 'docker.json').write_text(json.dumps(self.inspected))
        (evidence / (PROFILE + '-image.json')).write_text(json.dumps(self.inspected))
        # Existing inspect-built may record a short immutable Docker ID; the
        # wrapper must bind it to the exact full verified ID before exporting.
        (evidence / (PROFILE + '-image-ref.txt')).write_text(self.docker_id[7:19] + '\n')
        self.publication = {'profile': PROFILE, 'revision': REVISION, 'buildIdentity': IDENTITY,
                            'publish': False, 'digest': BASE_DIGEST}
        self.save_publication()
        trust_raw = (ROOT / 'sources/bluefin-trust.json').read_bytes()
        trust = json.loads(trust_raw)
        receipt = {'schema': 1, 'repository': 'closure-labs/finite', 'sourceRevision': REVISION,
                   'trustPolicySha256': hashlib.sha256(trust_raw).hexdigest(), 'verified': [{
                       'image': 'ghcr.io/ublue-os/bluefin@' + BASE_DIGEST,
                       'keySha256': trust['keySha256'], 'signatureFormat': 'legacy'}]}
        (evidence / 'upstream-verified.json').write_text(json.dumps(receipt))
        self.environment = {**os.environ, 'PATH': str(self.stubs) + os.pathsep + os.environ['PATH'],
            'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite', 'GITHUB_REF': 'refs/heads/validation',
            'GITHUB_SHA': REVISION, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
            'RUNNER_TEMP': str(self.root / 'runner'), 'TEST_COMMANDS': str(self.root / 'commands.jsonl'),
            'GH_TOKEN': 'must-not-be-passed-to-service', 'TEST_NATIVE_STATUS': 'pass'}
        self.stub('sudo', 'import subprocess,sys\nsys.exit(subprocess.call(sys.argv[1:]))\n')
        self.stub('systemctl', 'print("MemoryPeak=12345")\n')
        self.stub('awk', 'print(os.environ.get("TEST_MEMORY_KIB","16777216"))\n')
        self.stub('docker', 'from pathlib import Path\nprint(Path("docker.json").read_text())\n')
        self.stub('skopeo', '''import hashlib,json,os,sys
from pathlib import Path
assert '--format' in sys.argv and sys.argv[sys.argv.index('--format')+1]=='v2s2'
layout=Path(sys.argv[-1][4:].removesuffix(':audit'));(layout/'blobs/sha256').mkdir(parents=True)
config=Path('config.json').read_bytes()
if os.environ.get('TEST_CONFIG_MISMATCH')=='true': config+=b' '
def blob(raw,media):
    digest=hashlib.sha256(raw).hexdigest();(layout/'blobs/sha256'/digest).write_bytes(raw)
    return {'digest':'sha256:'+digest,'size':len(raw),'mediaType':media}
config_descriptor=blob(config,'application/vnd.docker.container.image.v1+json')
layer=blob(b'tiny-layer','application/vnd.docker.image.rootfs.diff.tar.gzip')
manifest={'schemaVersion':2,'mediaType':'application/vnd.docker.distribution.manifest.v2+json','config':config_descriptor,'layers':[layer]}
descriptor=blob(json.dumps(manifest).encode(),manifest['mediaType']);descriptor['annotations']={'org.opencontainers.image.ref.name':'audit'}
if os.environ.get('TEST_CORRUPT_LAYER')=='true': (layout/'blobs/sha256'/layer['digest'][7:]).write_bytes(b'bad-layer!')
(layout/'index.json').write_text(json.dumps({'schemaVersion':2,'manifests':[descriptor]}))
(layout/'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
''')
        self.stub('systemd-run', '''import json,os,sys
from pathlib import Path
from importlib.util import module_from_spec,spec_from_file_location
position=next(i for i,a in enumerate(sys.argv) if a.endswith('/local-candidate-evidence.py'))
layout=Path(sys.argv[position+1]);output=Path(sys.argv[position+2]);output.mkdir()
image='ghcr.io/closure-labs/finite@'+json.loads((layout/'index.json').read_text())['manifests'][0]['digest']
spec=spec_from_file_location('fixture_native',sys.argv[position]);native=module_from_spec(spec);spec.loader.exec_module(native)
native.validate_candidate(layout,sys.argv[sys.argv.index('--profile')+1],sys.argv[sys.argv.index('--identity')+1],os.environ['GITHUB_SHA'])
status=os.environ['TEST_NATIVE_STATUS'];code={'pass':0,'blocked':1,'scanner-error':2,'missing':0,'wrong-image':0,'complete':0,'complete-unhealthy':0,'complete-legacy':0}[status]
if status!='missing':
    result={'schema':1,'status':'pass' if status=='wrong-image' else 'complete' if status.startswith('complete') else status,'image':image if status!='wrong-image' else 'wrong',
        'sourceType':'locally-built-unpublished','releaseEligible':False,'signatureVerified':False}
    if status.startswith('complete'):
        result.update(mode='upstream-maintained-risk' if status=='complete-legacy' else 'maintainer-decision',
                      scannerHealth='unhealthy' if status=='complete-unhealthy' else 'healthy')
    (output/'security-result.json').write_text(json.dumps(result))
sys.exit(code)
''')

    def stub(self, name, code):
        prefix = '#!' + shutil.which('python3') + '\nimport json,os,sys\n'
        prefix += 'with open(os.environ["TEST_COMMANDS"],"a") as log: log.write(json.dumps([sys.argv[0],*sys.argv[1:]])+"\\n")\n'
        path = self.stubs / name
        path.write_text(prefix + code)
        path.chmod(0o755)

    def save_publication(self):
        (self.root / '.bluebuild' / (PROFILE + '-publication.json')).write_text(json.dumps(self.publication))

    def run_wrapper(self):
        return subprocess.run(['bash', str(SCRIPT), PROFILE], cwd=self.root, env=self.environment,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)

    def commands(self):
        path = self.root / 'commands.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def result(self):
        return json.loads((self.root / '.bluebuild' / ('diagnostic-' + PROFILE) / 'security-result.json').read_text())

    def test_requires_hosted_nonmain_repository_before_any_docker_operation(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/main')]:
            original = self.environment[key]
            self.environment[key] = value
            result = self.run_wrapper()
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(any(Path(command[0]).name == 'docker' for command in self.commands()))
            self.environment[key] = original

    def test_exact_existing_docker_id_export_and_service_bounds_without_credentials(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        docker = next(command for command in commands if Path(command[0]).name == 'docker')
        self.assertEqual(docker[1:], ['image', 'inspect', self.docker_id])
        skopeo = next(command for command in commands if Path(command[0]).name == 'skopeo')
        self.assertIn('docker-daemon:' + self.docker_id, skopeo)
        self.assertNotIn('docker://', ' '.join(skopeo))
        service = next(command for command in commands if Path(command[0]).name == 'systemd-run')
        for option in ('--property=MemoryMax=10240M', '--property=MemorySwapMax=0', '--property=RuntimeMaxSec=1800',
                       '--property=NoNewPrivileges=yes', '--property=CapabilityBoundingSet='):
            self.assertIn(option, service)
        self.assertNotIn('GH_TOKEN', ' '.join(service))
        self.assertNotIn('must-not-be-passed', ' '.join(service))
        self.assertEqual(list((self.root / 'runner').iterdir()), [])
        self.assertFalse(self.result()['releaseEligible'])

    def test_config_digest_change_fails_before_scanner_and_cleans_export(self):
        self.environment['TEST_CONFIG_MISMATCH'] = 'true'
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('configuration digest differs', result.stderr)
        self.assertFalse(any(Path(command[0]).name == 'systemd-run' for command in self.commands()))
        self.assertEqual(self.result()['status'], 'scanner-error')
        self.assertEqual(list((self.root / 'runner').iterdir()), [])

    def test_layer_tampering_and_insufficient_memory_are_scanner_errors(self):
        self.environment['TEST_MEMORY_KIB'] = '4194304'
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any(Path(command[0]).name in ('docker', 'skopeo') for command in self.commands()))
        self.setUp()
        self.environment['TEST_CORRUPT_LAYER'] = 'true'
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.result()['status'], 'scanner-error')
        self.assertEqual(list((self.root / 'runner').iterdir()), [])

    def test_published_wrong_revision_or_identity_prevents_export(self):
        for key, value in [('publish', True), ('revision', 'e' * 40), ('buildIdentity', 'v1:' + 'e' * 64)]:
            with self.subTest(key=key):
                self.setUp()
                self.publication[key] = value
                self.save_publication()
                result = self.run_wrapper()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(any(Path(command[0]).name in ('docker', 'skopeo', 'systemd-run') for command in self.commands()))

    def test_native_blocked_scanner_error_and_missing_or_inconsistent_result_are_distinct(self):
        for status, code in [('blocked', 1), ('scanner-error', 2), ('missing', 2), ('wrong-image', 2)]:
            with self.subTest(status=status):
                self.setUp()
                self.environment['TEST_NATIVE_STATUS'] = status
                result = self.run_wrapper()
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(self.result()['status'], 'blocked' if status == 'blocked' else 'scanner-error')
                self.assertEqual(list((self.root / 'runner').iterdir()), [])

    def test_healthy_maintainer_completion_remains_unsigned_nonrelease_diagnostic(self):
        for status, expected in (('complete', 0), ('complete-unhealthy', 2), ('complete-legacy', 2)):
            with self.subTest(status=status):
                self.setUp()
                self.environment['TEST_NATIVE_STATUS'] = status
                result = self.run_wrapper()
                self.assertEqual(result.returncode, expected, result.stderr)
                retained = self.result()
                self.assertFalse(retained['releaseEligible'])
                self.assertFalse(retained['signatureVerified'])
                self.assertEqual(retained['status'], 'complete' if expected == 0 else 'scanner-error')

    def test_changed_docker_image_and_stale_output_are_rejected(self):
        self.inspected[0]['Config']['Labels']['io.finite.profile'] = 'bluefin-next'
        (self.root / 'docker.json').write_text(json.dumps(self.inspected))
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any(Path(command[0]).name == 'skopeo' for command in self.commands()))
        before = (self.root / '.bluebuild' / ('diagnostic-' + PROFILE) / 'security-result.json').read_bytes()
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.root / '.bluebuild' / ('diagnostic-' + PROFILE) / 'security-result.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
