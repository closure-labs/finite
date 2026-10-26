#!/usr/bin/env python3
"""Validate cache benchmark measurements and matched-run aggregation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('benchmark', ROOT / 'scripts/ci/benchmark-ci-cache.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def report(mode, tool, repetition):
    return {'schema': 1, 'mode': mode, 'tool': tool, 'repetition': repetition,
            'revision': 'fixed-revision', 'lockSha256': 'fixed-lock', 'runId': '10',
            'status': 'success', 'setup': {'seconds': repetition * 2}, 'setupPlusColdSeconds': repetition * 3,
            'passes': [{'transport': {'receivedBytes': repetition * 100}}, {'seconds': repetition}]}


class CacheBenchmark(unittest.TestCase):
    def test_measures_same_narrow_closure_and_does_not_double_count_store(self):
        stores = [{'paths': 1, 'narBytes': 10}, {'paths': 2, 'narBytes': 30}, 100]
        before = {'monotonicSeconds': 10, 'transport': {'receivedBytes': 100, 'sentBytes': 20},
                  'filesystem': {'usedBytes': 1000}}
        after = {'monotonicSeconds': 15, 'transport': {'receivedBytes': 400, 'sentBytes': 30},
                 'filesystem': {'usedBytes': 1020}}
        realized = subprocess.CompletedProcess([], 0, '/nix/store/tools\n')
        with patch.object(benchmark, 'store_metrics', side_effect=stores), \
                patch.object(benchmark, 'snapshot', side_effect=[before, after]), \
                patch.object(benchmark.subprocess, 'run', return_value=realized) as run, \
                patch.object(benchmark.Path, 'is_dir', return_value=True):
            measured = benchmark.measure('scanner-tools', 'cold')
        self.assertEqual(measured['seconds'], 5)
        self.assertEqual(measured['transport'], {'receivedBytes': 300, 'sentBytes': 10})
        self.assertEqual(measured['addedStoreNarBytes'], 20)
        self.assertEqual(measured['closureNarBytes'], 100)
        self.assertEqual(run.call_args.args[0], ['nix', 'build', '--file', 'lib/ci-tools.nix',
                         'scanner-tools', '--no-link', '--print-out-paths'])

    def test_invalid_realization_output_is_rejected(self):
        for output in ('', '/tmp/tools\n', '/nix/store/a\n/nix/store/b\n'):
            with self.subTest(output=output), patch.object(benchmark, 'store_metrics', return_value={}), \
                    patch.object(benchmark, 'snapshot', return_value={'monotonicSeconds': 0}), \
                    patch.object(benchmark.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output)):
                with self.assertRaises(ValueError):
                    benchmark.measure('image-tools', 'warm')

    def test_store_counts_nar_bytes_once(self):
        records = {'a': {'narSize': 10, 'closureSize': 100}, 'b': {'narSize': 20, 'closureSize': 100}}
        with patch.object(benchmark.subprocess, 'check_output', return_value=json.dumps(records)):
            self.assertEqual(benchmark.store_metrics(), {'paths': 2, 'narBytes': 30})
            with self.assertRaises(ValueError):
                benchmark.store_metrics('/nix/store/a')

    def test_failure_report_is_retained_and_failure_propagates(self):
        with tempfile.TemporaryDirectory() as temp:
            start = Path(temp) / 'start.json'
            output = Path(temp) / 'benchmark.json'
            snap = {'monotonicSeconds': 0, 'transport': {}, 'filesystem': {'usedBytes': 0}}
            start.write_text(json.dumps(snap))
            with patch.dict(benchmark.os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': 'revision', 'GITHUB_RUN_ID': '10'}), \
                    patch.object(benchmark, 'snapshot', return_value=snap), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='nix 1'), \
                    patch.object(benchmark, 'measure', side_effect=subprocess.CalledProcessError(1, 'nix')), \
                    patch('builtins.print'):
                with self.assertRaises(subprocess.CalledProcessError):
                    benchmark.benchmark('none', 'image-tools', 1, start, output)
            saved = json.loads(output.read_text())
            self.assertEqual(saved['status'], 'error')
            self.assertEqual(saved['passes'], [])

    def write_reports(self, directory, changed=None):
        for mode in benchmark.MODES:
            for tool in benchmark.TOOLS:
                for repetition in (1, 2, 3):
                    item = report(mode, tool, repetition)
                    if changed:
                        changed(item)
                    path = directory / f'{mode}-{tool}-{repetition}' / 'benchmark.json'
                    path.parent.mkdir()
                    path.write_text(json.dumps(item))

    def test_aggregate_requires_three_matching_runs_and_reports_medians(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_reports(directory)
            output = directory / 'summary.md'
            with patch.dict(benchmark.os.environ, {}, clear=True):
                benchmark.summarize(directory, output)
            content = output.read_text()
            self.assertIn('| image-tools | baseline | 3 | 4.00 | 6.00 | 2.00 | 200.00 |', content)
            (directory / 'none-image-tools-3' / 'benchmark.json').unlink()
            with self.assertRaisesRegex(ValueError, 'three matched'):
                benchmark.summarize(directory, output)

    def test_mixed_revisions_and_partial_failure_do_not_qualify_lane(self):
        for field, value in [('revision', 'other'), ('status', 'error')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                def changed(item):
                    if (item['mode'], item['tool'], item['repetition']) == ('none', 'image-tools', 3):
                        item[field] = value
                self.write_reports(directory, changed)
                with patch.dict(benchmark.os.environ, {}, clear=True), self.assertRaises(ValueError):
                    benchmark.summarize(directory, directory / 'summary.md')

    def test_workflow_is_manual_pinned_and_repeats_each_matched_lane_three_times(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-ci-cache.yml').read_text())
        self.assertEqual(set(workflow.get('on', workflow.get(True))), {'workflow_dispatch', 'workflow_call'})
        job = workflow['jobs']['benchmark']
        self.assertEqual(job['strategy']['matrix'], {'mode': list(benchmark.MODES), 'tool': list(benchmark.TOOLS),
                         'repetition': [1, 2, 3]})
        setup = next(step for step in job['steps'] if step.get('uses') == '$/.github/actions/setup-nix')
        self.assertEqual(setup['with'], {'cache-mode': '${{ matrix.mode }}', 'cache-profile': 'sources'})
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(workflow['jobs']['summarize']['needs'], 'benchmark')
        downloads = next(step for step in workflow['jobs']['summarize']['steps'] if step.get('env', {}).get('REPORT_PATTERN'))
        self.assertIn('${{ github.run_attempt }}', downloads['env']['REPORT_PATTERN'])
        for job in workflow['jobs'].values():
            for step in job['steps']:
                action = step.get('uses', '')
                if action and not action.startswith('$/'):
                    self.assertRegex(action, r'@[a-f0-9]{40}$')

    def test_registered_entry_point_separates_benchmarks_and_diagnostic_qualification(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-image-tools.yml').read_text())
        event = workflow.get('on', workflow.get(True))['workflow_dispatch']
        self.assertEqual(event['inputs']['validation']['default'], 'tool-setup')
        jobs = workflow['jobs']
        self.assertEqual(jobs['cache-lanes']['uses'], '$/.github/workflows/benchmark-ci-cache.yml')
        diagnostic = jobs['qualification']
        self.assertIn("github.ref != 'refs/heads/main'", diagnostic['if'])
        self.assertIs(diagnostic['with']['validation_only'], True)
        self.assertIs(diagnostic['with']['force_qualification'], True)
        self.assertNotIn('secrets', diagnostic)
        self.assertNotIn('publish', jobs)


if __name__ == '__main__':
    unittest.main()
