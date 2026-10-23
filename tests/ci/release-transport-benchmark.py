#!/usr/bin/env python3
"""Complete-job gates require five warm pairs and one cold pair."""
from copy import deepcopy
import hashlib
import importlib.util
import tempfile
from pathlib import Path
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
from release_transport_benchmark import assess


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


if __name__ == '__main__':
    unittest.main()
