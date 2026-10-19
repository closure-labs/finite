#!/usr/bin/env python3
"""An attestation cannot relabel another image's native SBOM."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import subprocess
import unittest
from unittest.mock import patch

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

    def external_manifest(self, receipt):
        raw = (self.directory / 'image-manifest.json').read_bytes()
        return {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'artifactType': subject.SPDX_TYPE,
                'subject': {'mediaType': json.loads(raw)['mediaType'], 'digest': self.digest, 'size': len(raw)},
                'layers': [{'mediaType': subject.SPDX_TYPE, 'digest': 'sha256:' + receipt['sbomSha256'],
                            'size': receipt['sbomSize'], 'annotations': {'org.opencontainers.image.title': 'sbom.spdx.json'}}]}

    def test_external_predicate_binds_original_full_document_without_rewriting(self):
        document = {'spdxVersion': 'SPDX-2.3', 'SPDXID': 'SPDXRef-DOCUMENT',
                    'packages': [{'name': 'Unicode café', 'licenseInfoFromFiles': ['MIT', 'Apache-2.0']}],
                    'files': [{'fileName': '/full/original', 'checksums': [{'algorithm': 'SHA256', 'checksumValue': 'a' * 64}]}],
                    'relationships': [{'spdxElementId': 'SPDXRef-DOCUMENT', 'relationshipType': 'DESCRIBES', 'relatedSpdxElement': 'SPDXRef-test'}],
                    'annotations': [{'comment': 'retain every field'}]}
        self.write('sbom.spdx.json', document)
        self.record['files']['sbom.spdx.json'] = subject.inventory.sha256(self.directory / 'sbom.spdx.json')
        self.write('inventory-provenance.json', self.record)
        originals = {path.name: path.read_bytes() for path in self.directory.iterdir() if path.is_file()}
        receipt = self.verify()
        raw = json.dumps(self.external_manifest(receipt)).encode()
        def registry(args, **kwargs):
            if args[0] == 'attach':
                Path(args[args.index('--export-manifest') + 1]).write_bytes(raw)
                self.assertEqual(args[-2], self.image)
                self.assertEqual(args[-1], 'sbom.spdx.json:application/spdx+json')
            elif args[0] == 'manifest':
                self.assertEqual(args[-1], subject.REGISTRY + '@sha256:' + hashlib.sha256(raw).hexdigest())
                return raw
            else:
                Path(args[-1]).write_bytes(originals['sbom.spdx.json'])
            return b''
        output = self.directory.parent / (self.directory.name + '-generated')
        self.addCleanup(lambda: __import__('shutil').rmtree(output, ignore_errors=True))
        with patch.object(subject, 'registry_command', side_effect=registry):
            predicate = subject.publish(self.directory, 'finite', self.digest, output)
        self.assertEqual(json.loads((output / 'sbom-reference.json').read_text()), predicate)
        self.assertEqual(predicate['sbom']['sha256'], receipt['sbomSha256'])
        self.assertEqual(predicate['sbom']['size'], len(originals['sbom.spdx.json']))
        self.assertEqual(originals, {path.name: path.read_bytes() for path in self.directory.iterdir() if path.is_file()})
        self.assertEqual(json.loads(originals['sbom.spdx.json']), document)

    def test_external_manifest_rejects_wrong_subject_and_any_changed_full_document_descriptor(self):
        receipt = self.verify()
        manifest = self.external_manifest(receipt)
        variants = []
        for field, value in [('digest', 'sha256:' + 'f' * 64), ('size', 1), ('size', True), ('mediaType', 'wrong')]:
            other = deepcopy(manifest); other['subject'][field] = value; variants.append(other)
        for field, value in [('digest', 'sha256:' + 'f' * 64), ('size', 1), ('size', True), ('mediaType', 'wrong'),
                             ('annotations', {}), ('annotations', []), ('annotations', {'org.opencontainers.image.title': 'truncated.json'})]:
            other = deepcopy(manifest); other['layers'][0][field] = value; variants.append(other)
        for value in ([], [manifest['layers'][0], manifest['layers'][0]], {}, [None]):
            other = deepcopy(manifest); other['layers'] = value; variants.append(other)
        for field, value in [('artifactType', 'wrong'), ('schemaVersion', 1), ('mediaType', 'wrong'), ('subject', [])]:
            other = deepcopy(manifest); other[field] = value; variants.append(other)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.reference_predicate(receipt, json.dumps(value).encode(), (self.directory / 'image-manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            subject.reference_predicate(receipt, json.dumps(manifest).encode(), (self.directory / 'image-manifest.json').read_bytes() + b' ')
        for raw in (b'{', b'{"schemaVersion":2,"schemaVersion":2}', b'x' * (subject.MAX_MANIFEST + 1)):
            with self.assertRaises(ValueError):
                subject.reference_predicate(receipt, raw, (self.directory / 'image-manifest.json').read_bytes())

    def test_oversized_native_document_fails_before_transport(self):
        with (self.directory / 'sbom.spdx.json').open('r+b') as stream:
            stream.truncate(subject.inventory.FILES['sbom.spdx.json'] * 1024**2 + 1)
        with patch.object(subject, 'registry_command') as registry, self.assertRaises(ValueError):
            subject.publish(self.directory, 'finite', self.digest, self.directory / 'generated')
        registry.assert_not_called()

    def test_registry_command_has_execution_and_file_output_bounds(self):
        def process(args, **kwargs):
            self.assertEqual(kwargs['timeout'], 300)
            self.assertIsNotNone(kwargs['preexec_fn'])
            self.assertEqual(kwargs['stderr'], subject.subprocess.DEVNULL)
            kwargs['stdout'].write(b'x' * (subject.MAX_MANIFEST + 1))
        with patch.object(subject.subprocess, 'run', side_effect=process), self.assertRaisesRegex(ValueError, 'manifest bound'):
            subject.registry_command(['manifest', 'fetch', self.image])

    def test_remote_manifest_or_blob_integrity_failure_never_creates_predicate(self):
        receipt = self.verify()
        raw = json.dumps(self.external_manifest(receipt)).encode()
        for bad in ('manifest', 'blob'):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'generated'
                def registry(args, **kwargs):
                    if args[0] == 'attach':
                        Path(args[args.index('--export-manifest') + 1]).write_bytes(raw)
                    elif args[0] == 'manifest':
                        return raw + b' ' if bad == 'manifest' else raw
                    else:
                        Path(args[-1]).write_bytes(b'changed')
                    return b''
                with patch.object(subject, 'registry_command', side_effect=registry), self.assertRaises(ValueError):
                    subject.publish(self.directory, 'finite', self.digest, output)
                self.assertFalse((output / 'sbom-reference.json').exists())
        with patch.object(subject, 'registry_command') as registry, self.assertRaises(ValueError):
            subject.publish(self.directory, 'finite', self.digest, self.directory / 'generated')
        registry.assert_not_called()

    def test_only_nonresumed_current_source_can_generate_new_build_provenance(self):
        receipt = self.verify()
        self.assertEqual(receipt['sourceRevision'], 'a' * 40)
        for current, resume, expected in [('a' * 40, '', True), ('a' * 40, '123', False),
                                           ('b' * 40, '123', False), ('b' * 40, '', False)]:
            with self.subTest(current=current, resume=resume):
                self.assertEqual(subject.generate_provenance(receipt, current, resume), expected)
        for current, resume in [('not-a-revision', ''), ('a' * 40, '123;true')]:
            with self.assertRaises(ValueError):
                subject.generate_provenance(receipt, current, resume)

    def test_reuse_verifies_exact_image_original_source_and_required_provenance_identity(self):
        import yaml
        document = yaml.safe_load((ROOT / '.github/workflows/attest-image.yml').read_text())
        steps = document['jobs']['attest']['steps']
        original = next(step for step in steps if step.get('name') == 'Verify original build provenance for reused immutable image')
        fresh = next(step for step in steps if step.get('name') == 'Attest build provenance')
        self.assertEqual(original['if'], "steps.verified.outputs.generate_provenance != 'true'")
        self.assertEqual(fresh['if'], "steps.verified.outputs.generate_provenance == 'true'")
        self.assertEqual(original['env']['GH_TOKEN'], '${{ github.token }}')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gh = root / 'gh'
            interpreter = '#!' + shutil.which('bash') + '\n'
            gh.write_text(interpreter + 'printf "%s\\n" "$@" > "$CAPTURE"\nexit "$VERIFY_STATUS"\n')
            gh.chmod(0o700)
            nix = root / 'nix'
            nix.write_text(interpreter + 'while [[ $1 != --command ]]; do shift; done\nshift\nexec "$@"\n')
            nix.chmod(0o700)
            capture = root / 'arguments'
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], DIGEST=self.digest,
                       ORIGINAL_REVISION='a' * 40, CAPTURE=str(capture), VERIFY_STATUS='0')
            subprocess.run(['bash', '-e', '-c', original['run']], env=env, check=True)
            self.assertEqual(capture.read_text().splitlines(), ['attestation', 'verify', 'oci://' + self.image,
                '--repo', 'closure-labs/finite', '--signer-workflow', 'closure-labs/finite/.github/workflows/attest-image.yml',
                '--source-digest', 'a' * 40, '--source-ref', 'refs/heads/main', '--deny-self-hosted-runners',
                '--predicate-type', 'https://slsa.dev/provenance/v1'])
            env['VERIFY_STATUS'] = '1'
            self.assertNotEqual(subprocess.run(['bash', '-e', '-c', original['run']], env=env).returncode, 0)
        publish = next(step for step in steps if '--publish-reference' in step.get('run', ''))
        self.assertLess(steps.index(original), steps.index(publish))
        self.assertIn('nix develop --file lib/ci-tools.nix shell --command gh', original['run'])
        self.assertIn('nix shell --file lib/ci-tools.nix oras --command python3', publish['run'])
        binding = next(step for step in steps if step.get('id') == 'verified')
        self.assertIn('--current-revision "$GITHUB_SHA" --resume-run "$RESUME_RUN"', binding['run'])
        self.assertIn('> .bluebuild/attestation-subject.json', binding['run'])
        self.assertEqual(binding['env']['RESUME_RUN'], '${{ inputs.resume_run }}')
        publication = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())
        self.assertEqual(publication['jobs']['attest']['with']['resume_run'], '${{ inputs.resume_run }}')

    def test_workflow_checks_subject_before_registry_login_or_attestation(self):
        import yaml
        document = yaml.safe_load((ROOT / '.github/workflows/attest-image.yml').read_text())
        steps = document['jobs']['attest']['steps']
        check = next(i for i, step in enumerate(steps) if 'verify-attestation-subject.py --directory' in step.get('run', ''))
        credentials = next(i for i, step in enumerate(steps) if 'docker login' in step.get('run', ''))
        attest = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/attest@'))
        self.assertLess(check, credentials)
        self.assertLess(check, attest)
        publish = next(i for i, step in enumerate(steps) if '--publish-reference' in step.get('run', ''))
        self.assertLess(publish, attest)
        sbom_attest = steps[-2]['with']
        self.assertEqual(sbom_attest['predicate-type'], subject.PREDICATE_TYPE)
        self.assertEqual(sbom_attest['predicate-path'], '.bluebuild/sbom-attestation/sbom-reference.json')
        self.assertNotIn('sbom-path', sbom_attest)


if __name__ == '__main__':
    unittest.main()
