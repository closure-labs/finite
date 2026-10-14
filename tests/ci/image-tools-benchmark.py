#!/usr/bin/env python3
"""Exercise benchmark orchestration without invoking Nix or building tools."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('benchmark', ROOT / 'scripts/ci/benchmark-image-tools.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class Benchmark(unittest.TestCase):
    def test_baseline_runs_seven_unchanged_shell_commands(self):
        with patch.object(benchmark.subprocess, 'run') as run:
            result, output = benchmark.measure('baseline', 'cold')
        self.assertEqual(run.call_count, 7)
        self.assertTrue(all(call.args[0] == ['nix', 'develop', '--file', 'lib/ci-tools.nix', 'shell', '--command', 'true']
                            for call in run.call_args_list))
        self.assertIsNone(output)
        self.assertEqual(len(result['stages']), 7)

    def test_candidate_realizes_once_then_runs_seven_pinned_commands(self):
        realized = subprocess.CompletedProcess([], 0, '/nix/store/fixture-tools\n')
        with patch.object(benchmark.subprocess, 'run', return_value=realized) as run, \
                patch.object(benchmark.Path, 'is_file', return_value=True), \
                patch.object(benchmark.Path, 'exists', return_value=False):
            result, output = benchmark.measure('candidate', 'warm')
        self.assertEqual(run.call_count, 8)
        self.assertEqual(run.call_args_list[0].args[0], benchmark.command('candidate'))
        for call in run.call_args_list[1:]:
            self.assertEqual(call.args[0], ['true'])
            self.assertTrue(call.kwargs['env']['PATH'].startswith('/nix/store/fixture-tools/bin:'))
        self.assertEqual(output, Path('/nix/store/fixture-tools'))
        self.assertEqual(len(result['stages']), 8)

    def test_failures_are_not_reported_as_measurements(self):
        with patch.object(benchmark.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'nix')):
            with self.assertRaises(subprocess.CalledProcessError):
                benchmark.measure('baseline', 'cold')

    def test_store_size_does_not_double_count_shared_closures(self):
        paths = {'/nix/store/a': {'narSize': 10, 'closureSize': 100},
                 '/nix/store/b': {'narSize': 20, 'closureSize': 100}}
        with patch.object(benchmark.subprocess, 'check_output', return_value=json.dumps(paths)):
            self.assertEqual(benchmark.store_metrics(), {'paths': 2, 'narBytes': 30})
        with patch.object(benchmark.subprocess, 'check_output', return_value=json.dumps({'/nix/store/a': paths['/nix/store/a']})):
            self.assertEqual(benchmark.store_metrics('/nix/store/a'), 100)

    def test_manual_only_jobs_have_no_actions_cache(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-image-tools.yml').read_text())
        self.assertEqual(set(workflow.get('on', workflow.get(True))), {'workflow_dispatch'})
        job = workflow['jobs']['benchmark']
        self.assertEqual(job['strategy']['matrix']['mode'], ['baseline', 'candidate'])
        self.assertEqual(job['runs-on'], 'ubuntu-24.04')
        self.assertNotIn('cache-nix', json.dumps(job))
        self.assertNotIn('./.github/actions/setup-nix', json.dumps(job))
        setup = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())
        install = next(s for s in setup['runs']['steps'] if s.get('uses', '').startswith('DeterminateSystems/determinate-nix-action@'))
        self.assertIn(install['uses'], [s.get('uses') for s in job['steps']])
        self.assertEqual(next(s['with'] for s in job['steps'] if s.get('uses') == install['uses']), install['with'])
        upload = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['path'], '.bluebuild/benchmark-${{ matrix.mode }}.json')
        self.assertIs(upload['with']['include-hidden-files'], True)
        self.assertEqual(upload['with']['if-no-files-found'], 'error')


if __name__ == '__main__':
    unittest.main()
