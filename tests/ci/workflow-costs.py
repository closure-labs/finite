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
        # A receipt for attempt two cannot relabel work reused from attempt one.
        artifact['name'] = 'source-checks-10-2'
        changed = {**value, 'runAttempt': '2'}
        cost_receipts.nix_receipt(report, artifact, 'nix-checks.json', changed, set())
        self.assertEqual(report['receiptCoverage']['unmatched'], 1)

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
