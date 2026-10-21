#!/usr/bin/env python3
"""Paired preparation is idempotent; incomplete products require recovery."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import release_readiness as ready
spec = importlib.util.spec_from_file_location('delivery', ROOT / 'scripts/ci/delivery-health.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
SHA = 'a' * 40
BOT = 'cl-decider[bot]'


class Readiness(unittest.TestCase):
    def setUp(self):
        self.releases = {}
        self.tags = {}
        self.proposals = []
        self.version = '1.2.3'
        self.proposal = {'kind': 'release-set', 'payload': {'version': self.version, 'sourceRevision': SHA}}

    def api(self, endpoint, missing=False):
        if '/releases/tags/' in endpoint: return self.releases.get(endpoint.rsplit('/', 1)[-1])
        if '/git/ref/tags/' in endpoint: return self.tags.get(endpoint.rsplit('/', 1)[-1])
        if '/pulls?' in endpoint: return copy.deepcopy(self.proposals)
        if '/pulls/5/files?' in endpoint:
            return [{'filename': 'automation/decisions/releases/' + 'b' * 64 + '.json'}]
        if '/contents/' in endpoint:
            raw = json.dumps(self.proposal).encode()
            return {'encoding': 'base64', 'size': len(raw), 'content': base64.b64encode(raw).decode()}
        raise AssertionError(endpoint)

    def status(self):
        return ready.release_status(self.version, self.api, BOT)

    def test_development_version_skips_without_any_network(self):
        for version in ('01.2.3', '1.2', '1.2.3-rc1', '1.2.3-dev.1', '1.2.3-dev\n'):
            self.assertEqual(ready.release_status(version, lambda *_: self.fail('Unexpected network'))['state'], 'development')

    def stable_pair(self, version='1.2.2'):
        for channel in ready.CHANNELS:
            tag = channel + '-' + version
            self.releases[tag] = {'tag_name': tag, 'draft': False, 'prerelease': False,
                                  'published_at': '2026-10-21T00:00:00Z',
                                  'assets': [{'name': 'SHA256SUMS'}, {'name': 'SHA256SUMS.bundle.json'}]}
            self.tags[tag] = {'object': {'type': 'commit', 'sha': SHA}}

    def test_prerelease_waits_for_complete_stable_pair_at_one_revision(self):
        self.version = '1.2.3-dev'
        self.assertEqual(self.status()['state'], 'waiting-stable')
        self.stable_pair()
        self.releases['finite-dev-1.2.2']['draft'] = True
        self.assertEqual(self.status()['state'], 'waiting-stable')
        self.releases['finite-dev-1.2.2']['draft'] = False
        self.releases['finite-dev-1.2.2']['prerelease'] = True
        self.assertEqual(self.status()['state'], 'waiting-stable')
        self.releases['finite-dev-1.2.2']['prerelease'] = False
        self.assertEqual(self.status()['state'], 'unprepared')
        self.tags['finite-dev-1.2.2']['object']['sha'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.status()

    def test_prerelease_is_one_immutable_pair_and_existing_flags_must_match(self):
        self.version = '1.2.3-dev'
        for channel in ready.CHANNELS:
            self.releases[channel + '-' + self.version] = {'draft': False, 'prerelease': True}
        self.assertEqual(self.status()['state'], 'published')
        self.releases['finite-1.2.3-dev']['prerelease'] = False
        self.assertEqual(self.status()['state'], 'recovery')

    def test_stable_pair_requires_assets_and_resolves_bounded_annotated_tags(self):
        self.stable_pair()
        self.releases['finite-1.2.2']['assets'] = []
        self.assertFalse(ready.published_stable_pair('1.2.2', self.api))
        self.stable_pair()
        self.tags['finite-1.2.2']['object'] = {'type': 'tag', 'sha': 'b' * 40}
        def annotated(endpoint, **kwargs):
            if '/git/tags/' in endpoint:
                return {'object': {'type': 'commit', 'sha': SHA}}
            return self.api(endpoint, **kwargs)
        self.assertTrue(ready.published_stable_pair('1.2.2', annotated))
        def loop(endpoint, **kwargs):
            if '/git/tags/' in endpoint:
                return {'object': {'type': 'tag', 'sha': 'b' * 40}}
            return self.api(endpoint, **kwargs)
        with self.assertRaisesRegex(ValueError, 'does not resolve'):
            ready.published_stable_pair('1.2.2', loop)

    def test_both_published_versions_skip_and_partial_requires_recovery(self):
        self.assertEqual(self.status()['state'], 'unprepared')
        self.releases['finite-1.2.3'] = {'draft': False}
        self.assertEqual(self.status()['state'], 'recovery')
        self.releases['finite-dev-1.2.3'] = {'draft': False}
        self.assertEqual(self.status()['state'], 'published')
        self.releases['finite-dev-1.2.3']['draft'] = True
        self.assertEqual(self.status()['state'], 'recovery')
        self.releases.clear()
        self.tags['finite-1.2.3'] = {'object': {'sha': SHA}}
        self.assertEqual(self.status()['state'], 'recovery')

    def test_pending_bot_proposal_prevents_repeated_preparation(self):
        pull = {'number': 5, 'title': 'Review release-set abc', 'user': {'type': 'Bot', 'login': BOT},
                'head': {'sha': SHA}, 'changed_files': 1}
        self.proposals = [pull]
        self.assertEqual(self.status()['pullRequest'], 5)
        self.proposals = [{**pull, 'user': {'type': 'User', 'login': 'someone'}}]
        self.assertEqual(self.status()['state'], 'unprepared')

    def test_eligible_build_requires_same_revision_both_phases_and_preserved_bytes(self):
        run = {'id': 5, 'run_attempt': 2, 'path': '.github/workflows/build.yml', 'head_sha': SHA,
               'head_branch': 'main', 'status': 'completed', 'conclusion': 'success', 'event': 'push',
               'head_repository': {'full_name': ready.REPOSITORY}}
        jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success'}
                for channel in ready.CHANNELS for suffix in ('qualification / aggregate', 'promote')]
        artifacts = [{'name': f'finite-qualified-iso-{channel}-5-2', 'expired': False} for channel in ready.CHANNELS]
        self.assertTrue(ready.eligible_build(run, jobs, artifacts, SHA))
        for changed in ({'head_sha': 'c' * 40}, {'conclusion': 'failure'}, {'event': 'pull_request'}):
            self.assertFalse(ready.eligible_build({**run, **changed}, jobs, artifacts, SHA))
        self.assertFalse(ready.eligible_build(run, jobs[:-1], artifacts, SHA))
        self.assertFalse(ready.eligible_build(run, jobs, artifacts[:-1], SHA))
        artifacts[0]['expired'] = True
        self.assertFalse(ready.eligible_build(run, jobs, artifacts, SHA))

    def test_health_reports_each_channel_and_exact_failed_stage(self):
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        def run(number, sha, conclusion):
            return {'id': number, 'run_attempt': 1, 'head_sha': sha, 'head_branch': 'main',
                    'head_repository': {'full_name': ready.REPOSITORY}, 'event': 'push',
                    'status': 'completed', 'conclusion': conclusion,
                    'updated_at': (now - timedelta(hours=1)).isoformat()}
        def api(endpoint, **kwargs):
            if '/workflows/build.yml/runs?' in endpoint:
                return {'workflow_runs': [run(8, SHA, 'failure'), run(7, 'b' * 40, 'success')]}
            if '/runs/8/' in endpoint:
                return {'total_count': 1, 'jobs': [{'name': 'Publish (finite) / qualification / phase (fresh)', 'conclusion': 'failure'}]}
            if '/runs/7/' in endpoint:
                jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success'}
                        for channel in ready.CHANNELS for suffix in ('qualification / aggregate', 'promote')]
                return {'total_count': len(jobs), 'jobs': jobs}
            return self.api(endpoint, **kwargs)
        report = delivery.inspect(SHA, self.version, BOT, api, now)
        self.assertFalse(report['healthy'])
        self.assertIn('phase (fresh)', report['problems'][0])
        self.assertIn('Waiting for both', report['release']['reason'])
        for channel in ready.CHANNELS:
            self.assertEqual(report['channels'][channel]['promoted']['runId'], 7)
        self.assertIn('/actions/runs/7', delivery.summary(report))

    def test_dispatch_reconciles_running_work_before_one_mutation(self):
        report = {'release': {'state': 'unprepared'}, 'buildRun': 5}
        def api(endpoint):
            if endpoint.endswith('/git/ref/heads/main'): return {'object': {'sha': SHA}}
            return {'workflow_runs': [{'head_sha': SHA, 'status': 'in_progress'}]}
        with patch.object(delivery.subprocess, 'run') as run:
            self.assertIn('already', delivery.dispatch(report, SHA, api))
            run.assert_not_called()
        def empty(endpoint):
            return {'object': {'sha': SHA}} if endpoint.endswith('/git/ref/heads/main') else {'workflow_runs': []}
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, 'next reconciliation'):
                delivery.dispatch(report, SHA, empty)
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
