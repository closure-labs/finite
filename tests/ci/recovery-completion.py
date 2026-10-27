#!/usr/bin/env python3
"""Independent publication proof must join every native and live boundary."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import recovery_completion as completion

SHA = 'a' * 40
IDENTITY = 'v1:' + 'b' * 64
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'c' * 64


class Completion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.native = Path(self.temp.name)
        (self.native / 'approved-baseline.json').write_text(json.dumps(
            {'profile': 'finite', 'sourceRevision': SHA, 'buildIdentity': IDENTITY}))
        self.run = {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                    'path': '.github/workflows/build.yml', 'head_branch': 'main', 'event': 'schedule',
                    'head_sha': SHA, 'repository': {'full_name': completion.REPOSITORY},
                    'head_repository': {'full_name': completion.REPOSITORY}}
        self.jobs = [{'id': index + 1, 'name': 'Publish (finite) / ' + suffix, 'status': 'completed',
                      'conclusion': 'success', 'run_id': 123, 'run_attempt': 1, 'head_sha': SHA}
                     for index, suffix in enumerate(('promote', 'qualification / aggregate', 'security', 'sign'))]
        self.entries = [{'id': index + 1, 'name': kind + '-finite-123-1', 'expired': False,
                         'size_in_bytes': 100, 'digest': 'sha256:' + 'd' * 64,
                         'workflow_run': {'id': 123, 'head_sha': SHA}}
                        for index, kind in enumerate(('promotion', 'qualification', 'security'))]
        self.record = {'profile': 'finite', 'buildIdentity': IDENTITY, 'revision': SHA,
                       'sourceRevision': SHA, 'image': IMAGE, 'publish': True, 'accepted': True,
                       'tags': ['finite', 'latest'], 'qualificationMode': 'enforce', 'previousDigest': None}
        upstream = SimpleNamespace(PROFILES={'finite': (None, ['finite', 'latest'])}, REPOSITORY='ghcr.io/closure-labs/finite')
        self.security = SimpleNamespace(publication=SimpleNamespace(upstream=upstream), ARCHIVE_LIMIT=1024,
            extract=Mock(), require_fresh=Mock(), security=SimpleNamespace(load_policy=Mock(return_value={})), revalidate=Mock(return_value=({}, {'image': IMAGE})),
            inspect_candidate=Mock(return_value={'Digest': IMAGE.split('@')[1]}))
        self.qualification = SimpleNamespace(ARCHIVE_LIMIT=1024, extract=Mock(), validate=Mock(),
            qualification=SimpleNamespace(source_inputs=Mock(return_value={'source': 'bound'})))
        def download(entry, extract):
            if entry['id'] == 1:
                return {'finite-promoted.json': deepcopy(self.record)}
            if entry['id'] == 2:
                # Native extraction is covered by the shared qualification suite.
                # This fixture isolates joins and live invalidation.
                # Find the extraction directory through the callback closure.
                directory = dict(zip(extract.__code__.co_freevars, (c.cell_contents for c in extract.__closure__)))['directory']
                (directory / 'finite-acceptance.json').write_text(json.dumps(
                    {'revision': SHA, 'qualificationContext': {'inputs': {'source': 'bound'}}}))
            return None
        self.admission = Mock(return_value={'status': 'covered', 'decision': {'proposalHash': 'decision'}})
        patches = [patch.object(completion, 'current_build_identity', return_value=IDENTITY),
                   patch.object(completion.controller, 'api', return_value={'object': {'sha': SHA}}),
                   patch.object(completion.controller, 'module', side_effect=lambda name, _: self.security if 'security' in name else self.qualification),
                   patch.object(completion.controller, 'collection', side_effect=lambda path, _: deepcopy(self.jobs if path.endswith('/jobs') else self.entries)),
                   patch.object(completion, 'download', side_effect=download),
                   patch.object(completion.subprocess, 'run'),
                   patch('security_admission.verify', self.admission),
                   patch.dict(os.environ, {'GITHUB_SHA': SHA})]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    def authenticate(self):
        return completion.authenticate('finite', {'headSha': SHA}, self.native, 'decision', 'bot', self.run, IDENTITY)

    def test_complete_native_and_live_proof(self):
        proof = self.authenticate()
        self.assertEqual(proof['image'], IMAGE)
        self.assertEqual(proof['artifacts']['promotion']['id'], 1)
        self.assertEqual(self.security.inspect_candidate.call_count, 2)
        self.security.revalidate.assert_called_once()
        self.qualification.validate.assert_called_once()

    def test_changed_current_image_inputs_cannot_be_satisfied_by_an_old_equivalent_pair(self):
        with self.assertRaisesRegex(ValueError, 'profile/build identity'):
            completion.authenticate('finite', {'headSha': SHA}, self.native, 'decision', 'bot', self.run,
                                    'v1:' + 'f' * 64)

    def test_unknown_current_inputs_retain_recovery_without_reading_publishers(self):
        with patch.object(completion, 'current_build_identity', side_effect=ValueError('unavailable')), \
                patch.object(completion.controller, 'api') as api:
            self.assertIsNone(completion.completion('finite', {}, self.native, 'decision', 'bot'))
            api.assert_not_called()

    def test_untrusted_failed_or_wrong_attempt_jobs(self):
        for changes in ({'status': 'in_progress'}, {'conclusion': 'failure'}, {'run_attempt': 2}, {'head_sha': 'f' * 40}):
            original = deepcopy(self.jobs)
            self.jobs[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.authenticate()
            self.jobs = original
        self.jobs.append(deepcopy(self.jobs[0]))
        with self.assertRaises(ValueError): self.authenticate()

    def test_missing_expired_or_ambiguous_artifacts(self):
        for mutate in (lambda: self.entries.pop(), lambda: self.entries[0].update(expired=True),
                       lambda: self.entries[0].update(digest=None), lambda: self.entries.append(deepcopy(self.entries[0]))):
            original = deepcopy(self.entries)
            mutate()
            with self.assertRaises((ValueError, TypeError)): self.authenticate()
            self.entries = original

    def test_mismatched_profile_identity_or_partial_promotion(self):
        for field, value in (('profile', 'finite-dev'), ('buildIdentity', 'v1:' + 'f' * 64),
                             ('accepted', False), ('tags', ['finite']), ('qualificationMode', 'shadow')):
            original = deepcopy(self.record)
            self.record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.authenticate()
            self.record = original
        self.security.inspect_candidate.side_effect = [{'Digest': IMAGE.split('@')[1]}, {'Digest': 'sha256:' + 'f' * 64}]
        with self.assertRaises(ValueError): self.authenticate()

    def test_stale_security_revoked_coverage_or_changed_qualification(self):
        self.security.revalidate.side_effect = ValueError('stale security')
        with self.assertRaises(ValueError): self.authenticate()
        self.security.revalidate.side_effect = None
        self.admission.return_value = {'status': 'revoked'}
        with self.assertRaises(ValueError): self.authenticate()
        self.admission.return_value = {'status': 'covered', 'decision': {'proposalHash': 'other'}}
        with self.assertRaises(ValueError): self.authenticate()
        self.qualification.qualification.source_inputs.return_value = {'changed': True}
        with self.assertRaises(ValueError): self.authenticate()

    def test_source_ancestry_must_be_proven(self):
        with patch.object(completion.controller, 'api', return_value={'status': 'diverged'}):
            with self.assertRaises(ValueError): completion.ancestor(SHA, 'f' * 40)

    def test_missing_or_invalid_discovery_is_normal_recovery(self):
        with patch.object(completion.controller, 'api', return_value={'workflow_runs': []}):
            self.assertIsNone(completion.completion('finite', {}, self.native, 'decision', 'bot'))
        with patch.object(completion.controller, 'api', side_effect=ValueError('unavailable')):
            self.assertIsNone(completion.completion('finite', {}, self.native, 'decision', 'bot'))

    def test_archive_rejects_duplicate_keys_and_members(self):
        for contents in (['{"profile":"finite","profile":"other"}'], ['{}', '{}']):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for raw in contents: archive.writestr('proof.json', raw)
            stream.seek(0)
            with self.assertRaises(ValueError): completion.documents(stream, ['proof.json'])


if __name__ == '__main__': unittest.main()
