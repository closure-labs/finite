#!/usr/bin/env python3
"""Native timing includes failed work and reused jobs without double charging."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import workflow_costs as costs


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


if __name__ == '__main__':
    unittest.main()
