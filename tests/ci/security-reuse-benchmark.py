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
PROFILE = 'bluefin-generic'
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
        for values in [('ghcr.io/closure-labs/finite:finite', PROFILE, '50'),
                       (IMAGE, 'bluefin-next', '50'), (IMAGE, 'bluefin-dx-next', '50'),
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
                         'transportLimits': dict(benchmark.TRANSPORT_LIMITS),
                         'cacheKey': KEY, 'database': DB, 'transport': benchmark.transport(self.db)})

    def invoke(self, lane, inventory_miss=False, phase_failure=False, mode='all-lanes'):
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
            benchmark.scan(lane, 1, IMAGE, PROFILE, '50', self.start, self.seed, self.output, mode)
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

    def test_database_seed_cap_must_match_this_consumer(self):
        self.prepare_db()
        seed = json.loads(self.seed.read_text())
        seed['transportLimits']['maxBytes'] = 1024 ** 3
        save(self.seed, seed)
        with self.assertRaisesRegex(ValueError, 'exact successful seed'): self.invoke('db-only')

    def test_inventory_miss_and_missing_fresh_phases_fail_the_benchmark(self):
        with self.assertRaisesRegex(ValueError, 'wrong lane'): self.invoke('inventory-only', inventory_miss=True)
        with self.assertRaisesRegex(ValueError, 'successful'): self.invoke('baseline', phase_failure=True)
        self.assertEqual(json.loads(self.output.read_text())['status'], 'error')

    def test_failed_seed_does_not_feed_or_block_independent_readers(self):
        save(self.seed, {'kind': 'db-seed', 'status': 'error', 'error': 'transport bound rejected'})
        self.env.update(BENCHMARK_DB_KEY='', RESTORED_DB_KEY='')
        for lane in ('baseline', 'inventory-only'):
            with self.subTest(lane=lane):
                self.invoke(lane)
                record = json.loads(self.output.read_text())
                self.assertEqual(record['status'], 'success')
                self.assertEqual(record['binding'], BINDING)
                self.assertEqual(record['policySha256'], INFO['policySha256'])
                self.assertEqual({p['phase'] for p in record['phases']}, {
                    'database-update', 'database-coverage', 'vulnerability-scan', 'policy-evaluation'})
                self.assertTrue(all(p['success'] for p in record['phases']))
        with self.assertRaisesRegex(ValueError, 'exact successful seed'):
            self.invoke('db-only')

    def test_inventory_mode_needs_no_seed_and_cannot_run_database_lane(self):
        self.env.update(FINITE_REUSE_INVENTORY='true', FINITE_GRYPE_DB_CACHE='true', BENCHMARK_DB_KEY='', RESTORED_DB_KEY='')
        self.assertFalse(self.seed.exists())
        for lane in ('baseline', 'inventory-only'):
            with self.subTest(lane=lane):
                self.invoke(lane, mode='inventory-only')
                record = json.loads(self.output.read_text())
                self.assertEqual(record['mode'], 'inventory-only')
                self.assertEqual(self.child['FINITE_GRYPE_DB_CACHE'], 'false')
                self.assertEqual(record['binding'], BINDING)
                self.assertRegex(record['policyResultSha256'], r'^[0-9a-f]{64}$')
        with patch.object(benchmark, 'context') as context, self.assertRaises(ValueError):
            benchmark.scan('db-only', 1, IMAGE, PROFILE, '50', self.start, None, self.output, 'inventory-only')
        context.assert_not_called()


class TransportDiagnostics(unittest.TestCase):
    def test_byte_bound_is_checked_before_any_content_hash(self):
        observed = {'limits': dict(benchmark.TRANSPORT_LIMITS), 'entriesObserved': 2,
                    'regularFilesObserved': 2, 'bytesObserved': benchmark.MAX_DB_BYTES + 10,
                    'complete': True, 'files': {'large.sqlite': {'bytes': benchmark.MAX_DB_BYTES + 9},
                                               'small.json': {'bytes': 1}}}
        with patch.object(benchmark, 'transport_metadata', return_value=observed), \
             patch.object(benchmark, 'sha') as hashed, self.assertRaises(benchmark.TransportRejected) as failure:
            benchmark.transport(Path('/tmp/unused-fixture'))
        hashed.assert_not_called()
        self.assertEqual(failure.exception.observation, observed)
        self.assertIn('byte-limit', str(failure.exception))

    def test_file_count_and_metadata_entry_caps_retain_truthful_lower_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(33): (root / str(index)).write_bytes(b'x')
            with patch.object(benchmark, 'sha') as hashed, self.assertRaises(benchmark.TransportRejected) as failure:
                benchmark.transport(root)
            hashed.assert_not_called()
            observed = failure.exception.observation
            self.assertEqual((observed['regularFilesObserved'], observed['bytesObserved']), (33, 33))
            self.assertTrue(observed['complete'])
            for index in range(33, 257): (root / str(index)).write_bytes(b'x')
            with patch.object(benchmark, 'sha') as hashed, self.assertRaises(benchmark.TransportRejected) as failure:
                benchmark.transport(root)
            hashed.assert_not_called()
            observed = failure.exception.observation
            self.assertEqual(observed['entriesObserved'], 256)
            self.assertFalse(observed['complete'])
            self.assertEqual(observed['issue'], 'metadata-entry-limit')

    def test_seed_bound_failure_keeps_context_origin_schema_counts_and_exports_no_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / '.bluebuild/security-benchmark-db'
            output, github_output = root / 'seed/benchmark.json', root / 'github-output'
            github_output.write_text('')
            observed = {'limits': dict(benchmark.TRANSPORT_LIMITS), 'entriesObserved': 1,
                        'regularFilesObserved': 1, 'bytesObserved': benchmark.MAX_DB_BYTES + 1,
                        'complete': True, 'files': {'vulnerability.db': {'bytes': benchmark.MAX_DB_BYTES + 1}}}
            def updated(*_, **__):
                directory.mkdir(parents=True)
                return subprocess.CompletedProcess([], 0)
            with patch.dict(os.environ, {**environment(), 'GRYPE_DB_CACHE_DIR': str(directory),
                                         'GITHUB_OUTPUT': str(github_output)}, clear=True), \
                 patch.object(benchmark, 'ROOT', root), patch.object(benchmark, 'context', return_value=INFO), \
                 patch.object(benchmark, 'authenticate', return_value=BINDING), \
                 patch.object(benchmark, 'database_status', return_value=DB), \
                 patch.object(benchmark.subprocess, 'run', side_effect=updated) as update, \
                 patch.object(benchmark, 'transport_metadata', return_value=observed), \
                 patch.object(benchmark, 'sha') as hashed, self.assertRaises(benchmark.TransportRejected):
                benchmark.seed(IMAGE, PROFILE, '50', output)
            hashed.assert_not_called()
            self.assertEqual(update.call_args.args[0], ['grype', 'db', 'update'])
            retained = json.loads(output.read_text())
            self.assertEqual(retained['status'], 'error')
            self.assertEqual(retained['binding'], BINDING)
            self.assertEqual(retained['revision'], REVISION)
            self.assertEqual(retained['database'], DB)
            self.assertEqual(retained['transportObservation'], observed)
            self.assertEqual(retained['transportLimits']['maxBytes'], 2 * 1024 ** 3)
            self.assertNotIn('transport', retained)
            self.assertEqual(github_output.read_text(), '')
            self.assertLess(output.stat().st_size, 8192)

    def test_successful_fixture_transport_binds_exact_caps_and_file_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'fixture.db').write_bytes(b'fixture-only')
            result = benchmark.transport(root)
            self.assertEqual(result['limits'], benchmark.TRANSPORT_LIMITS)
            self.assertEqual(result['bytes'], 12)
            self.assertEqual(result['files']['fixture.db']['sha256'], benchmark.sha(root / 'fixture.db'))

    def test_changed_file_cannot_be_hashed_past_its_census_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'fixture.db').write_bytes(b'abc')
            observed = {'limits': dict(benchmark.TRANSPORT_LIMITS), 'entriesObserved': 1,
                        'regularFilesObserved': 1, 'bytesObserved': 2, 'complete': True,
                        'files': {'fixture.db': {'bytes': 2}}}
            with patch.object(benchmark, 'transport_metadata', return_value=observed), \
                 self.assertRaises(benchmark.TransportRejected) as failure:
                benchmark.transport(root)
            self.assertFalse(failure.exception.observation['complete'])
            self.assertEqual(failure.exception.observation['issue'], 'file-changed-during-hash')


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
                                                'transportLimits': dict(benchmark.TRANSPORT_LIMITS),
                                                'binding': BINDING, 'updateSeconds': 10})
        for i, lane in enumerate(benchmark.LANES):
            row = {'schema': 1, 'kind': 'reader', 'status': 'success', 'lane': lane, 'repetition': 1, **INFO,
                   'transportLimits': dict(benchmark.TRANSPORT_LIMITS),
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
                   'database': {**DB, 'schemaVersion': '7'}, 'databaseSnapshot': {'different': True}, 'attempt': '2',
                   'transportLimits': {**benchmark.TRANSPORT_LIMITS, 'maxBytes': 1024 ** 3}}
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

    def test_seed_failure_or_partial_lanes_cannot_produce_a_passing_comparison(self):
        seed_path = self.reports / 'seed/benchmark.json'
        seed = json.loads(seed_path.read_text())
        seed['status'] = 'error'
        save(seed_path, seed)
        with self.assertRaisesRegex(ValueError, 'every independent lane'):
            self.summarize()
        (self.reports / 'db-only/benchmark.json').unlink()
        with self.assertRaisesRegex(ValueError, 'every independent lane'):
            self.summarize()
        self.assertFalse(self.output.exists())


class InventorySummary(unittest.TestCase):
    def setUp(self):
        Summary.setUp(self)
        (self.reports / 'seed/benchmark.json').unlink()
        (self.reports / 'db-only/benchmark.json').unlink()
        self.run['jobs'] = [{'id': 1, 'name': 'Seed Grype DB transport', 'status': 'completed', 'conclusion': 'skipped'}]
        self.inventory_rows = []
        for repetition in (1, 2, 3):
            for lane in ('baseline', 'inventory-only'):
                row = copy.deepcopy(self.rows[0])
                phases = [{'phase': phase, 'seconds': 1, 'success': True} for phase in
                    ('database-update', 'database-coverage', 'vulnerability-scan', 'policy-evaluation')]
                if lane == 'baseline': phases.append({'phase': 'image-transfer', 'seconds': 10, 'success': True})
                row.update(mode='inventory-only', lane=lane, repetition=repetition,
                    inventoryReused=lane == 'inventory-only', policyResultSha256='2' * 64,
                    setupSeconds=12, scanSeconds=68 if lane == 'baseline' else 33,
                    setupPlusScanSeconds=80 if lane == 'baseline' else 45, phases=phases)
                self.inventory_rows.append(row)
                path = self.reports / (lane if repetition == 1 else f'{lane}-{repetition}') / 'benchmark.json'
                save(path, row)
                self.run['jobs'].append({'id': len(self.run['jobs']) + 1, 'name': f'Scan ({lane}, {repetition})',
                    'status': 'completed', 'conclusion': 'success', 'started_at': '2026-10-14T12:01:01Z',
                    'completed_at': '2026-10-14T12:02:41Z' if lane == 'baseline' else '2026-10-14T12:02:01Z'})
        save(self.metadata, self.run)

    def summarize(self, repetitions=3):
        with patch.dict(os.environ, environment(), clear=True):
            benchmark.summarize(self.reports, self.metadata, repetitions, self.output, mode='inventory-only')

    def test_six_matched_readers_report_no_seed_whole_job_and_phase_savings(self):
        self.summarize()
        result = json.loads(self.output.read_text())
        self.assertIsNone(result['seed']); self.assertIsNone(result['seedWholeJobSeconds'])
        self.assertTrue(result['runnerCohortMatched']); self.assertTrue(result['inventoryPolicyOutputsEquivalent'])
        self.assertFalse(result['releaseEligibilityEstablished'])
        self.assertEqual([r['samples'] for r in result['lanes']], [3, 3])
        self.assertEqual([r['wholeJobMedianSeconds'] for r in result['lanes']], [100, 60])
        self.assertEqual(result['lanes'][0]['phaseMedianSeconds']['image-transfer'], 10)
        self.assertEqual(result['wholeJobMedianSavedSeconds'], 40)
        self.assertEqual(result['wholeJobMedianSavedPercent'], 40)
        self.assertEqual(len(result['pairedComparisons']), 3)
        self.assertTrue(all(p['setupPlusScanSavedSeconds'] == 35 for p in result['pairedComparisons']))

    def test_policy_equivalence_retains_decisions_coverage_and_duplicate_observations(self):
        result = {'status': 'pass', 'scannedAt': STAMP, 'database': DB, 'coverage': {'totalPackages': 123},
            'observations': [{'component': 'one', 'aliases': ['CVE-2', 'CVE-1']}, {'component': 'two'}]}
        reordered = copy.deepcopy(result)
        reordered.update(scannedAt='2026-10-14T13:00:00Z', database={'separately': 'matched'})
        reordered['observations'].reverse(); reordered['observations'][1]['aliases'].reverse()
        self.assertEqual(benchmark.policy_equivalence(result), benchmark.policy_equivalence(reordered))
        for changed in ({**result, 'status': 'blocked'}, {**result, 'coverage': {'totalPackages': 124}},
                {**result, 'observations': result['observations'] + result['observations'][:1]}):
            self.assertNotEqual(benchmark.policy_equivalence(result), benchmark.policy_equivalence(changed))

    def test_missing_extra_seed_wrong_mode_or_fewer_repetitions_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, 'three matched'): self.summarize(1)
        path = self.reports / 'baseline/benchmark.json'; original = copy.deepcopy(self.inventory_rows[0])
        for change in ({'mode': 'all-lanes'}, {'lane': 'db-only'}, {'status': 'error'}):
            save(path, {**original, **change})
            with self.subTest(change=change), self.assertRaises(ValueError): self.summarize()
        save(path, original)
        save(self.reports / 'seed/benchmark.json', {'kind': 'db-seed', 'status': 'success'})
        with self.assertRaisesRegex(ValueError, 'every independent lane'): self.summarize()
        (self.reports / 'seed/benchmark.json').unlink()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'every independent lane'): self.summarize()
        self.assertFalse(self.output.exists())

    def test_changed_runner_output_database_source_or_fresh_phase_rejects_savings(self):
        original = copy.deepcopy(self.inventory_rows[0]); path = self.reports / 'baseline/benchmark.json'
        changes = {'runner': {**INFO['runner'], 'ImageVersion': 'another-image'},
            'policyResultSha256': '0' * 64, 'databaseSnapshot': {'changed': True},
            'revision': '0' * 40, 'inventoryReused': True, 'restoredCacheKey': KEY,
            'phases': original['phases'][1:], 'scanSeconds': -1, 'setupPlusScanSeconds': 10}
        for key, value in changes.items():
            save(path, {**original, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError): self.summarize()

    def test_inventory_mode_rejects_unexpected_executed_seed_and_failed_reader_job(self):
        for conclusion in ('failure', 'success'):
            self.run['jobs'][0]['conclusion'] = conclusion; save(self.metadata, self.run)
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(ValueError, 'unexpectedly ran'):
                self.summarize()
        self.run['jobs'][0]['conclusion'] = 'skipped'
        self.run['jobs'][1]['conclusion'] = 'failure'; save(self.metadata, self.run)
        with self.assertRaisesRegex(ValueError, 'successful independent job'): self.summarize()


class Workflow(unittest.TestCase):
    def test_bounded_main_only_read_scope_and_db_lane_isolation(self):
        path = ROOT / '.github/workflows/benchmark-security-reuse.yml'
        text = path.read_text(); workflow = yaml.safe_load(text)
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read', 'packages': 'read'})
        self.assertNotIn('secrets.', text)
        self.assertEqual(workflow[True]['workflow_dispatch']['inputs']['repetitions']['default'], '1')
        self.assertEqual(workflow['jobs']['scan']['strategy']['max-parallel'], 2)
        matrix = workflow['jobs']['scan']['strategy']['matrix']
        self.assertIn('["baseline","inventory-only","db-only"]', matrix['lane'])
        self.assertIn('["baseline","inventory-only"]', matrix['lane'])
        self.assertEqual(workflow[True]['workflow_dispatch']['inputs']['mode']['default'], 'all-lanes')
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

    def test_seed_failure_runs_independent_lanes_but_db_lane_fails_before_setup(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-security-reuse.yml').read_text())
        job = workflow['jobs']['scan']
        expression = job['if'].replace('&&', ' and ').replace('||', ' or ').replace('!cancelled()', 'not cancelled()')
        expression = ' '.join(expression.split())
        for state, cancelled, expected in [('success', False, True), ('failure', False, True),
                                           ('cancelled', True, False), ('skipped', False, False)]:
            with self.subTest(seed=state, cancelled=cancelled):
                selected = eval(expression, {'__builtins__': {}}, {
                    'always': lambda: True, 'cancelled': lambda: cancelled,
                    'needs': SimpleNamespace(seed=SimpleNamespace(result=state)),
                    'inputs': SimpleNamespace(mode='all-lanes'),
                    'github': SimpleNamespace(repository='closure-labs/finite', ref='refs/heads/main', event_name='workflow_dispatch')})
                self.assertEqual(bool(selected), expected)
        self.assertEqual(job['strategy']['max-parallel'], 2)
        guard = job['steps'][0]
        self.assertEqual(guard['if'], "matrix.lane == 'db-only' && needs.seed.result != 'success'")
        self.assertEqual(job['steps'][1]['uses'].split('@')[0], 'actions/checkout')
        for step in job['steps']:
            if step.get('name') in ("Read this attempt's authenticated seed receipt", 'Restore only the explicitly seeded DB transport'):
                self.assertEqual(step['if'], "matrix.lane == 'db-only'")
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, **environment(), 'BENCHMARK_REPETITION': '1'}
            result = subprocess.run(['bash', '-e', '-c', guard['run']], cwd=temporary,
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads((Path(temporary) / '.bluebuild/security-benchmark/benchmark.json').read_text())
            self.assertEqual(report['status'], 'error')
            self.assertFalse(report['scanStarted'])
            self.assertFalse(report['releaseEligibilityEstablished'])

    def test_inventory_mode_skips_seed_runs_six_readers_and_preserves_main_guard(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/benchmark-security-reuse.yml').read_text())
        seed, scan, summary = [workflow['jobs'][name] for name in ('seed', 'scan', 'summarize')]
        self.assertIn("inputs.mode != 'inventory-only'", seed['if'])
        expression = scan['if'].replace('&&', ' and ').replace('||', ' or ').replace('!cancelled()', 'not cancelled()')
        expression = ' '.join(expression.split())
        scope = {'always': lambda: True, 'cancelled': lambda: False,
            'needs': SimpleNamespace(seed=SimpleNamespace(result='skipped')),
            'inputs': SimpleNamespace(mode='inventory-only'),
            'github': SimpleNamespace(repository=benchmark.REPOSITORY, ref='refs/heads/main', event_name='workflow_dispatch')}
        self.assertTrue(eval(expression, {'__builtins__': {}}, scope))
        for state in ('success', 'failure'):
            scope['needs'].seed.result = state
            self.assertFalse(eval(expression, {'__builtins__': {}}, scope))
        scope['needs'].seed.result = 'skipped'; scope['github'].ref = 'refs/heads/topic'
        self.assertFalse(eval(expression, {'__builtins__': {}}, scope))
        matrix = scan['strategy']['matrix']
        self.assertEqual(next(iter(matrix)), 'repetition')
        self.assertIn("inputs.mode == 'inventory-only'", matrix['repetition'])
        self.assertIn('[1,2,3]', matrix['repetition'])
        self.assertIn("inputs.mode == 'inventory-only' && '3'", summary['env']['REPETITIONS'])
        measure = next(step for step in scan['steps'] if step.get('name') == 'Measure the isolated lane with fresh DB and current policy')
        self.assertIn('--mode "$BENCHMARK_MODE"', measure['run'])
        self.assertEqual(scan['strategy']['max-parallel'], 2)


if __name__ == '__main__':
    unittest.main()
