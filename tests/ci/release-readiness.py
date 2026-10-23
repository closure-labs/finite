#!/usr/bin/env python3
"""Paired preparation is idempotent; incomplete products require recovery."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
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
        if '/releases?' in endpoint: return list(self.releases.values())
        if '/git/matching-refs/tags/' in endpoint:
            prefix = endpoint.rsplit('/', 1)[-1]
            return [{'ref': 'refs/tags/' + tag} for tag in self.tags if tag.startswith(prefix)]
        if '/git/ref/tags/' in endpoint: return self.tags.get(endpoint.rsplit('/', 1)[-1])
        if '/pulls?' in endpoint: return copy.deepcopy(self.proposals)
        if endpoint.endswith('/pulls/5'):
            return {**copy.deepcopy(self.proposals[0]), 'changed_files': 1, 'state': 'open', 'base': {'ref': 'main'}}
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

    def test_skipped_development_version_uses_last_stable_and_preserves_reservations(self):
        self.version = '1.2.4-dev'
        self.stable_pair()
        self.releases['finite-1.2.3-dev'] = {'tag_name': 'finite-1.2.3-dev', 'draft': True}
        self.tags['finite-1.2.3-dev'] = {'object': {'type': 'commit', 'sha': SHA}}
        before = copy.deepcopy((self.releases, self.tags))
        self.assertEqual(ready.prerelease_base(self.version, self.api), '1.2.2')
        self.assertEqual(self.status()['state'], 'unprepared')
        self.assertEqual((self.releases, self.tags), before)

    def test_latest_stable_claim_cannot_fall_back_to_an_older_complete_pair(self):
        self.version = '1.2.11-dev'
        self.stable_pair('1.2.9')
        self.stable_pair('1.2.10')
        self.assertEqual(ready.prerelease_base(self.version, self.api), '1.2.10')
        del self.releases['finite-dev-1.2.10']
        self.assertEqual(self.status()['state'], 'waiting-stable')
        self.stable_pair('1.2.10')
        self.releases['finite-dev-1.2.10']['draft'] = True
        self.assertEqual(self.status()['state'], 'waiting-stable')
        # A read-only token can miss a draft but still sees its reserved tag.
        del self.releases['finite-1.2.10'], self.releases['finite-dev-1.2.10']
        self.assertEqual(self.status()['state'], 'waiting-stable')

    def test_stable_discovery_is_bounded_and_filters_other_cycles(self):
        self.stable_pair('1.1.9')
        self.stable_pair('1.2.4')
        self.stable_pair('2.2.1')
        self.assertIsNone(ready.prerelease_base('1.2.4-dev', self.api))
        self.stable_pair('1.2.2')
        entries = list(self.releases.values())
        calls = []
        def paged(endpoint, **kwargs):
            if '/releases?' in endpoint:
                calls.append(endpoint)
                return [{'tag_name': 'irrelevant'}] * 100 if endpoint.endswith('page=1') else entries
            return self.api(endpoint, **kwargs)
        self.assertEqual(ready.prerelease_base('1.2.4-dev', paged), '1.2.2')
        self.assertEqual(len(calls), 2)
        with self.assertRaisesRegex(ValueError, 'bounded pagination'):
            ready.prerelease_base('1.2.4-dev', lambda endpoint:
                [] if '/git/' in endpoint else [{'tag_name': 'irrelevant'}] * 100)
        for invalid in ({}, [{}], [{'tag_name': 1}]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'Invalid stable release inventory'):
                ready.prerelease_base('1.2.4-dev', lambda endpoint: [] if '/git/' in endpoint else invalid)
        for invalid in ({}, [{}], [{'ref': 'refs/heads/main'}], [{'ref': 'refs/tags/demo'}] * 1001):
            with self.subTest(invalid=str(invalid)[:60]), self.assertRaisesRegex(ValueError, 'stable tag inventory'):
                ready.prerelease_base('1.2.4-dev', lambda _: invalid)
        with self.assertRaisesRegex(RuntimeError, 'authorization'):
            ready.prerelease_base('1.2.4-dev', lambda _: (_ for _ in ()).throw(RuntimeError('authorization')))

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
                'head': {'sha': SHA}}
        self.proposals = [pull]
        self.assertEqual(self.status()['pullRequest'], 5)
        self.proposals = [{**pull, 'user': {'type': 'User', 'login': 'someone'}}]
        self.assertEqual(self.status()['state'], 'unprepared')

    def test_proposal_head_change_and_incomplete_live_inventory_fail_closed(self):
        self.proposals = [{'number': 5, 'title': 'Review release-set abc',
                           'user': {'type': 'Bot', 'login': BOT}, 'head': {'sha': SHA}}]
        for changed in ({'head': {'sha': 'c' * 40}}, {'changed_files': 2}, {'changed_files': None}):
            def api(endpoint, **kwargs):
                value = self.api(endpoint, **kwargs)
                return {**value, **changed} if endpoint.endswith('/pulls/5') else value
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                ready.release_status(self.version, api, BOT)

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

    def active_health(self, status, active_jobs, identity=SHA, total_count=None):
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        active = {'id': 8, 'run_attempt': 1, 'head_sha': identity, 'head_branch': 'main',
                  'head_repository': {'full_name': ready.REPOSITORY}, 'event': 'push',
                  'status': status, 'conclusion': None, 'updated_at': now.isoformat()}
        previous = {**active, 'id': 7, 'head_sha': 'b' * 40, 'status': 'completed', 'conclusion': 'success'}
        def api(endpoint, **kwargs):
            if '/workflows/build.yml/runs?' in endpoint:
                self.assertNotIn('status=completed', endpoint)
                return {'workflow_runs': [active, previous]}
            if '/runs/8/' in endpoint:
                return {'total_count': len(active_jobs) if total_count is None else total_count, 'jobs': active_jobs}
            if '/runs/7/' in endpoint:
                jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success'}
                        for channel in ready.CHANNELS for suffix in ('qualification / aggregate', 'promote')]
                return {'total_count': len(jobs), 'jobs': jobs}
            return self.api(endpoint, **kwargs)
        return delivery.inspect(SHA, 'development', BOT, api, now)

    def test_active_profile_failure_is_visible_before_other_profile_completes(self):
        jobs = [{'name': 'Publish (finite) / build / build', 'status': 'completed', 'conclusion': 'failure',
                 'steps': [{'name': 'Prepare candidate publication', 'conclusion': 'failure'}]},
                {'name': 'Publish (finite-dev) / qualification / phase (fresh)', 'status': 'in_progress'}]
        report = self.active_health('in_progress', jobs)
        self.assertFalse(report['healthy'])
        self.assertIn('Prepare candidate publication', report['problems'][0])
        self.assertIn('finite-dev', report['activeBuilds'][0]['runningPhases'][0])
        for channel in ready.CHANNELS:
            self.assertEqual(report['channels'][channel]['promoted']['runId'], 7)
        self.assertIn('/actions/runs/8', delivery.summary(report))
        self.assertIsNone(report['buildRun'])

    def test_queued_running_and_approval_waiting_builds_do_not_replace_successful_channels(self):
        for status in ('queued', 'in_progress', 'waiting'):
            report = self.active_health(status, [])
            self.assertTrue(report['healthy'])
            self.assertEqual(bool(report['blockers']), status == 'waiting')
            self.assertEqual(report['channels']['finite']['promoted']['runId'], 7)
        with self.assertRaisesRegex(ValueError, 'Invalid active build identity'):
            self.active_health('in_progress', [], identity='unknown')
        with self.assertRaisesRegex(ValueError, 'Unknown active build status'):
            self.active_health('unknown', [])
        for count in (1, 101):
            with self.assertRaisesRegex(ValueError, 'Active build job inventory is incomplete'):
                self.active_health('in_progress', [], total_count=count)

    def test_failed_preparation_requires_explicit_retry_without_dispatching_again(self):
        report = {'release': {'state': 'unprepared'}, 'buildRun': 7}
        for conclusion in ('failure', 'timed_out', 'cancelled', 'action_required'):
            def api(endpoint):
                return ({'object': {'sha': SHA}} if endpoint.endswith('/git/ref/heads/main') else
                        {'workflow_runs': [{'head_sha': SHA, 'status': 'completed', 'conclusion': conclusion}]})
            with self.subTest(conclusion=conclusion), patch.object(delivery.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'explicitly rerun'):
                    delivery.dispatch(report, SHA, api)
                run.assert_not_called()

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

    def test_another_revision_failure_does_not_block_one_new_dispatch(self):
        report = {'release': {'state': 'unprepared'}, 'buildRun': 7}
        def api(endpoint):
            return ({'object': {'sha': SHA}} if endpoint.endswith('/git/ref/heads/main') else
                    {'workflow_runs': [{'head_sha': 'b' * 40, 'status': 'completed', 'conclusion': 'failure'}]})
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertIn('Dispatched', delivery.dispatch(report, SHA, api))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads(run.call_args.kwargs['input']),
                             {'ref': 'main', 'inputs': {'build_run': '7'}})

    def test_monitor_is_read_only_and_retains_health_evidence(self):
        report = {'healthy': True, 'problems': [], 'channels': {},
                  'release': {'state': 'unprepared', 'reason': 'Ready to prepare'}}
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                summary = Path(temporary) / 'summary.md'
                with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': ready.REPOSITORY,
                                            'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA,
                                            'GITHUB_STEP_SUMMARY': str(summary)}), \
                        patch.object(delivery, 'root_version', return_value=self.version), \
                        patch.object(delivery, 'inspect', return_value=report), \
                        patch.object(delivery, 'dispatch', side_effect=AssertionError('Monitor must remain read-only')) as dispatch:
                    self.assertEqual(delivery.main(), 0)
                    dispatch.assert_not_called()
                retained = json.loads(Path('.bluebuild/delivery-health.json').read_text())
                self.assertTrue(retained['healthy'])
                self.assertEqual(retained['problems'], [])
                self.assertIn('Ready to prepare', summary.read_text())
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
