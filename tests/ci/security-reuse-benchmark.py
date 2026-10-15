#!/usr/bin/env python3
"""Mock scanner/DB work; verify benchmark isolation and fail-closed receipts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('benchmark_security', ROOT / 'scripts/ci/benchmark-security-reuse.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
PROFILE = 'bluefin-next'
REVISION = 'b' * 40
STAMP = '2026-10-14T12:00:00Z'
DB = {'valid': True, 'built': STAMP, 'schemaVersion': '6.0.3'}
KEY = 'grype-security-benchmark-v1-Linux-X64-' + 'c' * 64 + '-100-1'
BINDING = {'image': IMAGE, 'profile': PROFILE, 'originRun': 50, 'originAttempt': 1,
           'originRevision': REVISION, 'buildIdentity': 'v1:' + 'd' * 64,
           'nativeBuildJob': 1, 'nativeSecurityJob': 2, 'nativeSecurityArtifact': 3,
           'nativeSecurityArtifactSha256': 'sha256:' + 'e' * 64, 'signatureVerified': True}
INFO = {'revision': REVISION, 'runId': '100', 'attempt': '1', 'lockSha256': 'f' * 64,
        'policySha256': '1' * 64, 'runner': {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageVersion': 'fixture'},
        'platform': 'linux/amd64', 'tools': {'grype': 'grype 0.120.1'}, 'nixVersion': 'Nix fixture'}


def environment():
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': benchmark.REPOSITORY,
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': benchmark.WORKFLOW, 'GITHUB_SHA': REVISION,
            'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1', 'BENCHMARK_DB_KEY': KEY}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class Boundaries(unittest.TestCase):
    def test_main_manual_exact_workflow_and_no_write_credentials(self):
        benchmark.hosted(environment())
        changes = [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_EVENT_NAME', 'schedule'),
                   ('GITHUB_REPOSITORY', 'fork/finite'), ('GITHUB_REF', 'refs/heads/topic'),
                   ('GITHUB_WORKFLOW_REF', benchmark.WORKFLOW.replace('main', 'topic')),
                   ('GITHUB_SHA', 'invalid')]
        changes += [(key, 'fake-do-not-print') for key in benchmark.SECRET_NAMES]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                benchmark.hosted({**environment(), key: value})

    def test_inputs_require_immutable_profile_and_explicit_origin(self):
        benchmark.inputs(IMAGE, PROFILE, '50')
        for values in [('ghcr.io/closure-labs/finite:finite-next', PROFILE, '50'),
                       (IMAGE, 'unknown', '50'), (IMAGE, PROFILE, '0'), (IMAGE, PROFILE, '50;echo bad')]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                benchmark.inputs(*values)

    def test_origin_success_required_before_artifact_or_signature_use(self):
        api = Mock(return_value={'status': 'completed', 'conclusion': 'failure'})
        fetch = SimpleNamespace(publication=SimpleNamespace(github=api))
        with patch.dict(os.environ, environment(), clear=True), patch.object(benchmark, 'load_reuse', return_value=fetch), \
             patch.object(benchmark.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'overall successful'):
            benchmark.authenticate(IMAGE, PROFILE, '50')
        self.assertEqual(api.call_count, 1)
        run.assert_not_called()

    def test_authenticated_native_origin_and_public_key_verification(self):
        run_info = {'status': 'completed', 'conclusion': 'success', 'run_attempt': 1, 'head_sha': REVISION}
        record = {'profile': PROFILE, 'publish': True, 'qualificationMode': 'enforce',
                  'sourceRevision': REVISION, 'buildIdentity': BINDING['buildIdentity']}
        files = {PROFILE + '-publication.json': json.dumps(record).encode(), PROFILE + '-image-ref.txt': IMAGE.encode()}
        fetch = SimpleNamespace(
            publication=SimpleNamespace(github=Mock(side_effect=[run_info, [{'artifacts': []}], [{'jobs': []}]]),
                                        origin_files=Mock(return_value=files)),
            reuse=SimpleNamespace(metadata=Mock(return_value=({'id': 3, 'digest': BINDING['nativeSecurityArtifactSha256']}, {}, 1, 2))))
        with patch.dict(os.environ, environment(), clear=True), patch.object(benchmark, 'load_reuse', return_value=fetch), \
             patch.object(benchmark.subprocess, 'run') as command:
            result = benchmark.authenticate(IMAGE, PROFILE, '50')
        self.assertEqual(result, BINDING)
        self.assertEqual(command.call_args.args[0][:4], ['cosign', 'verify', '--new-bundle-format=false', '--key'])
        self.assertEqual(command.call_args.args[0][-1], IMAGE)

    def test_db_key_is_one_attempt_and_startup_schema_is_required(self):
        with patch.dict(os.environ, environment(), clear=True):
            self.assertEqual(benchmark.db_key(), KEY)
            with patch.dict(os.environ, {'BENCHMARK_DB_KEY': KEY.replace('-100-1', '-99-1')}), self.assertRaises(ValueError):
                benchmark.db_key()
        for state in [DB, {**DB, 'schemaVersion': 6}, {**DB, 'schemaVersion': 'v6.1.10'},
                      {**DB, 'valid': False}, {**DB, 'schemaVersion': None}]:
            with patch.object(benchmark.subprocess, 'check_output', return_value=json.dumps(state)):
                if state['valid'] and state['schemaVersion']:
                    self.assertEqual(benchmark.database_status(), state)
                else:
                    with self.assertRaises(ValueError): benchmark.database_status()

    def test_context_uses_cosign_version_json_and_fails_closed_on_version_errors(self):
        calls = []
        def version(command, **_):
            calls.append(command)
            if command[0] == 'git': return REVISION
            if command == ['cosign', '--version']:
                raise AssertionError('Cosign does not support the generic version flag')
            return 'fixture version'
        with patch.dict(os.environ, environment(), clear=True), patch.object(benchmark, 'sha', return_value='a'*64), \
             patch.object(benchmark.subprocess, 'check_output', side_effect=version):
            benchmark.context()
        self.assertIn(['cosign', 'version', '--json'], calls)
        for command in (['grype', '--version'], ['syft', '--version'], ['umoci', '--version'],
                        ['skopeo', '--version'], ['python3', '--version']):
            self.assertIn(command, calls)
        def failed(command, **kwargs):
            if command[0] == 'cosign': raise subprocess.CalledProcessError(1, command)
            return version(command, **kwargs)
        with patch.dict(os.environ, environment(), clear=True), patch.object(benchmark, 'sha', return_value='a'*64), \
             patch.object(benchmark.subprocess, 'check_output', side_effect=failed), self.assertRaises(subprocess.CalledProcessError):
            benchmark.context()

    def test_transport_rejects_links_and_missing_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError): benchmark.transport(root)
            (root / 'linked').symlink_to(root / 'elsewhere')
            with self.assertRaises(ValueError): benchmark.transport(root)


class Reader(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / '.bluebuild/security-benchmark-db'
        self.seed = self.root / 'seed.json'
        self.start = self.root / 'start.json'
        self.output = self.root / 'benchmark.json'
        save(self.start, {'monotonicSeconds': 0})
        self.env = {**environment(), 'GRYPE_DB_CACHE_DIR': str(self.db), 'RESTORED_DB_KEY': KEY}

    def prepare_db(self):
        self.db.mkdir(parents=True)
        (self.db / 'database.sqlite').write_bytes(b'fixture-only')
        save(self.seed, {'schema': 1, 'kind': 'db-seed', 'status': 'success', **INFO, 'binding': BINDING,
                         'cacheKey': KEY, 'database': DB, 'transport': benchmark.transport(self.db)})

    def invoke(self, lane, inventory_miss=False, phase_failure=False):
        def scan(command, **kwargs):
            self.child = kwargs['env']
            self.assertEqual(command[:2], ['bash', 'scripts/bluebuild/security-run.sh'])
            evidence = self.root / '.bluebuild/security-benchmark-scan'
            phases = [{'phase': p, 'seconds': 1, 'success': not phase_failure}
                      for p in ('database-update', 'database-coverage', 'vulnerability-scan', 'policy-evaluation')]
            save(evidence / 'phase-timings.json', {'inventoryReused': lane == 'inventory-only' and not inventory_miss, 'phases': phases})
            save(evidence / 'security-result.json', {'status': 'pass', 'image': IMAGE,
                'policySha256': INFO['policySha256'], 'scanner': '0.120.1', 'scannedAt': STAMP,
                'database': {'status': DB, 'providers': {'fedora': {'captured': STAMP}}}})
            save(evidence / 'inventory-provenance.json', {'image': IMAGE, 'generation': {'fixture': 'generation'},
                                                        'platformDigest': 'sha256:' + 'a' * 64})
            save(evidence / 'inventory-origin.json', {'originRun': 50, 'image': IMAGE})
            return subprocess.CompletedProcess(command, 0)
        with patch.dict(os.environ, self.env, clear=True), patch.object(benchmark, 'ROOT', self.root), \
             patch.object(benchmark, 'context', return_value=copy.deepcopy(INFO)), \
             patch.object(benchmark, 'authenticate', return_value=copy.deepcopy(BINDING)), \
             patch.object(benchmark, 'database_status', return_value=copy.deepcopy(DB)), \
             patch.object(benchmark.subprocess, 'run', side_effect=scan) as call:
            benchmark.scan(lane, 1, IMAGE, PROFILE, '50', self.start, self.seed, self.output)
        return call

    def test_lanes_override_normalized_flags_without_combining_effects(self):
        for lane in benchmark.LANES:
            with self.subTest(lane=lane):
                if lane == 'db-only': self.prepare_db()
                self.invoke(lane)
                report = json.loads(self.output.read_text())
                self.assertEqual(report['status'], 'success')
                self.assertEqual(self.child['FINITE_REUSE_INVENTORY'], str(lane == 'inventory-only').lower())
                self.assertEqual(self.child['FINITE_GRYPE_DB_CACHE'], str(lane == 'db-only').lower())
                self.assertFalse(report['releaseEligibilityEstablished'])
                self.assertEqual(report['database'], DB)

    def test_baseline_and_inventory_cannot_receive_a_database(self):
        self.prepare_db()
        for lane in ('baseline', 'inventory-only'):
            with self.subTest(lane=lane), self.assertRaisesRegex(ValueError, 'no transported database'):
                self.invoke(lane)

    def test_database_miss_or_mutated_seed_is_not_a_valid_db_only_sample(self):
        self.prepare_db()
        self.env['RESTORED_DB_KEY'] = ''
        with self.assertRaisesRegex(ValueError, 'exact successful seed'): self.invoke('db-only')
        self.env['RESTORED_DB_KEY'] = KEY
        (self.db / 'database.sqlite').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'transport bytes'): self.invoke('db-only')

    def test_inventory_miss_and_missing_fresh_phases_fail_the_benchmark(self):
        with self.assertRaisesRegex(ValueError, 'wrong lane'): self.invoke('inventory-only', inventory_miss=True)
        with self.assertRaisesRegex(ValueError, 'successful fresh'): self.invoke('baseline', phase_failure=True)
        self.assertEqual(json.loads(self.output.read_text())['status'], 'error')


class Summary(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.metadata = self.root / 'run.json'
        self.output = self.root / 'summary.json'
        self.reports = self.root / 'reports'
        self.rows = []
        jobs = [{'id': 1, 'name': 'Seed Grype DB transport', 'status': 'completed', 'conclusion': 'success',
                 'started_at': STAMP, 'completed_at': '2026-10-14T12:01:00Z'}]
        save(self.reports / 'seed/benchmark.json', {'kind': 'db-seed', 'status': 'success', **INFO,
                                                'binding': BINDING, 'updateSeconds': 10})
        for i, lane in enumerate(benchmark.LANES):
            row = {'schema': 1, 'kind': 'reader', 'status': 'success', 'lane': lane, 'repetition': 1, **INFO,
                   'binding': BINDING, 'inventoryGeneration': {'fixture': 'generation'}, 'platformDigest': 'sha256:'+'a'*64,
                   'scanner': '0.120.1', 'database': DB, 'databaseSnapshot': {'status': DB}, 'setupPlusScanSeconds': 20}
            self.rows.append(row)
            save(self.reports / lane / 'benchmark.json', row)
            jobs.append({'id': i+2, 'name': f'Scan ({lane}, 1)', 'status': 'completed', 'conclusion': 'success',
                         'started_at': '2026-10-14T12:01:01Z', 'completed_at': '2026-10-14T12:01:31Z'})
        self.run = {'id': 100, 'head_sha': REVISION, 'run_attempt': 1, 'jobs': jobs}
        save(self.metadata, self.run)

    def summarize(self):
        with patch.dict(os.environ, environment(), clear=True):
            benchmark.summarize(self.reports, self.metadata, 1, self.output)

    def test_matched_whole_jobs_and_separate_seed_cost(self):
        self.summarize()
        value = json.loads(self.output.read_text())
        self.assertEqual(value['seedWholeJobSeconds'], 60)
        self.assertEqual([lane['wholeJobMedianSeconds'] for lane in value['lanes']], [30]*3)
        self.assertEqual(value['repetitions'], 1)
        self.assertFalse(value['releaseEligibilityEstablished'])

    def test_changed_source_policy_tools_snapshot_or_attempt_rejects_comparison(self):
        changes = {'revision': 'c'*40, 'policySha256': 'c'*64, 'tools': {'grype': 'changed'},
                   'database': {**DB, 'schemaVersion': '7'}, 'databaseSnapshot': {'different': True}, 'attempt': '2'}
        original = copy.deepcopy(self.rows[0])
        for key, value in changes.items():
            save(self.reports / 'baseline/benchmark.json', {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError): self.summarize()

    def test_missing_duplicate_or_failed_reader_cannot_make_partial_savings_claim(self):
        path = self.reports / 'baseline/benchmark.json'
        path.unlink()
        with self.assertRaises(ValueError): self.summarize()
        save(path, self.rows[0]); save(self.reports / 'duplicate/benchmark.json', self.rows[0])
        with self.assertRaises(ValueError): self.summarize()
        (self.reports / 'duplicate/benchmark.json').unlink()
        self.run['jobs'][1]['conclusion'] = 'failure'; save(self.metadata, self.run)
        with self.assertRaises(ValueError): self.summarize()

    def test_current_attempt_repetition_types_and_impossible_durations_are_rejected(self):
        with patch.dict(os.environ, {**environment(), 'GITHUB_RUN_ATTEMPT': '2'}, clear=True), self.assertRaises(ValueError):
            benchmark.summarize(self.reports, self.metadata, 1, self.output)
        save(self.reports / 'baseline/benchmark.json', {**self.rows[0], 'repetition': True})
        with self.assertRaisesRegex(ValueError, 'canonical integer'): self.summarize()
        save(self.reports / 'baseline/benchmark.json', self.rows[0])
        for completed in ('2026-10-14T12:01:00Z', '2026-10-14T12:01:02Z', '2026-10-14T15:01:00Z'):
            changed = copy.deepcopy(self.run)
            changed['jobs'][1]['completed_at'] = completed
            save(self.metadata, changed)
            with self.subTest(completed=completed), self.assertRaisesRegex(ValueError, 'bounded measurement'):
                self.summarize()


class Workflow(unittest.TestCase):
    def test_bounded_main_only_read_scope_and_db_lane_isolation(self):
        path = ROOT / '.github/workflows/benchmark-security-reuse.yml'
        text = path.read_text(); workflow = yaml.safe_load(text)
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read', 'packages': 'read'})
        self.assertNotIn('secrets.', text)
        self.assertEqual(workflow[True]['workflow_dispatch']['inputs']['repetitions']['default'], '1')
        self.assertEqual(workflow['jobs']['scan']['strategy']['max-parallel'], 2)
        self.assertEqual(workflow['jobs']['scan']['strategy']['matrix']['lane'], list(benchmark.LANES))
        for job in workflow['jobs'].values():
            self.assertIn("github.ref == 'refs/heads/main'", job['if'])
            self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
            for step in job['steps']:
                if step.get('uses') == './.github/actions/setup-nix':
                    self.assertEqual(step['with']['cache-mode'], 'none')
        steps = workflow['jobs']['scan']['steps']
        restore = next(step for step in steps if step.get('id') == 'database')
        self.assertEqual(restore['if'], "matrix.lane == 'db-only'")
        self.assertIs(restore['with']['nix'], False)
        self.assertIs(restore['with']['save'], False)
        self.assertNotIn('restore-prefixes-first-match', restore['with'])
        self.assertIn('finite-ci-secrets-run repository-read --', text)
        # hashFiles must run after checkout rather than as a job-level value.
        self.assertNotIn('BENCHMARK_DB_KEY', workflow['jobs']['seed']['env'])
        seed = next(step for step in workflow['jobs']['seed']['steps'] if step.get('id') == 'seed')
        self.assertIn("hashFiles('flake.lock')", seed['env']['BENCHMARK_DB_KEY'])


if __name__ == '__main__':
    unittest.main()
