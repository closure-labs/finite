#!/usr/bin/env python3
"""Authenticate phase-producing attempts without rerunning accepted VM work."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('phase_collection', ROOT / 'scripts/bluebuild/collect-qualification.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
import archive_read


class Collection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'output'
        self.revision = 'a' * 40
        self.run = {'id': 10, 'run_attempt': 2, 'head_sha': self.revision,
                    'path': '.github/workflows/build.yml', 'event': 'push', 'head_branch': 'main',
                    'run_started_at': '2026-10-26T11:00:00Z',
                    'repository': {'full_name': c.REPOSITORY}, 'head_repository': {'full_name': c.REPOSITORY}}
        self.jobs = {1: [self.job(100, 1, 'fresh', '10:01', '10:02', success=False),
                         self.job(101, 1, 'upgrade', '10:03', '10:04')],
                     2: [self.job(200, 2, 'fresh', '11:01', '11:02'),
                         self.job(201, 2, 'upgrade', '10:03', '10:04')]}
        self.archives = {}
        self.artifacts = [self.artifact(300, 'fresh', 2, '11:01:30'),
                          self.artifact(301, 'upgrade', 1, '10:03:30')]
        self.transfer = patch.object(archive_read, 'download_archive', self.download)
        self.transfer.start(); self.addCleanup(self.transfer.stop)

    def job(self, number, attempt, phase, start, end, success=True):
        steps = ['Save authenticated reusable qualification'] if phase == 'reused' else ['Qualify immutable candidate phase', 'Save phase evidence']
        return {'id': number, 'run_id': 10, 'run_attempt': attempt, 'head_sha': self.revision,
                'name': c.job_name('finite-dev', phase), 'status': 'completed',
                'conclusion': 'success' if success else 'failure', 'runner_id': 1000 + (1 if phase == 'upgrade' else 0),
                'runner_name': 'runner-' + phase, 'started_at': '2026-10-26T' + start + ':00Z',
                'completed_at': '2026-10-26T' + end + ':00Z',
                'steps': [{'name': name, 'conclusion': 'success' if success else 'failure'} for name in steps]}

    def phase_value(self):
        return {'accepted': True, 'secureBoot': True, 'encryptedRoot': True, 'profile': 'finite-dev',
                'source': 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64,
                'iso': {'sha256': 'c' * 64}, 'qualificationContext': {'inputs': 'same'},
                'qualificationContextSha256': 'd' * 64}

    def artifact(self, number, phase, attempt, created):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zipped:
            if phase == 'reused':
                zipped.writestr('finite-dev-acceptance.json', '{}')
                zipped.writestr('finite-dev-desktop-acceptance.json', '{}')
            else:
                zipped.writestr('vm-' + phase + '/acceptance.json', json.dumps(self.phase_value()))
                zipped.writestr(f'finite-dev-{phase}-outcome.json', json.dumps({'outcome': 'success', 'phase': phase}))
                zipped.writestr('nix-setup.json', 'unrelated shared setup')
        raw = buffer.getvalue(); self.archives[number] = raw
        name = (f'qualification-reused-finite-dev-10-{attempt}' if phase == 'reused' else
                f'qualification-phase-finite-dev-{phase}-10-{attempt}')
        return {'id': number, 'name': name, 'expired': False, 'created_at': '2026-10-26T' + created + 'Z',
                'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size_in_bytes': len(raw),
                'workflow_run': {'id': 10, 'head_sha': self.revision}}

    def api(self, path):
        if '/attempts/' in path:
            attempt = int(path.split('/attempts/')[1].split('/')[0].split('?')[0])
            if '/jobs?' in path:
                return {'total_count': len(self.jobs[attempt]), 'jobs': deepcopy(self.jobs[attempt])}
            return {**deepcopy(self.run), 'run_attempt': attempt,
                    'run_started_at': f'2026-10-26T{10 if attempt == 1 else 11}:00:00Z'}
        if path.endswith('/artifacts?per_page=100&page=1'):
            return {'total_count': len(self.artifacts), 'artifacts': deepcopy(self.artifacts)}
        if '/actions/jobs/' in path:
            number = int(path.rsplit('/', 1)[1])
            return deepcopy(next(j for rows in self.jobs.values() for j in rows if j['id'] == number))
        if '/actions/artifacts/' in path:
            number = int(path.rsplit('/', 1)[1])
            return deepcopy(next(a for a in self.artifacts if a['id'] == number))
        self.fail(path)

    def download(self, stream, artifact, repository):
        self.assertEqual(repository, c.REPOSITORY)
        stream.write(self.archives[artifact['id']])

    def collector(self):
        return c.Collector(10, 2, self.revision, 'finite-dev', api=self.api)

    def collect(self):
        return self.collector().collect(['fresh', 'upgrade'], self.output)

    def test_fresh_retry_retains_successful_original_upgrade(self):
        origins = self.collect()
        self.assertEqual(origins['fresh']['attempt'], 2)
        self.assertEqual(origins['upgrade']['attempt'], 1)
        self.assertEqual(origins['upgrade']['job'], 101)
        receipt = json.loads((self.output / 'qualification-phase-origins.json').read_text())
        self.assertEqual(receipt['phases'], origins)
        self.assertTrue((self.output / 'vm-fresh/acceptance.json').is_file())
        self.assertTrue((self.output / 'vm-upgrade/acceptance.json').is_file())
        self.assertFalse((self.output / 'nix-setup.json').exists())

    def test_original_job_id_and_attempt_projection_also_retains_prior_success(self):
        self.jobs[2][1] = deepcopy(self.jobs[1][1])
        origins = self.collect()
        self.assertEqual(origins['upgrade']['job'], 101)
        self.assertEqual(origins['upgrade']['attempt'], 1)

    def carried_fresh(self):
        self.jobs[1][0] = self.job(100, 1, 'fresh', '10:01', '10:02')
        self.jobs[1][1]['conclusion'] = 'failure'
        self.jobs[2] = [self.job(200, 2, 'fresh', '10:01', '10:02'),
                        self.job(201, 2, 'upgrade', '11:03', '11:04')]
        self.artifacts = [self.artifact(300, 'fresh', 1, '10:01:30'),
                          self.artifact(301, 'upgrade', 2, '11:03:30')]

    def test_upgrade_retry_retains_original_fresh_and_iso_origin(self):
        self.carried_fresh()
        origins = self.collect()
        self.assertEqual(origins['fresh']['attempt'], 1)
        self.assertEqual(origins['upgrade']['attempt'], 2)
        value = self.phase_value()
        acceptance = {**value, 'candidate': value['source'], 'qualifiedIso': value['iso'],
                      'qualifiedAt': '2026-10-26T10:02:00Z',
                      'qualifiedIsoOrigin': {'run': 10, 'attempt': 1, 'revision': self.revision},
                      'qualificationPhaseOrigins': origins}
        c.verify_fresh_origin(acceptance, self.run, api=self.api)
        acceptance['qualifiedIso'] = {'sha256': 'e' * 64}
        with self.assertRaisesRegex(ValueError, 'differs from its original'):
            c.verify_fresh_origin(acceptance, self.run, api=self.api)

    def test_failed_phase_or_changed_runner_cannot_use_older_success(self):
        for change in ({'conclusion': 'failure'}, {'head_sha': 'c' * 40}, {'runner_id': 123456}):
            with self.subTest(change=change):
                original = deepcopy(self.jobs[2][1]); self.jobs[2][1].update(change)
                with self.assertRaises(ValueError): self.collect()
                self.assertFalse(self.output.exists())
                self.jobs[2][1] = original

    def test_wrong_origin_or_ambiguous_jobs_fail_closed(self):
        self.jobs[1].append(deepcopy(self.jobs[1][1])); self.jobs[1][-1]['id'] = 102
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.collect()
        self.assertFalse(self.output.exists())

    def test_wrong_workflow_repository_and_diagnostic_origin_rejected(self):
        for key, value in (('path', '.github/workflows/other.yml'), ('head_branch', 'other'),
                           ('event', 'pull_request'), ('head_repository', {'full_name': 'fork/finite'})):
            with self.subTest(key=key):
                original = self.run[key]; self.run[key] = value
                with self.assertRaises(ValueError): self.collector()
                self.run[key] = original

    def test_missing_or_invalid_artifact_never_falls_back(self):
        for change in ({'expired': True}, {'digest': 'sha256:' + '0' * 64},
                       {'workflow_run': {'id': 99, 'head_sha': self.revision}},
                       {'created_at': '2026-10-26T09:00:00Z'}):
            with self.subTest(change=change):
                original = deepcopy(self.artifacts[0]); self.artifacts[0].update(change)
                with self.assertRaises(ValueError): self.collect()
                self.assertFalse(self.output.exists())
                self.artifacts[0] = original
        self.artifacts.pop()
        with self.assertRaisesRegex(ValueError, 'missing'): self.collect()
        self.assertFalse(self.output.exists())

    def test_changed_archive_and_unsafe_members_publish_no_partial_evidence(self):
        original = self.archives[301]
        self.archives[301] = b'changed'
        with self.assertRaises(ValueError): self.collect()
        self.assertFalse(self.output.exists())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zipped: zipped.writestr('../escape', 'bad')
        self.archives[301] = buffer.getvalue()
        self.artifacts[1].update(size_in_bytes=len(buffer.getvalue()), digest='sha256:' + hashlib.sha256(buffer.getvalue()).hexdigest())
        with self.assertRaises(ValueError): self.collect()
        self.assertFalse(self.output.exists())

    def test_transfer_failure_leaves_no_collectable_partial_results(self):
        @contextmanager
        def interrupted(*_args):
            raise TimeoutError('interrupted')
            yield
        with self.assertRaises(TimeoutError):
            self.collector().collect(['fresh', 'upgrade'], self.output, reader=interrupted)
        self.assertFalse(self.output.exists())

    def test_existing_files_and_symlinked_destinations_are_not_overwritten(self):
        self.output.mkdir(); (self.output / 'vm-fresh').mkdir()
        existing = self.output / 'vm-fresh/acceptance.json'; existing.write_text('preserve')
        with self.assertRaises(ValueError): self.collect()
        self.assertEqual(existing.read_text(), 'preserve')
        self.assertFalse((self.output / 'vm-upgrade').exists())

    def test_reused_prepare_artifact_uses_actual_original_attempt(self):
        self.jobs = {1: [self.job(110, 1, 'reused', '10:01', '10:02')],
                     2: [self.job(210, 2, 'reused', '10:01', '10:02')]}
        self.artifacts = [self.artifact(310, 'reused', 1, '10:01:30')]
        origins = self.collector().collect(['reused'], self.output)
        self.assertEqual(origins['reused']['attempt'], 1)
        self.assertTrue((self.output / 'finite-dev-acceptance.json').exists())

    def test_recovery_rejects_forged_job_artifact_attempt_and_digest_origins(self):
        self.carried_fresh()
        origins = self.collect()
        value = self.phase_value()
        acceptance = {**value, 'candidate': value['source'], 'qualifiedIso': value['iso'],
                      'qualifiedAt': '2026-10-26T10:02:00Z',
                      'qualifiedIsoOrigin': {'run': 10, 'attempt': 1, 'revision': self.revision},
                      'qualificationPhaseOrigins': origins}
        for change in ({'job': 101}, {'artifactId': 301}, {'attempt': 3},
                       {'artifactDigest': 'sha256:' + '0' * 64}, {'run': 99}, {'revision': '0' * 40}):
            with self.subTest(change=change):
                altered = deepcopy(acceptance)
                altered['qualificationPhaseOrigins']['fresh'].update(change)
                with self.assertRaises(ValueError): c.verify_fresh_origin(altered, self.run, api=self.api)

    def test_current_attempt_failure_and_duplicate_artifacts_cannot_select_older_success(self):
        self.artifacts.append(deepcopy(self.artifacts[0])); self.artifacts[-1]['id'] = 399
        with self.assertRaisesRegex(ValueError, 'ambiguous'): self.collect()
        self.assertFalse(self.output.exists())
        self.artifacts.pop()
        self.jobs[2][0]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'not one successful'): self.collect()
        self.assertFalse(self.output.exists())

    def test_legacy_recovery_keeps_exact_attempt_requirement(self):
        expected = {'run': 10, 'attempt': 2, 'revision': self.revision}
        c.verify_fresh_origin({'qualifiedIsoOrigin': expected}, self.run,
                             api=lambda _: self.fail('Legacy origin needs no extra API reads'))
        with self.assertRaises(ValueError):
            c.verify_fresh_origin({'qualifiedIsoOrigin': {**expected, 'attempt': 1}}, self.run)


if __name__ == '__main__':
    unittest.main()
