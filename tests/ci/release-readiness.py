#!/usr/bin/env python3
"""Paired preparation is idempotent; incomplete products require recovery."""
import base64
import copy
import contextlib
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
spec = importlib.util.spec_from_file_location('reconciliation', ROOT / 'scripts/ci/reconcile-delivery.py')
reconciliation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconciliation)
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
                jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success', 'completed_at': now.isoformat()}
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
                jobs = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success', 'completed_at': now.isoformat()}
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
                                            'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': 'reconcile',
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


class DeliveryHistory(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.runs = []
        self.jobs = {}
        self.requests = []
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.file = str(Path(self.root.name) / 'scripts/ci/delivery-health.py')

    def add_run(self, number, channels=(), age=1, conclusion='success'):
        self.runs.append({'id': number, 'run_attempt': 1, 'head_sha': 'b' * 40,
                          'head_branch': 'main', 'head_repository': {'full_name': ready.REPOSITORY},
                          'event': 'push', 'status': 'completed', 'conclusion': conclusion,
                          # Updated metadata is not evidence of a fresh promotion.
                          'updated_at': self.now.isoformat(),
                          'created_at': (self.now - timedelta(days=10)).isoformat()})
        self.jobs[number] = [{'name': f'Publish ({channel}) / {suffix}', 'conclusion': 'success',
                             'completed_at': (self.now - timedelta(hours=age)).isoformat()}
                            for channel in channels for suffix in ('qualification / aggregate', 'promote')]

    def api(self, endpoint):
        self.requests.append(endpoint)
        if '/workflows/build.yml/runs?' in endpoint:
            page = int(endpoint.split('&page=')[-1]) if '&page=' in endpoint else 1
            start = (page - 1) * delivery.HISTORY_PAGE_SIZE
            return {'workflow_runs': self.runs[start:start + delivery.HISTORY_PAGE_SIZE]}
        if '/jobs?' in endpoint:
            number = int(endpoint.split('/runs/')[1].split('/')[0])
            return {'total_count': len(self.jobs[number]), 'jobs': self.jobs[number]}
        raise AssertionError(endpoint)

    def inspect(self, api=None):
        with patch.object(delivery, '__file__', self.file), \
                patch.object(delivery, 'release_status', return_value={'state': 'development', 'reason': 'No release'}):
            return delivery.inspect(SHA, 'development', BOT, api or self.api, self.now)

    def test_finds_both_promotions_after_more_than_thirty_source_only_builds(self):
        for number in range(50, 10, -1):
            self.add_run(number)
        self.add_run(10, ready.CHANNELS)
        report = self.inspect()
        self.assertTrue(report['healthy'])
        self.assertEqual(report['buildHistory'], {'state': 'exhausted', 'pages': 2, 'runs': 41})
        self.assertEqual(report['channels']['finite']['promoted']['runId'], 10)
        self.assertEqual(report['channels']['finite-dev']['promoted']['runId'], 10)
        # Old creation timestamps cannot truncate a recently retried promotion.
        self.assertIn('&page=2', ' '.join(self.requests))

    def test_older_created_run_with_recent_retry_supersedes_stale_promotion(self):
        self.add_run(2, ready.CHANNELS, age=40)
        self.add_run(1, ready.CHANNELS, age=1)
        report = self.inspect()
        self.assertTrue(report['healthy'])
        for channel in ready.CHANNELS:
            self.assertEqual(report['channels'][channel]['promoted']['runId'], 1)

    def test_native_completion_controls_exact_freshness_boundary(self):
        for hours, healthy in ((35.999, True), (36, False), (37, False)):
            self.runs.clear(); self.jobs.clear()
            self.add_run(1, ready.CHANNELS, age=hours)
            with self.subTest(hours=hours):
                report = self.inspect()
                self.assertEqual(report['healthy'], healthy)
                if not healthy:
                    self.assertTrue(all('36 hours' in problem for problem in report['problems']))

    def test_partial_channels_and_bounded_unknown_are_not_failed_publication(self):
        for number in range(delivery.HISTORY_PAGE_SIZE * delivery.HISTORY_MAX_PAGES, 0, -1):
            self.add_run(number, ('finite',) if number == 1 else ())
        report = self.inspect()
        self.assertEqual(report['buildHistory']['state'], 'limited')
        self.assertFalse(report['healthy'])
        self.assertEqual(report['channels']['finite']['promoted']['runId'], 1)
        self.assertIsNone(report['channels']['finite-dev']['promoted'])
        self.assertIn('evidence unavailable', report['problems'][0])
        self.assertIn('does not establish a failed publication', report['problems'][0])
        self.assertEqual(sum('/workflows/build.yml/' in endpoint for endpoint in self.requests), 5)

    def test_absent_history_does_not_claim_publication_failed(self):
        report = self.inspect()
        self.assertEqual(report['buildHistory']['state'], 'exhausted')
        self.assertFalse(report['healthy'])
        self.assertTrue(all('no recorded successful promotion' in problem for problem in report['problems']))
        self.assertFalse(any('Latest main build failed' in problem for problem in report['problems']))

    def test_true_latest_failure_is_preserved_alongside_older_promotions(self):
        self.add_run(2, conclusion='failure')
        self.jobs[2] = [{'name': 'Publish (finite-dev) / promote', 'conclusion': 'failure'}]
        self.add_run(1, ready.CHANNELS)
        report = self.inspect()
        self.assertFalse(report['healthy'])
        self.assertIn('Latest main build failed: Publish (finite-dev) / promote', report['problems'])

    def test_missing_native_completion_cannot_invent_freshness(self):
        self.add_run(1, ready.CHANNELS)
        del self.jobs[1][0]['completed_at']
        with self.assertRaisesRegex(ValueError, 'evidence unavailable'):
            self.inspect()

    def test_unavailable_page_and_duplicate_inventory_fail_closed(self):
        for number in range(31, 0, -1): self.add_run(number)
        from github_api import GitHubReadError
        def unavailable(endpoint):
            if '&page=2' in endpoint: raise GitHubReadError('Unavailable metadata')
            return self.api(endpoint)
        # Transport errors propagate; no healthy snapshot is fabricated.
        with self.assertRaisesRegex(GitHubReadError, 'Unavailable metadata'):
            self.inspect(unavailable)
        def duplicate(endpoint):
            result = self.api(endpoint)
            if '&page=2' in endpoint: result['workflow_runs'][0] = self.runs[0]
            return result
        with self.assertRaisesRegex(ValueError, 'repeated run identity'):
            self.inspect(duplicate)

    def test_incomplete_jobs_and_artifacts_cannot_authorize_preparation(self):
        self.add_run(1, ready.CHANNELS)
        def incomplete(endpoint):
            result = self.api(endpoint)
            if '/jobs?' in endpoint: result['total_count'] += 1
            return result
        with self.assertRaisesRegex(ValueError, 'job inventory is incomplete'):
            self.inspect(incomplete)
        self.runs[0]['head_sha'] = SHA
        def artifacts(endpoint):
            if '/artifacts?' in endpoint: return {'total_count': 1, 'artifacts': []}
            return self.api(endpoint)
        with self.assertRaisesRegex(ValueError, 'artifact inventory is incomplete'):
            self.inspect(artifacts)

    def test_time_budget_exhaustion_never_produces_a_healthy_snapshot(self):
        with patch.object(delivery.time, 'monotonic', side_effect=[0, delivery.HISTORY_SECONDS]):
            with self.assertRaisesRegex(ValueError, 'observation time budget exhausted'):
                self.inspect()

    def test_budget_crossing_during_last_read_rejects_late_result(self):
        with patch.object(delivery.time, 'monotonic', side_effect=[0, 0, delivery.HISTORY_SECONDS]):
            with self.assertRaisesRegex(ValueError, 'observation time budget exhausted'):
                self.inspect()


class DeliverySnapshots(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(contextlib.chdir(self.root))
        self.enterContext(patch.dict(os.environ, {'GITHUB_ACTIONS': 'true',
            'GITHUB_REPOSITORY': ready.REPOSITORY, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA,
            'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_JOB': 'reconcile',
            'GITHUB_OUTPUT': str(self.root / 'output'), 'GITHUB_STEP_SUMMARY': str(self.root / 'summary')}))
        self.report = {'healthy': True, 'problems': [], 'channels': {}, 'buildRun': 5,
                       'release': {'state': 'unprepared', 'reason': 'Ready to prepare'}}
        self.path = Path('.bluebuild/delivery-health.json')

    def produce(self, healthy=True):
        self.report['healthy'] = healthy
        with patch.object(delivery, 'root_version', return_value='1.2.3'), \
                patch.object(delivery, 'inspect', return_value=self.report) as inspect:
            self.assertEqual(delivery.main(), 0 if healthy else 1)
        return inspect

    def test_dispatch_reuses_one_read_only_inspection_even_when_health_is_unhealthy(self):
        for healthy in (True, False):
            inspect = self.produce(healthy)
            with patch.object(delivery, 'inspect', side_effect=AssertionError('No second inspection')), \
                    patch.object(delivery, 'dispatch', return_value='No preparation dispatch needed.') as dispatch:
                reconciliation.reconcile(self.path, delivery)
            inspect.assert_called_once()
            self.assertEqual(dispatch.call_args.args[0]['buildRun'], 5)
            self.assertEqual(dispatch.call_args.args[0]['healthy'], healthy)
            self.assertIn('snapshot=true', (self.root / 'output').read_text())

    def test_standalone_reconciliation_still_inspects_and_dispatches(self):
        with patch.object(delivery, 'root_version', return_value='1.2.3'), \
                patch.object(delivery, 'inspect', return_value=self.report) as inspect, \
                patch.object(delivery, 'dispatch', return_value='No preparation dispatch needed.') as dispatch:
            reconciliation.reconcile(delivery=delivery)
        inspect.assert_called_once()
        dispatch.assert_called_once_with(self.report, SHA)

    def test_cross_job_attempt_revision_and_invalid_dispatch_fields_never_dispatch(self):
        self.produce()
        original = json.loads(self.path.read_text())
        mutations = [('repository', 'other/repo'), ('revision', 'b' * 40), ('runId', '13'),
                     ('runAttempt', '3'), ('jobName', 'other'), ('schema', True)]
        for key, value in mutations:
            changed = copy.deepcopy(original)
            changed['snapshot'][key] = value
            self.path.write_text(json.dumps(changed))
            with self.subTest(key=key), patch.object(delivery, 'dispatch') as dispatch:
                with self.assertRaises(ValueError):
                    reconciliation.reconcile(self.path, delivery)
                dispatch.assert_not_called()
        for fields in ({'buildRun': True}, {'healthy': 'yes'}, {'release': None}):
            self.path.write_text(json.dumps({**original, **fields}))
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                delivery.read_snapshot(self.path)

    def test_missing_nonregular_oversized_and_duplicate_json_snapshots_reject(self):
        with self.assertRaises(ValueError):
            delivery.read_snapshot(self.path)
        self.path.parent.mkdir()
        self.path.write_text('x' * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            delivery.read_snapshot(self.path)
        self.path.write_text('{"snapshot":1,"snapshot":2}')
        with self.assertRaises(ValueError):
            delivery.read_snapshot(self.path)
        link = self.root / 'linked.json'
        link.symlink_to(self.path.resolve())
        with self.assertRaises(ValueError):
            delivery.read_snapshot(link)

    def test_failed_inspection_removes_stale_snapshot_and_cannot_dispatch(self):
        self.produce()
        with patch.object(delivery, 'inspect', side_effect=ValueError('Unavailable inventory')), \
                self.assertRaisesRegex(ValueError, 'Unavailable inventory'):
            delivery.main()
        self.assertFalse(self.path.exists())
        with patch.object(delivery, 'dispatch') as dispatch, self.assertRaises(ValueError):
            reconciliation.reconcile(self.path, delivery)
        dispatch.assert_not_called()

    def test_dispatch_failure_preserves_read_only_report(self):
        self.produce()
        before = self.path.read_bytes()
        with patch.object(delivery, 'dispatch', side_effect=ValueError('Lost response')), \
                self.assertRaisesRegex(ValueError, 'Lost response'):
            reconciliation.reconcile(self.path, delivery)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
