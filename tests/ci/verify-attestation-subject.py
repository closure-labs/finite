#!/usr/bin/env python3
"""An attestation cannot relabel another image's native SBOM."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('attestation_subject', ROOT / 'scripts/ci/verify-attestation-subject.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class Subject(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        revision, identity, base = 'a' * 40, 'v1:' + 'b' * 64, 'ghcr.io/ublue-os/bluefin@sha256:' + 'c' * 64
        config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.revision': revision, 'io.finite.profile': 'finite', 'io.finite.build-inputs': identity,
            'org.opencontainers.image.base.name': base.replace('@', ':stable@'), 'org.opencontainers.image.base.digest': base.split('@')[1]}}}
        config_raw = json.dumps(config)
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'size': len(config_raw.encode()),
                               'digest': 'sha256:' + hashlib.sha256(config_raw.encode()).hexdigest()}}
        manifest_raw = json.dumps(manifest)
        self.digest = 'sha256:' + hashlib.sha256(manifest_raw.encode()).hexdigest()
        self.image = 'ghcr.io/closure-labs/finite@' + self.digest
        baseline = {'schema': 1, 'status': 'verified', 'image': self.image, 'profile': 'finite',
                    'sourceRevision': revision, 'buildIdentity': identity, 'baseImage': base, 'trustPolicySha256': 'd' * 64}
        sbom = {'source': {'type': 'directory', 'metadata': {'path': '/tmp/fixture-rootfs'}},
                'distro': {'id': 'bluefin', 'versionID': '44'}, 'artifacts': [
                    {'id': str(i), 'type': 'rpm', 'foundBy': 'rpm-db-cataloger', 'name': 'pkg-' + str(i), 'version': '1'} for i in range(100)]}
        sbom['artifacts'][0].update(name='fedora-release-common', version='44-18')
        self.write('image-manifest.json', manifest)
        self.write('image-config.json', config)
        self.write('sbom.syft.json', sbom)
        self.write('sbom.spdx.json', {'spdxVersion': 'SPDX-2.3', 'SPDXID': 'SPDXRef-DOCUMENT', 'packages': []})
        self.write('extraction.json', {'schema': 1, 'method': 'umoci-rootless', 'toolVersion': 'umoci version 0.6.0',
                                     'signedDigest': self.digest, 'scannedManifestDigest': self.digest,
                                     'sourcePath': '/tmp/fixture-rootfs', 'basePath': '/tmp/fixture-rootfs', 'catalogers': 'image',
                                     'sbomSha256': subject.inventory.sha256(self.directory / 'sbom.syft.json')})
        self.write('security-result.json', {'schema': 1, 'status': 'pass', 'image': self.image, 'approvedBaseline': baseline})
        self.record = {'schema': 1, 'image': self.image, 'platformDigest': self.digest,
                       'files': {name: subject.inventory.sha256(self.directory / name) for name in subject.inventory.REQUIRED}}
        self.write('inventory-provenance.json', self.record)

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def verify(self, profile='finite', digest=None):
        return subject.verify(self.directory, profile, digest or self.digest)

    def test_authenticates_native_source_and_exact_spdx_bytes(self):
        receipt = self.verify()
        self.assertEqual(receipt['image'], self.image)
        self.assertEqual(receipt['sbomSha256'], subject.inventory.sha256(self.directory / 'sbom.spdx.json'))

    def test_wrong_image_and_profile_are_rejected(self):
        with self.assertRaises(ValueError): self.verify(digest='sha256:' + 'e' * 64)
        with self.assertRaisesRegex(ValueError, 'profile'): self.verify(profile='finite-dev')

    def test_foreign_spdx_replacement_fails_before_attestation(self):
        self.write('sbom.spdx.json', {'spdxVersion': 'SPDX-2.3', 'SPDXID': 'SPDXRef-DOCUMENT', 'packages': ['another image']})
        with self.assertRaisesRegex(ValueError, 'content hash/path mismatch'): self.verify()

    def test_relabelled_native_sbom_source_is_rejected_even_with_updated_hashes(self):
        sbom = json.loads((self.directory / 'sbom.syft.json').read_text())
        sbom['source']['metadata']['path'] = '/tmp/foreign-rootfs'
        self.write('sbom.syft.json', sbom)
        extraction = json.loads((self.directory / 'extraction.json').read_text())
        extraction['sbomSha256'] = subject.inventory.sha256(self.directory / 'sbom.syft.json')
        self.write('extraction.json', extraction)
        for name in ('sbom.syft.json', 'extraction.json'):
            self.record['files'][name] = subject.inventory.sha256(self.directory / name)
        self.write('inventory-provenance.json', self.record)
        with self.assertRaisesRegex(ValueError, 'extraction provenance'): self.verify()

    def test_wrong_platform_manifest_binding_is_rejected(self):
        self.record['platformDigest'] = 'sha256:' + 'f' * 64
        self.write('inventory-provenance.json', self.record)
        with self.assertRaisesRegex(ValueError, 'platform digest'): self.verify()

    def test_unhealthy_complete_or_blocked_result_cannot_be_attested(self):
        report = json.loads((self.directory / 'security-result.json').read_text())
        for fields in ({'status': 'scanner-error'}, {'status': 'blocked'},
                       {'status': 'complete', 'mode': 'maintainer-decision', 'scannerHealth': 'failed'}):
            with self.subTest(fields=fields):
                self.write('security-result.json', {**report, **fields})
                with self.assertRaisesRegex(ValueError, 'healthy native scan'): self.verify()
        self.write('security-result.json', {**report, 'status': 'complete', 'mode': 'maintainer-decision', 'scannerHealth': 'healthy'})
        self.assertEqual(self.verify()['image'], self.image)

    def test_symlink_missing_hash_and_duplicate_metadata_are_rejected(self):
        path = self.directory / 'sbom.spdx.json'
        outside = self.directory / 'outside.json'
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'hash/path mismatch'): self.verify()
        path.unlink()
        outside.rename(path)
        self.record['files'].pop('sbom.spdx.json')
        self.write('inventory-provenance.json', self.record)
        with self.assertRaisesRegex(ValueError, 'content bindings'): self.verify()
        (self.directory / 'security-result.json').write_text('{"image":"a","image":"b"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.verify()

    def test_workflow_checks_subject_before_registry_login_or_attestation(self):
        import yaml
        document = yaml.safe_load((ROOT / '.github/workflows/attest-image.yml').read_text())
        steps = document['jobs']['attest']['steps']
        check = next(i for i, step in enumerate(steps) if 'verify-attestation-subject.py --directory' in step.get('run', ''))
        credentials = next(i for i, step in enumerate(steps) if 'docker login' in step.get('run', ''))
        attest = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/attest@'))
        self.assertLess(check, credentials)
        self.assertLess(check, attest)


if __name__ == '__main__':
    unittest.main()
