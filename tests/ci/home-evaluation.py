#!/usr/bin/env python3
"""Keep scheduling trials strict about coverage, failures and complete costs."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('trial', ROOT / 'scripts/ci/benchmark-home-evaluation.py')
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class Evaluation(unittest.TestCase):
    def rows(self):
        return [{'mode': mode, 'seed': i == 0, 'status': 0, 'seconds': 100 if mode == 'serial' else 75,
                 'maxRSSKiB': 1000000, 'fingerprint': 'a' * 64}
                for i, mode in enumerate(('public',) + trial.ORDER)]

    def test_matching_complete_matrices_and_warm_medians_are_required(self):
        rows = self.rows()
        rows[0]['seconds'] = 900
        result = trial.assess(rows)
        self.assertTrue(result['performanceGatePassed'])
        self.assertEqual(result['warmMedianSeconds'], {'serial': 100, 'paired': 75})
        self.assertFalse(result['authorizesPublication'])
        for key, value in [('status', 1), ('status', False), ('fingerprint', 'b' * 64),
                           ('seconds', None), ('seconds', 0), ('seconds', float('inf')),
                           ('maxRSSKiB', None), ('maxRSSKiB', 7 * 1024**2), ('error', 'cleanup failed')]:
            changed = self.rows()
            changed[2][key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(trial.assess(changed)['performanceGatePassed'])
        self.assertFalse(trial.assess(rows[:-1])['performanceGatePassed'])
        for r in rows:
            if r['mode'] == 'paired': r['seconds'] = 95
        self.assertFalse(trial.assess(rows)['performanceGatePassed'])

    def test_fingerprints_include_every_case_and_path_in_order(self):
        value = {'cases': [{'identity': 'one'}, {'identity': 'two'}],
                 'aggregateDrvPath': '/nix/store/' + 'c' * 32 + '-finite-ci-checks.drv',
                 'checkNames': ['home-configurations', 'bluebuild'],
                 'paths': ['/nix/store/' + 'a' * 32 + '-one.drv', '/nix/store/' + 'b' * 32 + '-two.drv']}
        first = trial.fingerprint(value)
        self.assertNotEqual(first, trial.fingerprint({**value, 'paths': list(reversed(value['paths']))}))
        self.assertNotEqual(first, trial.fingerprint({**value, 'cases': list(reversed(value['cases']))}))
        for invalid in ({}, {**value, 'paths': []}, {**value, 'cases': []},
                        {**value, 'paths': ['/tmp/one', '/tmp/two']}):
            with self.assertRaises(ValueError): trial.fingerprint(invalid)

    def test_failure_retains_partial_sample_and_stops_service(self):
        env = {'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '1', 'PATH': '/usr/bin', 'HOME': '/tmp/home'}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, env, clear=True), \
                patch.object(trial.shutil, 'which', return_value='/usr/bin/nix'), \
                patch.object(trial.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('systemd-run', 930),
                                                                  subprocess.CompletedProcess([], 0)]) as run:
            root = Path(temporary)
            row = trial.measure('paired', 1, root)
            self.assertIsNone(row['status'])
            self.assertIn('error', row)
            self.assertIsNone(row['maxRSSKiB'])
            self.assertIsNone(row['fingerprint'])
            self.assertEqual(json.loads((root / 'sample-1.json').read_text()), row)
            args = run.call_args_list[0].args[0]
            for bound in ('--property=MemoryMax=6G', '--property=MemorySwapMax=0', '--property=RuntimeMaxSec=900'):
                self.assertIn(bound, args)
            self.assertIn('--no-eval-cache', args)
            self.assertNotIn('build', args)
            self.assertEqual(run.call_args_list[-1].args[0], ['sudo', 'systemctl', 'stop', 'finite-home-evaluation-12-1-1'])

    def test_failed_main_retains_the_attempt_without_following_samples(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
               'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': 'a' * 40,
               'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '1'}
        import contextlib
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary), \
                patch.object(trial.subprocess, 'check_output', return_value='nix (Determinate Nix 3.23.2)'), \
                patch.object(trial, 'measure', side_effect=[
                    {'mode': 'preflight', 'seed': False, 'status': 0, 'maxRSSKiB': 10000},
                    {'mode': 'public', 'seed': True, 'status': 137}]) as measure, \
                patch('builtins.print'):
            Path('flake.lock').write_text('{}')
            with self.assertRaises(ValueError): trial.main(env)
            result = json.loads(Path('.bluebuild/home-evaluation/report.json').read_text())
            self.assertEqual(len(result['samples']), 1)
            self.assertFalse(result['assessment']['performanceGatePassed'])
            self.assertEqual(measure.call_count, 2)
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary), \
                patch.object(trial.subprocess, 'check_output', return_value='nix (Determinate)'), \
                patch.object(trial, 'measure', return_value={'mode': 'preflight', 'status': 1}) as measure, \
                patch('builtins.print'):
            Path('flake.lock').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'preflight failed'): trial.main(env)
            result = json.loads(Path('.bluebuild/home-evaluation/report.json').read_text())
            self.assertEqual(result['samples'], [])
            self.assertEqual(result['preflight']['status'], 1)
            measure.assert_called_once()
        with self.assertRaises(ValueError): trial.main({})

    def test_manual_trial_has_no_other_benchmark_or_publication_jobs(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-ci-cache.yml').read_text())
        jobs = workflow['jobs']
        self.assertIn('!inputs.evaluation_only', jobs['benchmark']['if'])
        self.assertIn('!inputs.evaluation_only', jobs['summarize']['if'])
        selected = jobs['home-evaluation']
        self.assertIn("github.event_name == 'workflow_dispatch'", selected['if'])
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertFalse(any(s.get('secrets') for s in selected['steps']))
        self.assertEqual(next(s for s in selected['steps'] if s.get('uses') == './.github/actions/setup-nix')['with']['cache-mode'], 'none')
        retain = selected['steps'][-1]
        self.assertEqual(retain['if'], 'always()')
        self.assertEqual(retain['with']['retention-days'], 14)


if __name__ == '__main__':
    unittest.main()
