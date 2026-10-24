#!/usr/bin/env python3
"""Exercise recovery from fetch failures and prompt failure for broken checks."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('nix_checks', ROOT / 'scripts/ci/nix-checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
import nix_observation as observation
DRV = '/nix/store/' + 'a' * 32 + '-finite-ci-checks.drv'


class RetryChecks(unittest.TestCase):
    def test_pr_native_head_and_executed_merge_checkout_remain_distinct(self):
        value = observation.identity({'GITHUB_SHA': 'a' * 40, 'FINITE_OBSERVATION_REVISION': 'b' * 40})
        self.assertEqual(value['revision'], 'b' * 40)
        self.assertEqual(value['checkoutRevision'], 'a' * 40)
        self.assertEqual(observation.identity({'GITHUB_SHA': 'c' * 40})['revision'], 'c' * 40)

    def test_setup_observation_retains_partial_failure_and_unknown_cache(self):
        env = {'GITHUB_JOB': 'checks', 'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '2'}
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            observation.setup('setup-start', env)
            observation.setup('setup-finish', {**env, 'SETUP_STATUS': 'failure'})
            result = json.loads(Path('.bluebuild/nix-setup.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertIsNone(result['cache'])
            self.assertGreaterEqual(result['seconds'], 0)
            observation.setup('setup-start', env)
            observation.setup('cache-selection', {**env, 'STORE_KEY': 'snapshot', 'STORE_HIT': 'true'})
            observation.setup('setup-finish', {**env, 'SETUP_STATUS': 'success'})
            result = json.loads(Path('.bluebuild/nix-setup.json').read_text())
            self.assertEqual(result['cache']['STORE_KEY'], 'snapshot')
            self.assertEqual(result['cache']['STORE_HIT'], 'true')
            self.assertIsNone(result['cache']['SOURCE_HIT'])
            observation.setup('setup-start', env)
            with self.assertRaisesRegex(ValueError, 'differs from this job'):
                observation.setup('setup-finish', {**env, 'GITHUB_RUN_ATTEMPT': '3'})
            with self.assertRaisesRegex(ValueError, 'Oversized'):
                observation.write('large.json', {'payload': 'x' * observation.MAX_BYTES})
            self.assertFalse(Path('.bluebuild/large.json').exists())
            observation.setup('setup-start', {'GITHUB_JOB': 'other'})

    def test_explicit_diagnostic_setup_keeps_unknown_cache_distinct_from_a_miss(self):
        env = {'GITHUB_JOB': 'phase', 'FINITE_NIX_OBSERVATION': 'true', 'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '1'}
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            observation.setup('setup-start', env)
            observation.setup('cache-selection', env)
            observation.setup('setup-finish', {**env, 'SETUP_STATUS': 'success'})
            unknown = json.loads(Path('.bluebuild/nix-setup.json').read_text())
            self.assertIsNone(unknown['cache']['STORE_HIT'])
            observation.setup('setup-start', env)
            observation.setup('cache-selection', {**env, 'STORE_HIT': 'false'})
            missed = json.loads(Path('.bluebuild/nix-setup.json').read_text())
            self.assertEqual(missed['cache']['STORE_HIT'], 'false')
            Path('.bluebuild/nix-setup.json').unlink()
            observation.setup('setup-start', {'GITHUB_JOB': 'phase'})
            self.assertFalse(Path('.bluebuild/nix-setup.json').exists())

    def test_hosted_checks_root_successful_proofs_before_bounded_cache_gc(self):
        command = checks.check_command(DRV, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': '/tmp/runner'})
        self.assertEqual(command[command.index('--out-link') + 1], '/tmp/runner/finite-checks-cache-root')
        self.assertEqual(command[-1], DRV + '^*')
        self.assertNotIn('--no-link', command)
        self.assertIn('--no-link', checks.check_command(DRV, {}))
        with self.assertRaises(ValueError):
            checks.check_command(DRV, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': 'relative'})

    def phases(self, evaluation=(), builds=(), result=DRV):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Real child processes prove that the evaluator exits before build,
            # while a retry can leave partial stdout that must be truncated.
            script = root / 'nix'
            script.write_text('#!' + sys.executable + '''
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FAKE_NIX_ROOT'])
state = json.loads((root / 'state').read_text())
phase = 'evaluation' if sys.argv[1] == 'eval' else 'builds'
state['calls'].append({'phase':phase,'pid':os.getpid(),'args':sys.argv[1:]})
failures = state[phase]
failure = failures.pop(0) if failures else None
(root / 'state').write_text(json.dumps(state))
if failure:
    if phase == 'evaluation': print('partial evaluation result')
    print(failure, file=sys.stderr)
    sys.exit(1)
if phase == 'evaluation': print(state['result'])
''')
            script.chmod(0o755)
            state = root / 'state'
            state.write_text(json.dumps({'evaluation': list(evaluation), 'builds': list(builds),
                                         'result': result, 'calls': []}))
            summary = root / 'summary'
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'FAKE_NIX_ROOT': directory, 'GITHUB_ACTIONS': 'true',
                   'RUNNER_TEMP': directory, 'GITHUB_STEP_SUMMARY': str(summary)}
            with contextlib.chdir(root), patch.dict(os.environ, env, clear=True), patch.object(checks.time, 'sleep'), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    status = checks.run_checks(env)
                except ValueError:
                    status = 'invalid'
            self.receipt = json.loads((root / '.bluebuild/nix-checks.json').read_text())
            return status, json.loads(state.read_text())['calls'], summary.read_text()

    def test_evaluation_is_separate_and_builds_only_its_exact_derivation(self):
        status, calls, summary = self.phases()
        self.assertEqual(status, 0)
        self.assertEqual([c['phase'] for c in calls], ['evaluation', 'builds'])
        self.assertNotEqual(calls[0]['pid'], calls[1]['pid'])
        self.assertEqual(calls[0]['args'][-1], '.#ci-checks.drvPath')
        self.assertIn('--no-update-lock-file', calls[0]['args'])
        self.assertIn('--no-write-lock-file', calls[0]['args'])
        self.assertEqual(calls[1]['args'][-1], DRV + '^*')
        self.assertNotIn('.#ci-checks', calls[1]['args'])
        self.assertIn('--out-link', calls[1]['args'])
        self.assertIn('Evaluate aggregate', summary)
        self.assertIn('Build aggregate', summary)
        self.assertEqual(self.receipt['aggregateDerivation'], DRV)

    def test_evaluation_transport_retry_discards_partial_output(self):
        status, calls, _ = self.phases(evaluation=['HTTP error 503'])
        self.assertEqual(status, 0)
        self.assertEqual([c['phase'] for c in calls], ['evaluation', 'evaluation', 'builds'])

    def test_build_transport_retry_does_not_evaluate_again(self):
        status, calls, _ = self.phases(builds=['HTTP error 503'])
        self.assertEqual(status, 0)
        self.assertEqual([c['phase'] for c in calls], ['evaluation', 'builds', 'builds'])
        phases = self.receipt['phases']
        self.assertEqual([len(p['attempts']) for p in phases], [1, 2])
        self.assertEqual([p['status'] for p in phases[1]['attempts']], [1, 0])
        self.assertEqual(phases[1]['outcome'], 'success')
        self.assertGreaterEqual(phases[1]['seconds'], sum(p['seconds'] for p in phases[1]['attempts']) - .01)

    def test_partial_failures_are_retained_without_inventing_unstarted_builds(self):
        status, _, _ = self.phases(evaluation=['hash mismatch'])
        self.assertEqual(status, 1)
        self.assertEqual(len(self.receipt['phases']), 1)
        self.assertEqual(self.receipt['phases'][0]['outcome'], 'failure')
        self.assertEqual(self.receipt['phases'][0]['status'], 1)
        self.assertFalse(self.receipt['authorizesPublication'])
        self.phases(result='invalid')
        self.assertEqual(self.receipt['phases'][0]['outcome'], 'error')
        self.assertEqual(len(self.receipt['phases']), 1)

    def test_terminal_evaluation_and_build_failures_stop_their_phase(self):
        for errors in ({'evaluation': ['hash mismatch']}, {'builds': ['Reason: builder failed with exit code 1']}):
            with self.subTest(errors=errors):
                status, calls, summary = self.phases(**errors)
                self.assertEqual(status, 1)
                self.assertEqual(len(calls), 1 if 'evaluation' in errors else 2)
                self.assertIn('Evaluate aggregate', summary)

    def test_invalid_or_multiple_evaluation_outputs_never_build(self):
        for result in ('', DRV + '\n' + DRV, '.#ci-checks', '/tmp/checks.drv',
                       DRV + ' ' * 4096, DRV.replace('finite-ci-checks', 'other')):
            with self.subTest(result=result[:100]):
                status, calls, _ = self.phases(result=result)
                self.assertEqual(status, 'invalid')
                self.assertEqual([c['phase'] for c in calls], ['evaluation'])

    def test_only_transport_errors_are_retriable(self):
        for error in ('unable to download archive: HTTP error 504',
                      'HTTP error 429', 'connection reset by peer',
                      "Couldn't resolve host name", 'TLS connect error'):
            with self.subTest(error=error):
                self.assertTrue(checks.transient(error))
        for error in ('error: builder for /nix/store/test.drv failed with exit code 1',
                      'Reason: builder failed with exit code 1', 'hash mismatch',
                      "error: attribute 'package' missing", 'syntax error',
                      'HTTP error 401', 'HTTP error 403', 'HTTP error 404',
                      'Permission denied'):
            with self.subTest(error=error):
                self.assertFalse(checks.transient('warning: HTTP error 503\n' + error))
        self.assertFalse(checks.transient('unknown failure'))

    def invoke(self, failures, exit_status=1):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'command.py'
            script.write_text('''
import json, pathlib, sys
state = pathlib.Path(__file__).with_suffix('.json')
failures = json.loads(state.read_text())
if failures:
    message = failures.pop(0)
    state.write_text(json.dumps(failures))
    print(message)
    sys.exit(int(sys.argv[1]))
print('checks passed')
''')
            import json
            script.with_suffix('.json').write_text(json.dumps(failures))
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(checks.time, 'sleep') as sleep:
                result = checks.build([sys.executable, str(script), str(exit_status)])
            return result, output.getvalue(), sleep.call_args_list

    def test_transient_fetch_can_recover(self):
        result, output, sleeps = self.invoke(['error: HTTP error 504'])
        self.assertEqual(result, 0)
        self.assertIn('checks passed', output)
        self.assertEqual([call.args[0] for call in sleeps], [30])

    def test_retry_budget_is_bounded(self):
        result, output, sleeps = self.invoke(['error: HTTP error 503'] * 4)
        self.assertEqual(result, 1)
        self.assertEqual(output.count('error: HTTP error 503'), 3)
        self.assertEqual([call.args[0] for call in sleeps], [30, 60])

    def test_deterministic_failure_is_not_repeated(self):
        result, output, sleeps = self.invoke(['Reason: builder failed with exit code 1'])
        self.assertEqual(result, 1)
        self.assertNotIn('retrying', output)
        self.assertEqual(sleeps, [])

    def test_transport_warning_cannot_hide_signal_or_wrapper_failure(self):
        for status in (2, 126, 127, 128, 130, 137, 143, 255):
            with self.subTest(status=status):
                result, output, sleeps = self.invoke(['warning: HTTP error 503'], exit_status=status)
                self.assertEqual(result, status)
                self.assertNotIn('retrying', output)
                self.assertEqual(sleeps, [])
        for message in ('Killed', 'SIGKILL', 'SIGTERM', 'SIGINT', 'Out of memory', 'oom-killed', 'terminated by signal'):
            result, output, sleeps = self.invoke(['warning: HTTP error 503\n' + message])
            self.assertEqual(result, 1)
            self.assertNotIn('retrying', output)
            self.assertEqual(sleeps, [])


if __name__ == '__main__':
    unittest.main()
