#!/usr/bin/env python3
"""Parallel-phase evidence aggregation and authenticated exact reuse fixtures."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import shutil
import sys
import unittest
import warnings
import zipfile
import yaml
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/bluebuild' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


q = module('qualification_test_context', 'qualification-context.py')
r = module('qualification_test_reuse', 'reuse-qualification.py')
release = module('qualification_test_release', 'release-evidence.py')
predecessor = module('qualification_test_predecessor', 'reuse-predecessor-iso.py')
preflight = module('qualification_test_preflight', 'qualification-preflight.py')
retention = module('qualification_test_retention', 'prune-qualified-isos.py')


class Qualification(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.profile = 'finite'
        self.manifest = '{"schemaVersion":2,"manifests":[{"digest":"sha256:' + 'b' * 64 + '"}]}'
        self.candidate = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(self.manifest.encode()).hexdigest()
        self.previous = 'sha256:' + 'e' * 64
        self.source = 'c' * 40
        self.build = 'v1:' + 'd' * 64
        self.revision = 'f' * 40
        self.context = {'schema': 1, 'platform': 'linux/amd64', 'firmware': {'code': 'a' * 64},
                        'inputs': {'installer': 'b' * 64}, 'packages': 'qemu=1'}
        self.installer = {'finiteRevision': self.revision, 'resolvedImage': 'locked',
                          'secureBootCertificateSha256': 'a' * 64}
        self.observation = q.desktop.guest.observations('Enforcing', '1', '',
            'system_u:system_r:init_t:s0 1 systemd\nsystem_u:system_r:sshd_t:s0 22 sshd',
            'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=22,fd=3))', self.profile)
        self.write_phase('fresh')

    def write_phase(self, phase):
        base = self.directory / ('vm-' + phase)
        base.mkdir()
        fresh = phase == 'fresh'
        boot, manifest = ('first-boot', 'source') if fresh else ('updated', 'target')
        (base / (manifest + '-manifest.json')).write_text(self.manifest)
        (base / (boot + '.json')).write_text(json.dumps({'status': {'booted': {'image': {'imageDigest': 'sha256:' + 'b' * 64}}}}))
        (base / (boot + '-desktop.json')).write_text(json.dumps(self.observation))
        value = {'source': self.candidate if fresh else 'ghcr.io/closure-labs/finite@' + self.previous,
                 'profile': self.profile, 'accepted': True, 'secureBoot': True, 'encryptedRoot': True}
        if not fresh:
            value['target'] = self.candidate
        (base / 'acceptance.json').write_text(json.dumps(value))
        for operation in (['initialize'] if fresh else ['initialize', 'updated']):
            (base / ('functional-' + operation + '.json')).write_text(json.dumps(
                {'schema': 1, 'operation': operation, 'exitCode': 0}))
        iso = self.directory / ('iso-candidate' if fresh else 'iso-predecessor')
        iso.mkdir()
        (iso / (self.profile + '.iso')).write_bytes(b'pristine fixture ISO' if fresh else b'predecessor ISO')
        (iso / 'installation.json').write_text(json.dumps({'image': value['source'], 'profile': self.profile, 'installer': self.installer,
            'updateChannel': 'ghcr.io/closure-labs/finite:finite', 'installationTag': 'ghcr.io/closure-labs/finite:i' + '1' * 16}))
        (self.directory / (phase + '-qualification-context.json')).write_text(json.dumps(self.context))
        iso_name = self.profile + '.iso'
        (iso / 'SHA256SUMS').write_text(q.sha(iso / iso_name) + '  ' + iso_name + '\n'
            + q.sha(iso / 'installation.json') + '  installation.json\n')
        q.bind_phase(self.directory, phase)

    def test_functional_receipts_are_required_despite_successful_os_acceptance(self):
        path = self.directory / 'vm-fresh/functional-initialize.json'
        good = path.read_text()
        cases = [None, '{', '{}', json.dumps({'schema': 1, 'operation': 'initialize', 'exitCode': 7}),
                 json.dumps({'schema': 1, 'operation': 'updated', 'exitCode': 0}),
                 json.dumps({'schema': 1, 'operation': 'initialize', 'exitCode': False})]
        for value in cases:
            with self.subTest(value=value):
                path.unlink(missing_ok=True)
                if value is not None: path.write_text(value)
                with self.assertRaises((ValueError, OSError)): self.aggregate()
        path.write_text(good)
        self.assertTrue(self.aggregate()['accepted'])

    def test_upgrade_requires_both_functional_operations_from_upgrade_guest(self):
        self.write_phase('upgrade')
        for operation in ('initialize', 'updated'):
            path = self.directory / ('vm-upgrade/functional-' + operation + '.json')
            good = path.read_text()
            path.unlink()
            with self.assertRaises((ValueError, OSError)): self.aggregate(self.previous)
            path.write_text(json.dumps({'schema': 1, 'operation': operation, 'exitCode': 1}))
            with self.assertRaisesRegex(ValueError, 'functional check'): self.aggregate(self.previous)
            path.write_text(good)
        self.assertTrue(self.aggregate(self.previous)['accepted'])

    def aggregate(self, previous=''):
        return q.aggregate(self.directory, self.profile, self.candidate, previous, self.source, self.build, self.revision)

    def test_carried_fresh_phase_preserves_original_iso_producing_attempt(self):
        origins = {'schema': 1, 'repository': 'closure-labs/finite', 'run': 10, 'attempt': 2,
                   'revision': self.revision, 'profile': self.profile, 'validationOnly': False,
                   'phases': {'fresh': {'run': 10, 'attempt': 1, 'revision': self.revision,
                                        'job': 100, 'artifactId': 300, 'artifactDigest': 'sha256:' + '1' * 64,
                                        'completedAt': datetime.now(timezone.utc).isoformat()}}}
        (self.directory / 'qualification-phase-origins.json').write_text(json.dumps(origins))
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2',
                                     'FINITE_VALIDATION_ONLY': 'false'}):
            value = self.aggregate()
        self.assertEqual(value['qualifiedIsoOrigin'], {'run': 10, 'attempt': 1, 'revision': self.revision})
        self.assertEqual(value['qualificationPhaseOrigins'], origins['phases'])
        self.assertEqual(value['qualifiedAt'], origins['phases']['fresh']['completedAt'])

    def test_collected_origins_cannot_relabel_run_source_profile_or_future_attempt(self):
        base = {'schema': 1, 'repository': 'closure-labs/finite', 'run': 10, 'attempt': 2,
                'revision': self.revision, 'profile': self.profile, 'validationOnly': False,
                'phases': {'fresh': {'run': 10, 'attempt': 1, 'revision': self.revision,
                                     'job': 100, 'artifactId': 300, 'artifactDigest': 'sha256:' + '1' * 64,
                                        'completedAt': datetime.now(timezone.utc).isoformat()}}}
        for change in ({'run': 99}, {'revision': '0' * 40}, {'profile': 'other'}, {'validationOnly': True},
                       {'phases': {'fresh': {**base['phases']['fresh'], 'attempt': 3}}}):
            with self.subTest(change=change), patch.dict(os.environ, {
                    'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2', 'FINITE_VALIDATION_ONLY': 'false'}):
                (self.directory / 'qualification-phase-origins.json').write_text(json.dumps({**base, **change}))
                with self.assertRaises(ValueError): self.aggregate()

    def test_carried_phase_age_cannot_be_renewed_by_a_later_aggregate(self):
        origin = {'run': 10, 'attempt': 1, 'revision': self.revision, 'job': 100,
                  'artifactId': 300, 'artifactDigest': 'sha256:' + '1' * 64}
        for completed in (datetime.now(timezone.utc) - timedelta(hours=25),
                          datetime.now(timezone.utc) + timedelta(hours=1)):
            receipt = {'schema': 1, 'repository': 'closure-labs/finite', 'run': 10, 'attempt': 2,
                       'revision': self.revision, 'profile': self.profile, 'validationOnly': False,
                       'phases': {'fresh': {**origin, 'completedAt': completed.isoformat()}}}
            (self.directory / 'qualification-phase-origins.json').write_text(json.dumps(receipt))
            with patch.dict(os.environ, {'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2', 'FINITE_VALIDATION_ONLY': 'false'}):
                with self.assertRaisesRegex(ValueError, 'expired or from the future'): self.aggregate()

    def validate(self, acceptance=None, **overrides):
        if acceptance:
            (self.directory / (self.profile + '-acceptance.json')).write_text(json.dumps(acceptance))
        args = dict(directory=self.directory, profile=self.profile, candidate=self.candidate, previous='',
                    source=self.source, build_identity=self.build, context=self.context)
        args.update(overrides)
        return r.validate(**args)

    def test_diagnostic_receipt_is_marked_and_cannot_be_reused_for_publication_or_iso(self):
        with patch.dict(os.environ, FINITE_VALIDATION_ONLY='true'):
            q.bind_phase(self.directory, 'fresh')
            value = self.aggregate()
        self.assertTrue(value['validationOnly'])
        self.assertNotIn('qualifiedIsoOrigin', value)
        with self.assertRaisesRegex(ValueError, 'diagnostic mode'):
            self.aggregate()
        with self.assertRaisesRegex(ValueError, 'Diagnostic qualification'):
            self.validate()
        value['qualificationReuse'] = {'run': 123}
        with self.assertRaisesRegex(ValueError, 'Diagnostic qualification'):
            r.verify_reused_acceptance(value)
        with self.assertRaisesRegex(ValueError, 'Diagnostic qualification'):
            predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], self.context['inputs'])
        with self.assertRaisesRegex(ValueError, 'Diagnostic qualification'):
            release.validate_evidence({}, value, {}, 'finite', self.revision)

    def test_selector_implementation_changes_invalidate_old_qualification_context(self):
        tree = self.directory / 'input-tree'
        (tree / 'scripts/ci').mkdir(parents=True)
        (tree / 'sources').mkdir()
        (tree / 'sources/installer-security.json').write_text('{}')
        policy = tree / 'scripts/ci/ci-options.py'
        policy.write_text("DEFAULT_CHANNEL = 'finite-next'\n")
        before = q.source_inputs(tree)
        self.assertIn('scripts/ci/ci-options.py', before)
        value = self.aggregate()
        value['qualificationReuse'] = {'run': 123}
        value['qualificationContext']['inputs'] = before
        value['qualificationContextSha256'] = q.identity(value['qualificationContext'])
        policy.write_text("DEFAULT_CHANNEL = 'all'\n")
        self.assertNotEqual(before, q.source_inputs(tree))
        with self.assertRaisesRegex(ValueError, 'current installer/test'):
            r.verify_reused_acceptance(value, root=tree)

    def test_foundation_timing_dependency_is_bound_to_qualification(self):
        tree = self.directory / 'foundation-input-tree'
        (tree / 'scripts/ci').mkdir(parents=True)
        (tree / 'sources').mkdir()
        (tree / 'sources/installer-security.json').write_text('{}')
        validator = tree / 'scripts/ci/foundation_timings.py'
        validator.write_text('version = 1\n')
        before = q.source_inputs(tree)
        self.assertIn('scripts/ci/foundation_timings.py', before)
        value = self.aggregate()
        value['qualificationReuse'] = {'run': 123}
        value['qualificationContext']['inputs'] = before
        value['qualificationContextSha256'] = q.identity(value['qualificationContext'])
        validator.write_text('version = 2\n')
        with self.assertRaisesRegex(ValueError, 'current installer/test'):
            r.verify_reused_acceptance(value, root=tree)

    def test_nonselected_release_keeps_legacy_iso_run_and_does_not_claim_exact_bytes(self):
        acceptance = self.aggregate()
        acceptance.pop('qualifiedIsoOrigin', None)
        acceptance['qualificationContext']['inputs'] = q.source_inputs()
        acceptance['qualificationContextSha256'] = q.identity(acceptance['qualificationContext'])
        publication = {'profile': self.profile, 'revision': self.revision, 'sourceRevision': self.source,
                       'buildIdentity': self.build, 'previousDigest': ''}
        run = {'conclusion': 'success', 'head_branch': 'main', 'head_sha': self.revision,
               'head_repository': {'full_name': release.REPOSITORY}, 'id': 123,
               'path': '.github/workflows/build.yml', 'html_url': 'https://github.com/closure-labs/finite/actions/runs/123'}
        iso_run = {**run, 'id': 789, 'path': '.github/workflows/iso.yml'}
        artifacts = [{'name': f'qualification-{self.profile}-123-1', 'expired': False},
                     {'name': f'image-{self.profile}-123-1', 'expired': False}]
        downloaded = []
        def artifact(run_id, name, destination):
            downloaded.append((run_id, name))
            destination.mkdir(parents=True, exist_ok=True)
            if name.startswith('qualification-'):
                (destination / (self.profile+'-acceptance.json')).write_text(json.dumps(acceptance))
                desktop_path = q.desktop.verify(self.directory, acceptance)
                shutil.copy2(desktop_path, destination / desktop_path.name)
            elif name.startswith('image-'):
                (destination / (self.profile+'-publication.json')).write_text(json.dumps(publication))
            else:
                for path in (self.directory / 'iso-candidate').iterdir():
                    shutil.copy2(path, destination / path.name)
        original = Path.cwd()
        output = self.directory / 'output'
        env = {'GITHUB_SHA': self.revision, 'GITHUB_OUTPUT': str(output),
               'FINITE_QUALIFIED_ISO_PRESERVATION': 'true', 'FINITE_QUALIFIED_ISO_CHANNELS': 'finite-dev'}
        try:
            os.chdir(self.directory)
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['release-evidence.py', 'finite', '789', '123']), \
                    patch.object(release, 'github', side_effect=lambda path: iso_run if path.endswith('/789') else run), \
                    patch.object(release, 'artifact_names', side_effect=lambda run_id: artifacts if run_id=='123' else [{'name':'finite-iso-finite-789-1','expired':False}]), \
                    patch.object(release, 'artifact', side_effect=artifact), patch.object(release.subprocess, 'run'):
                release.main()
        finally:
            os.chdir(original)
        provenance = json.loads((self.directory / '.bluebuild/release/provenance.json').read_text())
        self.assertFalse(provenance['isoMatchesQualification'])
        self.assertIn(('789', 'finite-iso-finite-789-1'), downloaded)

    def test_profile_rename_preserves_exact_predecessor_and_candidate_bindings(self):
        self.write_phase('upgrade')
        path = self.directory / 'vm-upgrade/acceptance.json'
        value = json.loads(path.read_text())
        value['sourceProfile'] = 'bluefin-generic'
        path.write_text(json.dumps(value))
        result = self.aggregate(self.previous)
        self.assertEqual(result['profile'], 'finite')
        self.assertEqual(result['previousDigest'], self.previous)
        self.assertEqual(result['candidate'], self.candidate)
        value['sourceProfile'] = 'bluefin-dx-generic'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'different foundation'):
            self.aggregate(self.previous)

    def test_bootstrap_and_both_phases_aggregate_complete_desktop_evidence(self):
        bootstrap = self.aggregate()
        self.assertTrue(bootstrap['bootstrap'])
        self.assertEqual(bootstrap['qualifiedIso']['sha256'], hashlib.sha256(b'pristine fixture ISO').hexdigest())
        q.desktop.verify(self.directory, bootstrap)
        self.write_phase('upgrade')
        result = self.aggregate(self.previous)
        self.assertFalse(result['bootstrap'])
        self.assertEqual(result['previousDigest'], self.previous)
        receipt = json.loads(q.desktop.verify(self.directory, result).read_text())
        self.assertEqual(list(receipt['phases']), ['fresh', 'upgrade'])

    def test_upgrade_required_and_failed_or_other_candidate_never_aggregates(self):
        with self.assertRaises(ValueError):
            self.aggregate(self.previous)
        self.write_phase('upgrade')
        path = self.directory / 'vm-upgrade/acceptance.json'
        original = json.loads(path.read_text())
        for key, value in [('accepted', False), ('encryptedRoot', False), ('secureBoot', False),
                           ('target', 'ghcr.io/closure-labs/finite@sha256:' + '0' * 64), ('profile', 'bluefin-next')]:
            path.write_text(json.dumps({**original, key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.aggregate(self.previous)

    def test_different_runner_context_or_iso_metadata_fails(self):
        self.write_phase('upgrade')
        path = self.directory / 'vm-upgrade/acceptance.json'
        original = json.loads(path.read_text())
        changed = copy.deepcopy(original)
        changed['qualificationContext']['firmware']['code'] = '0' * 64
        changed['qualificationContextSha256'] = q.identity(changed['qualificationContext'])
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'different firmware'):
            self.aggregate(self.previous)
        path.write_text(json.dumps(original))
        iso_path = self.directory / 'iso-candidate/installation.json'
        iso_path.write_text(iso_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'metadata differs'):
            self.aggregate(self.previous)

    def test_reuse_exact_and_age_boundary_does_not_refresh_original_timestamp(self):
        value = self.aggregate()
        original = value['qualifiedAt']
        self.assertEqual(self.validate()['qualifiedAt'], original)
        timestamp = datetime.fromisoformat(original)
        self.validate(now=timestamp + timedelta(hours=24))
        with self.assertRaises(r.Unavailable):
            self.validate(now=timestamp + timedelta(hours=24, seconds=1))
        with self.assertRaisesRegex(ValueError, 'future'):
            self.validate(now=timestamp - timedelta(seconds=1))

    def test_context_candidate_predecessor_and_legacy_changes_require_fresh_tests(self):
        value = self.aggregate()
        for changes in ({'candidate': 'different'}, {'previous': self.previous}, {'profile': 'bluefin-next'},
                        {'source': '0' * 40}, {'build_identity': 'v1:' + '0' * 64},
                        {'context': {**self.context, 'platform': 'linux/arm64'}}):
            # Keep the evidence filename stable for the profile mismatch fixture.
            if 'profile' in changes:
                continue
            with self.subTest(changes=changes), self.assertRaises(r.Unavailable):
                self.validate(**changes)
        for field in ('qualifiedIso', 'qualificationContextSha256', 'qualifiedAt'):
            legacy = copy.deepcopy(value)
            legacy.pop(field)
            with self.subTest(field=field), self.assertRaises(r.Unavailable):
                self.validate(legacy)

    def test_hash_or_desktop_tampering_never_reuses(self):
        value = self.aggregate()
        value['qualificationContextSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.validate(value)
        value = self.aggregate()
        path = self.directory / (self.profile + '-desktop-acceptance.json')
        path.write_text(path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.validate()

    def test_final_reuse_gate_rechecks_queue_age_and_current_tests(self):
        value = self.aggregate()
        value['qualificationReuse'] = {'run': 123}
        stamp = datetime.fromisoformat(value['qualifiedAt'])
        with patch.object(r.qualification, 'source_inputs', return_value=self.context['inputs']):
            r.verify_reused_acceptance(value, now=stamp + timedelta(hours=23))
            with self.assertRaises(r.Unavailable):
                r.verify_reused_acceptance(value, now=stamp + timedelta(hours=25))
        with patch.object(r.qualification, 'source_inputs', return_value=self.context['inputs']), \
                patch.object(r.qualification, 'validate_certificate', side_effect=subprocess.CalledProcessError(1, ['openssl'])):
            with self.assertRaises(subprocess.CalledProcessError):
                r.verify_reused_acceptance(value, now=stamp)
        with patch.object(r.qualification, 'source_inputs', return_value={'installer': 'changed'}):
            with self.assertRaisesRegex(ValueError, 'current installer/test'):
                r.verify_reused_acceptance(value, now=stamp)

    def test_predecessor_uses_same_image_and_generation_even_after_qualification_expiry(self):
        value = self.aggregate()
        value['qualifiedAt'] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        (self.directory / (self.profile + '-acceptance.json')).write_text(json.dumps(value))
        self.assertEqual(predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1],
                         self.context['inputs'])['qualifiedAt'], value['qualifiedAt'])
        for digest, inputs in [('sha256:' + '0' * 64, self.context['inputs']),
                              (self.candidate.split('@')[1], {'installer': 'changed'})]:
            with self.assertRaises(predecessor.reuse.Unavailable):
                predecessor.compatible(self.directory, self.profile, digest, inputs)
        value['qualificationContextSha256'] = '0' * 64
        (self.directory / (self.profile + '-acceptance.json')).write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], self.context['inputs'])

    def test_predecessor_artifact_ignores_only_non_generating_entry_points(self):
        for path in ('scripts/bluebuild/local-vm.sh', 'scripts/bluebuild/reuse-predecessor-iso.py'):
            with self.subTest(path=path):
                value = self.aggregate()
                old = {**self.context['inputs'], path: {'sha256': 'old', 'executable': True}}
                value['qualificationContext']['inputs'] = old
                value['qualificationContextSha256'] = q.identity(value['qualificationContext'])
                receipt = self.directory / (self.profile + '-acceptance.json')
                receipt.write_text(json.dumps(value))
                current = {**old, path: {'sha256': 'new', 'executable': True}}
                predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], current)
                # The full receipt still differs: this exception applies only
                # to pristine bytes, never to reuse of an old VM verdict.
                with self.assertRaises(r.Unavailable):
                    self.validate(context={**self.context, 'inputs': current})
                value['qualificationContextSha256'] = '0' * 64
                receipt.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], current)

    def test_predecessor_generation_projection_preserves_other_inputs_and_modes(self):
        paths = ('scripts/bluebuild/iso.sh', 'scripts/bluebuild/prepare-installer.sh',
                 'scripts/bluebuild/vm-acceptance.sh', 'files/installer/secure-boot.pem',
                 'files/installer/lorax-post.sh', 'cosign.pub', 'scripts/bluebuild/new-helper.py')
        for path in paths:
            for change in ({'sha256': 'changed', 'executable': False},
                           {'sha256': 'old', 'executable': True}, None):
                with self.subTest(path=path, change=change):
                    original = {path: {'sha256': 'old', 'executable': False}}
                    current = {} if change is None else {path: change}
                    self.assertNotEqual(predecessor.generation_inputs(original),
                                        predecessor.generation_inputs(current))
        for missing in (None, [], 'legacy'):
            with self.assertRaises(predecessor.reuse.Unavailable):
                predecessor.generation_inputs(missing)

    def archive(self, extra=None):
        self.aggregate()
        stream = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(stream, 'w') as zipped:
            warnings.simplefilter('ignore', UserWarning)
            for name in (self.profile + '-acceptance.json', self.profile + '-desktop-acceptance.json'):
                zipped.writestr(name, (self.directory / name).read_bytes())
            if extra:
                zipped.writestr(*extra)
        data = stream.getvalue()
        return data, {'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'size_in_bytes': len(data)}

    def test_archive_authentication_and_bounded_fixed_names(self):
        data, artifact = self.archive(('../../outside', 'never extracted'))
        destination = self.directory / 'extracted'
        destination.mkdir()
        r.extract(io.BytesIO(data), artifact, destination, self.profile)
        self.assertEqual(sorted(path.name for path in destination.iterdir()),
                         sorted([self.profile + '-acceptance.json', self.profile + '-desktop-acceptance.json']))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            r.extract(io.BytesIO(data), {**artifact, 'digest': 'sha256:' + '0' * 64}, destination, self.profile)
        duplicate, metadata = self.archive((self.profile + '-acceptance.json', '{}'))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            r.extract(io.BytesIO(duplicate), metadata, destination, self.profile)

    def test_predecessor_restore_missing_tag_rebuilds_and_bad_signature_blocks(self):
        qualification_data, qualification_artifact = self.archive()
        fixture = Origin()
        fixture.setUp()
        fixture.run['head_sha'] = self.revision
        fixture.job['head_sha'] = self.revision
        qualification_artifact.update(fixture.artifact)
        qualification_artifact.update(digest='sha256:' + hashlib.sha256(qualification_data).hexdigest(),
            size_in_bytes=len(qualification_data), workflow_run={'id': 123, 'head_sha': self.revision})
        iso_dir = self.directory / 'iso-candidate'
        (iso_dir / 'signature.json').write_text('[]')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipped:
            for name in (self.profile + '.iso', 'installation.json', 'signature.json', 'SHA256SUMS'):
                zipped.writestr(name, (iso_dir / name).read_bytes())
        iso_data = stream.getvalue()
        iso_artifact = {'id': 679, 'name': 'finite-qualified-iso-finite-123-1', 'expired': False,
            'digest': 'sha256:' + hashlib.sha256(iso_data).hexdigest(), 'size_in_bytes': len(iso_data),
            'workflow_run': {'id': 123, 'head_sha': self.revision}}
        real_run = subprocess.run
        calls = []
        iso_failure = None
        iso_payload = iso_data
        def api(path, paginated=False):
            if '/jobs?' in path:
                return [{'jobs': [fixture.job]}]
            if '/artifacts?' in path:
                return [{'artifacts': [qualification_artifact, iso_artifact]}]
            return {'workflow_runs': [fixture.run]}
        def command(args, **kwargs):
            calls.append(args)
            if args[0] == 'gh':
                if '/678/zip' in args[-1]:
                    kwargs['stdout'].write(qualification_data)
                else:
                    self.assertEqual(kwargs['timeout'], predecessor.ISO_TRANSFER_TIMEOUT)
                    if iso_failure is not None:
                        kwargs['stdout'].write(b'partial archive')
                        raise iso_failure
                    kwargs['stdout'].write(iso_payload)
            elif args[0] == 'cosign':
                if bad_signature:
                    raise subprocess.CalledProcessError(1, args)
            else:
                return real_run(args, **kwargs)
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': r.REPOSITORY, 'GITHUB_REF': 'refs/heads/main'}
        with patch.dict(os.environ, env), patch.object(predecessor.qualification, 'source_inputs', return_value=self.context['inputs']), \
                patch.object(predecessor.reuse, 'github', side_effect=api), \
                patch.object(predecessor.subprocess, 'run', side_effect=command),                 patch.object(predecessor.release, 'progress_download',
                             side_effect=lambda cmd, archive, expected, timeout, maximum:
                             command(cmd, stdout=archive, timeout=timeout)):
            bad_signature = False
            cases = [(predecessor.reuse, 'metadata', predecessor.reuse.Unavailable('expired'), 'qualification-unavailable'),
                     (predecessor.reuse, 'extract', predecessor.reuse.Unavailable('legacy'), 'legacy-evidence'),
                     (predecessor, 'compatible', predecessor.Ineligible('generation-inputs-changed', 'changed', ['scripts/bluebuild/iso.sh']), 'generation-inputs-changed')]
            for owner, name, error, reason in cases:
                diagnostic = predecessor.Diagnostics()
                with self.subTest(reason=reason), patch.object(owner, name, side_effect=error), self.assertRaises(predecessor.reuse.Unavailable):
                    predecessor.restore(self.profile, self.candidate.split('@')[1], self.directory / 'ineligible', diagnostic)
                self.assertEqual(diagnostic.counts, {reason: 1})
                self.assertEqual((diagnostic.runs, diagnostic.artifacts), (1, 1))
            diagnostic = predecessor.Diagnostics()
            with patch.object(predecessor.release, 'qualified_iso_artifact', return_value=None), self.assertRaises(predecessor.reuse.Unavailable):
                predecessor.restore(self.profile, self.candidate.split('@')[1], self.directory / 'no-iso', diagnostic)
            self.assertEqual(diagnostic.counts, {'preserved-iso-missing': 1})
            diagnostic = predecessor.Diagnostics()
            with patch.object(predecessor.upstream, 'inspect', return_value=None), self.assertRaises(predecessor.reuse.Unavailable):
                predecessor.restore(self.profile, self.candidate.split('@')[1], self.directory / 'missing-tag', diagnostic)
            self.assertEqual(diagnostic.counts, {'installation-tag-missing': 1})
            self.assertFalse((self.directory / 'missing-tag').exists())
            info = {'Digest': self.candidate.split('@')[1]}
            with patch.object(predecessor.upstream, 'inspect', return_value=info):
                transfer = ['gh', 'api', f'repos/{r.REPOSITORY}/actions/artifacts/679/zip']
                for failure, expected in [
                    (subprocess.TimeoutExpired(transfer, predecessor.ISO_TRANSFER_TIMEOUT), predecessor.reuse.Unavailable),
                    (predecessor.release.UnproductiveISOTransfer(transfer, predecessor.ISO_TRANSFER_TIMEOUT,
                                                                'unproductive-rate', 123), predecessor.reuse.Unavailable),
                    (subprocess.CalledProcessError(1, transfer, stderr='HTTP 403'), subprocess.CalledProcessError),
                    (subprocess.CalledProcessError(1, transfer, stderr='HTTP 416'), subprocess.CalledProcessError),
                    (subprocess.TimeoutExpired(['cosign', 'verify'], 150), subprocess.TimeoutExpired),
                ]:
                    with self.subTest(failure=repr(failure)):
                        iso_failure = failure
                        before = sum(call == transfer for call in calls)
                        destination = self.directory / 'failed-transfer'
                        diagnostic = predecessor.Diagnostics()
                        with self.assertRaises(expected):
                            predecessor.restore(self.profile, self.candidate.split('@')[1], destination, diagnostic)
                        reason = 'iso-transfer-unproductive' if isinstance(failure, predecessor.release.UnproductiveISOTransfer) else 'iso-transfer-timeout'
                        self.assertEqual(diagnostic.counts, {reason: 1} if expected is predecessor.reuse.Unavailable else {})
                        self.assertFalse(destination.exists())
                        self.assertEqual(sum(call == transfer for call in calls), before + 1)
                iso_failure = None
                iso_payload = iso_data[:-1] + bytes([iso_data[-1] ^ 1])
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    predecessor.restore(self.profile, self.candidate.split('@')[1], self.directory / 'bad-archive')
                self.assertFalse((self.directory / 'bad-archive').exists())
                iso_payload = iso_data
                bad_signature = True
                with self.assertRaises(subprocess.CalledProcessError):
                    predecessor.restore(self.profile, self.candidate.split('@')[1], self.directory / 'bad-signature')
                self.assertFalse((self.directory / 'bad-signature').exists())
                bad_signature = False
                destination = self.directory / 'reused-predecessor'
                predecessor.restore(self.profile, self.candidate.split('@')[1], destination)
                self.assertEqual((destination / (self.profile + '.iso')).read_bytes(), b'pristine fixture ISO')
                self.assertEqual(json.loads((destination / 'installation.json').read_text())['installer']['finiteRevision'], self.revision)
                self.assertTrue((destination / 'iso-reuse.json').is_file())

    def test_predecessor_diagnostics_bound_paths_counts_and_exclusive_destination(self):
        diagnostic = predecessor.Diagnostics()
        for _ in range(2):
            diagnostic.miss('generation-inputs-changed', [f'scripts/file-{i}.py' for i in range(30)])
        diagnostic.miss('legacy-evidence', ['/absolute', '../escape', 'raw\nresponse', 'x' * 201])
        self.assertEqual(len(diagnostic.paths), 20)
        self.assertTrue(diagnostic.truncated)
        self.assertEqual(diagnostic.counts['generation-inputs-changed'], 2)
        with self.assertRaises(ValueError): diagnostic.miss('unbounded arbitrary exception')
        path = self.directory / 'observation.json'
        diagnostic.write(path, self.profile, self.previous, 'miss')
        raw = path.read_bytes()
        self.assertLess(len(raw), 16384)
        value = json.loads(raw)
        self.assertFalse(value['authorizesPublication'])
        self.assertEqual(value['outcome'], 'miss')
        with self.assertRaises(FileExistsError): diagnostic.write(path, self.profile, self.previous, 'hit')
        self.assertEqual(path.read_bytes(), raw)
        interrupted = self.directory / 'interrupted.json'
        with patch.object(predecessor.os, 'link', side_effect=OSError('interrupted publication')), self.assertRaises(OSError):
            diagnostic.write(interrupted, self.profile, self.previous, 'miss')
        self.assertFalse(interrupted.exists())
        with patch.dict(os.environ, GITHUB_RUN_ID='x' * 16384), self.assertRaises(ValueError):
            diagnostic.write(interrupted, self.profile, self.previous, 'miss')
        self.assertEqual(list(self.directory.glob('.predecessor-reuse-*')), [])
        link = self.directory / 'diagnostic-link'
        link.symlink_to(path)
        with self.assertRaises(ValueError): diagnostic.write(link, self.profile, self.previous, 'hit')
        directory_link = self.directory / 'directory-link'
        directory_link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValueError): diagnostic.write(directory_link / 'new.json', self.profile, self.previous, 'miss')

    def test_predecessor_diagnostics_retained_with_failed_native_phase(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        retain = next(s for s in workflow['jobs']['phase']['steps'] if s.get('name') == 'Save phase evidence')
        self.assertEqual(retain['if'], 'always()')
        self.assertIn('.bluebuild/*-predecessor-reuse.json', retain['with']['path'].splitlines())
        self.assertIn('--diagnostics ".bluebuild/$PROFILE-predecessor-reuse.json"',
                      (ROOT / 'scripts/bluebuild/qualify.sh').read_text())

    def test_predecessor_diagnostics_cli_preserves_hit_miss_and_integrity_error(self):
        from contextlib import redirect_stdout, redirect_stderr
        for error, expected, outcome in ((None, 0, 'hit'),
                (predecessor.reuse.Unavailable('none'), 3, 'miss'),
                (ValueError('forged archive'), 2, 'error'),
                (subprocess.CalledProcessError(1, ['cosign']), 2, 'error')):
            with self.subTest(outcome=outcome):
                path = self.directory / ('diagnostic-' + str(expected) + '.json')
                path.unlink(missing_ok=True)
                args = ['reuse-predecessor-iso.py', '--profile', self.profile, '--digest', self.previous,
                        '--output', str(self.directory / 'restore'), '--diagnostics', str(path)]
                with patch.object(sys, 'argv', args), patch.object(predecessor, 'restore', side_effect=error), redirect_stdout(io.StringIO()):
                    self.assertEqual(predecessor.main(), expected)
                self.assertEqual(json.loads(path.read_text())['outcome'], outcome)
                with patch.object(sys, 'argv', args), patch.object(predecessor, 'restore', side_effect=error), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(predecessor.main(), expected)  # Existing diagnostic cannot mask original status.

    def test_predecessor_diagnostics_no_artifacts_and_known_generation_paths(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': r.REPOSITORY, 'GITHUB_REF': 'refs/heads/main'}
        diagnostic = predecessor.Diagnostics()
        def api(path, paginated=False):
            return [{'artifacts': []}] if paginated else {'workflow_runs': [{'id': 123}]}
        with patch.dict(os.environ, env), patch.object(predecessor.qualification, 'source_inputs', return_value={}), patch.object(predecessor.reuse, 'github', side_effect=api), self.assertRaises(predecessor.reuse.Unavailable):
            predecessor.restore(self.profile, self.previous, self.directory / 'restore', diagnostic)
        self.assertEqual(diagnostic.counts, {'no-qualification-artifact': 1})
        value = self.aggregate()
        current = {**self.context['inputs'], 'scripts/new.py': 'b' * 64}
        with self.assertRaises(predecessor.Ineligible) as raised:
            predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], current)
        self.assertEqual(raised.exception.reason, 'generation-inputs-changed')
        self.assertEqual(raised.exception.paths, ['scripts/new.py'])
        self.assertFalse(raised.exception.omitted_paths)
        with self.assertRaises(predecessor.Ineligible) as raised:
            predecessor.compatible(self.directory, self.profile, self.candidate.split('@')[1], {})
        self.assertEqual(raised.exception.paths, [])
        self.assertTrue(raised.exception.omitted_paths)

    def test_exact_release_iso_archive_is_hash_bound_and_rejects_other_bytes(self):
        value = self.aggregate()
        path = self.directory / 'iso-candidate'
        (path / 'signature.json').write_text('[]')
        (path / 'SHA256SUMS').write_text('fixture')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipped:
            for name in (value['qualifiedIso']['name'], 'installation.json', 'signature.json', 'SHA256SUMS'):
                zipped.writestr(name, (path / name).read_bytes())
        data = stream.getvalue()
        run = {'id': 123, 'head_sha': self.revision}
        artifact = {'id': 456, 'size_in_bytes': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
                    'workflow_run': run}
        destination = self.directory / 'release'
        destination.mkdir()
        def download(command, stdout, **kwargs):
            self.assertEqual(kwargs['timeout'], 1800, 'Release fetch keeps its strict existing transfer policy')
            stdout.write(data)
        with patch.object(release.subprocess, 'run', side_effect=download):
            release.authenticated_iso(artifact, run, value, destination)
            self.assertEqual((destination / value['qualifiedIso']['name']).read_bytes(), b'pristine fixture ISO')
            changed = copy.deepcopy(value)
            changed['qualifiedIso']['sha256'] = '0' * 64
            another = self.directory / 'invalid-release'; another.mkdir()
            with self.assertRaisesRegex(ValueError, 'pristine bytes'):
                release.authenticated_iso(artifact, run, changed, another)

    def test_iso_transfer_timeout_stops_real_child_before_extracting_partial_bytes(self):
        value = self.aggregate()
        run = {'id': 123, 'head_sha': self.revision}
        artifact = {'id': 456, 'size_in_bytes': 100, 'digest': 'sha256:' + '0' * 64, 'workflow_run': run}
        destination = self.directory / 'timeout-release'
        destination.mkdir()
        tools = self.directory / 'bin'; tools.mkdir()
        gh = tools / 'gh'
        gh.write_text('#!' + sys.executable + '\nimport sys,time\nsys.stdout.write("partial archive"); sys.stdout.flush(); time.sleep(2)\n')
        gh.chmod(0o755)
        with patch.dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH']):
            for progress in (False, True):
                with self.subTest(progress=progress), self.assertRaises(subprocess.TimeoutExpired):
                    release.authenticated_iso(artifact, run, value, destination, download_timeout=0.05,
                                              progress=progress)
                self.assertEqual(list(destination.iterdir()), [])
        for timeout in (0, -1, True, 1801, float('nan')):
            with self.assertRaisesRegex(ValueError, 'bounded positive timeout'):
                release.authenticated_iso(artifact, run, value, destination, download_timeout=timeout)


class TransferProgress(unittest.TestCase):
    def trace(self, expected, received, until=595):
        clock = [0]
        with patch.object(release.time, 'monotonic', side_effect=lambda: clock[0]):
            budget = release.ISOTransferProgress(expected, 600)
            for now in range(5, until + 1, 5):
                clock[0] = now
                reason = budget.observe(min(expected, received(now)))
                if reason:
                    return now, reason
        return None

    def test_observed_slow_ratio_falls_back_after_sustained_window(self):
        # 2.04 / 7.14 GiB after 600s, represented in MiB-sized units.
        self.assertEqual(self.trace(7140, lambda t: int(2040 * t / 600)),
                         (180, 'unproductive-rate'))

    def test_successful_observed_and_near_cap_rates_keep_full_budget(self):
        for duration in (131, 387, 590, 600):
            with self.subTest(duration=duration):
                self.assertIsNone(self.trace(7140, lambda t: int(7140 * t / duration)))

    def test_startup_grace_stalls_and_late_improvement(self):
        self.assertEqual(self.trace(7140, lambda t: 0), (120, 'no-progress'))
        self.assertEqual(self.trace(7140, lambda t: 2000), (120, 'no-progress'))
        self.assertIsNone(self.trace(7140, lambda t: 0 if t < 115 else 1000 + (t - 115) * 20))
        # A fast startup followed by >90 seconds without new bytes is optional
        # transport failure, not permission to consume the partial archive.
        self.assertEqual(self.trace(7140, lambda t: min(t, 200) * 20), (290, 'no-progress'))

    def test_recent_improvement_resets_slow_classification(self):
        self.assertIsNone(self.trace(7140, lambda t: t * 3 if t < 150 else 450 + (t - 150) * 30))

    def test_deadline_and_inconsistent_byte_counts(self):
        clock = [0]
        with patch.object(release.time, 'monotonic', side_effect=lambda: clock[0]):
            budget = release.ISOTransferProgress(100, 600)
            clock[0] = 600
            self.assertEqual(budget.observe(100), 'deadline')
            for sequence in ((10, 9), (101,)):
                clock[0] = 0
                budget = release.ISOTransferProgress(100, 600)
                with self.assertRaises(ValueError):
                    for size in sequence:
                        clock[0] += 5
                        budget.observe(size)

    def fake_download(self, rate, *, status=0, expected=7140):
        clock = [0]
        class Child:
            returncode = None
            killed = False
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def poll(self): return self.returncode
            def kill(self): self.killed = True; self.returncode = -9
            def wait(self, timeout=None):
                if self.returncode is not None: return self.returncode
                clock[0] += timeout
                size = min(expected, int(clock[0] * rate))
                archive.truncate(size)
                if size == expected or status:
                    self.returncode = status
                    return status
                raise subprocess.TimeoutExpired(['gh', 'api', 'fixture'], timeout)
        child = Child()
        with tempfile.TemporaryFile() as archive, \
                patch.object(release.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(release.subprocess, 'Popen', return_value=child) as popen:
            try:
                release.progress_download(['gh', 'api', 'fixture'], archive, expected, 600, 1 << 30)
            finally:
                self.assertEqual(popen.call_count, 1)
                self.child, self.elapsed = child, clock[0]

    def test_unproductive_child_is_killed_and_reaped_without_retry(self):
        with self.assertRaises(release.UnproductiveISOTransfer) as caught:
            self.fake_download(3.4)
        self.assertEqual(caught.exception.reason, 'unproductive-rate')
        self.assertEqual(self.elapsed, 180)
        self.assertTrue(self.child.killed)
        self.assertEqual(self.child.returncode, -9)

    def test_successful_child_and_http_failure_are_not_retried(self):
        self.fake_download(20)
        self.assertFalse(self.child.killed)
        with self.assertRaises(subprocess.CalledProcessError):
            self.fake_download(0, status=1)
        self.assertFalse(self.child.killed)


class Origin(unittest.TestCase):
    def setUp(self):
        self.profile = 'finite'
        self.run = {'id': 123, 'run_attempt': 2, 'status': 'completed', 'conclusion': 'success',
            'head_branch': 'main', 'head_sha': 'a' * 40, 'event': 'workflow_dispatch',
            'path': '.github/workflows/build.yml', 'repository': {'full_name': r.REPOSITORY},
            'head_repository': {'full_name': r.REPOSITORY}}
        self.job = {'id': 45, 'name': f'Publish ({self.profile}) / qualification / aggregate',
            'status': 'completed', 'conclusion': 'success', 'run_id': 123, 'run_attempt': 1, 'head_sha': 'a' * 40}
        self.artifact = {'id': 678, 'name': 'qualification-finite-123-1', 'expired': False,
            'size_in_bytes': 2345, 'digest': 'sha256:' + 'b' * 64, 'workflow_run': {'id': 123, 'head_sha': 'a' * 40}}

    def test_qualification_metadata_uses_shared_reader_for_each_collection(self):
        for path, key in (('actions/runs/123/artifacts?per_page=100', 'artifacts'),
                          ('actions/runs/123/attempts/1/jobs?per_page=100', 'jobs')):
            with self.subTest(path=path), patch.object(r, 'get_metadata', return_value=[]) as get:
                self.assertEqual(r.github(path, True), [])
            get.assert_called_once_with('repos/closure-labs/finite/' + path, collection=key)

    def test_original_available_rerun_artifact_requires_its_exact_successful_attempt(self):
        self.assertEqual(r.metadata(self.run, [self.job], self.artifact, self.profile), (45, 1))
        for field, value in [('conclusion', 'failure'), ('run_attempt', 2), ('run_id', 124), ('head_sha', 'c' * 40)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                r.metadata(self.run, [{**self.job, field: value}], self.artifact, self.profile)

    def test_unsuccessful_native_attempts_are_ineligible_with_sanitized_origin(self):
        for conclusion in ('failure', 'cancelled', 'timed_out', 'skipped', 'neutral',
                           'action_required', 'stale', 'startup_failure'):
            with self.subTest(conclusion=conclusion), self.assertRaises(r.Unavailable) as caught:
                r.metadata(self.run, [{**self.job, 'conclusion': conclusion}], self.artifact, self.profile)
            self.assertEqual(str(caught.exception), 'Qualification aggregate is ineligible: '
                             'run=123; attempt=1; job=45; conclusion=' + conclusion)

    def test_failed_attempt_cannot_hide_corrupt_origin_or_archive_binding(self):
        failed = {**self.job, 'conclusion': 'failure'}
        changes = [('run_attempt', 2), ('run_id', 124), ('head_sha', 'c' * 40), ('id', '45')]
        for field, value in changes:
            with self.subTest(field=field), self.assertRaises(ValueError) as caught:
                r.metadata(self.run, [{**failed, field: value}], self.artifact, self.profile)
            self.assertNotIsInstance(caught.exception, r.Unavailable)
        for artifact in ({**self.artifact, 'digest': 'invalid'},
                         {**self.artifact, 'workflow_run': {'id': 124, 'head_sha': 'a' * 40}}):
            with self.assertRaises(ValueError) as caught:
                r.metadata(self.run, [failed], artifact, self.profile)
            self.assertNotIsInstance(caught.exception, r.Unavailable)
        for status, conclusion in (('in_progress', 'success'), ('completed', None), ('completed', 'unknown')):
            for artifact in (self.artifact, {**self.artifact, 'expired': True}, {**self.artifact, 'digest': None}):
                with self.subTest(status=status, conclusion=conclusion, artifact=artifact), self.assertRaises(ValueError) as caught:
                    r.metadata(self.run, [{**self.job, 'status': status, 'conclusion': conclusion}],
                               artifact, self.profile)
                self.assertNotIsInstance(caught.exception, r.Unavailable)

    def test_legacy_producer_or_missing_hash_falls_back_to_fresh(self):
        with self.assertRaises(r.Unavailable):
            r.metadata(self.run, [], self.artifact, self.profile)
        with self.assertRaises(r.Unavailable):
            r.metadata(self.run, [self.job], {**self.artifact, 'digest': None}, self.profile)

    def test_untrusted_run_and_substituted_archive_are_rejected(self):
        for field, value in [('conclusion', 'cancelled'), ('event', 'pull_request'), ('head_branch', 'feature'),
                             ('path', '.github/workflows/qualification.yml'), ('repository', {'full_name': 'other/repo'})]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                r.metadata({**self.run, field: value}, [self.job], self.artifact, self.profile)
        for field, value in [('digest', 'invalid'), ('size_in_bytes', r.ARCHIVE_LIMIT + 1),
                             ('workflow_run', {'id': 124, 'head_sha': 'a' * 40})]:
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                r.metadata(self.run, [self.job], {**self.artifact, field: value}, self.profile)


class LazyReuse(unittest.TestCase):
    def setUp(self):
        self.fixture = Qualification()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.acceptance = f.aggregate()
        self.desktop = (f.directory / 'finite-desktop-acceptance.json').read_bytes()
        origin = Origin()
        origin.setUp()
        self.run = {**origin.run, 'head_sha': f.revision, 'updated_at': datetime.now(timezone.utc).isoformat()}
        self.job = {**origin.job, 'head_sha': f.revision}
        self.artifact = {**origin.artifact, 'workflow_run': {'id': self.run['id'], 'head_sha': f.revision}}
        self.output = f.directory / 'reused'
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': r.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': '1' * 40,
                    'CANDIDATE_DIGEST': f.candidate.split('@')[1], 'PREVIOUS_DIGEST': '',
                    'SOURCE_REVISION': f.source, 'BUILD_IDENTITY': f.build}
        self.context = copy.deepcopy(f.context)
        self.calls = []
        self.empty = False
        self.corrupt_archive = False
        self.omit_desktop = False
        self.history = None
        self.downloads = []

    def exercise(self):
        artifacts, archives, jobs = [], {}, {}
        for attempt, conclusion, acceptance in (self.history or [(1, 'success', self.acceptance)]):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('finite-acceptance.json', json.dumps(acceptance))
                if not self.omit_desktop:
                    zipped.writestr('finite-desktop-acceptance.json', self.desktop)
            data = archive.getvalue()
            artifact = {**self.artifact, 'id': self.artifact['id'] + attempt - 1,
                        'name': f'qualification-finite-{self.run["id"]}-{attempt}',
                        'size_in_bytes': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
            artifacts.append(artifact)
            archives[artifact['id']] = data
            jobs[attempt] = {**self.job, 'run_attempt': attempt, 'conclusion': conclusion}
        def api(path, paginated=False):
            self.calls.append(path)
            if '/runs?' in path: return {'workflow_runs': [] if self.empty else [self.run]}
            if '/artifacts?' in path: return [{'artifacts': artifacts}]
            if '/jobs?' in path: return [{'jobs': [jobs[int(path.split('/attempts/')[1].split('/')[0])]]}]
            raise AssertionError('Unexpected API request: ' + path)
        def download(command, **kwargs):
            artifact_id = int(command[-1].split('/artifacts/')[1].split('/')[0])
            self.assertEqual(command, ['gh', 'api', f'repos/{r.REPOSITORY}/actions/artifacts/{artifact_id}/zip'])
            self.downloads.append(artifact_id)
            data = archives[artifact_id]
            kwargs['stdout'].write(b'x' * len(data) if self.corrupt_archive else data)
        with patch.dict(os.environ, self.env), patch.object(r, 'github', side_effect=api), \
                patch.object(r.subprocess, 'run', side_effect=download), \
                patch.object(r.qualification, 'source_inputs', return_value=self.fixture.context['inputs']), \
                patch.object(r, 'prepare_context', return_value=self.context) as prepare, \
                patch.object(r, 'validate', wraps=r.validate) as validate:
            self.prepare, self.validate = prepare, validate
            return r.reuse('finite', self.output, prepare_tools=True)

    def test_successful_rerun_mismatch_then_failed_old_artifact_falls_back_to_fresh(self):
        self.history = [(1, 'failure', self.acceptance),
                        (2, 'success', {**self.acceptance, 'candidate': 'different'})]
        with self.assertRaisesRegex(r.Unavailable, 'No fresh exact qualification'):
            self.exercise()
        self.assertEqual(self.downloads, [679])
        self.assertEqual([path for path in self.calls if '/attempts/' in path],
                         ['actions/runs/123/attempts/2/jobs?per_page=100',
                          'actions/runs/123/attempts/1/jobs?per_page=100'])
        self.prepare.assert_not_called()
        self.validate.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_successful_rerun_accepts_only_its_own_bound_aggregate_and_artifact(self):
        self.history = [(1, 'failure', self.acceptance), (2, 'success', self.acceptance)]
        origin = self.exercise()
        self.assertEqual(origin['attempt'], 2)
        self.assertEqual(origin['artifactId'], 679)
        self.assertEqual(origin['job'], self.job['id'])
        self.assertEqual(self.downloads, [679])
        self.validate.assert_called_once()
        self.assertNotIn('actions/runs/123/attempts/1/jobs?per_page=100', self.calls)

    def test_no_evidence_does_not_prepare_context_or_create_output(self):
        self.empty = True
        with self.assertRaises(r.Unavailable): self.exercise()
        self.prepare.assert_not_called()
        self.validate.assert_not_called()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.output.exists())

    def test_static_misses_skip_tools_without_extra_metadata_queries(self):
        original = copy.deepcopy(self.acceptance)
        for field, value in (('candidate', 'different'), ('previousDigest', 'different'),
                             ('profile', 'finite-dev'), ('sourceRevision', '0' * 40),
                             ('buildIdentity', 'v1:' + '0' * 64), ('qualificationContext', {})):
            with self.subTest(field=field):
                self.acceptance = {**original, field: value}
                self.calls.clear()
                with self.assertRaises(r.Unavailable): self.exercise()
                self.prepare.assert_not_called()
                self.validate.assert_not_called()
                self.assertEqual(len(self.calls), 3)
                self.assertFalse(self.output.exists())

    def test_missing_malformed_diagnostic_and_untrusted_evidence_cannot_authorize_reuse(self):
        self.omit_desktop = True
        with self.assertRaises(r.Unavailable): self.exercise()
        self.prepare.assert_not_called()
        self.omit_desktop = False
        original = copy.deepcopy(self.acceptance)
        for value in ([], None, {**original, 'validationOnly': True}):
            self.acceptance = value
            with self.assertRaises(ValueError): self.exercise()
            self.prepare.assert_not_called()
            self.assertFalse(self.output.exists())
        self.acceptance = original
        self.run['head_repository'] = {'full_name': 'foreign/repository'}
        with self.assertRaises(ValueError): self.exercise()
        self.prepare.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_archive_substitution_fails_before_tool_preparation(self):
        self.corrupt_archive = True
        with self.assertRaisesRegex(ValueError, 'archive digest'): self.exercise()
        self.prepare.assert_not_called()
        self.validate.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_possible_match_still_checks_actual_runtime_and_racing_source_context(self):
        for field, value in (('firmware', {'code': 'changed'}), ('packages', 'qemu=changed'),
                             ('inputs', {'installer': 'changed while provisioning'})):
            with self.subTest(field=field):
                self.context = {**self.fixture.context, field: value}
                with self.assertRaises(r.Unavailable): self.exercise()
                self.prepare.assert_called_once()
                self.validate.assert_called_once()
                self.assertFalse(self.output.exists())

    def test_possible_match_still_checks_verdict_hash_age_and_complete_phase_evidence(self):
        original = copy.deepcopy(self.acceptance)
        for field, value in (('accepted', False), ('secureBoot', False), ('encryptedRoot', False),
                             ('qualificationContextSha256', '0' * 64),
                             ('qualifiedAt', (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()),
                             ('qualifiedIso', {'name': 'wrong.iso'}),
                             ('vmSecurityEvidence', {'path': 'finite-desktop-acceptance.json', 'sha256': '0' * 64})):
            with self.subTest(field=field):
                self.acceptance = {**original, field: value}
                with self.assertRaises(ValueError): self.exercise()
                self.prepare.assert_called_once()
                self.validate.assert_called_once()
                self.assertFalse(self.output.exists())
        self.acceptance = original
        desktop = json.loads(self.desktop)
        desktop['phases'] = {}
        self.desktop = json.dumps(desktop).encode()
        self.acceptance['vmSecurityEvidence']['sha256'] = hashlib.sha256(self.desktop).hexdigest()
        with self.assertRaisesRegex(ValueError, 'required fresh/upgrade'): self.exercise()
        self.validate.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_evidence_expiring_during_lazy_tool_preparation_falls_back_to_fresh(self):
        start = datetime.now(timezone.utc)
        self.acceptance['qualifiedAt'] = (start - timedelta(hours=24) + timedelta(seconds=1)).isoformat()
        with patch.object(r, 'datetime', wraps=datetime) as clock:
            clock.now.side_effect = [start, start + timedelta(seconds=30)]
            with self.assertRaises(r.Unavailable): self.exercise()
        self.prepare.assert_called_once()
        self.validate.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_real_eligible_resumed_source_undergoes_complete_verification_once(self):
        # The producer revision and image source deliberately differ.
        origin = self.exercise()
        self.prepare.assert_called_once()
        self.validate.assert_called_once()
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(origin['qualificationRevision'], self.fixture.revision)
        value = json.loads((self.output / 'finite-acceptance.json').read_text())
        self.assertEqual(value['revision'], self.env['GITHUB_SHA'])
        self.assertEqual(value['qualifiedAt'], self.acceptance['qualifiedAt'])
        self.assertEqual(value['sourceRevision'], self.fixture.source)
        r.qualification.desktop.verify(self.output, value)

    def test_workflow_only_reports_reuse_after_full_checker_success(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        step = next(item for item in workflow['jobs']['prepare']['steps'] if item.get('id') == 'reuse')
        tool = self.fixture.directory / 'python3'
        tool.write_text('#!/bin/sh\nexit "$TEST_STATUS"\n')
        tool.chmod(0o755)
        output = self.fixture.directory / 'github-output'
        for status in (0, 2, 3):
            output.unlink(missing_ok=True)
            result = subprocess.run(['bash', '-e', '-c', step['run']],
                env={**os.environ, 'PROFILE': 'finite', 'GITHUB_OUTPUT': str(output),
                     'TEST_STATUS': str(status), 'PATH': str(tool.parent) + os.pathsep + os.environ['PATH']},
                check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2 if status == 2 else 0)
            self.assertEqual(output.read_text().splitlines(),
                             ['reused=false', 'reused=true'] if status == 0 else ['reused=false'])

    def test_lazy_tools_use_original_smoke_identity_and_pinned_context_interpreter(self):
        before = dict(os.environ)
        env = {**before, 'PATH': '/fixture/bin:' + before['PATH'],
               'FINITE_VM_FIRMWARE_DIR': '/fixture/fw', 'FINITE_VM_TOOLS_MANIFEST': '/fixture/manifest'}
        for failure in (False, True):
            def context(command, **kwargs):
                self.assertEqual(command[:3], ['python3', str(ROOT / 'scripts/bluebuild/qualification-context.py'), 'context'])
                self.assertEqual(kwargs['env'], env)
                self.assertEqual(kwargs['cwd'], ROOT)
                self.assertTrue(kwargs['check'])
                if failure: raise subprocess.CalledProcessError(1, command)
                (Path(command[-1]) / 'qualification-context.json').write_text(json.dumps(self.context))
            with patch.object(r.qualification.vm_tools, 'provision', return_value=env) as provision, \
                    patch.object(r.qualification.vm_tools, 'smoke') as smoke, \
                    patch.object(r.subprocess, 'run', side_effect=context):
                if failure:
                    with self.assertRaises(subprocess.CalledProcessError): r.prepare_context()
                else:
                    self.assertEqual(r.prepare_context(), self.context)
                provision.assert_called_once_with('nix')
                smoke.assert_called_once_with(env)
                self.assertEqual(dict(os.environ), before)


class ExecutionGate(unittest.TestCase):
    def setUp(self):
        self.revision = 'a' * 40
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
            'GITHUB_SHA': self.revision, 'GITHUB_REF': 'refs/heads/ci/qualification-benchmark',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'FINITE_VALIDATION_ONLY': 'true', 'PREVIOUS_DIGEST': 'sha256:'+'e'*64,
            'GITHUB_WORKFLOW_REF': 'closure-labs/finite/.github/workflows/benchmark-image-tools.yml@refs/heads/ci/qualification-benchmark'}

    def test_only_explicit_manual_branch_benchmark_authorizes_diagnostics(self):
        with patch.object(preflight.production, 'require_current') as main:
            result = preflight.require_eligible(self.revision, self.env)
            self.assertEqual(result, {'validationOnly': True, 'revision': self.revision})
            main.assert_not_called()

    def test_main_pr_fork_other_workflow_and_wrong_checkout_are_rejected(self):
        mutations = [('GITHUB_REF', 'refs/heads/main'), ('GITHUB_REF', 'refs/tags/test'),
            ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'push'),
            ('GITHUB_REPOSITORY', 'other/finite'), ('GITHUB_ACTIONS', 'false'),
            ('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/build.yml@refs/heads/ci/qualification-benchmark'),
            ('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/benchmark-image-tools.yml@refs/heads/main'),
            ('GITHUB_SHA', 'b' * 40), ('FINITE_VALIDATION_ONLY', 'yes')]
        with patch.object(preflight.production, 'require_current') as main:
            for key, value in mutations:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    preflight.require_eligible(self.revision, {**self.env, key: value})
            main.assert_not_called()

    def test_default_main_path_retains_existing_eligibility_rule_and_branch_cannot_opt_out(self):
        default = {**self.env, 'FINITE_VALIDATION_ONLY': 'false'}
        with patch.object(preflight.production, 'require_current', return_value=self.revision) as main:
            with self.assertRaisesRegex(ValueError, 'Production qualification'):
                preflight.require_eligible(self.revision, default)
            main.assert_not_called()
            default['GITHUB_REF'] = 'refs/heads/main'
            result = preflight.require_eligible(self.revision, default)
            self.assertFalse(result['validationOnly'])
            main.assert_called_once_with(self.revision)

    def test_compression_is_manual_diagnostic_only_and_unknown_modes_fail_closed(self):
        with patch.object(preflight.production,'require_current') as main:
            self.assertTrue(preflight.require_eligible(self.revision,{**self.env,'FINITE_INSTALLER_COMPRESSION':'zstd'})['validationOnly'])
            for changes in ({'FINITE_VALIDATION_ONLY':'false'}, {'GITHUB_REF':'refs/heads/main'}, {'GITHUB_EVENT_NAME':'pull_request'}, {'GITHUB_WORKFLOW_REF':'closure-labs/finite/.github/workflows/build.yml@refs/heads/ci/qualification-benchmark'}, {'FINITE_INSTALLER_COMPRESSION':'lz4'}, {'PREVIOUS_DIGEST':''}, {'PREVIOUS_DIGEST':'mutable:tag'}):
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    preflight.require_eligible(self.revision,{**self.env,'FINITE_INSTALLER_COMPRESSION':'zstd',**changes})
            main.assert_not_called()

    def test_diagnostic_iso_size_is_measured_without_changing_production_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'image.iso').write_bytes(b'iso bytes')
            (directory/'installation.json').write_text(json.dumps({'installer':{'source':'pinned'}}))
            with patch.object(q.subprocess,'run'),patch.dict(os.environ,FINITE_VALIDATION_ONLY='false'):
                baseline=q.iso_binding(directory)
                self.assertNotIn('sizeBytes',baseline)
                with patch.dict(os.environ,FINITE_VALIDATION_ONLY='true'):
                    diagnostic=q.iso_binding(directory)
                self.assertEqual(diagnostic['sizeBytes'],9)
                self.assertEqual({k:v for k,v in diagnostic.items() if k!='sizeBytes'},baseline)

    def test_compression_variants_have_different_context_identities(self):
        original_sha=q.sha
        def digest(path):
            return original_sha(path) if Path(path).name=='lorax-zstd.conf' else 'a'*64
        with patch.object(q,'validate_certificate'),patch.object(q,'source_inputs',return_value={}),patch.object(q,'sha',side_effect=digest),patch.object(q.vm_tools,'identity',return_value={'schema':1}),patch.dict(os.environ,FINITE_VM_TOOLS_MANIFEST='fixture',FINITE_INSTALLER_COMPRESSION='default'):
            baseline=q.context()
            self.assertNotIn('installerCompression',baseline)
            with patch.dict(os.environ,FINITE_INSTALLER_COMPRESSION='zstd'):
                diagnostic=q.context()
            self.assertNotEqual(q.identity(baseline),q.identity(diagnostic))
            self.assertEqual(diagnostic['installerCompression']['presetSha256'],original_sha(ROOT/'files/installer/lorax-zstd.conf'))
            with patch.dict(os.environ,FINITE_INSTALLER_COMPRESSION='unknown'),self.assertRaises(ValueError):q.context()

    def test_functional_job_is_required_and_preserves_native_producer_contract(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        functional = workflow['jobs']['functional']
        self.assertEqual(functional['needs'], ['prepare', 'phase'])
        self.assertEqual(functional['name'], 'aggregate')
        self.assertIn("needs.phase.result == 'success'", functional['if'])
        self.assertNotIn('continue-on-error', functional)
        step = next(step for step in functional['steps'] if 'collect-qualification.py' in step.get('run', ''))
        self.assertNotIn('continue-on-error', step)
        self.assertIn('qualification-context.py aggregate', step['run'])
        self.assertEqual(workflow['jobs']['phase']['env']['FINITE_SEPARATE_FUNCTIONAL'], True)
        call = workflow.get('on', workflow.get(True))['workflow_call']
        self.assertEqual(call['outputs']['evidence']['value'], '${{ jobs.functional.outputs.evidence }}')

    def test_workflow_diagnostic_artifacts_and_cache_gates_are_distinct(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        call = workflow.get('on', workflow.get(True))['workflow_call']
        self.assertFalse(call['inputs']['validation_only']['default'])
        self.assertEqual(call['inputs']['installer_compression']['default'],'default')
        for name in ('prepare','phase','functional'):
            self.assertEqual(workflow['jobs'][name]['env']['FINITE_INSTALLER_COMPRESSION'],'${{ inputs.installer_compression }}')
        for name in ('prepare','functional'):
            setup = next(step for step in workflow['jobs'][name]['steps'] if step.get('uses') == '$/.github/actions/setup-nix')
            self.assertEqual(setup['if'], '${{ !inputs.validation_only }}')
        phase_steps = workflow['jobs']['phase']['steps']
        gate_index = next(i for i,step in enumerate(phase_steps) if step.get('id') == 'benchmark')
        setup_index = next(i for i,step in enumerate(phase_steps) if step.get('uses') == '$/.github/actions/setup-nix')
        self.assertLess(gate_index,setup_index)
        retention = next(step for step in workflow['jobs']['functional']['steps'] if step.get('name') == 'Save qualification evidence')
        self.assertEqual(retention['with']['retention-days'], '${{ inputs.validation_only && 14 || 90 }}')
        prepare = workflow['jobs']['prepare']
        self.assertIn('benchmark-image-tools.yml', prepare['if'])
        reuse = next(step for step in prepare['steps'] if step.get('id') == 'reuse')
        self.assertIn('!inputs.validation_only', reuse['if'])
        self.assertIn("env.FINITE_QUALIFICATION_REUSE == 'true'", reuse['if'])
        self.assertIn('!inputs.force_qualification', reuse['if'])
        phase = workflow['jobs']['phase']
        # Only explicit controlled trials may stop sibling VM phases early.
        self.assertEqual(phase['strategy']['fail-fast'], "${{ inputs.validation_only && inputs.installer_benchmark != '' }}")
        preserved = next(step for step in phase['steps'] if step.get('name') == 'Preserve pristine qualified candidate ISO for the pilot')
        self.assertIn('!inputs.validation_only', preserved['if'])
        self.assertIn("steps.acceptance.outputs.functional_passed == 'true'", preserved['if'])
        self.assertIn("contains(format(',{0},', env.FINITE_QUALIFIED_ISO_CHANNELS), format(',{0},', inputs.channel))", preserved['if'])
        for job, prefix in [('phase', 'qualification-diagnostic-phase'), ('functional', 'qualification-diagnostic')]:
            upload = next(step for step in workflow['jobs'][job]['steps']
                          if step.get('name') == ('Save phase evidence' if job == 'phase' else 'Save qualification evidence'))
            self.assertIn(prefix, upload['with']['name'])
            self.assertIn('inputs.validation_only', upload['with']['name'])


class IsoScope(unittest.TestCase):
    def env(self, selector='finite', enabled='true'):
        return {'FINITE_QUALIFIED_ISO_PRESERVATION': enabled, 'FINITE_QUALIFIED_ISO_CHANNELS': selector}

    def test_release_strictness_is_limited_to_selected_channels(self):
        release.require_iso_fallback('finite-dev', '123', self.env())
        with self.assertRaisesRegex(ValueError, 'exact qualified ISO'):
            release.require_iso_fallback('finite', '123', self.env())
        release.require_iso_fallback('finite', '123', self.env(enabled='false'))
        with self.assertRaisesRegex(ValueError, 'No preserved qualified ISO'):
            release.require_iso_fallback('finite-dev', '', self.env())

    def test_retention_plans_all_selected_profiles_before_execution(self):
        with patch.object(sys, 'argv', ['prune-qualified-isos.py', '--apply']), \
                patch.object(retention.module, 'plan_iso_retention', return_value=[]) as plan, \
                patch.object(retention.module, 'apply_iso_retention') as execute:
            for selector, enabled, expected in [('finite', 'true', ('finite',)),
                    ('finite, finite-dev', 'true', ('finite', 'finite-dev')),
                    ('all', 'true', ('finite', 'finite-dev')), ('finite', 'false', ())]:
                with self.subTest(selector=selector, enabled=enabled), \
                        patch.dict(os.environ, self.env(selector, enabled=enabled)):
                    plan.reset_mock()
                    execute.reset_mock()
                    retention.main()
                    if expected:
                        plan.assert_called_with(expected)
                        execute.assert_called_with([], apply=True)
                    else:
                        plan.assert_not_called()
                        execute.assert_not_called()
            execute.reset_mock()
            plan.side_effect = r.GitHubReadError('second profile incomplete')
            with patch.dict(os.environ, self.env('all')), self.assertRaises(r.GitHubReadError):
                retention.main()
            execute.assert_not_called()

    def predecessor_guard(self, profile, selector, diagnostic, status=0):
        source = (ROOT / 'scripts/bluebuild/qualify.sh').read_text()
        guard = source.split('  reused=false\n', 1)[1].split('  if [[ $reused != true ]]; then', 1)[0]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        measure = directory / 'scripts/bluebuild/measure.py'
        measure.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'scripts/bluebuild/measure.py', measure)
        binary = directory / 'bin'
        binary.mkdir()
        nix = binary / 'nix'
        nix.write_text('#!' + shutil.which('bash') + '\ntouch "${FINITE_REUSE_TEST_MARKER:?}"\nexit "${FINITE_REUSE_TEST_STATUS:-0}"\n')
        nix.chmod(0o755)
        script = directory / 'guard.sh'
        script.write_text('''#!/usr/bin/env bash
set -euo pipefail
PROFILE=$1
current=upgrade
iso_dir=unused
digest=unused
reused=false
iso_preservation_enabled=$(python3 "$2" --iso-preservation "$PROFILE")
probe() {
''' + guard + '\nprintf "%s\\n" "$reused"\n}\nprobe\n')
        marker = directory / 'called'
        env = dict(os.environ, **self.env(selector), FINITE_VALIDATION_ONLY=diagnostic,
                   PROFILE=profile,
                   FINITE_REUSE_TEST_MARKER=str(marker), FINITE_REUSE_TEST_STATUS=str(status),
                   PATH=str(binary) + os.pathsep + os.environ['PATH'])
        result = subprocess.run(['bash', str(script), profile, str(ROOT / 'scripts/ci/ci-options.py')],
                                env=env, cwd=directory, capture_output=True, text=True)
        timings = directory / '.bluebuild' / (profile + '-timings.jsonl')
        records = [json.loads(line) for line in timings.read_text().splitlines()] if timings.exists() else []
        return result, marker.exists(), records

    def test_actual_predecessor_guard_excludes_other_channels_and_all_diagnostics(self):
        cases = [('finite', 'finite', 'false', True),
                 ('finite', 'finite-dev', 'false', False),
                 ('finite-dev', 'finite', 'false', False),
                 ('finite', 'all', 'true', False)]
        for profile, selector, diagnostic, expected in cases:
            result, called, records = self.predecessor_guard(profile, selector, diagnostic)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(called, expected, (profile, selector, diagnostic))
            self.assertEqual(bool(records), expected)

    def test_measured_predecessor_reuse_preserves_success_miss_and_rejection(self):
        for status, expected_exit, reused in [(0, 0, 'true'), (3, 0, 'false'), (2, 2, None)]:
            with self.subTest(status=status):
                result, called, records = self.predecessor_guard('finite', 'finite', 'false', status)
                self.assertTrue(called)
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                if reused is not None:
                    self.assertEqual(result.stdout.strip(), reused)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['stage'], 'predecessor-iso-reuse')
                self.assertEqual(records[0]['status'], status)
                self.assertGreaterEqual(records[0]['seconds'], 0)


class StageTelemetry(unittest.TestCase):
    def test_outcome_retains_distinct_phase_timings_in_both_artifact_paths(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        step = next(s for s in workflow['jobs']['phase']['steps'] if s.get('name') == 'Record phase outcome')
        for job, name in [('phase', 'Save phase evidence'), ('functional', 'Save qualification evidence')]:
            upload = next(s for s in workflow['jobs'][job]['steps'] if s.get('name') == name)
            self.assertIn('.bluebuild/*-stages.jsonl', upload['with']['path'].splitlines())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            evidence = directory / '.bluebuild'
            evidence.mkdir()
            records = {}
            for phase, status in [('fresh', 0), ('upgrade', 3)]:
                record = {'stage': 'iso-generation' if phase == 'fresh' else 'predecessor-iso-reuse',
                          'seconds': 42, 'status': status}
                records[phase] = record
                (evidence / 'bluefin-next-timings.jsonl').write_text(json.dumps(record) + '\n')
                env = dict(os.environ, PROFILE='bluefin-next', PHASE=phase, OUTCOME='success',
                           GITHUB_STEP_SUMMARY=str(directory / 'summary'))
                result = subprocess.run(['bash', '-e', '-c', step['run']], cwd=directory, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for phase, record in records.items():
                retained = evidence / ('bluefin-next-' + phase + '-stages.jsonl')
                self.assertEqual(json.loads(retained.read_text()), record)
            (evidence / 'bluefin-next-timings.jsonl').unlink()
            env['OUTCOME'] = 'failure'
            result = subprocess.run(['bash', '-e', '-c', step['run']], cwd=directory, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class BootBudget(unittest.TestCase):
    def boot(self, *, fatal=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        state = directory / 'state'
        state.mkdir()
        (state / 'secrets').mkdir()
        (state / 'secrets/luks-key').write_text('test secret')
        (state / 'clock').write_text('0\n0\n591\n596\n600\n')
        if fatal:
            (state / 'first-boot.log').write_text('Kernel panic - not syncing: fixture fatal boot\n')
        source = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        function = source.split('boot_vm() {', 1)[1].split('\npoweroff_vm() {', 1)[0]
        script = directory / 'boot.sh'
        script.write_text('''#!/usr/bin/env bash
set -u
state=$1
secrets=$state/secrets
phase_name=fresh
qemu_args=()
ssh_args=()
monotonic_seconds() {
  local value
  value=$(head -1 "$state/clock")
  tail -n +2 "$state/clock" >"$state/clock.tmp"
  mv "$state/clock.tmp" "$state/clock"
  printf '%s\n' "$value"
}
qemu-system-x86_64() { exec sleep 1000; }
python3() { exec sleep 1000; }
record_duration() { :; }
timeout() { printf '%s\n' "$1" >>"$state/attempts"; return 1; }
ssh() { return 1; }
sleep() { printf '%s\n' "$1" >>"$state/sleeps"; }
pid=
log_pid=
trap 'kill "$pid" "$log_pid" 2>/dev/null || true; wait "$pid" "$log_pid" 2>/dev/null || true' EXIT
''' + 'boot_vm() {' + function + '\nboot_vm first-boot\n')
        result = subprocess.run(['bash', str(script), str(state)], capture_output=True, text=True, timeout=10)
        return state, result

    def test_attempt_and_sleep_are_capped_to_remaining_readiness_deadline(self):
        state, result = self.boot()
        self.assertEqual(result.returncode, 1)
        self.assertEqual((state / 'attempts').read_text().splitlines(), ['9s'])
        self.assertEqual((state / 'sleeps').read_text().splitlines(), ['4'])
        self.assertIn('SSH did not become available', result.stderr)

    def test_unambiguous_kernel_panic_fails_before_ssh_or_sleep(self):
        state, result = self.boot(fatal=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Fatal boot failure', result.stderr)
        self.assertFalse((state / 'attempts').exists())
        self.assertFalse((state / 'sleeps').exists())



class IsoRetention(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': r.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ID': '999'}
        self.runs = []
        self.artifacts = {}
        for number in range(1, 5):
            created = (self.now - timedelta(hours=number)).isoformat()
            run = {'id': number, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                   'head_branch': 'main', 'event': 'push', 'path': '.github/workflows/build.yml',
                   'repository': {'full_name': r.REPOSITORY},
                   'head_repository': {'full_name': r.REPOSITORY}, 'head_sha': str(number) * 40,
                   'created_at': created}
            self.runs.append(run)
            self.artifacts[number] = [{'id': number * 10 + n, 'name': f'finite-qualified-iso-{profile}-{number}-1',
                'created_at': created, 'expired': False,
                'workflow_run': {'id': number, 'head_sha': run['head_sha'], 'head_branch': 'main'}}
                for n, profile in enumerate(('finite', 'finite-dev'))]
        self.requests = []

    def reply(self, endpoint, **kwargs):
        self.requests.append(endpoint)
        self.assertNotIn('/actions/artifacts?', endpoint)
        if '/workflows/build.yml/runs?' in endpoint:
            self.assertIn('branch=main&status=success&created=%3E%3D2026-10-25T06%3A00%3A00Z', endpoint)
            return {'total_count': len(self.runs), 'workflow_runs': self.runs}
        number = int(endpoint.split('/runs/')[1].split('/')[0])
        return {'total_count': len(self.artifacts[number]), 'artifacts': self.artifacts[number]}

    def plan(self, profiles=('finite', 'finite-dev')):
        import github_api
        with patch.dict(os.environ, self.env), patch.object(github_api, 'get_json', side_effect=self.reply), \
                patch.object(r.subprocess, 'run') as mutation:
            result = r.plan_iso_retention(profiles, self.now)
            mutation.assert_not_called()
            return result

    def test_valid_receipts_keep_two_per_profile_without_repository_inventory(self):
        # Repository-wide cardinality is irrelevant: no such endpoint is read.
        self.assertEqual([a['id'] for a in self.plan()], [30, 40, 31, 41])
        self.assertEqual(len(self.requests), 5)

    def test_older_attempts_expired_artifacts_and_timestamp_ties_are_not_witnesses(self):
        self.runs[0]['run_attempt'] = 2
        self.artifacts[2][0]['expired'] = True
        self.assertEqual(self.plan(('finite',)), [])
        self.setUp()
        self.artifacts[1][0]['created_at'] = self.artifacts[2][0]['created_at'] = self.now.isoformat()
        self.assertEqual([a['id'] for a in self.plan(('finite',))], [30, 40])
        self.artifacts[3][0]['created_at'] = self.now.isoformat()
        self.assertEqual([a['id'] for a in self.plan(('finite',))], [40])

    def test_unseen_old_run_reruns_cannot_make_a_candidate_top_two(self):
        # An unqueried old run can upload a new ISO, which remains untouched.
        # It cannot remove either of the two newer observed witnesses.
        selected = self.plan(('finite',))
        for candidate in selected:
            self.assertGreaterEqual(sum(a[0]['created_at'] > candidate['created_at']
                                        for a in self.artifacts.values()), 2)

    def test_wrong_provenance_and_malformed_metadata_fail_before_any_write(self):
        cases = [('head_sha', 'f' * 40), ('head_branch', 'other'), ('id', 999)]
        for key, value in cases:
            with self.subTest(binding=key):
                original = copy.deepcopy(self.artifacts)
                self.artifacts[4][1]['workflow_run'][key] = value
                with self.assertRaises(ValueError): self.plan()
                self.artifacts = original
        for field, value in [('status', 'in_progress'), ('conclusion', 'failure'),
                ('event', 'pull_request'), ('path', '.github/workflows/other.yml'),
                ('created_at', '2026-01-01T00:00:00Z')]:
            with self.subTest(run=field):
                original = copy.deepcopy(self.runs)
                self.runs[3][field] = value
                with self.assertRaises(ValueError): self.plan()
                self.runs = original
        self.artifacts[4].append(dict(self.artifacts[4][1], id=999))
        with self.assertRaises(ValueError): self.plan()

    def test_run_pagination_boundaries_count_drift_and_page_exhaustion_fail_closed(self):
        import github_api
        for count in (100, 101):
            runs = [dict(self.runs[0], id=n) for n in range(1, count + 1)]
            def read(endpoint, **kwargs):
                if '/workflows/' in endpoint:
                    page = int(endpoint.rsplit('page=', 1)[1])
                    return {'total_count': count, 'workflow_runs': runs[(page-1)*100:page*100]}
                return {'total_count': 0, 'artifacts': []}
            with patch.dict(os.environ, self.env), patch.object(github_api, 'get_json', side_effect=read):
                self.assertEqual(r.plan_iso_retention(('finite',), self.now), [])
        for mode in ('exhaustion', 'count drift', 'duplicate', 'truncated'):
            def bad(endpoint, **kwargs):
                page = int(endpoint.rsplit('page=', 1)[1])
                records = [dict(self.runs[0], id=(page-1)*100+n) for n in range(1, 101)]
                if mode == 'duplicate' and page == 2: records[0]['id'] = 1
                if mode == 'truncated': records = records[:1]
                return {'total_count': 2001 + (page == 2 and mode == 'count drift'), 'workflow_runs': records}
            with self.subTest(mode=mode), patch.dict(os.environ, self.env), \
                    patch.object(github_api, 'get_json', side_effect=bad), \
                    patch.object(r.subprocess, 'run') as mutation, self.assertRaises(r.GitHubReadError):
                r.prune_iso('finite', apply=True)
            mutation.assert_not_called()

    def test_artifact_listing_incompleteness_or_deadline_blocks_entire_plan(self):
        import github_api
        for error in (r.GitHubReadError('GitHub metadata discovery deadline exhausted'),
                      r.GitHubReadError('GitHub metadata page limit exhausted')):
            original = self.reply
            def read(endpoint, **kwargs):
                if '/runs/4/artifacts?' in endpoint:
                    raise error
                return original(endpoint, **kwargs)
            with patch.dict(os.environ, self.env), patch.object(github_api, 'get_json', side_effect=read), \
                    patch.object(r.subprocess, 'run') as mutation, self.assertRaises(r.GitHubReadError):
                r.apply_iso_retention(r.plan_iso_retention(('finite',), self.now), apply=True)
            mutation.assert_not_called()

    def test_retention_boundary_and_future_attempt_fail_closed(self):
        self.runs[3]['created_at'] = (self.now - timedelta(days=7)).isoformat()
        self.assertEqual([a['id'] for a in self.plan(('finite',))], [30, 40])
        self.artifacts[4][0]['name'] = 'finite-qualified-iso-finite-4-2'
        with self.assertRaisesRegex(ValueError, 'future attempt'):
            self.plan()

    def test_dry_run_never_writes_and_apply_uses_only_the_complete_plan(self):
        plan = self.plan(('finite',))
        with patch.object(r.subprocess, 'run') as mutation:
            r.apply_iso_retention(plan)
            mutation.assert_not_called()
            r.apply_iso_retention(plan, apply=True)
            self.assertEqual(mutation.call_count, 2)
            self.assertTrue(all(c.args[0][3] == 'DELETE' for c in mutation.call_args_list))


class QualificationClock(unittest.TestCase):
    def test_offsets_across_dst_fold_represent_the_same_utc_instant(self):
        now = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        for stamp in ('2026-11-01T06:30:00Z', '2026-11-01T01:30:00-05:00',
                      '2026-11-01T02:30:00-04:00'):
            self.assertEqual(q.collected_time({'fresh': {'completedAt': stamp}}, now), now)

    def test_exact_freshness_boundaries_and_clock_disagreement_remain_fail_closed(self):
        now = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        for age in (timedelta(0), timedelta(hours=24)):
            stamp = (now - age).isoformat()
            self.assertEqual(q.collected_time({'fresh': {'completedAt': stamp}}, now), now - age)
        for age, reason in ((timedelta(microseconds=-1), 'future'),
                            (timedelta(hours=-1), 'future'),
                            (timedelta(hours=24, microseconds=1), 'expired')):
            with self.assertRaisesRegex(ValueError, 'reason=' + reason) as error:
                q.collected_time({'fresh': {'completedAt': (now - age).isoformat()}}, now)
            self.assertIn('source=github-job', str(error.exception))
            self.assertIn('observedAt=2026-11-01T06:30:00+00:00', str(error.exception))
        with self.assertRaisesRegex(ValueError, 'missing-timezone'):
            q.collected_time({'fresh': {'completedAt': '2026-11-01T06:30:00'}}, now)

if __name__ == '__main__':
    unittest.main()
