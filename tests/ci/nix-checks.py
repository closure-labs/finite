#!/usr/bin/env python3
"""Exercise recovery from fetch failures and prompt failure for broken checks."""
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import subprocess
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('nix_checks', ROOT / 'scripts/ci/nix-checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
import nix_observation as observation
import source_proof as proof
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

    def phases(self, evaluation=(), builds=(), result=DRV, source_env=None):
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
                   'GITHUB_JOB': 'fixture', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                   'RUNNER_TEMP': directory, 'GITHUB_STEP_SUMMARY': str(summary)}
            env.update(source_env or {})
            with contextlib.chdir(root), patch.dict(os.environ, env, clear=True), patch.object(checks.time, 'sleep'), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    status = checks.run_checks(env)
                except ValueError:
                    status = 'invalid'
            path = root / '.bluebuild/nix-checks.json'
            self.receipt = json.loads(path.read_text()) if path.exists() else None
            path = root / '.bluebuild/source-reuse.json'
            self.reuse_receipt = json.loads(path.read_text()) if path.exists() else None
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

    def test_enabled_reuse_records_its_own_receipt_without_executed_phases(self):
        record = {'mode': 'enabled', 'hit': True, 'eligible': True, 'reason': 'verified-exact-queue-proof',
                  'producer': {'aggregateDerivation': DRV}, 'shadowMatch': None}
        with patch.object(proof, 'prepare', return_value=(None, record)):
            status, calls, _ = self.phases()
        self.assertEqual(status, 0)
        self.assertEqual(calls, [])
        self.assertIsNone(self.receipt)
        self.assertTrue(self.reuse_receipt['hit'])

    def test_shadow_matches_and_mismatches_still_execute_the_full_aggregate(self):
        for expected in (DRV, DRV.replace('a' * 32, 'b' * 32)):
            record = {'mode': 'shadow', 'hit': False, 'eligible': True, 'reason': 'verified-exact-queue-proof',
                      'producer': {'aggregateDerivation': expected}, 'shadowMatch': None}
            with self.subTest(expected=expected), patch.object(proof, 'prepare', return_value=(None, record)):
                status, calls, _ = self.phases()
            self.assertEqual(status, 0)
            self.assertEqual([call['phase'] for call in calls], ['evaluation', 'builds'])
            self.assertEqual(self.reuse_receipt['shadowMatch'], expected == DRV)

    def test_failed_lookup_falls_back_to_full_checks_without_inventing_a_miss(self):
        record = {'mode': 'enabled', 'hit': None, 'eligible': None, 'reason': 'lookup-timeout',
                  'producer': None, 'shadowMatch': None}
        with patch.object(proof, 'prepare', return_value=(None, record)):
            status, calls, _ = self.phases()
        self.assertEqual(status, 0)
        self.assertEqual([call['phase'] for call in calls], ['evaluation', 'builds'])
        self.assertIsNone(self.reuse_receipt['hit'])

    def test_evaluation_transport_retry_discards_partial_output(self):
        status, calls, _ = self.phases(evaluation=['HTTP error 503'])
        self.assertEqual(status, 0)
        self.assertEqual([c['phase'] for c in calls], ['evaluation', 'evaluation', 'builds'])

    def test_real_children_record_attempt_cpu_and_io_without_claiming_daemon_or_rss(self):
        status, _, _ = self.phases(builds=['HTTP error 503'])
        self.assertEqual(status, 0)
        for phase in self.receipt['phases']:
            for attempt in phase['attempts']:
                usage = attempt['childResourceUsage']
                self.assertEqual(usage['scope'], 'terminated-and-waited-children')
                self.assertFalse(usage['includesDaemonWork'])
                self.assertGreater(usage['userCpuSeconds'] + usage['systemCpuSeconds'], 0)
                self.assertIs(type(usage['blockInputOperations']), int)
                self.assertGreaterEqual(usage['blockInputOperations'], 0)
                self.assertGreaterEqual(usage['blockOutputOperations'], 0)
                self.assertEqual(set(usage), {'scope', 'includesDaemonWork', 'userCpuSeconds', 'systemCpuSeconds',
                                             'blockInputOperations', 'blockOutputOperations'})

    def test_attempt_counters_subtract_prior_commands_and_do_not_include_retry_sleep(self):
        samples = [(10., 2., 100, 200), (12., 3., 103, 207),
                   (12., 3., 103, 207), (15., 4., 105, 211),
                   (15., 4., 105, 211), (16., 6., 108, 212)]
        with patch.object(checks, 'child_usage', side_effect=samples):
            status, _, _ = self.phases(evaluation=['HTTP error 503'])
        self.assertEqual(status, 0)
        attempts = [a['childResourceUsage'] for phase in self.receipt['phases'] for a in phase['attempts']]
        self.assertEqual([a['userCpuSeconds'] for a in attempts], [2., 3., 1.])
        self.assertEqual([a['systemCpuSeconds'] for a in attempts], [1., 1., 2.])
        self.assertEqual([a['blockInputOperations'] for a in attempts], [3, 2, 3])
        self.assertEqual([a['blockOutputOperations'] for a in attempts], [7, 4, 1])
        self.assertEqual([a['status'] for a in self.receipt['phases'][0]['attempts']], [1, 0])

    def test_unavailable_usage_stays_unknown_and_preserves_failure(self):
        with patch.object(checks.resource, 'getrusage', side_effect=OSError('unavailable')):
            status, _, _ = self.phases(evaluation=['hash mismatch'])
        self.assertEqual(status, 1)
        self.assertEqual(self.receipt['phases'][0]['outcome'], 'failure')
        self.assertIsNone(self.receipt['phases'][0]['attempts'][0]['childResourceUsage'])
        self.assertIsNone(checks.usage_delta(None, (1., 2., 3, 4)))
        self.assertIsNone(checks.usage_delta((1., 2., 3, 4), None))
        self.assertIsNone(checks.usage_delta((1., 2., 3, 4), (0., 2., 3, 4)))

    def test_unlaunched_command_keeps_unknown_usage_and_original_error(self):
        attempts = []
        with patch.object(checks.subprocess, 'Popen', side_effect=FileNotFoundError('missing')):
            with self.assertRaises(FileNotFoundError):
                checks.build(['missing'], observations=attempts)
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[0]['status'])
        self.assertIsNone(attempts[0]['childResourceUsage'])

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


class SourceProof(unittest.TestCase):
    def setUp(self):
        self.head = 'c' * 40
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_JOB': 'checks', 'GITHUB_EVENT_NAME': 'push',
                    'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': self.head, 'GITHUB_RUN_ID': '400',
                    'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_REPOSITORY': proof.REPOSITORY,
                    'GITHUB_REPOSITORY_ID': '10', 'FINITE_SOURCE_PROOF_REUSE': 'enabled'}
        cohort = {'sourceRevision': self.head, 'nixExecutable': '/nix/store/' + 'b' * 32 + '-determinate-nix/bin/nix',
                  'nixVersion': 'Determinate Nix 3.23.2', 'pythonVersion': '3.12.3', 'pythonExecutable': '/usr/bin/python3.12',
                  'lockSha256': {name: 'a' * 64 for name in ('flake.lock', 'devenv.lock')},
                  'settingsSha256': {name: 'b' * 64 for name in proof.SETTINGS}, 'publicOptionsSha256': 'e' * 64,
                  'platform': {'os': 'Linux', 'arch': 'X64', 'label': 'ubuntu-24.04'}}
        self.config = {'schema': 1, 'cohort': cohort, 'fingerprint': proof.digest(cohort)}
        repo = {'id': 10, 'full_name': proof.REPOSITORY}
        self.producer = {'id': 300, 'run_attempt': 1, 'path': proof.WORKFLOW, 'event': 'merge_group',
            'head_branch': 'gh-readonly-queue/main/pr-7-' + 'd' * 40, 'head_sha': self.head,
            'repository': copy.deepcopy(repo), 'head_repository': copy.deepcopy(repo),
            'status': 'completed', 'conclusion': 'success', 'updated_at': '2026-10-25T12:04:00Z'}
        self.consumer = {**copy.deepcopy(self.producer), 'id': 400, 'run_attempt': 2, 'head_branch': 'main',
                         'event': 'push', 'status': 'in_progress', 'conclusion': None, 'created_at': '2026-10-25T12:05:00Z'}
        self.job = {'id': 22, 'run_id': 300, 'run_attempt': 1, 'head_sha': self.head,
                    'name': 'Nix and runtime contracts', 'status': 'completed', 'conclusion': 'success',
                    'labels': ['ubuntu-24.04'], 'started_at': '2026-10-25T12:00:00Z',
                    'completed_at': '2026-10-25T12:03:00Z'}
        self.value = {'schema': 1, 'kind': 'finite-nix-observation', 'authorizesPublication': False,
            'repository': proof.REPOSITORY, 'revision': self.head, 'checkoutRevision': self.head,
            'runId': '300', 'runAttempt': '1', 'jobName': 'checks', 'aggregateDerivation': DRV,
            'workflowRef': proof.REPOSITORY + '/' + proof.WORKFLOW + '@refs/heads/' + self.producer['head_branch'],
            'reuseProof': copy.deepcopy(self.config), 'phases': [
                {'stage': stage, 'status': 0, 'outcome': 'success', 'startedAt': start, 'seconds': seconds,
                 'attempts': [{'attempt': 1, 'status': 0, 'seconds': seconds}]}
                for stage, start, seconds in [('Evaluate aggregate', '2026-10-25T12:00:01Z', 100),
                                              ('Build aggregate', '2026-10-25T12:01:42Z', 50)]]}
        self.artifact = {'id': 99, 'name': 'source-checks-300-1', 'expired': False,
                         'workflow_run': {'id': 300, 'head_sha': self.head, 'repository_id': 10, 'head_repository_id': 10}}
        self.now = datetime(2026, 10, 25, 12, 10, tzinfo=timezone.utc)
        self.calls = []
        self.refresh_archive()

    def refresh_archive(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as zipped:
            zipped.writestr('nix-checks.json', json.dumps(self.value))
            zipped.writestr('nix-setup.json', '{}')
        self.raw = raw.getvalue()
        self.artifact.update(size_in_bytes=len(self.raw), digest='sha256:' + hashlib.sha256(self.raw).hexdigest())

    @contextlib.contextmanager
    def reader(self, artifact):
        raw = io.BytesIO(self.raw)
        proof.authenticate(raw, artifact)
        yield raw

    def api(self, endpoint):
        self.calls.append(endpoint)
        if endpoint.endswith('/actions/runs/400'):
            return copy.deepcopy(self.consumer)
        if '/workflows/build.yml/runs?' in endpoint:
            return {'total_count': 1, 'workflow_runs': [copy.deepcopy(self.producer)]}
        if '/attempts/1/jobs?' in endpoint:
            return {'total_count': 1, 'jobs': [copy.deepcopy(self.job)]}
        if '/actions/runs/300/artifacts?' in endpoint:
            return {'total_count': 1, 'artifacts': [copy.deepcopy(self.artifact)]}
        raise AssertionError('Unexpected lookup: ' + endpoint)

    def lookup(self):
        return proof.lookup(self.env, self.config, self.api, self.reader, self.now)

    def test_exact_native_queue_proof_is_eligible(self):
        value = self.lookup()
        self.assertTrue(value['eligible'])
        self.assertEqual(value['producer']['jobId'], 22)
        self.assertEqual(value['producer']['artifactDigest'], self.artifact['digest'])
        self.assertEqual(len(self.calls), 4)

    def test_forged_mismatched_failed_or_reused_native_producers_reject(self):
        changes = [('producer', 'event', 'pull_request'), ('producer', 'head_sha', 'f' * 40),
                   ('producer', 'conclusion', 'failure'), ('producer', 'status', 'in_progress'),
                   ('producer', 'head_branch', 'feature'), ('producer', 'head_repository', {'id': 11, 'full_name': 'fork/repo'}),
                   ('job', 'conclusion', 'failure'), ('job', 'run_attempt', 2), ('job', 'head_sha', 'f' * 40),
                   ('job', 'labels', []), ('consumer', 'event', 'workflow_dispatch'),
                   ('consumer', 'head_branch', 'feature')]
        for name, key, value in changes:
            original = copy.deepcopy(getattr(self, name))
            getattr(self, name)[key] = value
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                self.lookup()
            setattr(self, name, original)

    def test_expired_oversized_wrong_origin_or_altered_archive_rejects(self):
        changes = [{'expired': True}, {'size_in_bytes': proof.LIMIT + 1}, {'digest': None},
                   {'workflow_run': {'id': 301, 'head_sha': self.head, 'repository_id': 10, 'head_repository_id': 10}}]
        for change in changes:
            original = copy.deepcopy(self.artifact)
            self.artifact.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.lookup()
            self.artifact = original
        self.raw += b'tampered'
        with self.assertRaises(ValueError):
            self.lookup()

    def test_incomplete_or_legacy_receipt_never_authorizes_reuse(self):
        changes = [('runAttempt', '2'), ('revision', 'f' * 40), ('checkoutRevision', 'f' * 40),
                   ('authorizesPublication', True), ('authorizesPublication', 0),
                   ('schema', True), ('reuseProof', None), ('phases', [])]
        for key, value in changes:
            original = copy.deepcopy(self.value)
            self.value[key] = value
            self.refresh_archive()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.lookup()
            self.value = original
        self.value['phases'][0]['attempts'] = []
        self.refresh_archive()
        with self.assertRaises(ValueError):
            self.lookup()

    def test_configuration_mismatch_is_known_ineligible(self):
        self.value['reuseProof']['cohort']['pythonVersion'] = '3.12.4'
        self.value['reuseProof']['fingerprint'] = proof.digest(self.value['reuseProof']['cohort'])
        self.refresh_archive()
        self.assertEqual(self.lookup(), {'eligible': False, 'reason': 'configuration-mismatch'})

    def test_future_expired_and_out_of_job_phases_reject(self):
        for value in ('2026-10-25T12:06:00Z', '2026-10-24T11:00:00Z'):
            self.producer['updated_at'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.lookup()
        self.producer['updated_at'] = '2026-10-25T12:04:00Z'
        self.value['phases'][1]['seconds'] = 1000
        self.refresh_archive()
        with self.assertRaises(ValueError):
            self.lookup()

    def test_missing_and_truncated_inventory_preserve_distinct_reasons(self):
        def api(endpoint):
            if '/workflows/build.yml/runs?' in endpoint:
                return {'total_count': 0, 'workflow_runs': []}
            return self.api(endpoint)
        self.assertEqual(proof.lookup(self.env, self.config, api, self.reader, self.now),
                         {'eligible': False, 'reason': 'no-exact-queue-proof'})
        def truncated(endpoint):
            if '/workflows/build.yml/runs?' in endpoint:
                return {'total_count': 6, 'workflow_runs': [self.producer]}
            return self.api(endpoint)
        with self.assertRaises(ValueError):
            proof.lookup(self.env, self.config, truncated, self.reader, self.now)

    def test_disabled_manual_and_schedule_paths_never_lookup(self):
        with patch.object(proof, 'helper', side_effect=AssertionError('Unexpected source lookup')):
            config, result = proof.prepare({**self.env, 'FINITE_SOURCE_PROOF_REUSE': 'off'})
            self.assertIsNone(config)
            self.assertIsNone(result['eligible'])
            self.assertIsNone(result['hit'])
            for event in ('pull_request', 'schedule', 'workflow_dispatch'):
                self.assertEqual(proof.prepare({**self.env, 'GITHUB_EVENT_NAME': event}), (None, None))

    def test_enabled_shadow_and_failed_lookups_have_honest_receipts(self):
        result = {**self.lookup(), 'configuration': self.config}
        for mode in ('enabled', 'shadow'):
            with patch.object(proof, 'helper', return_value=result):
                _, receipt = proof.prepare({**self.env, 'FINITE_SOURCE_PROOF_REUSE': mode})
            self.assertEqual(receipt['hit'], mode == 'enabled')
            self.assertTrue(receipt['eligible'])
            self.assertFalse(receipt['authorizesPublication'])
        for failure in ({'eligible': None, 'reason': 'lookup-timeout'}, {'eligible': 'yes'},
                        {**result, 'configuration': None}):
            with patch.object(proof, 'helper', return_value=failure):
                _, receipt = proof.prepare(self.env)
            self.assertIsNone(receipt['eligible'])
            self.assertIsNone(receipt['hit'])

    def test_timeout_kills_the_entire_lookup_process_group(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.pid = 4321
        process.wait.side_effect = [subprocess.TimeoutExpired('lookup', 15), 0]
        with patch.object(proof.subprocess, 'Popen', return_value=process) as popen, \
                patch.object(proof.os, 'killpg') as kill:
            self.assertEqual(proof.helper('--lookup', self.env)['reason'], 'lookup-timeout')
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        kill.assert_called_once_with(4321, proof.signal.SIGKILL)
        self.assertEqual(process.wait.call_count, 2)

    def test_partial_lookup_and_clock_failure_preserve_unknown_measurements(self):
        result = {'eligible': None, 'reason': 'lookup-timeout', 'producer': {'unverified': True}}
        with patch.object(proof, 'helper', return_value=result), \
                patch.object(proof.time, 'monotonic', side_effect=[10, 9]):
            _, receipt = proof.prepare(self.env)
        self.assertIsNone(receipt['hit'])
        self.assertIsNone(receipt['producer'])
        self.assertIsNone(receipt['seconds'])

    def test_configuration_hashes_only_selected_settings_and_clean_locked_inputs(self):
        settings = {key: {'value': 'fixture'} for key in proof.SETTINGS}
        settings['access-tokens'] = {'value': 'fixture-secret-token'}
        settings['substituters'] = {'value': ['https://fixture-password@cache.invalid']}
        env = {**self.env, 'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64'}
        def metadata(command, **kwargs):
            if command == ['nix', '--version']:
                return 'nix (Determinate Nix 3.23.2) 2.35.2'
            if command == ['git', 'rev-parse', 'HEAD']:
                return self.head
            if command == ['git', 'status', '--porcelain', '--untracked-files=no']:
                return ''
            raise AssertionError(command)
        def config(command, **kwargs):
            self.assertEqual(command, ['nix', 'config', 'show', '--json'])
            kwargs['stdout'].write(json.dumps(settings).encode())
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory), \
                patch.object(proof.subprocess, 'check_output', side_effect=metadata), \
                patch.object(proof.subprocess, 'run', side_effect=config), \
                patch.object(observation.shutil, 'which', return_value='/nix/store/' + 'b' * 32 + '-determinate-nix/bin/nix'):
            for name in ('flake.lock', 'devenv.lock'):
                Path(name).write_text('{}')
            current = proof.configuration(env)
            self.assertTrue(proof.valid_configuration(current, self.head))
            encoded = json.dumps(current)
            self.assertNotIn('fixture-secret-token', encoded)
            self.assertNotIn('fixture-password', encoded)
            settings['access-tokens']['value'] = 'different-secret'
            self.assertEqual(proof.configuration(env), current)
            self.assertEqual(proof.configuration({**env, 'GH_TOKEN': 'fixture-read-token'}), current)
            self.assertEqual(proof.configuration({**env, 'FINITE_SOURCE_PROOF_REUSE': 'shadow'}), current)
            self.assertNotEqual(proof.configuration({**env, 'FINITE_OPTIMIZED_CACHES': 'true'}), current)
            Path('flake.lock').write_text('{"changed":true}')
            self.assertNotEqual(proof.configuration(env), current)
            del settings['sandbox']
            with self.assertRaises(ValueError):
                proof.configuration(env)

    def test_helper_errors_never_print_config_or_exception_secrets(self):
        output = io.StringIO()
        with patch.object(proof, 'configuration', side_effect=ValueError('fixture-private-token')), \
                contextlib.redirect_stdout(output):
            proof.main()
        self.assertNotIn('fixture-private-token', output.getvalue())
        self.assertIsNone(json.loads(output.getvalue())['eligible'])

    def test_lookup_without_credentials_is_unknown_without_metadata_or_network(self):
        for tokens in ({}, {'GH_TOKEN': '', 'GITHUB_TOKEN': ' '}):
            output = io.StringIO()
            with patch.dict(proof.os.environ, tokens, clear=True), \
                    patch.object(proof.sys, 'argv', ['source_proof.py', '--lookup']), \
                    patch.object(proof, 'configuration') as config, \
                    patch.object(proof, 'lookup') as lookup, contextlib.redirect_stdout(output):
                proof.main()
            self.assertEqual(json.loads(output.getvalue()),
                             {'eligible': None, 'reason': 'lookup-auth-unavailable'})
            config.assert_not_called()
            lookup.assert_not_called()

    def test_native_token_names_reach_lookup_without_becoming_receipt_data(self):
        for key in ('GH_TOKEN', 'GITHUB_TOKEN'):
            output = io.StringIO()
            with patch.dict(proof.os.environ, {key: 'fixture-private-token'}, clear=True), \
                    patch.object(proof.sys, 'argv', ['source_proof.py', '--lookup']), \
                    patch.object(proof, 'configuration', return_value=self.config), \
                    patch.object(proof, 'lookup', return_value={'eligible': False, 'reason': 'no-exact-queue-proof'}) as lookup, \
                    contextlib.redirect_stdout(output):
                proof.main()
            lookup.assert_called_once()
            self.assertEqual(json.loads(output.getvalue())['configuration'], self.config)
            self.assertNotIn('fixture-private-token', output.getvalue())

    def test_queue_configuration_capture_does_not_require_lookup_credentials(self):
        output = io.StringIO()
        with patch.dict(proof.os.environ, {}, clear=True), \
                patch.object(proof.sys, 'argv', ['source_proof.py', '--configuration']), \
                patch.object(proof, 'configuration', return_value=self.config), \
                patch.object(proof, 'lookup') as lookup, contextlib.redirect_stdout(output):
            proof.main()
        self.assertEqual(json.loads(output.getvalue()), {'configuration': self.config})
        lookup.assert_not_called()

    def test_interrupted_transfer_and_missing_receipt_never_produce_a_proof(self):
        @contextlib.contextmanager
        def interrupted(artifact):
            raise subprocess.TimeoutExpired('download', 10)
            yield
        with self.assertRaises(subprocess.TimeoutExpired):
            proof.lookup(self.env, self.config, self.api, interrupted, self.now)
        def missing(endpoint):
            if '/artifacts?' in endpoint:
                return {'total_count': 0, 'artifacts': []}
            return self.api(endpoint)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            proof.lookup(self.env, self.config, missing, self.reader, self.now)


if __name__ == '__main__':
    unittest.main()
