#!/usr/bin/env python3
"""Native timing includes failed work and reused jobs without double charging."""
from copy import deepcopy
import contextlib
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import workflow_costs as costs
import cost_receipts
spec = importlib.util.spec_from_file_location('stage_measure', ROOT / 'scripts/bluebuild/measure.py')
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class SourceRepetition(unittest.TestCase):
    def setUp(self):
        self.revision = 'b' * 40
        self.aggregate = '/nix/store/' + 'a' * 32 + '-finite-ci-checks.drv'
        self.cohort = {'lockSha256': {'flake.lock': 'c' * 64, 'devenv.lock': 'd' * 64},
                       'nixExecutable': '/nix/store/nix/bin/nix', 'pythonExecutable': '/usr/bin/python3'}
        def job(identity, start, finish, seconds):
            return {'jobId': identity, 'runAttempt': 1, 'role': 'checks', 'status': 'completed',
                    'conclusion': 'success', 'startedAt': start, 'completedAt': finish,
                    'checkoutRevision': self.revision, 'nixAggregateDerivation': self.aggregate,
                    'runnerSeconds': seconds, 'exclusiveRunnerSeconds': seconds,
                    'runner': {'toolCohort': deepcopy(self.cohort)},
                    'stages': [{'stage': name, 'seconds': elapsed, 'outcome': 'success', 'status': 0,
                                'startedAt': start if name == 'Evaluate aggregate' else
                                (costs.timestamp(start) + costs.timedelta(seconds=seconds / 2)).isoformat()}
                               for name, elapsed in [('Evaluate aggregate', 30), ('Build aggregate', 20)]]}
        self.proof = {'repository': costs.REPOSITORY, 'workflow': '.github/workflows/build.yml',
                      'event': 'merge_group', 'status': 'completed', 'conclusion': 'success', 'runId': 10,
                      'sourceRevision': self.revision, 'headBranch': 'gh-readonly-queue/main/pr-1-base',
                      'jobs': [job(100, '2026-10-25T01:00:00Z', '2026-10-25T01:01:00Z', 60),
                               {'jobId': 101, 'role': 'build', 'conclusion': 'success',
                                'completedAt': '2026-10-25T01:03:00Z', 'runnerSeconds': 60}]}
        self.target = {**deepcopy(self.proof), 'event': 'workflow_dispatch', 'headBranch': 'main', 'runId': 20,
                       'jobs': [job(200, '2026-10-25T01:04:00Z', '2026-10-25T01:06:00Z', 120)]}
        self.target['jobs'][0]['stages'][0]['seconds'] = 70
        self.target['jobs'][0]['stages'][1]['startedAt'] = '2026-10-25T01:05:10Z'

    def report(self, proof=None):
        return costs.source_repetition([self.proof if proof is None else proof, self.target])

    def test_source_rollout_counts_unique_native_jobs_and_preserves_incomplete_coverage(self):
        run = {**deepcopy(self.target), 'event': 'push'}
        job = run['jobs'][0]
        job['sourceReuse'] = {'mode': 'shadow', 'eligible': True, 'hit': False, 'shadowMatch': True,
                              'reason': 'verified-exact-queue-proof', 'producer': {'jobId': 100}, 'lookupSeconds': 2}
        report = costs.source_proof_rollout([self.proof, run, deepcopy(run)])
        self.assertEqual(report['shadowMatches'], 1)
        self.assertEqual(report['enabledHits'], 0)
        self.assertIsNone(report['activationDecision'])
        self.assertEqual(len(report['rows']), 1)
        job['conclusion'] = 'failure'
        self.assertEqual(costs.source_proof_rollout([run])['shadowMatches'], 0)
        job['sourceReuse']['shadowMatch'] = False
        self.assertEqual(costs.source_proof_rollout([run])['shadowMismatches'], 1)
        del job['sourceReuse']
        self.assertEqual(costs.source_proof_rollout([run])['unknownJobs'], 1)

    def test_exact_recorded_inputs_repeat_without_authorizing_or_double_adding_cost(self):
        before = deepcopy([self.proof, self.target])
        report = self.report()
        self.assertEqual(report['repeatedJobs'], 1)
        self.assertEqual(report['repeatedKnownRunnerSeconds'], 120)
        self.assertEqual(report['repeatedNestedPhaseSeconds'], 90)
        self.assertEqual(report['repeatedKnownExclusiveRunnerSeconds'], 120)
        self.assertEqual(report['rows'][0]['queueProof'], {'runId': 10, 'jobId': 100, 'runAttempt': 1})
        self.assertFalse(report['authorizesPublication'])
        self.assertFalse(report['productionReuseEnabled'])
        self.assertFalse(report['eligibilityEvaluated'])
        self.assertIsNone(report['rows'][0]['reuseEligible'])
        self.assertIsNone(report['rows'][0]['reuseHit'])
        self.assertIsNone(report['rows'][0]['nativeRunnerImage'])
        self.assertEqual([self.proof, self.target], before)

    def test_source_shadow_gate_requires_whole_workflow_success(self):
        run = {**deepcopy(self.target), 'event': 'push'}
        run['jobs'][0]['sourceReuse'] = {'mode': 'shadow', 'eligible': True, 'hit': False,
                                       'shadowMatch': True, 'reason': 'verified-exact-queue-proof'}
        for status, conclusion in (('in_progress', None), ('completed', 'failure'),
                                   ('completed', 'cancelled'), ('completed', 'success')):
            run.update(status=status, conclusion=conclusion)
            with self.subTest(status=status, conclusion=conclusion):
                report = costs.source_proof_rollout([run])
                self.assertEqual(report['shadowMatches'], int(conclusion == 'success'))
                self.assertEqual(report['costCohorts'][0]['knownRunnerSeconds'], 120)

    def test_source_cost_cohorts_conserve_retries_failures_active_and_unknown_cost(self):
        runs = []
        for identity, mode, eligible, elapsed, status, conclusion in (
                (200, 'shadow', True, 120, 'completed', 'success'),
                (201, 'enabled', True, 30, 'completed', 'success'),
                (202, 'enabled', True, 40, 'completed', 'failure'),
                (203, 'enabled', None, 15, 'in_progress', None),
                (204, None, None, None, 'completed', 'failure')):
            run = {**deepcopy(self.target), 'event': 'push', 'runId': identity,
                   'sourceRevision': ('c' if identity == 201 else 'b') * 40}
            job = run['jobs'][0]
            job.update(jobId=identity, runnerSeconds=elapsed, status=status, conclusion=conclusion,
                       sourceReuse={'mode': mode, 'eligible': eligible,
                                    'hit': None if eligible is None else mode == 'enabled' and eligible is True,
                                    'reason': 'verified-exact-queue-proof' if eligible else None})
            runs.append(run)
        retry = {**deepcopy(runs[0]), 'jobs': [deepcopy(runs[0]['jobs'][0]),
                                             {**deepcopy(runs[1]['jobs'][0]), 'jobId': 205, 'runAttempt': 2}]}
        # Carried earlier-attempt jobs appear in native retry inventories once.
        retry['jobs'][1]['sourceReuse']['mode'] = 'shadow'
        retry['jobs'][1]['sourceReuse']['hit'] = False
        report = costs.source_proof_rollout([*runs, retry])
        self.assertEqual(len(report['rows']), 6)
        self.assertEqual(sum(row['knownRunnerSeconds'] or 0 for row in report['costCohorts']), 235)
        self.assertEqual(sum(row['unknownDurationJobs'] for row in report['costCohorts']), 1)
        active = next(row for row in report['costCohorts'] if row['status'] == 'in_progress')
        self.assertEqual(active['knownRunnerSeconds'], 15)
        self.assertIsNone(active['completedJobMedianSeconds'])
        self.assertEqual({row['sourceRevision'] for row in report['costCohorts']}, {'b' * 40, 'c' * 40})
        self.assertEqual(costs.source_proof_rollout([runs[1]])['costCohorts'][0]['completedJobMedianSeconds'], 30)
        conflict = deepcopy(runs[0]); conflict['jobs'][0]['runnerSeconds'] = 121
        with self.assertRaisesRegex(ValueError, 'Conflicting native source-job'):
            costs.source_proof_rollout([runs[0], conflict])
        rendered = costs.markdown({'observedAt': 'now', 'baseline': {'cohorts': []},
                                   'observation': {'cohorts': [], 'complete': False}, 'limitations': [],
                                   'sourceProofRollout': report})
        self.assertIn('Whole-job occupancy includes setup, lookup, retention and cleanup', rendered)
        self.assertIn('Active elapsed time remains censored', rendered)
        self.assertIn('| unknown | unknown | unknown | unknown | failure/success |', rendered)
        self.assertIn('| 15 | 0 | unknown |', rendered)

    def test_source_aggregate_or_recorded_tools_cannot_match_across_cohorts(self):
        for change in ('source', 'aggregate', 'tool'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'source':
                    self.target['sourceRevision'] = self.target['jobs'][0]['checkoutRevision'] = 'e' * 40
                elif change == 'aggregate':
                    self.target['jobs'][0]['nixAggregateDerivation'] = self.aggregate.replace('a' * 32, 'e' * 32)
                else:
                    self.target['jobs'][0]['runner']['toolCohort']['pythonExecutable'] = '/usr/bin/python3.11'
                self.assertEqual(self.report()['rows'][0]['state'], 'no-earlier-matching-queue-proof-observed')

    def test_native_pr_head_does_not_substitute_for_actual_checkout(self):
        self.target['jobs'][0]['checkoutRevision'] = 'e' * 40
        self.assertIn('exact-checkout-revision', self.report()['rows'][0]['missing'])
        self.assertEqual(self.report()['unknownJobs'], 1)

    def test_entire_queue_workflow_must_finish_before_target_starts(self):
        self.proof['jobs'][1]['completedAt'] = '2026-10-25T01:05:00Z'
        self.assertEqual(self.report()['repeatedJobs'], 0)

    def test_failed_active_or_nonqueue_run_is_not_a_successful_queue_proof(self):
        for field, value in [('status', 'in_progress'), ('conclusion', 'failure'),
                             ('event', 'pull_request'), ('headBranch', 'other')]:
            with self.subTest(field=field):
                proof = {**self.proof, field: value}
                self.assertEqual(self.report(proof)['observedQueueProofs'], 0)

    def test_missing_queue_timestamps_do_not_create_a_proof(self):
        self.proof['jobs'][1]['completedAt'] = None
        self.assertEqual(self.report()['observedQueueProofs'], 0)

    def test_missing_receipts_and_tools_remain_unknown(self):
        for field in ('checkoutRevision', 'nixAggregateDerivation', 'stages', 'toolCohort'):
            with self.subTest(field=field):
                self.setUp()
                job = self.target['jobs'][0]
                if field == 'toolCohort': job['runner'][field] = None
                elif field == 'stages': job[field] = []
                else: job.pop(field)
                report = self.report()
                self.assertEqual(report['unknownJobs'], 1)
                self.assertEqual(report['repeatedJobs'], 0)
                self.assertIsNone(report['rows'][0]['reuseHit'])

    def test_partial_failed_or_invalid_phases_remain_unknown(self):
        for mutation in ('partial', 'failed', 'nan', 'negative', 'boolean', 'outside-job'):
            with self.subTest(mutation=mutation):
                self.setUp()
                phases = self.target['jobs'][0]['stages']
                if mutation == 'partial': phases.pop()
                elif mutation == 'failed': phases[0]['outcome'] = 'failure'
                else: phases[0]['seconds'] = {'nan': float('nan'), 'negative': -1,
                                               'boolean': True, 'outside-job': 500}[mutation]
                self.assertEqual(self.report()['unknownJobs'], 1)

    def test_invalid_job_interval_or_nonmain_dispatch_remains_unknown(self):
        for mutation in ('missing-time', 'reversed-time', 'no-timezone', 'branch'):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation == 'branch': self.target['headBranch'] = 'other'
                else:
                    self.target['jobs'][0]['startedAt'] = {'missing-time': None,
                        'reversed-time': '2026-10-25T02:00:00Z', 'no-timezone': '2026-10-25T01:04:00'}[mutation]
                self.assertEqual(self.report()['unknownJobs'], 1)

    def test_copied_phase_timestamps_do_not_become_current_source_cost(self):
        self.target['jobs'][0]['stages'][0]['startedAt'] = '2026-10-24T01:04:00Z'
        report = self.report()
        self.assertEqual(report['repeatedJobs'], 0)
        self.assertIn('phase-native-interval', report['rows'][0]['missing'])
        self.assertEqual(report['rows'][0]['runnerSeconds'], 120)

    def test_overlapping_serial_aggregate_phases_remain_unknown(self):
        self.target['jobs'][0]['stages'][1]['startedAt'] = '2026-10-25T01:04:30Z'
        self.assertIn('serial-aggregate-phases', self.report()['rows'][0]['missing'])

    def test_no_observed_proof_is_not_a_cache_miss(self):
        report = costs.source_repetition([self.target])
        self.assertEqual(report['rows'][0]['state'], 'no-earlier-matching-queue-proof-observed')
        self.assertIsNone(report['rows'][0]['reuseEligible'])
        self.assertIsNone(report['rows'][0]['reuseHit'])

    def test_reused_source_job_across_retry_projections_is_counted_once(self):
        replay = {**deepcopy(self.target), 'runAttempt': 2}
        report = costs.source_repetition([self.proof, self.target, replay])
        self.assertEqual(report['repeatedJobs'], 1)
        self.assertEqual(report['repeatedKnownRunnerSeconds'], 120)
        replay['jobs'][0]['runnerSeconds'] = 121
        with self.assertRaisesRegex(ValueError, 'Conflicting native source-job'):
            costs.source_repetition([self.proof, self.target, replay])

    def test_latest_available_proof_is_selected_deterministically(self):
        later = deepcopy(self.proof)
        later['runId'] = 11
        later['jobs'][0]['jobId'] = 110
        later['jobs'][1]['completedAt'] = '2026-10-25T01:03:30Z'
        report = costs.source_repetition([later, self.target, self.proof])
        self.assertEqual(report['rows'][0]['queueProof']['runId'], 11)

    def test_unknown_native_and_exclusive_time_are_preserved(self):
        self.target['jobs'][0].update(runnerSeconds=None, exclusiveRunnerSeconds=None)
        report = self.report()
        self.assertEqual(report['repeatedRunnerTimeUnknownJobs'], 1)
        self.assertEqual(report['repeatedExclusiveTimeUnknownJobs'], 1)
        self.assertIsNone(report['rows'][0]['runnerSeconds'])
        self.assertIsNone(report['rows'][0]['exclusiveRunnerSeconds'])

    def test_unserializable_cohort_is_unknown_and_foreign_workflows_are_excluded(self):
        self.target['jobs'][0]['runner']['toolCohort']['extra'] = float('nan')
        self.assertIn('serializable-tool-cohort', self.report()['rows'][0]['missing'])
        for field, value in [('repository', 'fork/repo'), ('workflow', '.github/workflows/other.yml')]:
            with self.subTest(field=field):
                report = costs.source_repetition([{**self.target, field: value}])
                self.assertEqual(report['rows'], [])

    def test_markdown_labels_overlapping_measurements_and_unknown_coverage(self):
        report = {'observedAt': 'now', 'baseline': {'cohorts': []},
                  'observation': {'cohorts': [], 'complete': False}, 'limitations': [],
                  'sourceRepetition': self.report()}
        rendered = costs.markdown(report)
        self.assertIn('120.0 known native runner seconds', rendered)
        self.assertIn('90.0 nested evaluation/build seconds', rendered)
        self.assertIn('These measurements overlap', rendered)
        self.assertIn('Unseen queue proofs are not cache misses', rendered)


class Costs(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.run = {'id': 10, 'run_attempt': 2, 'repository': {'full_name': costs.REPOSITORY},
                    'head_sha': 'a' * 40, 'path': '.github/workflows/build.yml', 'status': 'completed',
                    'event': 'workflow_dispatch', 'conclusion': 'success', 'html_url': 'https://github.com/run/10',
                    'created_at': '2026-10-23T10:00:00Z'}
        self.job = {'id': 1, 'run_id': 10, 'run_attempt': 1, 'head_sha': 'a' * 40,
                    'name': 'Publish (finite) / build / build', 'status': 'completed', 'conclusion': 'failure',
                    'created_at': '2026-10-23T10:00:00Z', 'started_at': '2026-10-23T10:01:00Z',
                    'completed_at': '2026-10-23T10:03:00Z', 'steps': []}
        self.jobs = [self.job]

    def api(self, endpoint):
        if endpoint.endswith('/attempts/1'): return {**self.run, 'run_attempt': 1, 'conclusion': 'failure'}
        if '/jobs?' in endpoint: return {'total_count': len(self.jobs), 'jobs': deepcopy(self.jobs)}
        raise AssertionError(endpoint)

    def observe(self):
        return costs.observe(self.run, self.api, self.now)

    def test_reused_native_job_is_charged_once_with_failed_work(self):
        report = self.observe()
        self.assertEqual(len(report['attempts']), 2)
        self.assertEqual(len(report['jobs']), 1)
        self.assertEqual(report['jobs'][0]['runAttempt'], 1)
        row = costs.aggregate([report])[0]
        self.assertEqual(row['runnerSeconds'], 120)
        self.assertEqual(row['queueSeconds'], 60)
        self.assertEqual(row['conclusions'], {'failure': 1})

    def copied_job_report(self, changes=None, *, run_changes=None, original_changes=None):
        original = {**self.job, 'runner_id': 100, 'runner_name': 'GitHub Actions 100',
                    'conclusion': 'success', **(original_changes or {})}
        clone = {**deepcopy(original), 'id': 2, 'run_attempt': 2, **(changes or {})}
        run = {**self.run, 'run_started_at': '2026-10-23T10:10:00Z', **(run_changes or {})}
        def api(endpoint):
            if endpoint.endswith('/attempts/1'):
                return {**run, 'run_attempt': 1, 'run_started_at': '2026-10-23T10:00:00Z'}
            if '/jobs?' in endpoint:
                rows = [original] if '/attempts/1/' in endpoint else [clone]
                return {'total_count': len(rows), 'jobs': deepcopy(rows)}
            self.fail('Unexpected endpoint: ' + endpoint)
        return costs.observe(run, api, self.now)

    def test_copied_check_run_identity_charges_original_runner_execution_once(self):
        report = self.copied_job_report()
        self.assertEqual(len(report['jobs']), 1)
        self.assertEqual(report['jobs'][0]['jobId'], 1)
        self.assertEqual(report['jobs'][0]['runAttempt'], 1)
        self.assertEqual(report['jobs'][0]['nativeAliases'], [{'jobId': 2, 'runAttempt': 2}])
        self.assertEqual(costs.aggregate([report])[0]['runnerSeconds'], 120)
        costs.exclusive_occupancy(report)
        self.assertEqual(report['jobs'][0]['exclusiveRunnerSeconds'], 120)

    def test_real_retry_and_prior_failure_both_remain_charged(self):
        report = self.copied_job_report(
            {'started_at': '2026-10-23T10:11:00Z', 'completed_at': '2026-10-23T10:13:00Z'},
            original_changes={'conclusion': 'failure'})
        self.assertEqual(len(report['jobs']), 2)
        self.assertEqual(sum(j['runnerSeconds'] for j in report['jobs']), 240)
        self.assertEqual(costs.aggregate([report])[0]['conclusions'], {'failure': 2})

    def test_different_runner_or_steps_cannot_prove_copied_execution(self):
        for change in ({'runner_id': 101}, {'runner_name': 'another runner'},
                       {'steps': [{'name': 'different step', 'conclusion': 'success'}]},
                       {'name': 'different job'}, {'conclusion': 'failure'}):
            with self.subTest(change=change):
                self.assertEqual(len(self.copied_job_report(change)['jobs']), 2)

    def test_missing_execution_identity_is_not_assumed_duplicate(self):
        for change in ({'runner_id': None}, {'runner_id': 0}, {'runner_name': None}):
            with self.subTest(change=change):
                self.assertEqual(len(self.copied_job_report(original_changes=change)['jobs']), 2)
        for start in (None, 'invalid', '2026-10-23T10:02:00Z'):
            with self.subTest(start=start):
                self.assertEqual(len(self.copied_job_report(run_changes={'run_started_at': start})['jobs']), 2)

    def test_active_and_cancelled_work_remain_visible(self):
        self.job.update(status='in_progress', conclusion=None, completed_at=None)
        self.run.update(status='in_progress', conclusion=None)
        report = self.observe()
        self.assertEqual(report['jobs'][0]['runnerSeconds'], 7140)
        self.assertEqual(report['elapsedSeconds'], 7200)
        self.job.update(status='completed', conclusion='cancelled', completed_at='2026-10-23T10:02:00Z')
        self.assertEqual(costs.aggregate([self.observe()])[0]['conclusions'], {'cancelled': 1})

    def test_profile_and_recovery_classification(self):
        self.job['name'] = 'Publish (finite-dev) / build / build'
        self.job['steps'] = [{'name': 'Validate and resume immutable candidate', 'conclusion': 'success'}]
        report = self.observe()
        self.assertEqual(report['category'], 'recovery')
        self.assertEqual(report['jobs'][0]['profile'], 'finite-dev')
        self.run['event'] = 'merge_group'
        self.assertEqual(self.observe()['category'], 'merge_queue')

    def test_native_source_job_names_keep_roles_and_unique_retry_costs(self):
        expected = {'Nix and runtime contracts': 'checks', 'Documentation checks': 'docs',
                    'Select checks': 'selection', 'CI gate': 'gate'}
        self.jobs = [{**self.job, 'id': index + 1, 'name': name}
                     for index, name in enumerate(expected)]
        report = self.observe()
        self.assertEqual({j['name']: j['role'] for j in report['jobs']}, expected)
        self.assertEqual(len(report['jobs']), 4)
        self.assertEqual(sum(row['runnerSeconds'] for row in costs.aggregate([report])), 480)
        self.assertTrue(all(j['profile'] == 'shared_or_unknown' for j in report['jobs']))
        self.assertTrue(all(j['qualificationReuseHit'] is None for j in report['jobs']))
        for name in ('Nix and runtime contracts (new)', 'Future runtime checks', 'Documentation validation'):
            self.assertEqual(costs.job_role(name), 'unknown')

    def test_legacy_qualification_does_not_become_a_current_phase_or_profile(self):
        self.job['name'] = 'Publish (bluefin-dx-next) / qualification / qualify'
        historical = self.observe()
        self.assertEqual(historical['jobs'][0]['role'], 'qualification')
        self.assertEqual(historical['jobs'][0]['profile'], 'shared_or_unknown')
        self.job['name'] = 'Publish (finite-dev) / qualification / phase (upgrade)'
        current = self.observe()
        self.assertEqual(current['jobs'][0]['role'], 'qualification-upgrade')
        self.assertEqual(current['jobs'][0]['profile'], 'finite-dev')
        self.assertEqual({r['role'] for r in costs.aggregate([historical, current])},
                         {'qualification', 'qualification-upgrade'})
        self.assertEqual(costs.job_role('Publish (finite) / other / qualify'), 'unknown')

    def test_authority_roles_bind_native_workflow_and_conserve_retry_cost(self):
        worker = 'authority (269, ' + 'a' * 40 + ', ' + 'b' * 40 + ')'
        self.run['path'] = '.github/workflows/decision-authority.yml'
        self.jobs = [{**self.job, 'id': number, 'name': name}
                     for number, name in enumerate(('discover', 'authority', worker), 1)]
        report = self.observe()
        self.assertEqual([j['role'] for j in report['jobs']],
                         ['authority-discovery', 'maintainer-authority', 'maintainer-authority'])
        self.assertEqual(len(report['jobs']), 3)
        self.assertEqual(sum(r['runnerSeconds'] for r in costs.aggregate([report])), 360)
        self.assertTrue(all(j['profile'] == 'shared_or_unknown' for j in report['jobs']))
        for name in ('discover', 'authority', worker, 'authority (269, invalid, invalid)'):
            self.assertEqual(costs.job_role(name), 'unknown')
            self.assertEqual(costs.job_role(name, '.github/workflows/other.yml'), 'unknown')
        for name in ('authority (0, ' + 'a' * 40 + ', ' + 'b' * 40 + ')', 'discover (future)'):
            self.assertEqual(costs.job_role(name, self.run['path']), 'unknown')
        self.run['path'] = '.github/workflows/decision-events.yml'
        self.jobs = [{**self.job, 'name': 'collect'}]
        self.assertEqual(self.observe()['jobs'][0]['role'], 'decision-event-collection')
        self.assertEqual(costs.job_role('collect'), 'unknown')

    def test_skipped_synthetic_job_is_zero_cost(self):
        self.job['conclusion'] = 'skipped'
        self.assertEqual(self.observe()['jobs'][0]['runnerSeconds'], 0)

    def test_foreign_job_and_attempt_bindings_rejected(self):
        self.job['run_id'] = 999
        with self.assertRaisesRegex(ValueError, 'Job differs'): self.observe()
        self.job['run_id'] = 10
        self.job['run_attempt'] = 3
        with self.assertRaises(ValueError): self.observe()

    def test_reuse_check_success_is_not_a_hit(self):
        self.job['steps'] = [{'name': 'Check exact qualification reuse', 'conclusion': 'success'},
                            {'name': 'Install context tools for the reuse pilot', 'conclusion': 'success'},
                            {'name': 'Save authenticated reusable qualification', 'conclusion': 'skipped'}]
        self.assertFalse(self.observe()['jobs'][0]['qualificationReuseHit'])
        self.job['steps'][-1]['conclusion'] = 'success'
        self.assertTrue(self.observe()['jobs'][0]['qualificationReuseHit'])

    def test_incomplete_native_pagination_and_reversed_time_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            costs.inventory(lambda _: {'total_count': 2, 'jobs': [self.job]}, 'repos/x/jobs', 'jobs')
        with self.assertRaises(ValueError): costs.seconds('2026-10-23T12:00:00Z', '2026-10-23T11:00:00Z')

    def test_stage_receipt_binds_candidate_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = {**os.environ, 'PROFILE': 'finite', 'GITHUB_REPOSITORY': costs.REPOSITORY,
                           'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_SHA': 'a' * 40,
                           'SOURCE_REVISION': 'b' * 40, 'CANDIDATE_DIGEST': 'sha256:' + 'c' * 64}
            status = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/measure.py'), 'fixture',
                                     sys.executable, '-c', 'raise SystemExit(7)'], cwd=temporary, env=environment).returncode
            self.assertEqual(status, 7)
            receipt = json.loads((Path(temporary) / '.bluebuild/finite-timings.jsonl').read_text())
            self.assertEqual(receipt['runAttempt'], '2')
            self.assertEqual(receipt['sourceRevision'], 'b' * 40)
            self.assertEqual(receipt['candidateDigest'], 'sha256:' + 'c' * 64)
            self.assertEqual(receipt['status'], 7)
            self.assertFalse(receipt['authorizesPublication'])
            self.assertEqual(receipt['childResourceUsage']['scope'], 'terminated-and-waited-children')
            self.assertFalse(receipt['childResourceUsage']['includesDaemonWork'])

    def test_groups_separate_workflow_event_role_and_revision(self):
        report = self.observe()
        other = deepcopy(report)
        other.update(sourceRevision='b' * 40, event='push')
        self.assertEqual(len(costs.aggregate([report, other])), 2)
        self.assertIsNone(report['jobs'][0]['qualificationReuseHit'])
        self.assertEqual(report['jobs'][0]['predecessorReuse'], {'eligible': None, 'hit': None, 'missReason': None})

    def test_bounded_receipts_authenticate_and_do_not_charge_retried_jobs_twice(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        report = self.observe()
        record = {'schema': 1, 'kind': 'finite-stage-timing', 'repository': costs.REPOSITORY,
                  'runId': '10', 'runAttempt': '1', 'revision': 'a' * 40, 'profile': 'finite',
                  'jobName': self.job['name'], 'stage': 'predecessor-iso-reuse', 'seconds': 2.5,
                  'status': 3, 'startedAt': '2026-10-23T10:01:00Z'}
        artifact = {'id': 20, 'name': 'image-finite-10-1', 'expired': False,
                    'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('finite-timings.jsonl', json.dumps(record) + '\n' + json.dumps(record) + '\n')
            raw.seek(0)
            yield raw
        cost_receipts.join(report, [artifact], reader)
        self.assertEqual(len(report['jobs'][0]['stages']), 1)
        self.assertEqual(report['jobs'][0]['predecessorReuse']['missReason'], 'unavailable')
        self.assertFalse(report['jobs'][0]['predecessorReuse']['hit'])
        record['revision'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'native producer'):
            cost_receipts.join(report, [artifact], reader)
        artifact['size_in_bytes'] = cost_receipts.MAX_ARCHIVE + 1
        cost_receipts.join(report, [artifact], reader)
        self.assertEqual(report['receiptCoverage']['read'], 0)

    def test_fresh_inventory_receipt_does_not_infer_a_reuse_miss(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        self.job['name'] = 'Publish (finite) / security'
        report = self.observe()
        artifact = {'id': 20, 'name': 'security-finite-10-1', 'expired': False,
                    'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('phase-timings.json', json.dumps({'schema': 1, 'inventoryReused': False}))
            raw.seek(0)
            yield raw
        cost_receipts.join(report, [artifact], reader)
        result = report['jobs'][0]['inventoryReuse']
        self.assertFalse(result['observedReused'])
        self.assertIsNone(result['eligible'])
        self.assertIsNone(result['hit'])
        self.assertIsNone(result['missReason'])

    def scanner_costs(self, *, compact=True, phases=None):
        self.job['name'] = 'Publish (finite) / security'
        artifact = {'id': 20, 'name': ('security-costs' if compact else 'security') + '-finite-10-1',
                    'expired': False, 'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        value = {'schema': 1, 'inventoryReused': False, 'phases': phases if phases is not None else [
            {'phase': 'image-transfer', 'seconds': 45.5, 'success': True},
            {'phase': 'inventory-cataloging', 'seconds': 12, 'success': False}]}
        return artifact, value

    def scanner_reader(self, value, member='phase-timings.json'):
        from contextlib import contextmanager
        import io, zipfile
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                if member is not None:
                    archive.writestr(member, json.dumps(value))
            raw.seek(0)
            yield raw
        return reader

    def predecessor_observation(self):
        self.job['name'] = 'Publish (finite) / qualification / phase (upgrade)'
        artifact = {'id': 20, 'name': 'qualification-phase-finite-upgrade-10-1', 'expired': False,
                    'digest': 'sha256:' + 'c' * 64, 'size_in_bytes': 1000,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        value = {'schema': 1, 'kind': 'finite-predecessor-iso-reuse', 'authorizesPublication': False,
                 'repository': costs.REPOSITORY, 'runId': '10', 'runAttempt': '1', 'revision': 'a' * 40,
                 'profile': 'finite', 'predecessorDigest': 'sha256:' + 'b' * 64, 'outcome': 'miss',
                 'runsExamined': 20, 'artifactsExamined': 2, 'missCounts': {'generation-inputs-changed': 2},
                 'changedInputPaths': ['scripts/bluebuild/iso.sh'], 'changedInputPathsTruncated': False}
        return artifact, value

    def test_predecessor_observations_bind_to_native_upgrade_and_preserve_unknowns(self):
        artifact, value = self.predecessor_observation()
        for outcome in ('hit', 'miss', 'error'):
            report = self.observe()
            cost_receipts.join(report, [artifact, artifact],
                self.scanner_reader({**value, 'outcome': outcome}, 'finite-predecessor-reuse.json'))
            job = report['jobs'][0]
            self.assertEqual(job['predecessorReuseDiagnostics']['outcome'], outcome)
            self.assertEqual(job['predecessorReuseDiagnostics']['artifactId'], 20)
            self.assertIsNone(job['predecessorReuse']['hit'])  # Diagnostics alone never establish a measured command verdict.
            self.assertEqual(sum(row['runnerSeconds'] for row in costs.aggregate([report])), 120)
        report = self.observe()
        cost_receipts.join(report, [], self.scanner_reader(value))
        self.assertIsNone(report['jobs'][0]['predecessorReuseDiagnostics'])
        self.assertIsNone(report['jobs'][0]['predecessorReuse']['hit'])
        value['runAttempt'] = '2'
        cost_receipts.join(report, [{**artifact, 'name': 'qualification-phase-finite-upgrade-10-2'}],
                           self.scanner_reader(value, 'finite-predecessor-reuse.json'))
        self.assertEqual(report['receiptCoverage']['unmatched'], 1)

    def test_predecessor_observations_reject_forged_origins_and_unbounded_values(self):
        artifact, value = self.predecessor_observation()
        for field, bad in [('schema', True), ('kind', 'other'), ('authorizesPublication', True),
                ('repository', 'fork/finite'), ('runId', '11'), ('revision', 'd' * 40),
                ('runAttempt', '0'), ('profile', 'other'), ('predecessorDigest', 'mutable:tag'),
                ('outcome', 'accepted'), ('runsExamined', 21), ('runsExamined', True),
                ('artifactsExamined', 1000001), ('missCounts', {'raw exception': 1}),
                ('missCounts', {'legacy-evidence': True}), ('missCounts', {'legacy-evidence': 0}),
                ('changedInputPaths', ['../escape']), ('changedInputPaths', ['x' * 201]),
                ('changedInputPaths', ['a', 'a']), ('changedInputPaths', ['a'] * 21),
                ('changedInputPathsTruncated', 1)]:
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                cost_receipts.join(self.observe(), [artifact],
                    self.scanner_reader({**value, field: bad}, 'finite-predecessor-reuse.json'))
        for member in ('finite-dev-predecessor-reuse.json',):
            with self.assertRaises(ValueError):
                cost_receipts.join(self.observe(), [artifact], self.scanner_reader(value, member))
        for name in ('qualification-phase-finite-fresh-10-1', 'qualification-phase-finite-dev-upgrade-10-1'):
            with self.assertRaises(ValueError):
                cost_receipts.join(self.observe(), [{**artifact, 'name': name}],
                                   self.scanner_reader(value, 'finite-predecessor-reuse.json'))
        with self.assertRaisesRegex(ValueError, 'Oversized'):
            cost_receipts.join(self.observe(), [artifact], self.scanner_reader({**value, 'extra': 'x' * 16384}, 'finite-predecessor-reuse.json'))
        with self.assertRaises(ValueError):
            cost_receipts.join(self.observe(), [artifact], self.scanner_reader([], 'finite-predecessor-reuse.json'))

    def test_predecessor_observations_reject_conflicts_and_mismatched_measured_status(self):
        artifact, value = self.predecessor_observation()
        report = self.observe()
        seen = set()
        report['receiptCoverage'] = {'unmatched': 0}
        cost_receipts.predecessor_reuse_receipt(report, artifact, value, seen)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            cost_receipts.predecessor_reuse_receipt(report, artifact, {**value, 'outcome': 'hit'}, seen)
        for outcome, measured in (('hit', 3), ('miss', 0), ('error', 3)):
            report = self.observe()
            report['jobs'][0]['stages'] = [{'stage': 'predecessor-iso-reuse', 'status': measured}]
            with self.assertRaisesRegex(ValueError, 'measured command'):
                cost_receipts.join(report, [artifact], self.scanner_reader({**value, 'outcome': outcome}, 'finite-predecessor-reuse.json'))

    def test_compact_scanner_receipt_survives_oversized_full_evidence(self):
        import cost_receipts
        artifact, value = self.scanner_costs()
        legacy = {**artifact, 'id': 21, 'name': 'security-finite-10-1',
                  'size_in_bytes': cost_receipts.MAX_ARCHIVE + 1}
        report = self.observe()
        cost_receipts.join(report, [legacy, artifact], self.scanner_reader(value))
        self.assertEqual(report['receiptCoverage']['read'], 1)
        self.assertEqual(report['receiptCoverage']['unavailable'], ['expired-or-size-bound'])
        job = report['jobs'][0]
        self.assertEqual([s['seconds'] for s in job['stages']], [45.5, 12])
        self.assertTrue(all(s['nested'] for s in job['stages']))
        self.assertEqual(job['stages'][1]['status'], 'failure')
        self.assertEqual(costs.aggregate([report])[0]['runnerSeconds'], 120)
        self.assertEqual(sum(row['failedSamples'] for row in costs.stage_opportunities([report])), 1)
        self.assertIsNone(job['inventoryReuse']['hit'])
        self.assertIsNone(job['candidateDigest'])

    def test_full_and_compact_scanner_receipts_do_not_duplicate_retry_costs(self):
        import cost_receipts
        artifact, value = self.scanner_costs(phases=[
            {'phase': 'database-update', 'seconds': 10, 'success': False},
            {'phase': 'database-update', 'seconds': 20, 'success': True}])
        legacy = {**artifact, 'id': 21, 'name': 'security-finite-10-1'}
        for items in ([artifact, legacy, artifact], [legacy, artifact]):
            report = self.observe()
            cost_receipts.join(report, items, self.scanner_reader(value))
            self.assertEqual(len(report['jobs']), 1)
            self.assertEqual(len(report['jobs'][0]['stages']), 2)
            row = costs.stage_opportunities([report])[0]
            self.assertEqual((row['seconds'], row['samples'], row['failedSamples']), (30, 2, 1))
            self.assertEqual(report['jobs'][0]['runnerSeconds'], 120)

    def test_resumed_scanner_timings_cannot_be_charged_to_the_receiving_job(self):
        import cost_receipts
        artifact, value = self.scanner_costs(phases=[
            {'phase': 'rootfs-extraction', 'seconds': 150, 'success': True},
            {'phase': 'inventory-cataloging', 'seconds': 171, 'success': True}])
        value['inventoryReused'] = True
        legacy = {**artifact, 'id': 21, 'name': 'security-finite-10-1'}
        for category, steps in (
                ('recovery', []),
                ('publication', [{'name': 'Revalidate fresh security evidence for a resumed candidate',
                                  'conclusion': 'success'}]),
                ('publication', [{'name': 'Revalidate fresh security evidence for a resumed candidate',
                                  'conclusion': 'failure'}])):
            with self.subTest(category=category, steps=steps):
                self.job['steps'] = steps
                report = self.observe()
                report['category'] = category
                cost_receipts.join(report, [artifact, legacy, artifact], self.scanner_reader(value))
                job = report['jobs'][0]
                self.assertEqual(job['runnerSeconds'], 120)
                self.assertEqual(job['stages'], [])
                self.assertEqual(costs.stage_opportunities([report]), [])
                self.assertTrue(all(item is None for item in job['inventoryReuse'].values()))
                attribution = job['securityTimingAttribution']
                self.assertEqual(attribution['status'], 'unknown')
                self.assertEqual(attribution['reportedPhases'], value['phases'])
                self.assertTrue(attribution['reportedInventoryReused'])
                self.assertEqual(sum(row['runnerSeconds'] for row in costs.aggregate([report])), 120)

    def test_short_resumed_timings_and_fresh_scan_fallback_still_need_producer_binding(self):
        import cost_receipts
        artifact, value = self.scanner_costs(phases=[
            {'phase': 'vulnerability-scan', 'seconds': 3, 'success': True}])
        # A successful revalidation step can also mean unavailable evidence and
        # a subsequent fresh scan. Neither duration nor an inventory flag proves
        # the legacy phase receipt was produced by this job.
        self.job['steps'] = [{'name': 'Revalidate fresh security evidence for a resumed candidate',
                              'conclusion': 'success'}]
        report = self.observe()
        cost_receipts.join(report, [artifact], self.scanner_reader(value))
        self.assertEqual(report['jobs'][0]['stages'], [])
        self.assertFalse(report['jobs'][0]['securityTimingAttribution']['reportedInventoryReused'])
        self.assertIsNone(report['jobs'][0]['inventoryReuse']['observedReused'])

    def test_skipped_security_revalidation_does_not_hide_new_scan_costs(self):
        import cost_receipts
        artifact, value = self.scanner_costs()
        self.job['steps'] = [{'name': 'Revalidate fresh security evidence for a resumed candidate',
                              'conclusion': 'skipped'}]
        report = self.observe()
        cost_receipts.join(report, [artifact], self.scanner_reader(value))
        self.assertEqual([stage['seconds'] for stage in report['jobs'][0]['stages']], [45.5, 12])
        self.assertNotIn('securityTimingAttribution', report['jobs'][0])

    def test_conflicting_scanner_projections_fail_closed(self):
        import cost_receipts
        artifact, value = self.scanner_costs()
        report = self.observe()
        seen = set()
        report['receiptCoverage'] = {'unmatched': 0}
        cost_receipts.security_receipt(report, artifact, value, seen)
        changed = deepcopy(value)
        changed['phases'][0]['seconds'] += 1
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            cost_receipts.security_receipt(report, artifact, changed, seen)

    def test_compact_scanner_schema_duration_and_member_bounds(self):
        import cost_receipts
        artifact, value = self.scanner_costs()
        invalid = [None, [], {**value, 'schema': True}, {**value, 'schema': 2},
                   {**value, 'inventoryReused': 'false'}, {**value, 'phases': None},
                   {**value, 'phases': value['phases'] * 17}]
        for field, item in [('seconds', True), ('seconds', -1), ('seconds', 86401),
                            ('seconds', float('nan')), ('seconds', float('inf')),
                            ('success', 0), ('phase', '../image-transfer')]:
            bad = deepcopy(value)
            bad['phases'][0][field] = item
            invalid.append(bad)
        for bad in invalid:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                cost_receipts.join(self.observe(), [artifact], self.scanner_reader(bad))
        for member in (None, 'wrong.json'):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, 'compact'):
                cost_receipts.join(self.observe(), [artifact], self.scanner_reader(value, member))
        with self.assertRaises(ValueError):
            cost_receipts.join(self.observe(), [artifact], self.scanner_reader({**value, 'unused': 'x' * 65536}))

    def test_scanner_costs_bind_native_source_attempt_profile_and_workflow(self):
        import cost_receipts
        artifact, value = self.scanner_costs()
        for changed in ({**artifact, 'workflow_run': {'id': 10, 'head_sha': 'b' * 40}},
                        {**artifact, 'workflow_run': {'id': 11, 'head_sha': 'a' * 40}},
                        {**artifact, 'digest': None}):
            with self.subTest(artifact=changed), self.assertRaisesRegex(ValueError, 'native'):
                cost_receipts.join(self.observe(), [changed], self.scanner_reader(value))
        for name in ('security-costs-finite-10-2', 'security-costs-finite-dev-10-1'):
            report = self.observe()
            cost_receipts.join(report, [{**artifact, 'name': name}], self.scanner_reader(value))
            self.assertEqual(report['receiptCoverage']['unmatched'], 1)
            self.assertEqual(report['jobs'][0]['stages'], [])
        report = self.observe()
        report['workflow'] = '.github/workflows/other.yml'
        with self.assertRaises(ValueError):
            cost_receipts.join(report, [artifact], self.scanner_reader(value))

    def test_compact_scanner_upload_is_failure_safe_and_contains_only_timings(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())
        steps = workflow['jobs']['security']['steps']
        upload = next(s for s in steps if s.get('name') == 'Retain bounded scanner costs including failures')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['path'], '.bluebuild/security-${{ inputs.profile }}/phase-timings.json')
        self.assertEqual(upload['with']['if-no-files-found'], 'ignore')
        self.assertEqual(upload['with']['retention-days'], 14)
        legacy = next(s for s in steps if s.get('name') == 'Retain scanner evidence including failures')
        self.assertEqual(legacy['with']['retention-days'], 90)
        self.assertEqual(legacy['with']['path'], '.bluebuild/security-${{ inputs.profile }}/')

    def source_reuse(self):
        self.run.update(event='push', head_branch='main')
        self.job['name'] = 'Nix and runtime contracts'
        artifact = {'id': 20, 'name': 'source-checks-10-1', 'expired': False,
                    'size_in_bytes': 2000, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        value = {'schema': 1, 'kind': 'finite-source-reuse', 'authorizesPublication': False,
                 'repository': costs.REPOSITORY, 'runId': '10', 'runAttempt': '1',
                 'revision': 'a' * 40, 'checkoutRevision': 'a' * 40, 'jobName': 'checks',
                 'workflowRef': costs.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main',
                 'mode': 'enabled', 'eligible': True, 'hit': True, 'reason': 'verified-exact-queue-proof',
                 'seconds': 2., 'startedAt': '2026-10-23T10:01:00Z', 'shadowMatch': None,
                 'producer': {'runId': 9, 'runAttempt': 1, 'jobId': 50, 'artifactId': 51,
                              'artifactDigest': 'sha256:' + 'd' * 64, 'revision': 'a' * 40,
                              'aggregateDerivation': '/nix/store/' + 'b' * 32 + '-finite-ci-checks.drv'}}
        return artifact, value

    def test_source_reuse_is_a_reference_not_a_duplicate_producer_charge(self):
        from contextlib import contextmanager
        import io, zipfile
        artifact, value = self.source_reuse()
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as zipped:
                zipped.writestr('source-reuse.json', json.dumps(value))
            raw.seek(0)
            yield raw
        report = self.observe()
        before = report['jobs'][0]['runnerSeconds']
        cost_receipts.join(report, [artifact, artifact], reader)
        job = report['jobs'][0]
        self.assertEqual(job['runnerSeconds'], before)
        self.assertTrue(job['sourceReuse']['hit'])
        self.assertEqual(job['sourceReuse']['producer']['jobId'], 50)
        self.assertEqual([row['stage'] for row in job['stages']], ['Source proof lookup'])
        self.assertEqual(job['stages'][0]['seconds'], 2.)
        # Native retry projections must not relabel an earlier job as a consumer.
        report = self.observe()
        report['receiptCoverage'] = {'unmatched': 0}
        cost_receipts.source_reuse_receipt(report, {**artifact, 'name': 'source-checks-10-2'},
                                         {**value, 'runAttempt': '2'}, set())
        self.assertEqual(report['receiptCoverage']['unmatched'], 1)
        self.assertNotIn('sourceReuse', report['jobs'][0])
        report = self.observe()
        report['jobs'][0]['stages'] = [{'stage': 'Evaluate aggregate', 'seconds': 100.}]
        with self.assertRaisesRegex(ValueError, 'cannot claim executed'):
            cost_receipts.join(report, [artifact], reader)

    def test_source_reuse_unknown_disabled_and_missed_remain_distinct(self):
        artifact, original = self.source_reuse()
        for mode, eligible, hit, reason in [('off', None, None, 'disabled'),
                ('enabled', None, None, 'lookup-unavailable'),
                ('shadow', None, None, 'lookup-auth-unavailable'),
                ('enabled', False, False, 'no-exact-queue-proof')]:
            value = {**original, 'mode': mode, 'eligible': eligible, 'hit': hit, 'reason': reason, 'producer': None}
            if mode == 'off':
                value.update(seconds=None, startedAt=None)
            report = self.observe()
            cost_receipts.source_reuse_receipt(report, artifact, value, set())
            observed = report['jobs'][0]['sourceReuse']
            self.assertIs(observed['eligible'], eligible)
            self.assertIs(observed['hit'], hit)
            self.assertEqual(len(report['jobs'][0]['stages']), 0 if mode == 'off' else 1)

    def test_invalid_source_reuse_claims_do_not_join(self):
        artifact, value = self.source_reuse()
        for change in ({'repository': 'fork/repo'}, {'runAttempt': '2'}, {'checkoutRevision': 'f' * 40},
                       {'schema': True}, {'mode': 'shadow'}, {'eligible': None}, {'producer': {}},
                       {'hit': 'true'}, {'seconds': float('nan')}, {'authorizesPublication': True},
                       {'eligible': False, 'hit': False, 'reason': 'lookup-timeout', 'producer': None},
                       {'eligible': None, 'hit': None, 'reason': 'no-exact-queue-proof', 'producer': None},
                       {'eligible': None, 'hit': None, 'reason': 'disabled', 'producer': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cost_receipts.source_reuse_receipt(self.observe(), artifact, {**value, **change}, set())

    def test_nix_observations_join_original_attempt_without_double_charging(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        self.job['name'] = 'Nix and runtime contracts'
        report = self.observe()
        native_seconds = report['jobs'][0]['runnerSeconds']
        value = {'schema': 1, 'kind': 'finite-nix-observation', 'authorizesPublication': False,
                 'repository': costs.REPOSITORY, 'runId': '10', 'runAttempt': '1',
                 'revision': 'a' * 40, 'checkoutRevision': 'b' * 40, 'jobName': 'checks',
                 'workflowRef': costs.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main',
                 'runner': {'ImageVersion': '20261023'}, 'toolCohort': {}, 'phases': [{
                     'stage': 'Evaluate aggregate', 'startedAt': '2026-10-23T10:01:00Z',
                     'seconds': 20.0, 'status': 1, 'outcome': 'failure', 'attempts': [
                         {'attempt': 1, 'status': 1, 'seconds': 20.0}]}]}
        setup = {**value, 'startedAt': '2026-10-23T10:01:00Z', 'seconds': None,
                 'status': None, 'cache': None}
        setup.pop('phases')
        artifact = {'id': 20, 'name': 'source-checks-10-1', 'expired': False,
                    'size_in_bytes': 1000, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr('nix-checks.json', json.dumps(value))
                archive.writestr('nix-setup.json', json.dumps(setup))
            raw.seek(0)
            yield raw
        cost_receipts.join(report, [artifact, artifact], reader)
        job = report['jobs'][0]
        self.assertEqual(job['runnerSeconds'], native_seconds)
        self.assertEqual(job['checkoutRevision'], 'b' * 40)
        self.assertEqual(len(job['stages']), 2)
        self.assertEqual(job['stages'][0]['status'], 1)
        self.assertIsNone(job['stages'][1]['seconds'])
        self.assertIsNone(job['nixCache'])
        self.assertIsNone(job['candidateDigest'])
        self.assertIsNone(job['predecessorReuse']['hit'])
        rows = costs.stage_opportunities([report])
        self.assertEqual(rows[0]['failedSamples'], 1)
        self.assertEqual(rows[1]['stage'], 'Nix setup')
        self.assertIsNone(rows[1]['seconds'])
        self.assertIsNone(rows[1]['medianSeconds'])
        self.assertEqual(rows[1]['unknownDurationSamples'], 1)
        for key, wrong in [('revision', 'b' * 40), ('runAttempt', '2'), ('jobName', 'build'),
                           ('authorizesPublication', True), ('schema', True), ('workflowRef', 'other/workflow')]:
            with self.subTest(key=key):
                changed = {**value, key: wrong}
                with self.assertRaisesRegex(ValueError, 'native producer'):
                    cost_receipts.nix_receipt(report, artifact, 'nix-checks.json', changed, set())
        for elapsed in (-1, True, float('nan'), None):
            changed = deepcopy(value)
            changed['phases'][0]['seconds'] = elapsed
            with self.subTest(elapsed=elapsed), self.assertRaisesRegex(ValueError, 'duration'):
                cost_receipts.nix_receipt(report, artifact, 'nix-checks.json', changed, set())
        changed = deepcopy(value)
        changed['phases'][0]['attempts'] *= 4
        with self.assertRaisesRegex(ValueError, 'retry observations'):
            cost_receipts.nix_receipt(report, artifact, 'nix-checks.json', changed, set())
        usage = {'scope': 'terminated-and-waited-children', 'includesDaemonWork': False,
                 'userCpuSeconds': 3.25, 'systemCpuSeconds': 1.,
                 'blockInputOperations': 10, 'blockOutputOperations': 15}
        for resource_value in (None, usage):
            changed = deepcopy(value)
            changed['phases'][0]['attempts'][0]['childResourceUsage'] = resource_value
            projected = self.observe()
            cost_receipts.nix_receipt(projected, artifact, 'nix-checks.json', changed, set())
            self.assertEqual(projected['jobs'][0]['runnerSeconds'], native_seconds)
            self.assertEqual(projected['jobs'][0]['stages'][0]['attempts'][0]['childResourceUsage'], resource_value)
        for key, wrong in [('scope', 'whole-runner'), ('includesDaemonWork', True),
                           ('userCpuSeconds', True), ('userCpuSeconds', float('nan')),
                           ('systemCpuSeconds', -1), ('systemCpuSeconds', float('inf')),
                           ('blockInputOperations', 1.5), ('blockOutputOperations', True),
                           ('blockOutputOperations', 2**63)]:
            changed = deepcopy(value)
            changed['phases'][0]['attempts'][0]['childResourceUsage'] = {**usage, key: wrong}
            with self.subTest(resource=key, wrong=wrong), self.assertRaisesRegex(ValueError, 'resource'):
                cost_receipts.nix_receipt(self.observe(), artifact, 'nix-checks.json', changed, set())
        for invalid in ({}, [], 'unknown', {**usage, 'peakRss': 123}):
            changed = deepcopy(value)
            changed['phases'][0]['attempts'][0]['childResourceUsage'] = invalid
            with self.subTest(resource=invalid), self.assertRaisesRegex(ValueError, 'resource'):
                cost_receipts.nix_receipt(self.observe(), artifact, 'nix-checks.json', changed, set())
        # A receipt for attempt two cannot relabel work reused from attempt one.
        artifact['name'] = 'source-checks-10-2'
        changed = {**value, 'runAttempt': '2'}
        cost_receipts.nix_receipt(report, artifact, 'nix-checks.json', changed, set())
        self.assertEqual(report['receiptCoverage']['unmatched'], 1)

    def reconciliation_costs(self):
        self.run['path'] = '.github/workflows/decision-proposals.yml'
        self.job['name'] = 'reconcile'
        artifact = {'id': 20, 'name': 'reconciliation-costs-10-1', 'expired': False,
                    'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        value = {'schema': 1, 'kind': 'finite-reconciliation-costs', 'authorizesPublication': False,
                 'repository': costs.REPOSITORY, 'runId': '10', 'runAttempt': '1',
                 'revision': 'a' * 40, 'checkoutRevision': 'b' * 40, 'jobName': 'reconcile',
                 'workflowRef': costs.REPOSITORY + '/.github/workflows/decision-proposals.yml@refs/heads/main',
                 'truncated': False, 'stages': [
                     {'stage': 'reconciliation', 'profile': None, 'seconds': None, 'outcome': 'running'},
                     {'stage': 'packet-download', 'profile': 'finite', 'seconds': 12.5, 'outcome': 'success'},
                     {'stage': 'authority-check', 'profile': 'finite-dev', 'seconds': 0, 'outcome': 'error'}]}
        for row in value['stages']:
            row['startedAt'] = '2026-10-23T10:01:00Z'
        return artifact, value

    def test_reconciliation_phases_bind_producing_job_and_preserve_partial_unknown_cost(self):
        import cost_receipts
        artifact, value = self.reconciliation_costs()
        report = self.observe()
        cost_receipts.join(report, [artifact, artifact], self.scanner_reader(value, 'reconciliation-costs.json'))
        job = report['jobs'][0]
        self.assertEqual(len(report['jobs']), 1)
        self.assertEqual(job['runnerSeconds'], 120)
        self.assertEqual(job['checkoutRevision'], 'b' * 40)
        self.assertEqual(len(job['stages']), 3)
        self.assertEqual([row['profile'] for row in job['stages']], [None, 'finite', 'finite-dev'])
        self.assertIsNone(job['stages'][0]['seconds'])
        self.assertIsNone(job['stages'][0]['status'])
        self.assertEqual(job['stages'][2]['seconds'], 0)
        self.assertEqual(job['stages'][2]['status'], 'failure')
        self.assertTrue(all(row['nested'] for row in job['stages']))
        self.assertEqual(sum(row['failedSamples'] for row in costs.stage_opportunities([report])), 1)
        self.assertEqual(sum(row['unknownDurationSamples'] for row in costs.stage_opportunities([report])), 1)
        self.assertEqual(sum(row['runnerSeconds'] for row in costs.aggregate([report])), 120)

    def test_reconciliation_receipts_cannot_relabel_native_workflow_source_attempt_or_job(self):
        import cost_receipts
        artifact, value = self.reconciliation_costs()
        invalid = [('schema', True), ('kind', 'other'), ('authorizesPublication', True),
                   ('repository', 'fork/finite'), ('runId', '11'), ('runAttempt', '2'),
                   ('revision', 'd' * 40), ('jobName', 'checks'), ('workflowRef', 'other'),
                   ('truncated', 0), ('checkoutRevision', 'bad'),
                   ('historicalReadWorkers', True), ('historicalReadWorkers', 2), ('historicalReadWorkers', '4')]
        for field, wrong in invalid:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'native producer'):
                cost_receipts.join(self.observe(), [artifact],
                                   self.scanner_reader({**value, field: wrong}, 'reconciliation-costs.json'))
        report = self.observe()
        report['workflow'] = '.github/workflows/build.yml'
        with self.assertRaisesRegex(ValueError, 'native producer'):
            cost_receipts.join(report, [artifact], self.scanner_reader(value, 'reconciliation-costs.json'))
        report = self.observe()
        value['runAttempt'] = '2'
        cost_receipts.join(report, [{**artifact, 'name': 'reconciliation-costs-10-2'}],
                           self.scanner_reader(value, 'reconciliation-costs.json'))
        self.assertEqual(report['receiptCoverage']['unmatched'], 1)
        self.assertEqual(report['jobs'][0]['stages'], [])

    def test_reconciliation_schema_and_compact_archive_bounds_fail_closed(self):
        import cost_receipts
        artifact, value = self.reconciliation_costs()
        invalid = [None, {**value, 'stages': []}, {**value, 'stages': value['stages'] * 22}]
        for key, wrong in [('stage', '../escape'), ('profile', 'foreign'), ('seconds', True),
                           ('seconds', -1), ('seconds', 86401), ('seconds', float('nan')),
                           ('seconds', float('inf')), ('outcome', 'unreviewed'),
                           ('startedAt', '2026-10-23T10:01:00')]:
            changed = deepcopy(value)
            changed['stages'][1][key] = wrong
            invalid.append(changed)
        changed = deepcopy(value)
        changed['stages'][0]['seconds'] = 1
        invalid.append(changed)
        for changed in invalid:
            with self.subTest(value=changed), self.assertRaises(ValueError):
                cost_receipts.join(self.observe(), [artifact], self.scanner_reader(changed, 'reconciliation-costs.json'))
        for member in (None, 'other.json'):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, 'compact'):
                cost_receipts.join(self.observe(), [artifact], self.scanner_reader(value, member))
        with self.assertRaises(ValueError):
            cost_receipts.join(self.observe(), [artifact], self.scanner_reader(
                {**value, 'oversized': 'x' * 65536}, 'reconciliation-costs.json'))

    def test_conflicting_reconciliation_projections_are_rejected(self):
        import cost_receipts
        artifact, value = self.reconciliation_costs()
        report = self.observe()
        report['receiptCoverage'] = {'unmatched': 0}
        seen = set()
        cost_receipts.reconciliation_receipt(report, artifact, value, seen)
        changed = deepcopy(value)
        changed['stages'][1]['seconds'] = 11
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            cost_receipts.reconciliation_receipt(report, artifact, changed, seen)

    def test_reconciliation_unknown_checkout_duration_and_truncation_stay_explicit(self):
        import cost_receipts
        artifact, value = self.reconciliation_costs()
        value.update(checkoutRevision=None, truncated=True)
        value['stages'][1]['seconds'] = None
        report = self.observe()
        cost_receipts.join(report, [artifact], self.scanner_reader(value, 'reconciliation-costs.json'))
        job = report['jobs'][0]
        self.assertIsNone(job['checkoutRevision'])
        self.assertTrue(job['reconciliationTimingsTruncated'])
        self.assertIsNone(job['stages'][1]['seconds'])
        self.assertIsNone(job['candidateDigest'])
        self.assertIsNone(job['inventoryReuse']['hit'])

    def test_controller_worker_mode_is_authenticated_and_legacy_mode_stays_unknown(self):
        artifact, value = self.reconciliation_costs()
        for workers in (None, 1, 4):
            current = {**value}
            if workers is not None:
                current['historicalReadWorkers'] = workers
            report = self.observe()
            cost_receipts.join(report, [artifact], self.scanner_reader(current, 'reconciliation-costs.json'))
            self.assertEqual(report['jobs'][0]['reconciliationReadWorkers'], workers)
            self.assertEqual(report['jobs'][0]['role'], 'decision-reconciliation')
            self.assertEqual(sum(row['runnerSeconds'] for row in costs.aggregate([report])), 120)
        self.assertEqual(costs.job_role('reconcile', '.github/workflows/unrelated.yml'), 'unknown')

    def test_reconciliation_upload_is_bounded_and_failure_safe(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/decision-proposals.yml').read_text())
        upload = next(step for step in workflow['jobs']['reconcile']['steps']
                      if step.get('name') == 'Retain bounded reconciliation costs including failures')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['path'], '.bluebuild/reconciliation-costs.json')
        self.assertEqual(upload['with']['if-no-files-found'], 'ignore')
        self.assertEqual(upload['with']['retention-days'], 14)

    def test_exclusive_occupancy_measures_blocking_lower_bound_without_double_counting(self):
        report = self.observe()
        second = deepcopy(report['jobs'][0])
        second.update(jobId=2, runnerSeconds=60, completedAt='2026-10-23T10:02:00Z')
        report['jobs'].append(second)
        costs.exclusive_occupancy(report)
        self.assertEqual([j['exclusiveRunnerSeconds'] for j in report['jobs']], [60, 0])
        report['status'] = 'in_progress'
        costs.exclusive_occupancy(report)
        self.assertTrue(all(j['exclusiveRunnerSeconds'] is None for j in report['jobs']))

    def blocking_fixture(self):
        report = self.observe()
        first = report['jobs'][0]
        # The producer is projected through two retry attempts by observe().
        first['stages'] = [{'stage': 'outer', 'startedAt': '2026-10-23T10:01:10Z',
                            'seconds': 100, 'status': 7},
                           {'stage': 'parallel', 'startedAt': '2026-10-23T10:01:20Z',
                            'seconds': 20, 'status': 0},
                           {'stage': 'nested', 'startedAt': '2026-10-23T10:02:30Z',
                            'seconds': 30, 'status': 0}]
        for identity, begin, finish in ((2, '10:01:20', '10:01:40'), (3, '10:02:10', '10:02:40')):
            job = deepcopy(first)
            job.update(jobId=identity, startedAt='2026-10-23T' + begin + 'Z',
                       completedAt='2026-10-23T' + finish + 'Z', stages=[], runnerSeconds=20 if identity == 2 else 30)
            report['jobs'].append(job)
        costs.exclusive_occupancy(report)
        return report

    def test_stage_blocking_intersects_multiple_parallel_intervals_and_retains_failures(self):
        report = self.blocking_fixture()
        self.assertEqual([j['exclusiveRunnerSeconds'] for j in report['jobs']], [70, 0, 0])
        rows = {row['stage']: row for row in costs.stage_opportunities([report])}
        self.assertEqual(rows['outer']['exclusiveRunnerSeconds'], 50)
        self.assertEqual(rows['parallel']['exclusiveRunnerSeconds'], 0)
        self.assertEqual(rows['nested']['exclusiveRunnerSeconds'], 20)
        self.assertEqual(rows['outer']['failedSamples'], 1)
        self.assertEqual(rows['outer']['samples'], 1)
        self.assertIsNone(rows['outer']['criticalPathContribution'])
        self.assertEqual(sum(r['runnerSeconds'] for r in costs.aggregate([report])), 170)

    def test_stage_unknown_placement_is_distinct_from_measured_zero(self):
        report = self.blocking_fixture()
        report['jobs'][0]['stages'].append({'stage': 'outer', 'seconds': 5, 'status': 0})
        row = next(row for row in costs.stage_opportunities([report]) if row['stage'] == 'outer')
        self.assertEqual(row['exclusiveRunnerSeconds'], 50)
        self.assertEqual(row['exclusiveOccupancyUnknownSamples'], 1)
        self.assertEqual(row['samples'], 2)
        relative = costs.stage_opportunities([{**report, 'jobs': [{**report['jobs'][0],
                    'stages': [{'stage': 'guest-home-init', 'seconds': 5, 'status': 0}]}]}])[0]
        self.assertIsNone(relative['exclusiveRunnerSeconds'])
        self.assertEqual(relative['exclusiveOccupancyUnknownSamples'], 1)

    def test_active_or_partial_native_intervals_cannot_place_stages(self):
        for change in ('active', 'missing-job-duration', 'missing-job-end'):
            with self.subTest(change=change):
                report = self.blocking_fixture()
                if change == 'active': report['status'] = 'in_progress'
                elif change == 'missing-job-duration': report['jobs'][1]['runnerSeconds'] = None
                else: report['jobs'][1]['completedAt'] = None
                costs.exclusive_occupancy(report)
                row = costs.stage_opportunities([report])[0]
                self.assertIsNone(row['exclusiveRunnerSeconds'])
                self.assertEqual(row['exclusiveOccupancyUnknownSamples'], 1)
                self.assertTrue(all(job['exclusiveRunnerIntervals'] is None for job in report['jobs']))

    def test_bad_or_unbounded_stage_intervals_remain_unknown(self):
        job = self.blocking_fixture()['jobs'][0]
        base = job['stages'][0]
        for change in ({'startedAt': None}, {'startedAt': '2026-10-23T10:01:10'},
                       {'startedAt': '2026-10-23T10:00:58Z'}, {'seconds': 112},
                       {'seconds': None}, {'seconds': float('nan')}, {'seconds': float('inf')},
                       {'seconds': True}, {'seconds': -1}, {'seconds': 86401}):
            with self.subTest(change=change):
                self.assertIsNone(costs.stage_exclusive_seconds(job, {**base, **change}))

    def test_second_precision_tolerance_is_clipped_to_native_job(self):
        job = self.blocking_fixture()['jobs'][0]
        self.assertEqual(costs.stage_exclusive_seconds(job, {'startedAt': '2026-10-23T10:00:59.5Z',
                                                            'seconds': 121}), 70)
        self.assertEqual(costs.stage_exclusive_seconds(job, {'startedAt': '2026-10-23T10:01:10Z',
                                                            'seconds': 0}), 0)

    def test_skipped_jobs_use_no_intervals_and_leave_native_cost_conserved(self):
        report = self.blocking_fixture()
        report['jobs'].append({**deepcopy(report['jobs'][0]), 'jobId': 4, 'stages': [],
                               'runnerSeconds': 0, 'startedAt': None, 'completedAt': None,
                               'status': 'completed', 'conclusion': 'skipped'})
        costs.exclusive_occupancy(report)
        self.assertEqual(report['jobs'][-1]['exclusiveRunnerIntervals'], [])
        self.assertEqual(report['jobs'][0]['exclusiveRunnerSeconds'], 70)
        self.assertEqual(sum(r['runnerSeconds'] for r in costs.aggregate([report])), 170)

    def test_stage_markdown_shows_overlaps_and_partial_known_coverage(self):
        run = self.blocking_fixture()
        run['jobs'][0]['stages'].append({'stage': 'relative', 'seconds': None, 'status': None})
        report = {'observedAt': 'now', 'baseline': {'cohorts': []},
                  'observation': {'cohorts': [], 'complete': False}, 'limitations': [],
                  'rankedStages': costs.stage_opportunities([run])}
        rendered = costs.markdown(report)
        self.assertIn('nested stages overlap and must not be added', rendered)
        self.assertIn('blocking lower bound, not exact dependency DAG contribution', rendered)
        self.assertIn('| 100.0 | 50.0 | 0 |', rendered)
        self.assertIn('| unknown | unknown | 1 |', rendered)

    def test_queue_and_production_guest_receipts_bind_to_distinct_native_jobs(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        for lane in ('finite', 'finite-dev'):
            self.job['name'] = f'Validate ({lane}) / build'
            phase_job = {**self.job, 'id': 2, 'name': f'Publish ({lane}) / qualification / phase (fresh)'}
            self.jobs = [self.job, phase_job]
            report = self.observe()
            artifacts = [{'id': index, 'name': f'{prefix}-{lane}{suffix}-10-1', 'expired': False,
                          'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                          'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
                         for index, prefix, suffix in ((20, 'image', ''), (21, 'qualification-phase', '-fresh'))]
            values = {'image': [{'stage': 'startup-checks', 'seconds': 2, 'status': 0},
                                {'stage': 'home-init', 'seconds': 319, 'status': 7}],
                      'qualification': [{'stage': 'home-init', 'seconds': 339, 'status': 0}]}
            @contextmanager
            def reader(artifact, repository):
                image = artifact['name'].startswith('image-')
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, 'w') as archive:
                    archive.writestr(('vm-local' if image else 'vm-fresh') + '/guest-timings.json',
                                     json.dumps({'schema': 1, 'stages': values['image' if image else 'qualification']}))
                raw.seek(0)
                yield raw
            cost_receipts.join(report, artifacts + artifacts[:1], reader)
            jobs = {j['role']: j for j in report['jobs']}
            self.assertEqual([(s['stage'], s['seconds'], s['status']) for s in jobs['build']['stages']],
                             [('startup-checks', 2, 0), ('home-init', 319, 7)])
            self.assertEqual([s['seconds'] for s in jobs['qualification-fresh']['stages']], [339])
            self.assertEqual(report['receiptCoverage']['unmatched'], 0)
            values['image'].append(values['image'][0])
            with self.assertRaisesRegex(ValueError, 'Duplicate or invalid'):
                cost_receipts.join(report, artifacts, reader)

    def test_foundation_observation_is_native_bound_optional_and_not_a_host_clock(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        self.job['name'] = 'Validate (finite) / build'
        artifact = {'id': 20, 'name': 'image-finite-10-1', 'expired': False,
                    'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        record = {'schema': 1, 'kind': 'foundation-stage-timing', 'authorizesPublication': False,
                  'stage': 'initialization', 'seconds': 12.5, 'status': 7, 'outcome': 'error',
                  'startedAt': '2026-10-27T01:00:00Z'}
        observation = {'schema': 1, 'stages': [record], 'rejectedRecords': 1}
        value = {'schema': 1, 'stages': [{'stage': 'home-init', 'seconds': 13, 'status': 7}], 'foundation': observation}
        member = ['vm-local/guest-timings.json']
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr(member[0], json.dumps(value))
            raw.seek(0)
            yield raw
        report = self.observe()
        cost_receipts.join(report, [artifact, artifact], reader)
        job = report['jobs'][0]
        self.assertEqual(job['foundationTimings'], observation)
        self.assertEqual(len(job['stages']), 2)
        stage = job['stages'][0]
        self.assertEqual((stage['stage'], stage['seconds'], stage['status']), ('foundation-initialization', 12.5, 7))
        self.assertNotIn('startedAt', stage)
        self.assertIsNone(costs.stage_exclusive_seconds(job, stage))
        for change in ({'stage': 'unreviewed'}, {'seconds': True}, {'seconds': float('inf')},
                       {'seconds': 10**800}, {'authorizesPublication': True}, {'status': 0},
                       {'startedAt': '2026-10-27T01:00:00'}, {'status': True}, {'private': 'data'}):
            with self.subTest(change=change):
                observation['stages'] = [{**record, **change}]
                with self.assertRaises(ValueError):
                    cost_receipts.join(self.observe(), [artifact], reader)
        observation['stages'] = [record, record]
        with self.assertRaisesRegex(ValueError, 'Duplicate Foundation'):
            cost_receipts.join(self.observe(), [artifact], reader)
        observation['stages'] = [record]
        member[0] = 'vm-fresh/guest-timings.json'
        with self.assertRaisesRegex(ValueError, 'phase differs'):
            cost_receipts.join(self.observe(), [artifact], reader)
        member[0] = 'vm-local/guest-timings.json'
        del value['foundation']
        report = self.observe()
        cost_receipts.join(report, [artifact], reader)
        self.assertIsNone(report['jobs'][0]['foundationTimings'])

    def test_host_vm_installation_cleanup_and_legacy_unknown_status_are_preserved(self):
        import cost_receipts
        from contextlib import contextmanager
        import io, zipfile
        self.job['name'] = 'Validate (finite) / build'
        report = self.observe()
        artifact = {'id': 20, 'name': 'image-finite-10-1', 'expired': False,
                    'size_in_bytes': 500, 'digest': 'sha256:' + 'c' * 64,
                    'workflow_run': {'id': 10, 'head_sha': 'a' * 40}}
        value = {'schema': 1, 'seconds': {'installation': 284, 'persistence-customization': 1, 'cleanup': 2},
                 'status': {'installation': 7, 'cleanup': 7}}
        member = ['vm-local/timings.json']
        @contextmanager
        def reader(*args):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                archive.writestr(member[0], json.dumps(value))
            raw.seek(0)
            yield raw
        cost_receipts.join(report, [artifact], reader)
        stages = {s['stage']: s for s in report['jobs'][0]['stages']}
        self.assertEqual(stages['installation']['status'], 7)
        self.assertEqual(stages['cleanup']['status'], 7)
        self.assertIsNone(stages['persistence-customization']['status'])
        ranked = {row['stage']: row for row in costs.stage_opportunities([report])}
        self.assertEqual(ranked['persistence-customization']['failedSamples'], 0)
        self.assertEqual(ranked['persistence-customization']['unknownStatusSamples'], 1)
        member[0] = 'vm-upgrade/timings.json'
        with self.assertRaisesRegex(ValueError, 'phase differs'):
            cost_receipts.join(report, [artifact], reader)

    def test_observer_uses_only_existing_read_only_audit_credentials(self):
        import yaml
        path = ROOT / '.github/workflows/workflow-costs.yml'
        data = yaml.safe_load(path.read_text())
        self.assertEqual(data['permissions'], {'contents': 'read', 'actions': 'read'})
        steps = data['jobs']['observe']['steps']
        token = next(step['with'] for step in steps if step.get('id') == 'audit-token')
        self.assertEqual({k: v for k, v in token.items() if k.startswith('permission-')},
                         {'permission-administration': 'read'})
        collector = next(step for step in steps if step.get('name', '').startswith('Collect native'))
        self.assertEqual(collector['env']['GH_TOKEN'], '${{ steps.audit-token.outputs.token }}')
        for forbidden in ('DECIDER_KEY', 'COSIGN_PRIVATE_KEY', 'MERGE_QUEUE_TOKEN', 'CACHIX_AUTH_TOKEN'):
            self.assertNotIn(forbidden, path.read_text())

    def test_fourteen_day_and_seven_day_windows(self):
        report = costs.collect(api=lambda _: {'total_count': 0, 'workflow_runs': []}, now=self.now,
                               rollout=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
        self.assertTrue(report['observation']['complete'])
        self.assertEqual(report['baseline']['start'], '2026-10-01T12:00:00+00:00')
        self.assertEqual(report['observation']['end'], '2026-10-22T12:00:00+00:00')
        report = costs.collect(api=lambda _: {'total_count': 0, 'workflow_runs': []}, now=self.now)
        self.assertFalse(report['observation']['complete'])
        self.assertFalse(report['authorizesPublication'])


class ChildResources(unittest.TestCase):
    def test_deltas_keep_zero_distinct_from_missing_or_reset_counters(self):
        before = {'userCpuSeconds': 10.5, 'systemCpuSeconds': 2, 'blockInputOperations': 100,
                  'blockOutputOperations': 70}
        after = {'userCpuSeconds': 12, 'systemCpuSeconds': 2, 'blockInputOperations': 140,
                 'blockOutputOperations': 20}
        value = measure.resource_delta(before, after)
        self.assertEqual(value['userCpuSeconds'], 1.5)
        self.assertEqual(value['systemCpuSeconds'], 0)
        self.assertEqual(value['blockInputOperations'], 40)
        self.assertIsNone(value['blockOutputOperations'])
        for missing in ({}, {'userCpuSeconds': float('nan')}):
            value = measure.resource_delta(missing, after)
            self.assertTrue(all(value[name] is None for name in measure.RESOURCE_FIELDS))

    def test_resource_read_failure_does_not_replace_command_failure(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary), \
                patch.object(sys, 'argv', ['measure.py', 'failure', sys.executable, '-c', 'raise SystemExit(7)']), \
                patch.dict(os.environ, PROFILE='finite'), \
                patch.object(measure.resource, 'getrusage', side_effect=OSError('unavailable')):
            self.assertEqual(measure.main(), 7)
            value = json.loads(Path('.bluebuild/finite-timings.jsonl').read_text())
        self.assertEqual(value['status'], 7)
        self.assertTrue(all(value['childResourceUsage'][name] is None for name in measure.RESOURCE_FIELDS))

    def test_native_success_failure_and_signal_preserve_output_and_status(self):
        for command, expected, recorded in [('raise SystemExit(0)', 0, 0),
                                            ('raise SystemExit(7)', 7, 7),
                                            ('import signal; os.kill(os.getpid(), signal.SIGTERM)', 143, -15)]:
            with self.subTest(status=recorded), tempfile.TemporaryDirectory() as temporary:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/measure.py'), 'resource-fixture',
                                         sys.executable, '-c', 'import os; print("child-output", flush=True); ' + command],
                                        cwd=temporary, env={**os.environ, 'PROFILE': 'finite'}, capture_output=True, text=True)
                value = json.loads((Path(temporary) / '.bluebuild/finite-timings.jsonl').read_text())
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(result.stdout, 'child-output\n')
            self.assertEqual(value['status'], recorded)
            self.assertFalse(value['authorizesPublication'])
            for name in measure.RESOURCE_FIELDS:
                self.assertIsNotNone(value['childResourceUsage'][name])
                self.assertGreaterEqual(value['childResourceUsage'][name], 0)


if __name__ == '__main__':
    unittest.main()
