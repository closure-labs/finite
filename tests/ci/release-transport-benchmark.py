#!/usr/bin/env python3
"""Complete-job gates require five warm pairs and one cold pair."""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path
import sys
import unittest
import yaml
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
from archive_read import authenticate
from release_transport_benchmark import assess, collect


class Benchmark(unittest.TestCase):
    def setUp(self):
        self.samples = [{'phase': phase, 'pair': pair, 'mode': mode, 'reference': 'same-packet',
                         'inventorySha256': 'same-products', 'revision': 'same-code', 'imageVersion': 'same-image', 'toolCohortSha256': 'same-tools',
                         'correctness': True, 'conclusion': 'success', 'completeJobSeconds': 400 if mode == 'legacy' else 350}
                        for phase, pair in [('cold', 1)] + [('warm', i) for i in range(1, 6)] for mode in ('legacy', 'receipt')]

    def test_complete_matched_pairs_pass_performance_but_never_enable_production(self):
        report = assess(self.samples)
        self.assertTrue(report['performanceGatePassed'])
        self.assertEqual(report['warmSecondsSaved'], 50)
        self.assertFalse(report['productionEnabled'])
        self.assertEqual(report['adoption'], 'retain-current-production-path')

    def test_incomplete_failing_changed_products_or_tool_cohorts_do_not_pass(self):
        self.assertFalse(assess(self.samples[:-1])['performanceGatePassed'])
        for field, value in [('correctness', False), ('conclusion', 'failure'), ('inventorySha256', 'changed'),
                             ('correctness', 'true'),
                             ('imageVersion', None), ('revision', 'changed')]:
            rows = deepcopy(self.samples)
            rows[0][field] = value
            with self.subTest(field=field): self.assertFalse(assess(rows)['performanceGatePassed'])
        with self.assertRaises(ValueError): assess(self.samples + self.samples[:1])

    def test_both_warm_thresholds_and_cold_limit_apply(self):
        rows = deepcopy(self.samples)
        for row in rows:
            if row['phase'] == 'warm': row['completeJobSeconds'] = 200 if row['mode'] == 'legacy' else 175
        self.assertFalse(assess(rows)['performanceGatePassed'], '25 seconds fails the 30-second floor')
        rows = deepcopy(self.samples)
        for row in rows:
            if row['phase'] == 'warm': row['completeJobSeconds'] = 1000 if row['mode'] == 'legacy' else 950
        self.assertFalse(assess(rows)['performanceGatePassed'], '5 percent fails the relative floor')
        rows = deepcopy(self.samples)
        rows[1]['completeJobSeconds'] = 441
        self.assertFalse(assess(rows)['performanceGatePassed'])
        rows[1]['completeJobSeconds'] = 440
        self.assertTrue(assess(rows)['performanceGatePassed'])

    def test_partial_failed_transfer_is_an_incomplete_result_not_a_saving(self):
        rows = deepcopy(self.samples)
        rows[0].pop('inventorySha256')
        rows[0]['correctness'] = False
        self.assertFalse(assess(rows)['performanceGatePassed'])
        rows[0]['completeJobSeconds'] = float('nan')
        with self.assertRaises(ValueError): assess(rows)

    def test_pair_report_keeps_unmatched_images_and_each_failed_threshold(self):
        rows = deepcopy(self.samples)
        rows[2]['imageVersion'] = 'different-image'
        report = assess(rows)
        pair = next(p for p in report['pairComparisons'] if p['phase'] == 'warm' and p['pair'] == 1)
        self.assertEqual(pair['imageVersions'], {'legacy': 'different-image', 'receipt': 'same-image'})
        self.assertFalse(pair['runnerImagesMatched'])
        self.assertTrue(pair['toolsMatched'])
        self.assertIn('runner-image-or-tool-cohort-mismatch', report['gateFailures'])
        self.assertFalse(report['performanceGatePassed'])
        rows = deepcopy(self.samples)
        for row in rows:
            if row['mode'] == 'receipt': row['completeJobSeconds'] = 450
        self.assertEqual(set(assess(rows)['gateFailures']),
                         {'warm-median-minimum-seconds', 'warm-median-minimum-relative', 'cold-cost-regression'})
        report = assess(self.samples[:-1])
        self.assertEqual(report['pairComparisons'][-1]['missingModes'], ['receipt'])
        self.assertIsNone(report['pairComparisons'][-1]['runnerImagesMatched'])
        self.assertEqual(report['verifiedSampleCount'], 11)
        self.assertEqual(report['failedSampleCount'], 0)
        self.assertNotIn('failed-or-inconsistent-samples', report['gateFailures'])
        self.assertIn('incomplete-sample-set', report['gateFailures'])

    def test_diagnostic_matches_publishers_final_approved_asset_hash_pass(self):
        spec = importlib.util.spec_from_file_location('benchmark_transport', ROOT / 'scripts/ci/benchmark-release-transport.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from release_set import prepare
        payload = {'version': '1.2.3', 'sourceRevision': 'a' * 40, 'channels': {}}
        evidence = {}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for lane in ('finite', 'finite-dev'):
                directory = root / ('release-' + lane)
                directory.mkdir()
                (directory / 'image.iso').write_bytes(lane.encode())
                digest = hashlib.sha256(lane.encode()).hexdigest()
                payload['channels'][lane] = {'tag': lane + '-1.2.3', 'imageDigest': 'sha256:' + digest,
                                             'isoSha256': digest, 'assets': {'image.iso': digest}}
                evidence[lane] = {'status': 'qualified', 'sourceRevision': 'a' * 40,
                                  'imageDigest': 'sha256:' + digest, 'isoSha256': digest}
            document = prepare(payload, evidence)
            module.validate_products(root, document)
            (root / 'release-finite/image.iso').write_bytes(b'altered')
            with self.assertRaisesRegex(ValueError, 'approved asset hash mismatch'):
                module.validate_products(root, document)

    def test_workflow_runs_all_pairs_without_signing_or_decision_mutation(self):
        data = yaml.safe_load((ROOT / '.github/workflows/benchmark-release-transport.yml').read_text())
        rows = data['jobs']['consumer']['strategy']['matrix']['include']
        self.assertEqual(len(rows), 12)
        self.assertEqual(data['jobs']['producer']['permissions'], {'contents': 'read', 'actions': 'read', 'packages': 'write'})
        text = (ROOT / '.github/workflows/benchmark-release-transport.yml').read_text()
        self.assertNotIn('COSIGN_PRIVATE_KEY', text)
        self.assertNotIn('decision-controller.py propose', text)


class NativeCollection(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 10, 'run_attempt': 1, 'head_sha': 'a' * 40, 'event': 'workflow_dispatch',
                    'path': '.github/workflows/benchmark-release-transport.yml', 'status': 'completed',
                    'conclusion': 'success', 'repository': {'full_name': 'closure-labs/finite'},
                    'head_repository': {'full_name': 'closure-labs/finite'}}
        self.producer_run = {**self.run, 'id': 20, 'head_sha': 'b' * 40}
        self.producer = {'runId': 20, 'runAttempt': 1, 'headSha': 'b' * 40,
                         'workflow': 'benchmark-release-transport.yml', 'repository': 'closure-labs/finite'}
        self.producer_jobs = [{'id': 99, 'run_id': 20, 'run_attempt': 1, 'head_sha': 'b' * 40,
                              'name': 'producer', 'status': 'completed', 'conclusion': 'success',
                              'started_at': '2026-10-23T00:00:00Z', 'completed_at': '2026-10-23T00:01:40Z'}]
        self.jobs, self.artifacts, self.blobs, self.values = [], [], {}, []
        fixture = Benchmark()
        fixture.setUp()
        for index, sample in enumerate(fixture.samples):
            name = f'consumer-{sample["phase"]}-{sample["pair"]}-{sample["mode"]}'
            job = {'id': index + 1, 'run_id': 10, 'run_attempt': 1, 'head_sha': 'a' * 40,
                   'name': name, 'status': 'completed', 'conclusion': 'success',
                   'started_at': '2026-10-23T00:00:00Z',
                   'completed_at': '2026-10-23T00:06:40Z' if sample['mode'] == 'legacy' else '2026-10-23T00:05:50Z'}
            self.jobs.append(job)
            value = {**sample, 'schema': 1, 'kind': 'finite-release-transport-sample', 'runId': 10,
                     'runAttempt': 1, 'revision': 'a' * 40, 'jobName': name, 'producer': self.producer}
            self.values.append(value)
            self.artifacts.append({'id': index + 100, 'name': f'release-transport-sample-{sample["phase"]}-{sample["pair"]}-{sample["mode"]}-10-1',
                                   'expired': False, 'workflow_run': {'id': 10, 'head_sha': 'a' * 40}})
            self.archive(index, {'transport-sample.json': json.dumps(value), 'ci-timings.jsonl': ''})
        self.jobs.append({**self.jobs[0], 'id': 30, 'name': 'producer', 'conclusion': 'skipped',
                          'started_at': '2026-10-23T00:00:01Z', 'completed_at': '2026-10-23T00:00:00Z'})

    def archive(self, index, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as zipped:
            for name, content in entries.items(): zipped.writestr(name, content)
        raw = output.getvalue()
        artifact = self.artifacts[index]
        self.blobs[artifact['id']] = raw
        artifact.update(size_in_bytes=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())

    @contextmanager
    def reader(self, artifact, repository):
        self.assertEqual(repository, 'closure-labs/finite')
        stream = io.BytesIO(self.blobs[artifact['id']])
        authenticate(stream, artifact)
        yield stream

    def api(self, endpoint):
        prefix = 'repos/closure-labs/finite/actions/runs/'
        self.assertTrue(endpoint.startswith(prefix), endpoint)
        path = endpoint.removeprefix(prefix)
        if path == '10': return self.run
        if path == '20/attempts/1': return self.producer_run
        for query, key, values in [('10/attempts/1/jobs?', 'jobs', self.jobs),
                                    ('20/attempts/1/jobs?', 'jobs', self.producer_jobs),
                                    ('10/artifacts?', 'artifacts', self.artifacts)]:
            if path.startswith(query): return {'total_count': len(values), key: values}
        self.fail('Unexpected external read: ' + endpoint)

    def collect(self):
        return collect(10, self.api, reader=self.reader)

    def test_native_complete_cost_includes_each_job_once_and_keeps_producer_separate(self):
        self.jobs.append(deepcopy(self.jobs[0]))
        self.producer_jobs.append(deepcopy(self.producer_jobs[0]))
        report = self.collect()
        self.assertTrue(report['performanceGatePassed'])
        self.assertEqual(report['knownRunnerSeconds'], 4500)
        self.assertEqual(len(report['nativeJobs']), 13)
        self.assertEqual(report['producers'][0]['runnerSeconds'], 100)
        self.assertFalse(report['productionEnabled'])

    def test_setup_failure_without_artifact_retains_native_cost_and_fails_gate(self):
        missing = self.artifacts.pop(0)
        self.jobs[0]['conclusion'] = 'failure'
        self.run['conclusion'] = 'failure'
        report = self.collect()
        self.assertEqual(report['knownRunnerSeconds'], 4500)
        self.assertEqual(report['missingSampleJobs'], [self.jobs[0]['id']])
        self.assertEqual(len(report['samples']), 11)
        self.assertIn('native-run-failed', report['gateFailures'])
        self.assertFalse(report['performanceGatePassed'])
        self.assertIn(missing['id'], self.blobs)

    def test_all_setup_failures_keep_cost_and_unknown_producer(self):
        self.artifacts.clear()
        self.run['conclusion'] = 'failure'
        for job in self.jobs[:-1]: job['conclusion'] = 'failure'
        report = self.collect()
        self.assertEqual(report['knownRunnerSeconds'], 4500)
        self.assertEqual(report['nativeJobConclusions'], {'failure': 12, 'skipped': 1})
        self.assertEqual(report['producerCostCoverage'], 'unknown-without-sample-producer')
        self.assertEqual(report['verifiedSampleCount'], 0)
        self.assertIsNone(report['productIdentityConsistent'])
        self.assertEqual(len(report['missingSampleJobs']), 12)
        self.assertFalse(report['performanceGatePassed'])

    def test_failed_transfer_with_only_timing_member_is_partial_not_a_saving(self):
        self.jobs[0]['conclusion'] = 'failure'
        self.run['conclusion'] = 'failure'
        self.archive(0, {'ci-timings.jsonl': '{"status":1}\n'})
        report = self.collect()
        self.assertEqual(report['knownRunnerSeconds'], 4500)
        self.assertEqual(report['unscoredSamples'][0]['reason'], 'failed-job-without-sample-member')
        self.assertFalse(report['performanceGatePassed'])
        self.jobs[0]['conclusion'] = 'success'
        with self.assertRaisesRegex(ValueError, 'Missing diagnostic transport sample'): self.collect()

    def test_missing_or_zero_native_duration_is_unknown_or_unscored(self):
        self.jobs[0]['completed_at'] = None
        report = self.collect()
        self.assertEqual(report['knownRunnerSeconds'], 4100)
        self.assertEqual(report['unknownDurationJobs'], [1])
        self.assertIn('incomplete-native-job-costs', report['gateFailures'])
        self.assertEqual(report['unscoredSamples'][0]['reason'], 'missing-or-nonpositive-native-duration')
        self.jobs[0]['completed_at'] = self.jobs[0]['started_at']
        report = self.collect()
        self.assertEqual(report['unknownDurationJobs'], [])
        self.assertFalse(report['performanceGatePassed'])

    def test_invalid_present_digest_sample_or_job_binding_fails_closed(self):
        original = self.artifacts[0]['digest']
        self.artifacts[0]['digest'] = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): self.collect()
        self.artifacts[0]['digest'] = original
        changed = {**self.values[0], 'jobName': self.jobs[1]['name']}
        self.archive(0, {'transport-sample.json': json.dumps(changed)})
        with self.assertRaisesRegex(ValueError, 'differs from native'): self.collect()
        self.archive(0, {'transport-sample.json': json.dumps(self.values[0])})
        self.jobs[0]['head_sha'] = 'c' * 40
        with self.assertRaisesRegex(ValueError, 'Diagnostic job differs'): self.collect()

    def test_failed_producer_and_retried_consumer_are_rejected(self):
        self.producer_run['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'producer changed or did not succeed'): self.collect()
        self.producer_run['conclusion'] = 'success'
        self.producer_jobs[0]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'producer job did not succeed'): self.collect()
        self.producer_jobs[0]['conclusion'] = 'success'
        self.run['run_attempt'] = 2
        with self.assertRaisesRegex(ValueError, 'unretried'): self.collect()

    def test_unknown_producer_cost_is_retained_and_blocks_gate(self):
        self.producer_jobs[0]['completed_at'] = None
        report = self.collect()
        self.assertIsNone(report['producers'][0]['runnerSeconds'])
        self.assertEqual(report['producers'][0]['unknownDurationJobs'], [99])
        self.assertEqual(report['producerCostCoverage'], 'incomplete-native-producer-costs')
        self.assertIn('incomplete-native-producer-costs', report['gateFailures'])
        self.assertFalse(report['performanceGatePassed'])

    def test_missing_native_jobs_and_workflow_failure_never_pass(self):
        self.jobs.pop(0)
        self.artifacts.pop(0)
        report = self.collect()
        self.assertEqual(report['missingNativeJobs'], [{'phase': 'cold', 'pair': 1, 'mode': 'legacy'}])
        self.assertFalse(report['performanceGatePassed'])

    def test_workflow_failure_prevents_gate_even_when_all_samples_pass(self):
        self.run['conclusion'] = 'failure'
        report = self.collect()
        self.assertTrue(report['complete'])
        self.assertIn('native-run-failed', report['gateFailures'])
        self.assertFalse(report['performanceGatePassed'])

    def test_conflicting_jobs_ambiguous_samples_and_wrong_artifact_origins_are_rejected(self):
        self.jobs.append({**self.jobs[0], 'conclusion': 'failure'})
        with self.assertRaisesRegex(ValueError, 'Conflicting duplicate'): self.collect()
        self.jobs.pop()
        self.artifacts.append(deepcopy(self.artifacts[0]))
        with self.assertRaisesRegex(ValueError, 'twelve-sample bound'): self.collect()
        self.artifacts.pop()
        self.artifacts[0]['workflow_run']['head_sha'] = 'c' * 40
        with self.assertRaisesRegex(ValueError, 'Invalid native transport sample artifact'): self.collect()


if __name__ == '__main__':
    unittest.main()
