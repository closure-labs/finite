#!/usr/bin/env python3
"""Local metadata tests only; image extraction/cataloging is mocked."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('local_candidate', ROOT / 'scripts/ci/local-candidate-evidence.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
REVISION = 'a' * 40
IDENTITY = 'v1:' + 'b' * 64
PROFILE = 'finite'
OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'


def confirmed_risk(image, profile='finite'):
    return {'id': 'confirmed-fixture', 'digest': image.split('@')[1], 'profile': profile,
            'platform': 'linux/amd64', 'component': 'pkg:rpm/fedora/example@1', 'severity': 'Critical',
            'impact': 'Host compromise', 'reason': 'Fixture review', 'attackerPath': 'Hostile imported file',
            'selinuxAssessment': 'Applicable confinement does not prevent the confirmed path',
            'reviewedBy': 'Fixture reviewer', 'reviewedAt': '2026-10-12T00:00:00Z',
            'advisories': ['CVE-2026-1234'], 'locations': ['/usr/bin/example'],
            'officialSources': ['https://example.org/advisory'], 'severityEvidence': ['Official Critical rating'],
            'affectedCodeEvidence': ['Exact binary and vulnerable code reviewed'],
            'preconditions': ['Supported desktop import'], 'selinuxEvidence': ['Relevant domain reviewed']}


class LocalCandidate(unittest.TestCase):
    def setUp(self):
        self.policy = mod.policy_module.load_policy(ROOT / 'automation/security/image-policy.json')
        self.policy.pop('mode', None)  # Original fixtures remain explicitly legacy.
        self.policy.pop('blockingBasis', None)
        self.policy.pop('confirmedDesktopRisks', None)
        policy_loader = patch.object(mod.policy_module, 'load_policy', return_value=self.policy)
        policy_loader.start()
        self.addCleanup(policy_loader.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.layout = self.root / 'layout'
        (self.layout / 'blobs/sha256').mkdir(parents=True)
        mod.write_json(self.layout / 'oci-layout', {'imageLayoutVersion': '1.0.0'})
        self.config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.revision': REVISION,
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.base.name': 'ghcr.io/ublue-os/bluefin:stable@sha256:' + 'd' * 64,
            'org.opencontainers.image.base.digest': 'sha256:' + 'd' * 64,
            'io.finite.profile': PROFILE, 'io.finite.build-inputs': IDENTITY}},
            'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'c' * 64]}}
        self.layer = self.blob(b'metadata-only-test-layer', 'application/vnd.oci.image.layer.v1.tar')
        self.rebuild()

    def blob(self, data, media_type):
        raw = data if isinstance(data, bytes) else json.dumps(data, separators=(',', ':')).encode()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        (self.layout / 'blobs/sha256' / digest[7:]).write_bytes(raw)
        return {'mediaType': media_type, 'digest': digest, 'size': len(raw)}

    def rebuild(self, indexed=False):
        self.config_descriptor = self.blob(self.config, 'application/vnd.oci.image.config.v1+json')
        manifest = {'schemaVersion': 2, 'mediaType': OCI_MANIFEST,
                    'config': self.config_descriptor, 'layers': [self.layer]}
        self.manifest = self.blob(manifest, OCI_MANIFEST)
        descriptor = self.manifest
        if indexed:
            child = {**self.manifest, 'platform': {'os': 'linux', 'architecture': 'amd64'}}
            descriptor = self.blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                                    'manifests': [child]}, 'application/vnd.oci.image.index.v1+json')
        self.descriptor = {**descriptor, 'annotations': {'org.opencontainers.image.ref.name': 'audit'}}
        mod.write_json(self.layout / 'index.json', {'schemaVersion': 2, 'manifests': [self.descriptor]})

    def validate(self):
        return mod.validate_candidate(self.layout, PROFILE, IDENTITY, REVISION)

    def test_direct_and_indexed_manifest_binding(self):
        for indexed in (False, True):
            self.rebuild(indexed)
            result = self.validate()
            self.assertEqual(result['image'], 'ghcr.io/closure-labs/finite@' + self.descriptor['digest'])
            self.assertEqual(result['platformDigest'], self.manifest['digest'])
            self.assertEqual(result['configurationDigest'], self.config_descriptor['digest'])
            self.assertEqual(result['layers'], 1)

    def test_configuration_identity_and_platform_are_exact(self):
        changes = [('os', 'windows'), ('architecture', 'arm64'),
                   ('org.opencontainers.image.revision', 'd' * 40),
                   ('org.opencontainers.image.source', 'https://github.com/other/repository'),
                   ('io.finite.profile', 'bluefin-next'), ('io.finite.build-inputs', 'v1:' + 'd' * 64)]
        original = copy.deepcopy(self.config)
        for key, value in changes:
            with self.subTest(key=key):
                self.config = copy.deepcopy(original)
                if key in ('os', 'architecture'):
                    self.config[key] = value
                else:
                    self.config['config']['Labels'][key] = value
                self.rebuild()
                with self.assertRaisesRegex(ValueError, 'configuration'):
                    self.validate()

    def test_config_and_manifest_byte_tampering_fail(self):
        for descriptor in (self.config_descriptor, self.manifest):
            with self.subTest(digest=descriptor['digest']):
                path = self.layout / 'blobs/sha256' / descriptor['digest'][7:]
                original = path.read_bytes()
                # Preserve length and valid JSON so SHA validation is exercised.
                path.write_bytes(original.replace(b'linux', b'linuz') if b'linux' in original else original.replace(b'config', b'confix'))
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    self.validate()
                path.write_bytes(original)

    def test_index_requires_unique_audit_entry(self):
        for descriptors in ([], [self.descriptor, self.descriptor],
                            [{**self.descriptor, 'annotations': {}}],
                            [{**self.descriptor, 'annotations': {'org.opencontainers.image.ref.name': 'other'}}]):
            with self.subTest(descriptors=descriptors):
                mod.write_json(self.layout / 'index.json', {'schemaVersion': 2, 'manifests': descriptors})
                with self.assertRaisesRegex(ValueError, 'unambiguous audit'):
                    self.validate()

    def test_index_platform_ambiguity_rejected(self):
        child = {**self.manifest, 'platform': {'os': 'linux', 'architecture': 'amd64'}}
        descriptor = self.blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                                'manifests': [child, child]}, 'application/vnd.oci.image.index.v1+json')
        descriptor['annotations'] = {'org.opencontainers.image.ref.name': 'audit'}
        mod.write_json(self.layout / 'index.json', {'schemaVersion': 2, 'manifests': [descriptor]})
        with self.assertRaisesRegex(ValueError, 'one supported linux/amd64'):
            self.validate()

    def test_descriptor_traversal_foreign_url_and_boolean_size_rejected(self):
        for change in ({'digest': 'sha256:../../escape'}, {'size': True}, {'urls': ['https://example.invalid/layer']},
                       {'mediaType': 'unreviewed'}, {'size': self.descriptor['size'] + 1}):
            with self.subTest(change=change):
                descriptor = {**self.descriptor, **change}
                mod.write_json(self.layout / 'index.json', {'schemaVersion': 2, 'manifests': [descriptor]})
                with self.assertRaises(ValueError):
                    self.validate()

    def test_metadata_size_and_duplicate_keys_rejected(self):
        path = self.layout / 'index.json'
        path.write_bytes(b'x' * (mod.LIMIT + 1))
        with self.assertRaisesRegex(ValueError, 'bounded'):
            self.validate()
        path.write_text('{"schemaVersion":2,"schemaVersion":2,"manifests":[]}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            self.validate()

    def test_input_and_blob_symlinks_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.layout, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            mod.validate_candidate(alias, PROFILE, IDENTITY, REVISION)
        for name in ('index.json', 'blobs/sha256/' + self.config_descriptor['digest'][7:],
                     'blobs/sha256/' + self.layer['digest'][7:]):
            with self.subTest(name=name):
                path = self.layout / name
                target = self.root / 'saved'
                path.rename(target)
                path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, 'Symlink'):
                    self.validate()
                path.unlink()
                target.rename(path)

    def test_parent_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'traversal'):
            mod.validate_candidate(self.layout / '..' / 'layout', PROFILE, IDENTITY, REVISION)

    def test_missing_layer_or_diff_id_mismatch_rejected(self):
        path = self.layout / 'blobs/sha256' / self.layer['digest'][7:]
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.validate()
        self.layer = self.blob(b'metadata-only-test-layer', 'application/vnd.oci.image.layer.v1.tar')
        self.config['rootfs']['diff_ids'] = []
        self.rebuild()
        with self.assertRaisesRegex(ValueError, 'layer inventory'):
            self.validate()

    def test_same_size_layer_tampering_is_rejected_before_scan(self):
        path = self.layout / 'blobs/sha256' / self.layer['digest'][7:]
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        self.assertEqual(path.stat().st_size, self.layer['size'])
        with self.assertRaisesRegex(ValueError, 'layer blob digest mismatch'):
            self.validate()
        output = self.root / 'tampered-layer'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        scan.assert_not_called()
        result = json.loads((output / 'security-result.json').read_text())
        self.assertEqual(result['status'], 'scanner-error')
        self.assertFalse(result['releaseEligible'])

    def test_hosted_boundary_precedes_output_creation(self):
        output = self.root / 'evidence'
        with patch.dict(mod.os.environ, {}, clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        scan.assert_not_called()
        self.assertFalse(output.exists())

    def environment(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite', 'GITHUB_SHA': REVISION,
                'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}

    def result(self, status):
        return {'schema': 1, 'status': status, 'image': self.validate()['image'], 'scannedAt': '2026-10-12T00:00:00Z',
                'scanner': 'fixture', 'policySha256': 'd' * 64, 'coverage': {'effective': 'fedora:44'},
                'matches': 1, 'blocked': [{}] if status == 'blocked' else [], 'exceptionsApplied': [],
                'mode': 'fixable-severity', 'advisories': [], 'observations': [], 'releaseBlockers': []}

    def context(self):
        return {'schema': 1, 'status': 'verified', 'image': self.validate()['image'], 'profile': PROFILE,
                'sourceRevision': REVISION, 'buildIdentity': IDENTITY,
                'baseImage': 'ghcr.io/ublue-os/bluefin@sha256:' + 'd' * 64,
                'trustPolicySha256': mod.policy_module.file_sha256(ROOT / 'sources/bluefin-trust.json')}

    def test_risk_mode_requires_context_before_scanner_launch(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        output = self.root / 'missing-context'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        scan.assert_not_called()
        self.assertIn('approved baseline', json.loads((output / 'security-result.json').read_text())['error'])

    def test_supplied_context_is_exactly_bound_and_advisories_remain_visible(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        context = self.context()
        path = self.root / 'approved.json'
        mod.write_json(path, context)
        output = self.root / 'risk-evidence'
        result = self.result('pass')
        observation = {'component': 'pkg:rpm/fedora/example@1', 'advisory': 'CVE-2026-1', 'severity': 'High',
                       'knownExploited': False, 'fixVersions': ['2'], 'disposition': 'advisory'}
        result.update(mode='upstream-maintained-risk', approvedBaseline=context,
                      advisories=[observation], observations=[observation])
        with patch.dict(mod.os.environ, self.environment(), clear=True), \
             patch.object(mod, 'scan_candidate', return_value=result) as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                       '--approved-baseline', str(path)]), 0)
        self.assertEqual(scan.call_args.kwargs['approved_baseline'], context)
        self.assertEqual((output / 'approved-baseline.json').read_bytes(), path.read_bytes())
        provenance = json.loads((output / 'source-provenance.json').read_text())
        self.assertEqual(provenance['approvedBaselineEvidenceSha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        summary = json.loads((output / 'security-summary.json').read_text())
        self.assertEqual(summary['blockingRecords'], 0)
        self.assertEqual(summary['advisoryRecords'], 1)
        self.assertEqual(summary['observationRecords'], 1)
        self.assertFalse(summary['releaseEligible'])
        self.assertFalse(summary['signatureVerified'])

    def test_malformed_or_mismatched_context_never_launches_scanner(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        context = self.context()
        for key, value in [('schema', True), ('status', 'assumed'), ('image', 'ghcr.io/closure-labs/finite@sha256:' + 'e' * 64),
                           ('profile', 'bluefin-next'), ('sourceRevision', 'e' * 40), ('buildIdentity', 'v1:' + 'e' * 64),
                           ('trustPolicySha256', 'e' * 64), ('baseImage', 'ghcr.io/ublue-os/bluefin@sha256:' + 'e' * 64)]:
            with self.subTest(key=key):
                path = self.root / ('context-' + key + '.json')
                mod.write_json(path, {**context, key: value})
                output = self.root / ('mismatched-' + key)
                with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
                    self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                               '--approved-baseline', str(path)]), 2)
                scan.assert_not_called()
                self.assertFalse(json.loads((output / 'security-result.json').read_text())['releaseEligible'])

    def test_context_symlink_and_missing_advisory_result_fail_closed(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        context = self.context()
        path = self.root / 'context.json'
        mod.write_json(path, context)
        alias = self.root / 'context-link.json'
        alias.symlink_to(path)
        output = self.root / 'context-link-error'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                       '--approved-baseline', str(alias)]), 2)
        scan.assert_not_called()
        result = self.result('pass')
        result.update(mode='upstream-maintained-risk', approvedBaseline=context)
        result.pop('advisories')
        output = self.root / 'missing-advisory-result'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate', return_value=result):
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                       '--approved-baseline', str(path)]), 2)
        self.assertEqual(json.loads((output / 'security-result.json').read_text())['status'], 'scanner-error')

    def test_critical_only_baseline_and_exact_mode_are_required(self):
        self.policy['mode'] = 'desktop-critical-only'
        output = self.root / 'critical-no-context'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        scan.assert_not_called()
        context = self.context()
        path = self.root / 'critical-context.json'
        mod.write_json(path, context)
        for mode, expected in [('desktop-critical-only', 0), ('upstream-maintained-risk', 2)]:
            result = self.result('pass')
            result.update(mode=mode, approvedBaseline=context, trackedReleaseConcerns=[{
                'id': 'fixture-concern', 'profiles': [PROFILE], 'riskClass': 'local-privilege-escalation',
                'reason': 'Source concern not classified Critical', 'officialSources': ['https://kernel.org/'],
                'reviewedBy': 'Fixture', 'reviewedAt': '2026-10-12T00:00:00Z',
                'unblockEvidence': 'Specific source proof', 'severity': 'Unknown', 'advisories': []}])
            output = self.root / ('critical-' + mode)
            with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate', return_value=result):
                self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                           '--approved-baseline', str(path)]), expected)
            self.assertFalse(json.loads((output / 'security-result.json').read_text())['releaseEligible'])
            if expected == 0:
                summary = json.loads((output / 'security-summary.json').read_text())
                self.assertEqual(summary['trackedReleaseConcerns'][0]['severity'], 'Unknown')

    def test_reviewed_basis_retains_confirmed_hold_and_rejects_basis_mismatch(self):
        basis = 'reviewed-desktop-exploitability'
        self.policy.update(mode='desktop-critical-only', blockingBasis=basis, confirmedDesktopRisks=[])
        context = self.context()
        path = self.root / 'reviewed-context.json'
        mod.write_json(path, context)
        risk = confirmed_risk(context['image'], PROFILE)
        for label, basis_value, holds, expected in [('unconfirmed', basis, [], 0),
                ('confirmed', basis, [risk], 1), ('wrong-basis', 'other', [], 2),
                ('wrong-digest', basis, [{**risk, 'digest': 'sha256:' + 'f' * 64}], 2)]:
            self.policy['confirmedDesktopRisks'] = [risk] if holds else []
            result = self.result('pass')
            result.update(mode='desktop-critical-only', blockingBasis=basis_value, approvedBaseline=context,
                          trackedReleaseConcerns=[], releaseBlockers=holds, status='blocked' if holds else 'pass')
            if label == 'confirmed':
                result['blocked'] = [{'component': risk['component'], 'advisory': 'CVE-2026-1234',
                    'severity': 'High', 'aliases': ['CVE-2026-1234'], 'locations': ['/usr/bin/example'],
                    'locationCoverage': 'complete', 'reason': 'confirmed-desktop-exploitability', 'disposition': 'blocked',
                    'confirmedRiskReviews': [risk['id']]}]
            output = self.root / ('reviewed-' + label)
            with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate', return_value=result):
                self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY,
                                           '--approved-baseline', str(path)]), expected)
            if expected != 2:
                summary = json.loads((output / 'security-summary.json').read_text())
                self.assertEqual(summary['blockingBasis'], basis)
                self.assertEqual(summary['releaseBlockers'], holds)
                self.assertFalse(summary['releaseEligible'])

    def test_native_pass_and_blocked_never_grant_release(self):
        for status, expected in (('pass', 0), ('blocked', 1)):
            with self.subTest(status=status):
                output = self.root / ('evidence-' + status)
                with patch.dict(mod.os.environ, self.environment(), clear=True), \
                     patch.object(mod, 'scan_candidate', return_value=self.result(status)):
                    self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), expected)
                result = json.loads((output / 'security-result.json').read_text())
                provenance = json.loads((output / 'source-provenance.json').read_text())
                for document in (result, provenance):
                    self.assertFalse(document['releaseEligible'])
                    self.assertFalse(document['signatureVerified'])
                    self.assertEqual(document['sourceType'], 'locally-built-unpublished')
                self.assertEqual(provenance['revision'], REVISION)
                self.assertEqual(provenance['configurationDigest'], self.config_descriptor['digest'])

    def test_source_hold_blocks_without_inventing_vulnerability_records(self):
        hold = {'id': 'fixture-source-hold', 'profiles': [PROFILE],
                'riskClass': 'local-privilege-escalation', 'reason': 'Unqualified source fix',
                'officialSources': ['https://kernel.org/'], 'reviewedBy': 'Security reviewer',
                'reviewedAt': '2026-10-12T00:00:00Z', 'unblockEvidence': 'Verified compatible source fix'}
        result = self.result('blocked')
        result.update(blocked=[], releaseBlockers=[hold])
        output = self.root / 'source-held'
        with patch.dict(mod.os.environ, self.environment(), clear=True), \
             patch.object(mod, 'scan_candidate', return_value=result):
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 1)
        summary = json.loads((output / 'security-summary.json').read_text())
        self.assertEqual(summary['releaseBlockers'], [hold])
        self.assertEqual(summary['releaseBlockerRecords'], 1)
        self.assertEqual(summary['blockingRecords'], 0)
        self.assertFalse(summary['releaseEligible'])

    def test_malformed_or_contradictory_source_hold_is_scanner_error(self):
        for suffix, holds in [('malformed', [{}]), ('missing', [])]:
            result = self.result('blocked')
            result.update(blocked=[], releaseBlockers=holds)
            output = self.root / ('bad-source-hold-' + suffix)
            with patch.dict(mod.os.environ, self.environment(), clear=True), \
                 patch.object(mod, 'scan_candidate', return_value=result):
                self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
            self.assertEqual(json.loads((output / 'security-result.json').read_text())['status'], 'scanner-error')

    def test_scanner_error_retains_provenance_and_distinct_exit(self):
        output = self.root / 'scanner-error'
        with patch.dict(mod.os.environ, self.environment(), clear=True), \
             patch.object(mod, 'scan_candidate', side_effect=subprocess.CalledProcessError(1, ['grype', 'db', 'update'])):
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        self.assertTrue((output / 'source-provenance.json').exists())
        self.assertEqual(json.loads((output / 'security-result.json').read_text())['status'], 'scanner-error')

    def test_configuration_failure_prevents_scanner_launch(self):
        self.config['architecture'] = 'arm64'
        self.rebuild()
        output = self.root / 'invalid-config'
        with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
            self.assertEqual(mod.main([str(self.layout), str(output), '--profile', PROFILE, '--identity', IDENTITY]), 2)
        scan.assert_not_called()
        self.assertEqual(json.loads((output / 'security-result.json').read_text())['status'], 'scanner-error')

    def test_existing_or_symlink_output_cannot_be_overwritten(self):
        output = self.root / 'existing'
        output.mkdir()
        original = output / 'security-result.json'
        original.write_text('existing evidence')
        alias = self.root / 'output-alias'
        alias.symlink_to(output, target_is_directory=True)
        for path in (output, alias):
            with patch.dict(mod.os.environ, self.environment(), clear=True), patch.object(mod, 'scan_candidate') as scan:
                self.assertEqual(mod.main([str(self.layout), str(path), '--profile', PROFILE, '--identity', IDENTITY]), 2)
            scan.assert_not_called()
            self.assertEqual(original.read_text(), 'existing evidence')

    def test_native_orchestration_reuses_policy_and_preserves_layout(self):
        self.rebuild(indexed=True)
        candidate = self.validate()
        output = self.root / 'native'
        output.mkdir()
        original_index = (self.layout / 'index.json').read_bytes()
        calls = []

        def fake_run(args, destination=None):
            calls.append(args)
            if args[:2] == ['umoci', 'unpack']:
                pointer = Path(args[args.index('--image') + 1].removesuffix(':audit'))
                self.assertNotEqual(pointer, self.layout)
                self.assertFalse((pointer / 'blobs/sha256').is_symlink())
                for source in candidate['paths']:
                    self.assertEqual((pointer / 'blobs/sha256' / source.name).stat().st_ino, source.stat().st_ino)
                (Path(args[-1]) / 'rootfs').mkdir(parents=True)
            elif args[0] == 'syft':
                for arg in args:
                    if arg.startswith(('syft-json=', 'spdx-json=')):
                        Path(arg.split('=', 1)[1]).write_text('{}')
            elif destination:
                destination.write_text('[]' if 'search' in args else '{}')

        native_result = self.result('blocked')
        with patch.object(mod.scan_module, 'run', side_effect=fake_run), \
             patch.object(mod.subprocess, 'check_output', return_value='umoci version 0.6.2'), \
             patch.object(mod.policy_module, 'inventory', return_value={'effective': 'fedora:44'}) as inventory, \
             patch.object(mod.policy_module, 'evaluate', return_value=native_result) as evaluate:
            result = mod.scan_candidate(self.layout, output, candidate)
        self.assertEqual(result['status'], 'blocked')
        inventory.assert_called_once()
        evaluate.assert_called_once()
        self.assertEqual(evaluate.call_args.args[2], candidate['image'])
        self.assertIsNone(evaluate.call_args.kwargs['approved_baseline'])
        self.assertEqual(evaluate.call_args.kwargs['manifests']['extraction']['sourceType'], 'locally-built-unpublished')
        self.assertEqual((self.layout / 'index.json').read_bytes(), original_index)
        self.assertIn(['grype', 'db', 'update'], calls)
        grype_scan = next(args for args in calls if args[0] == 'grype' and any(arg.startswith('sbom:') for arg in args))
        self.assertIn('--show-suppressed', grype_scan)
        self.assertFalse(any(args[0] in ('docker', 'podman', 'cosign') for args in calls))
        self.assertFalse(any('run' in args for args in calls))
        self.assertEqual(list(self.root.glob('finite-candidate-scan-*')), [])


if __name__ == '__main__':
    unittest.main()
