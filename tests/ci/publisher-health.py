#!/usr/bin/env python3
"""Publisher health authenticates discovery and never treats builds as publication."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import publisher_health as health
from security_decisions import canonical_hash
spec = importlib.util.spec_from_file_location('delivery_health', ROOT / 'scripts/ci/delivery-health.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class PublisherHealth(unittest.TestCase):
    def setUp(self):
        self.proposal = {'kind': 'release-set', 'payload': {'version': '1.2.3', 'sourceRevision': 'a' * 40,
            'channels': {c: {'tag': c + '-1.2.3', 'assets': {'image.iso': 'b' * 64}} for c in health.CHANNELS}}}
        self.run = {'id': 99, 'run_attempt': 2, 'head_sha': 'c' * 40, 'head_branch': 'main',
                    'head_repository': {'full_name': health.REPOSITORY}, 'event': 'workflow_dispatch',
                    'path': '.github/workflows/publish-release-set.yml', 'status': 'completed', 'conclusion': 'failure'}
        self.identity = {'schema': 1, 'proposalHash': canonical_hash(self.proposal),
                         'payloadDigest': canonical_hash(self.proposal['payload']), 'version': '1.2.3',
                         'repository': health.REPOSITORY, 'workflow': 'publish-release-set.yml',
                         'runId': 99, 'runAttempt': 2, 'headSha': 'c' * 40}
        self.artifact = {'id': 10, 'name': 'release-execution-identity-99-2', 'expired': False,
                         'workflow_run': {'id': 99, 'head_sha': 'c' * 40}}
        self.artifacts = [self.artifact]
        self.jobs = [{'name': 'publish', 'conclusion': 'failure',
                      'steps': [{'name': 'stage-publication', 'conclusion': 'failure'}]}]
        self.runs = [self.run]
        self.public = []
        self.requests = []
        self.producer = None
        self.producer_jobs = []
        self.zip_identity()

    def zip_identity(self, content=None):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('release-execution-identity.json', content or json.dumps(self.identity))
        self.raw = archive.getvalue()
        self.artifact.update(size_in_bytes=len(self.raw), digest='sha256:' + hashlib.sha256(self.raw).hexdigest())

    def api(self, endpoint, **kwargs):
        self.requests.append(endpoint)
        if '/workflows/publish-release-set.yml/' in endpoint: return {'workflow_runs': self.runs}
        if '/artifacts?' in endpoint: return {'total_count': len(self.artifacts), 'artifacts': self.artifacts}
        if endpoint.endswith('/attempts/2') and self.producer is not None: return self.producer
        if '/attempts/2/jobs?' in endpoint and self.producer is not None:
            return {'total_count': len(self.producer_jobs), 'jobs': self.producer_jobs}
        if '/jobs?' in endpoint: return {'total_count': len(self.jobs), 'jobs': self.jobs}
        if endpoint.endswith('/pending_deployments'): return [{'environment': {'name': 'release'}}]
        if '/releases/tags/' in endpoint:
            channel = endpoint.rsplit('/', 1)[1].removesuffix('-1.2.3')
            if channel not in self.public: return None
            return {'tag_name': channel + '-1.2.3', 'draft': False, 'prerelease': False,
                    'body': '<!-- finite-release-set:' + canonical_hash(self.proposal['payload']) + ' -->',
                    'assets': [{'name': name, 'state': 'uploaded', 'digest': 'sha256:' + 'b' * 64}
                               for name in ('image.iso', 'SHA256SUMS', 'SHA256SUMS.bundle.json')]}
        if '/git/ref/tags/' in endpoint: return {'object': {'type': 'commit', 'sha': 'a' * 40}}
        raise AssertionError(endpoint)

    def download(self, *args, **kwargs):
        kwargs['stdout'].write(self.raw)

    def inspect(self):
        with patch.object(health.subprocess, 'run', side_effect=self.download):
            return health.inspect_publisher(self.proposal, self.api)

    def test_failed_publisher_reports_phase_and_link(self):
        result = self.inspect()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['phase'], 'publish / stage-publication')
        self.assertIn('/99/attempts/2', result['runUrl'])

    def test_environment_wait_is_identified(self):
        self.run.update(status='waiting', conclusion=None)
        self.jobs = [{'name': 'sign', 'conclusion': None}]
        self.assertEqual(self.inspect()['state'], 'waiting_approval')

    def test_partial_and_complete_publication(self):
        self.public = ['finite']
        self.assertEqual(self.inspect()['state'], 'partial')
        self.public = list(health.CHANNELS)
        self.run.update(conclusion='success')
        self.assertEqual(self.inspect()['state'], 'published')

    def test_successful_job_without_public_products_is_unknown(self):
        self.run['conclusion'] = 'success'
        self.assertEqual(self.inspect()['state'], 'unknown')

    def test_missing_identity_and_no_runs_are_distinguished(self):
        self.artifacts = []
        self.assertEqual(self.inspect()['state'], 'unknown')
        self.runs = []
        self.assertEqual(self.inspect()['state'], 'not_started')

    def test_forged_binding_digest_and_identity_cannot_correlate(self):
        for kind in ('binding', 'digest', 'attempt', 'payload', 'oversized'):
            self.setUp()
            if kind == 'binding': self.artifact['workflow_run']['head_sha'] = 'd' * 40
            if kind == 'digest': self.artifact['digest'] = 'sha256:' + 'd' * 64
            if kind == 'attempt': self.identity['runAttempt'] = 1; self.zip_identity()
            if kind == 'payload': self.identity['payloadDigest'] = 'd' * 64; self.zip_identity()
            if kind == 'oversized': self.zip_identity(' ' * (health.IDENTITY_LIMIT + 1))
            with self.subTest(kind=kind): self.assertEqual(self.inspect()['state'], 'unknown')

    def test_queued_and_running_states(self):
        for status, expected in [('queued', 'queued'), ('in_progress', 'running')]:
            self.run.update(status=status, conclusion=None)
            self.assertEqual(self.inspect()['state'], expected)

    def reused_preparation(self):
        self.producer = dict(self.run)
        self.run = {**self.run, 'run_attempt': 3, 'status': 'in_progress', 'conclusion': None}
        self.runs = [self.run]
        prepare = {'name': 'prepare', 'conclusion': 'success', 'status': 'completed',
                   'started_at': '2026-10-22T15:29:34Z', 'completed_at': '2026-10-22T15:44:43Z'}
        self.producer_jobs = [dict(prepare)]
        self.jobs = [dict(prepare), {'name': 'publish', 'conclusion': None}]

    def test_publication_retry_authenticates_reused_identity_and_current_state(self):
        self.reused_preparation()
        result = self.inspect()
        self.assertEqual(result['state'], 'running')
        self.assertIn('/attempts/3', result['runUrl'])
        self.assertEqual(result['identityRunAttempt'], 2)
        self.run.update(status='completed', conclusion='success')
        self.public = list(health.CHANNELS)
        self.assertEqual(self.inspect()['state'], 'published')

    def test_reused_identity_preserves_current_failure_phase(self):
        self.reused_preparation()
        self.run.update(status='completed', conclusion='failure')
        self.jobs[1].update(conclusion='failure', steps=[{'name': 'commit-publication', 'conclusion': 'failure'}])
        result = self.inspect()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['phase'], 'publish / commit-publication')

    def test_prior_identity_requires_native_reuse_and_producer_binding(self):
        for kind in ('new-preparation', 'failed-producer', 'missing-times', 'foreign-head', 'wrong-attempt', 'forged-digest', 'duplicate'):
            self.setUp()
            self.reused_preparation()
            if kind == 'new-preparation': self.jobs[0]['started_at'] = '2026-10-22T16:00:00Z'
            if kind == 'failed-producer': self.producer_jobs[0]['conclusion'] = 'failure'
            if kind == 'missing-times': self.jobs[0].pop('completed_at')
            if kind == 'foreign-head': self.producer['head_sha'] = 'd' * 40
            if kind == 'wrong-attempt': self.producer['run_attempt'] = 1
            if kind == 'forged-digest': self.artifact['digest'] = 'sha256:' + 'd' * 64
            if kind == 'duplicate': self.artifacts.append(dict(self.artifact, id=11))
            with self.subTest(kind=kind): self.assertEqual(self.inspect()['state'], 'unknown')

    def test_invalid_current_identity_never_falls_back_to_older_identity(self):
        self.reused_preparation()
        self.artifact = dict(self.artifact, id=11, name='release-execution-identity-99-3')
        self.artifacts.append(self.artifact)
        self.assertEqual(self.inspect()['state'], 'unknown')

    def test_successful_preparation_is_never_automatically_redispatched(self):
        report = {'release': {'state': 'unprepared'}, 'buildRun': 8}
        def api(endpoint):
            if endpoint.endswith('/git/ref/heads/main'):
                return {'object': {'sha': 'a' * 40}}
            return {'workflow_runs': [{'head_sha': 'a' * 40, 'status': 'completed', 'conclusion': 'success'}]}
        with patch.object(delivery.subprocess, 'run') as mutation:
            self.assertIn('already succeeded', delivery.dispatch(report, 'a' * 40, api))
        mutation.assert_not_called()

    def test_healthy_builds_do_not_hide_failed_publisher_and_wait_is_informational(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decisions = root / 'automation/decisions/releases'
            decisions.mkdir(parents=True)
            (decisions / (canonical_hash(self.proposal) + '.json')).write_text(json.dumps(self.proposal))
            now = datetime.now(timezone.utc)
            build = {**self.run, 'id': 8, 'head_sha': 'a' * 40, 'path': '.github/workflows/build.yml',
                     'conclusion': 'success', 'updated_at': now.isoformat()}
            jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success'}
                    for channel in health.CHANNELS for suffix in ('qualification / aggregate', 'promote')]
            def api(endpoint, **kwargs):
                if '/workflows/build.yml/' in endpoint: return {'workflow_runs': [build]}
                if '/runs/8/attempts/' in endpoint: return {'total_count': len(jobs), 'jobs': jobs}
                if '/runs/8/artifacts?' in endpoint: return {'total_count': 0, 'artifacts': []}
                if '/git/ref/tags/' in endpoint: return None
                return self.api(endpoint, **kwargs)
            with patch.object(delivery, '__file__', str(root / 'scripts/ci/delivery-health.py')), \
                    patch.object(health.subprocess, 'run', side_effect=self.download):
                report = delivery.inspect('a' * 40, '1.2.3', None, api, now)
                self.assertFalse(report['healthy'])
                self.assertEqual(report['release']['state'], 'failed')
                self.assertIn('stage-publication', delivery.summary(report))
                self.run.update(status='waiting', conclusion=None)
                report = delivery.inspect('a' * 40, '1.2.3', None, api, now)
                self.assertTrue(report['healthy'])
                self.assertTrue(report['blockers'])


if __name__ == '__main__':
    unittest.main()
