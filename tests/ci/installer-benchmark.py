#!/usr/bin/env python3
"""Cohort matching, whole-job gates and failed-work conservation."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('installer_benchmark', ROOT / 'scripts/ci/installer-benchmark.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def plan():
    return {'schema': 1, 'repository': b.REPOSITORY, 'authorizesPublication': False,
        'createdAt': '2026-10-24T00:00:00+00:00', 'head': 'a' * 40,
        'runnerImage': '20261023.334.3', 'pairs': list(b.PAIRS),
        'profiles': {p: {'inputs': {'CANDIDATE_DIGEST': 'sha256:' + 'b' * 64,
            'PREVIOUS_DIGEST': 'sha256:' + 'c' * 64, 'BUILD_IDENTITY': 'v1:' + 'd' * 64,
            'SOURCE_REVISION': 'e' * 40}, 'runtimeCohorts': {'fresh': 'f' * 64, 'upgrade': 'f' * 64}}
            for p in b.PROFILES}}


def samples():
    return [{'runId': i + 1, 'profile': profile, 'pair': pair, 'mode': mode,
        'temperature': pair.split('-')[0], 'eligible': True, 'reasons': [],
        'knownRunnerSeconds': 400 if mode == 'default' else 350,
        'phases': [{'phase': phase, 'runnerSeconds': 180 if mode == 'default' else 150, 'toolCohort': {'python': 'pinned'},
                    'runtimeCohort': 'f' * 64, 'cacheKey': 'exact' if pair.startswith('warm') else None,
                    'qualificationContext': {'inputs': 'same', **({'installerCompression': {'type': 'zstd'}} if mode == 'zstd' else {})}}
                   for phase in ('fresh', 'upgrade')]}
        for i, (profile, pair, mode) in enumerate((p, pair, mode)
            for p in b.PROFILES for pair in b.PAIRS for mode in b.MODES)]


class Gates(unittest.TestCase):
    def test_all_predeclared_samples_required_and_never_authorize_publication(self):
        values = samples(); result = b.compare(plan(), values)
        self.assertTrue(result['performanceGatePassed'])
        self.assertFalse(result['adopted']); self.assertFalse(result['authorizesPublication'])
        self.assertEqual(result['knownRunnerSeconds'], sum(s['knownRunnerSeconds'] for s in values))
        for index in range(len(values)):
            self.assertFalse(b.compare(plan(), values[:index] + values[index + 1:])['performanceGatePassed'])

    def test_unknown_mismatch_and_failures_cannot_be_replaced(self):
        for mutation in ('cohort', 'cache', 'tools', 'unknown', 'failed', 'unassigned'):
            with self.subTest(mutation=mutation):
                values = samples(); arm = values[3]
                if mutation in ('cohort', 'cache', 'tools'):
                    key = {'cohort': 'runtimeCohort', 'cache': 'cacheKey', 'tools': 'toolCohort'}[mutation]
                    arm['phases'][0][key] = 'different'
                elif mutation == 'unassigned':
                    values.append({'runId': 99, 'knownRunnerSeconds': 80, 'eligible': False})
                else:
                    arm['eligible'] = False
                self.assertFalse(b.compare(plan(), values)['performanceGatePassed'])
        values = samples(); values.append({**values[0], 'runId': 99})
        with self.assertRaisesRegex(ValueError, 'replacement'): b.compare(plan(), values)
        with self.assertRaisesRegex(ValueError, 'twice'): b.compare(plan(), [*samples(), samples()[0]])

    def test_whole_job_and_per_phase_cold_regressions_and_both_warm_thresholds(self):
        for seconds in (371, 361):
            values = samples()
            for value in values:
                if value['mode'] == 'zstd': value['knownRunnerSeconds'] = seconds
            self.assertFalse(b.compare(plan(), values)['performanceGatePassed'])
        for field in ('workflow', 'phase'):
            values = samples()
            if field == 'workflow': values[1]['knownRunnerSeconds'] = 441
            else: values[1]['phases'][0]['runnerSeconds'] = 199
            self.assertFalse(b.compare(plan(), values)['performanceGatePassed'])

    def test_declared_runner_mismatch_stops_before_setup(self):
        value = {'schema': 1, 'planSha256': b.sha(plan()), 'pair': 'warm-1', 'temperature': 'warm',
            'runnerImage': plan()['runnerImage'], 'runtimeCohorts': plan()['profiles']['finite']['runtimeCohorts']}
        env = {'FINITE_VALIDATION_ONLY': 'true', 'FINITE_BENCHMARK_PHASE': 'fresh', 'ImageVersion': 'old'}
        with self.assertRaisesRegex(ValueError, 'Runner image'): b.controls.controls(json.dumps(value), env)
        env['ImageVersion'] = value['runnerImage']
        self.assertEqual(b.controls.controls(json.dumps(value), env), value)
        for key, replacement in [('schema', True), ('temperature', 'cold'), ('planSha256', None), ('runtimeCohorts', {}), ('pair', 'warm-6')]:
            altered = {**value, key: replacement}
            with self.subTest(key=key), self.assertRaises(ValueError): b.controls.controls(json.dumps(altered), env)
        with self.assertRaises(ValueError): b.controls.controls(json.dumps(value), {**env, 'FINITE_VALIDATION_ONLY': 'false'})

    def test_forged_native_origins_and_preexisting_runs_reject(self):
        native = {'id': 1, 'head_sha': plan()['head'], 'repository': {'full_name': b.REPOSITORY},
            'event': 'workflow_dispatch', 'head_branch': 'diagnostic',
            'path': '.github/workflows/benchmark-image-tools.yml', 'created_at': '2026-10-24T01:00:00Z'}
        for key, replacement in [('id', 2), ('head_sha', 'b' * 40), ('repository', {'full_name': 'other/repo'}),
                ('event', 'pull_request'), ('head_branch', 'main'), ('path', '.github/workflows/build.yml'),
                ('created_at', '2026-10-23T23:59:59Z')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                b.native_sample(1, plan(), lambda endpoint: {**native, key: replacement})

    def test_failed_and_retried_native_cost_is_retained_without_gate_eligibility(self):
        native = {'id': 1, 'head_sha': plan()['head'], 'repository': {'full_name': b.REPOSITORY},
            'event': 'workflow_dispatch', 'head_branch': 'diagnostic', 'run_attempt': 2,
            'status': 'completed', 'conclusion': 'failure',
            'path': '.github/workflows/benchmark-image-tools.yml', 'created_at': '2026-10-24T01:00:00Z'}
        cost = {'jobs': [{'jobId': 10, 'runnerSeconds': 125}, {'jobId': 20, 'runnerSeconds': None}]}
        with patch.object(b, 'observe', return_value=cost):
            value = b.native_sample(1, plan(), lambda endpoint: native)
        self.assertFalse(value['eligible']); self.assertEqual(value['knownRunnerSeconds'], 125)
        self.assertEqual(value['unknownDurationJobs'], [20])


class NativeReceipts(unittest.TestCase):
    def setUp(self):
        self.plan = plan(); self.native = {'id': 1}
        self.cost = {'jobs': [{'jobId': i, 'name': f'qualification / phase ({phase})',
            'conclusion': 'success', 'runnerSeconds': 100} for i, phase in enumerate(('fresh', 'upgrade'))]}
        core = {name: {'count': 2, 'sha256': 'a' * 64} for name in
                ('runtimeRpms','installerRpms','repositoryMetadata','repositoryConfiguration')}
        runtime = {**core, 'schema': 1, 'authorizesPublication': False,
            'cohortSha256': b.sha(core), 'compression': {'type': 'xz', 'args': ['-Xbcj', 'x86']}}
        self.plan['profiles']['finite']['runtimeCohorts'] = dict.fromkeys(('fresh','upgrade'), b.sha(core))
        entry = self.plan['profiles']['finite']; inputs = entry['inputs']
        value = {'schema': 1, 'planSha256': b.sha(self.plan), 'pair': 'warm-1', 'temperature': 'warm',
            'runnerImage': self.plan['runnerImage'], 'runtimeCohorts': entry['runtimeCohorts']}
        self.docs, self.hashes = {}, {}
        self.prefix = 'qualification-diagnostic-finite-1-1/'
        context = {'schema': 2, 'packages': 'pinned'}
        iso = {'sizeBytes': 400, 'installer': {'runtimeProvenance': runtime}}
        accepted = {'schema': 2, 'revision': self.plan['head'], 'profile': 'finite',
            'sourceRevision': inputs['SOURCE_REVISION'], 'buildIdentity': inputs['BUILD_IDENTITY'],
            'candidate': 'ghcr.io/closure-labs/finite@' + inputs['CANDIDATE_DIGEST'],
            'previousDigest': inputs['PREVIOUS_DIGEST'], 'accepted': True, 'secureBoot': True,
            'encryptedRoot': True, 'validationOnly': True, 'bootstrap': False,
            'qualificationContext': context, 'qualificationContextSha256': b.sha(context),
            'qualifiedIso': iso, 'vmSecurityEvidence': {'sha256': 'd' * 64}}
        self.docs[self.prefix + 'finite-acceptance.json'] = accepted
        self.docs[self.prefix + 'finite-desktop-acceptance.json'] = {'desktop': 'fixture'}
        self.hashes[self.prefix + 'finite-desktop-acceptance.json'] = 'd' * 64
        for phase in ('fresh', 'upgrade'):
            prefix = f'qualification-diagnostic-phase-finite-{phase}-1-1/'
            self.docs[prefix + f'finite-{phase}-benchmark.json'] = {'schema': 1,
                'authorizesPublication': False, 'repository': b.REPOSITORY, 'revision': self.plan['head'],
                'runId': 1, 'runAttempt': 1, 'profile': 'finite', 'phase': phase, 'inputs': inputs,
                'mode': 'default', 'controls': value}
            self.docs[prefix + f'vm-{phase}/acceptance.json'] = {
                'source': 'ghcr.io/closure-labs/finite@' + inputs['CANDIDATE_DIGEST' if phase == 'fresh' else 'PREVIOUS_DIGEST'],
                'target': accepted['candidate'], 'profile': 'finite', 'accepted': True, 'secureBoot': True,
                'encryptedRoot': True, 'validationOnly': True, 'qualificationContext': context,
                'qualificationContextSha256': b.sha(context), 'iso': copy.deepcopy(iso)}
            self.docs[prefix + f'finite-{phase}-stages.jsonl'] = [{'schema': 1, 'authorizesPublication': False,
                'repository': b.REPOSITORY, 'revision': self.plan['head'], 'runId': 1, 'runAttempt': 1,
                'profile': 'finite', 'phase': phase, 'candidateDigest': inputs['CANDIDATE_DIGEST'],
                'sourceRevision': inputs['SOURCE_REVISION'], 'buildIdentity': inputs['BUILD_IDENTITY'],
                'runner': {'ImageVersion': self.plan['runnerImage']}, 'status': 0,
                'toolCohort': {'tools': 'pinned'}, 'stage': stage} for stage in
                ('installer-prepare', 'image-acquisition', 'iso-build', 'vm-acceptance')]
            self.docs[prefix + 'nix-setup.json'] = {'schema': 1, 'kind': 'finite-nix-observation', 'runId': 1, 'runAttempt': 1,
                'repository': b.REPOSITORY, 'revision': self.plan['head'], 'authorizesPublication': False,
                'status': 'success', 'cache': {'STORE_HIT': 'true', 'STORE_KEY': 'exact'}}

    def verify(self):
        with patch.object(b.desktop, 'validate') as validate:
            value = b.verify_documents(self.plan, self.native, self.cost, self.docs, self.hashes)
            validate.assert_called_once()
            return value

    def test_complete_receipts_pass_but_unknown_and_missed_cache_hits_do_not(self):
        self.assertTrue(self.verify()['eligible'])
        setup = self.docs['qualification-diagnostic-phase-finite-fresh-1-1/nix-setup.json']
        for hit in (None, 'false', ''):
            setup['cache']['STORE_HIT'] = hit
            self.assertFalse(self.verify()['eligible'])

    def test_altered_products_control_origins_and_desktop_hashes_fail_closed(self):
        accepted = self.docs[self.prefix + 'finite-acceptance.json']
        accepted['candidate'] = 'ghcr.io/closure-labs/finite@sha256:' + '9' * 64
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        control = self.docs['qualification-diagnostic-phase-finite-fresh-1-1/finite-fresh-benchmark.json']
        control['runId'] = 2
        with self.assertRaises(ValueError): self.verify()
        self.setUp(); self.hashes[self.prefix + 'finite-desktop-acceptance.json'] = 'bad'
        with self.assertRaises(ValueError): self.verify()

    def test_partial_stages_and_mismatched_runner_remain_ineligible(self):
        key = 'qualification-diagnostic-phase-finite-fresh-1-1/finite-fresh-stages.jsonl'
        self.docs[key].pop()
        self.assertFalse(self.verify()['eligible'])
        self.setUp(); self.docs[key][0]['runner']['ImageVersion'] = 'other'
        self.assertFalse(self.verify()['eligible'])


if __name__ == '__main__':
    unittest.main()
