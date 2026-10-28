#!/usr/bin/env python3
"""Offline fixtures for isolated DB-overlap boundaries, cleanup and comparison."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('database_overlap_benchmark', ROOT / 'scripts/ci/benchmark-database-overlap.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
REVISION = 'b' * 40
STAMP = '2026-10-28T12:00:00Z'


def environment():
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_WORKFLOW_REF': M.WORKFLOW, 'GITHUB_SHA': REVISION,
            'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1', 'RUNNER_OS': 'Linux',
            'RUNNER_ARCH': 'X64', 'ImageVersion': 'fixture-image', 'PATH': '/usr/bin:/bin'}


def database(path='/private/arm/db/6/vulnerability.db'):
    return {'status': {'schemaVersion': '6.0.3', 'from': 'https://example.invalid/fixture-db.tar.zst',
                       'built': STAMP, 'path': path, 'valid': True},
            'providers': {'fedora': {'captured': STAMP, 'input': 'xxh64:fedora-fixture'},
                          'kev': {'captured': STAMP, 'input': 'xxh64:kev-fixture'}}}


def phases(lane):
    values = [{'phase': name, 'seconds': 1, 'success': True} for name in
              ('image-transfer', 'rootfs-extraction', 'inventory-cataloging', 'database-update',
               'database-coverage', 'vulnerability-scan', 'policy-evaluation')]
    if lane == 'overlap': values[3]['concurrentWithInventory'] = True
    return values


def native(lane):
    db = database(); del db['status']['path']
    return {'scannerStatus': 'complete', 'scanner': '0.120.1', 'scannerReportedDatabaseIdentity': db,
            'policyResultSha256': 'c' * 64, 'coverage': {'effective': 'fedora:44', 'rpmCount': 1000},
            'databaseCoverageRecords': 2, 'platformDigest': 'sha256:' + 'd' * 64,
            'inventoryGeneration': {'platform': 'linux/amd64', 'tools': {'syft': 'fixture'}},
            'phases': phases(lane), 'overlap': None if lane == 'serial' else {
                'updateSucceeded': True, 'privateColdDatabase': True, 'updateTimeoutSeconds': 600,
                'waitAfterInventorySeconds': 0},
            'nativeInventoryVerified': True, 'humanAdmissionEvaluated': False}


def resources(lane='serial'):
    return {'schema': 1, 'lane': lane, 'exitCode': 0, 'diskFloorBreached': False,
            'memoryMaxBytes': M.MEMORY, 'memorySwapMaxBytes': 0,
            'peakMemoryBytes': 1024**3, 'scanWallSeconds': 100 if lane == 'serial' else 80,
            'memoryEvents': {'low': 0, 'high': 0, 'max': 0, 'oom': 0, 'oom_kill': 0},
            'diskFreeStartBytes': 20 * 1024**3, 'diskFreeMinimumBytes': 10 * 1024**3,
            'diskSamples': 4, 'ioStat': '8:0 rbytes=1024 wbytes=2048 rios=1 wios=2\n',
            'runnerNetworkDelta': {'rx_bytes': 1024, 'tx_bytes': 128},
            'workerWallSeconds': 102 if lane == 'serial' else 82,
            'nativeTemporaryCleanupVerified': True, 'native': native(lane), 'nativeEvidence': {}}


def arm(lane):
    return {'lane': lane, 'serviceStarted': True, 'serviceQuiescent': True, 'timedOut': False,
            'workspaceRemoved': True, 'exitCode': 0, 'armWallSeconds': 110 if lane == 'serial' else 90,
            'worker': resources(lane)}


def reports_and_jobs():
    reports, jobs = [], []
    for order in M.ORDERS:
        for repetition in (1, 2, 3):
            arms = [arm(lane) for lane in M.ORDERS[order]]
            report = {'schema': 1, 'experiment': 'database-overlap', 'status': 'matched-scanner-observations',
                      'order': order, 'repetition': repetition, 'policy': copy.deepcopy(M.POLICY),
                      'revision': REVISION, 'runId': '100', 'attempt': '1',
                      'lockSha256': 'e' * 64, 'policySha256': 'f' * 64, 'platform': 'linux/amd64',
                      'tools': {'grype': 'grype 0.120.1'}, 'nixVersion': 'Nix fixture',
                      'runner': {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageVersion': 'fixture-image'},
                      'runnerHardware': {'logicalCPUs': 4, 'cpuModels': ['fixture'], 'memoryTotalKiB': 16000000},
                      'binding': {'image': IMAGE, 'profile': 'finite', 'originRun': 50},
                      'arms': arms, 'comparison': M.pair_valid(arms),
                      'setupSeconds': 30, 'pairWallSeconds': 205, 'setupPlusPairSeconds': 235,
                      'releaseEligibilityEstablished': False, 'productionChangeRecommended': False}
            reports.append(report)
            jobs.append({'id': len(jobs) + 1, 'name': f'Database overlap ({order}, {repetition})',
                         'status': 'completed', 'conclusion': 'success', 'run_id': 100, 'run_attempt': 1,
                         'head_sha': REVISION, 'started_at': '2026-10-28T12:00:00Z',
                         'completed_at': '2026-10-28T12:05:00Z'})
    return reports, [{'total_count': len(jobs), 'jobs': jobs}]


class Boundaries(unittest.TestCase):
    def test_hosted_exact_manual_main_without_credentials(self):
        with patch.dict(os.environ, environment(), clear=True): M.hosted()
        changes = [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'fork/finite'),
                   ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_EVENT_NAME', 'pull_request'),
                   ('GITHUB_REF', 'refs/heads/topic'), ('GITHUB_WORKFLOW_REF', M.WORKFLOW.replace('main', 'topic')),
                   ('GITHUB_SHA', 'not-a-sha'), ('RUNNER_OS', 'macOS'), ('RUNNER_ARCH', 'ARM64'),
                   ('ImageVersion', ''), ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ID', '1;echo fail'),
                   ('GITHUB_RUN_ATTEMPT', '01')]
        changes.extend((name, 'fixture-secret-not-used') for name in M.REUSE.SECRET_NAMES)
        for key, value in changes:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {**environment(), key: value}, clear=True), \
                 self.assertRaises(ValueError): M.hosted()

    def test_local_guard_precedes_native_process_or_output(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(M.subprocess, 'Popen') as launch, \
             self.assertRaises(ValueError): M.benchmark(argparse.Namespace())
        launch.assert_not_called()

    def test_database_identity_normalizes_only_owned_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = database(str(root / 'db/6/vulnerability.db'))
            source['status']['futureField'] = {'retained': 'identity'}
            source['providers']['fedora']['futureField'] = 'also retained'
            original = copy.deepcopy(source)
            result = M.owned_database(source, root)
            expected = copy.deepcopy(source); del expected['status']['path']
            self.assertEqual(result, expected)
            self.assertEqual(source, original)
            other = copy.deepcopy(source); other['status']['path'] = str(root / 'private-overlap/6/db')
            self.assertEqual(M.owned_database(other, root), result)

    def test_database_identity_rejects_external_linked_and_incomplete_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = database(str(root / 'db/6/vulnerability.db'))
            mutations = [(['status', 'path'], '/outside/db'), (['status', 'path'], str(root)),
                         (['status', 'valid'], False), (['status', 'schemaVersion'], ''),
                         (['status', 'from'], ''), (['status', 'error'], 'invalid hash'),
                         (['status', 'built'], '2026-10-28T12:00:00'), (['providers'], {}),
                         (['providers', 'fedora', 'input'], ''),
                         (['providers', 'kev', 'captured'], 'not-a-timestamp')]
            for keys, value in mutations:
                current = copy.deepcopy(original); target = current
                for key in keys[:-1]: target = target[key]
                target[keys[-1]] = value
                with self.subTest(keys=keys), self.assertRaises(ValueError): M.owned_database(current, root)
            (root / 'linked').symlink_to(root / 'outside')
            current = copy.deepcopy(original); current['status']['path'] = str(root / 'linked/db')
            with self.assertRaises(ValueError): M.owned_database(current, root)

    def test_cgroup_requires_real_owned_nonce_and_hard_caps(self):
        unit = 'finite-db-benchmark-' + 'a' * 16
        values = {'/proc/self/cgroup': '0::/system.slice/' + unit + '.service\n',
                  '/sys/fs/cgroup/system.slice/' + unit + '.service/memory.max': str(M.MEMORY),
                  '/sys/fs/cgroup/system.slice/' + unit + '.service/memory.swap.max': '0',
                  '/sys/fs/cgroup/system.slice/' + unit + '.service/pids.max': '256'}
        def read(path, *_, **__): return values[str(path)]
        with patch.object(Path, 'read_text', read):
            self.assertEqual(M.cgroup_path(unit).name, unit + '.service')
            for field, invalid in [('memory.max', 'max'), ('memory.swap.max', '4096'), ('pids.max', 'max')]:
                path = '/sys/fs/cgroup/system.slice/' + unit + '.service/' + field
                before = values[path]; values[path] = invalid
                with self.subTest(field=field), self.assertRaises(ValueError): M.cgroup_path(unit)
                values[path] = before
            values['/proc/self/cgroup'] = '0::/unrelated.service\n'
            with self.assertRaises(ValueError): M.cgroup_path(unit)
        with self.assertRaises(ValueError): M.cgroup_path('not-owned')

    def test_required_successful_phase_and_exact_overlap_marker(self):
        for lane in ('serial', 'overlap'):
            original = {'inventoryReused': False, 'phases': phases(lane)}
            self.assertEqual(M.phases_valid(original, lane), original['phases'])
            for mutate in (
                    lambda x: x.update(inventoryReused=True),
                    lambda x: x['phases'].pop(),
                    lambda x: x['phases'].append(copy.deepcopy(x['phases'][0])),
                    lambda x: x['phases'][0].update(success=False),
                    lambda x: x['phases'][0].update(seconds=float('nan')),
                    lambda x: x['phases'][0].update(seconds=True),
                    lambda x: x['phases'][3].update(concurrentWithInventory=lane != 'overlap')):
                changed = copy.deepcopy(original); mutate(changed)
                with self.subTest(lane=lane), self.assertRaises(ValueError): M.phases_valid(changed, lane)

    def test_required_resources_reject_oom_floor_cap_and_missing_telemetry(self):
        self.assertEqual(M.resources_valid(resources())['exitCode'], 0)
        for key, invalid in [('exitCode', 1), ('exitCode', False), ('memoryMaxBytes', M.MEMORY + 1), ('memorySwapMaxBytes', 1),
                             ('peakMemoryBytes', M.MEMORY + 1), ('peakMemoryBytes', True),
                             ('scanWallSeconds', 0), ('scanWallSeconds', float('inf')),
                             ('memoryEvents', {}), ('memoryEvents', {'oom': 1, 'oom_kill': 0}),
                             ('memoryEvents', {'oom': 0, 'oom_kill': 1}),
                             ('diskFloorBreached', True), ('diskSamples', 0),
                             ('diskFreeMinimumBytes', M.HEADROOM - 1), ('diskFreeStartBytes', 0),
                             ('ioStat', None), ('ioStat', ''), ('ioStat', 'garbage'),
                             ('ioStat', '8:0 rbytes=unknown wbytes=2 rios=1 wios=2'),
                             ('runnerNetworkDelta', {}),
                             ('runnerNetworkDelta', {'rx_bytes': -1, 'tx_bytes': 0})]:
            value = resources(); value[key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError): M.resources_valid(value)

    def test_evidence_census_retains_small_receipts_hashes_omitted_raw_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); evidence = root / 'evidence'; evidence.mkdir()
            for name in M.REQUIRED: (evidence / name).write_text('{}\n')
            (evidence / 'sbom.syft.json').write_text('{"fixture":"large-file-class"}\n')
            result = M.retain_evidence(evidence, root / 'retained')
            self.assertFalse(result['sbom.syft.json']['retained'])
            self.assertFalse((root / 'retained/sbom.syft.json').exists())
            for name in M.REQUIRED:
                self.assertTrue(result[name]['retained'])
                self.assertEqual(result[name]['sha256'], hashlib.sha256(b'{}\n').hexdigest())
                self.assertEqual((root / 'retained' / name).read_bytes(), b'{}\n')
            (evidence / 'linked').symlink_to(root / 'retained/security-result.json')
            with self.assertRaises(ValueError): M.retain_evidence(evidence, root / 'rejected')

    def test_evidence_caps_checked_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); evidence = root / 'evidence'; evidence.mkdir()
            for name in M.REQUIRED: (evidence / name).write_text('{}\n')
            with patch.object(M, 'EVIDENCE_BYTES', 1), patch.object(M.REUSE, 'sha') as hashing, self.assertRaises(ValueError):
                M.retain_evidence(evidence, root / 'output')
            hashing.assert_not_called()
            with patch.object(M, 'RETAIN_BYTES', 1), patch.object(M.REUSE, 'sha') as hashing, self.assertRaises(ValueError):
                M.retain_evidence(evidence, root / 'output')
            hashing.assert_not_called()


class NativeEvidence(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.evidence = self.root / 'arm/evidence'; self.evidence.mkdir(parents=True)
        self.policy_hash = 'f' * 64
        M.save(self.root / 'automation/security/image-policy.json', {'mode': 'maintainer-decision'})
        self.result = {'status': 'complete', 'mode': 'maintainer-decision', 'scannerHealth': 'healthy',
                       'image': IMAGE, 'policySha256': self.policy_hash, 'scanner': '0.120.1',
                       'database': database(str(self.root / 'arm/db/6/vulnerability.db')),
                       'coverage': {'effective': 'fedora:44', 'rpmCount': 1000},
                       'databaseCoverageRecords': 2, 'scannedAt': STAMP}
        self.provenance = {'platformDigest': 'sha256:' + 'd' * 64,
                           'generation': {'platform': 'linux/amd64', 'tools': {'syft': 'fixture'}}}

    def invoke(self, lane='serial', overlap=None):
        M.save(self.evidence / 'security-result.json', self.result)
        M.save(self.evidence / 'phase-timings.json', {'inventoryReused': False, 'phases': phases(lane)})
        if overlap is not None: M.save(self.evidence / 'database-overlap.json', overlap)
        security = SimpleNamespace(RISK_MODES={'maintainer-decision'})
        inventory = SimpleNamespace(verify=Mock(return_value=self.provenance))
        with patch.object(M, 'ROOT', self.root), patch.object(M, 'module', side_effect=[security, inventory]):
            value = M.native_receipt(self.evidence, self.root / 'arm', lane, IMAGE, self.policy_hash,
                                     {'grype': 'grype 0.120.1'})
        inventory.verify.assert_called_once_with(self.evidence, IMAGE, security, True)
        return value

    def test_normal_policy_and_full_inventory_verification_remain_mandatory(self):
        value = self.invoke()
        self.assertTrue(value['nativeInventoryVerified'])
        self.assertFalse(value['humanAdmissionEvaluated'])
        self.assertEqual(value['platformDigest'], self.provenance['platformDigest'])
        self.assertNotIn('path', value['scannerReportedDatabaseIdentity']['status'])
        self.assertEqual(value['scannerReportedDatabaseIdentity']['providers'], self.result['database']['providers'])

    def test_native_failure_wrong_image_policy_or_scanner_does_not_become_success(self):
        original = copy.deepcopy(self.result)
        for field, value in [('status', 'scanner-error'), ('scannerHealth', 'unhealthy'),
                             ('image', IMAGE.replace('a' * 64, 'b' * 64)), ('policySha256', 'a' * 64),
                             ('scanner', '0.120.2')]:
            self.result = copy.deepcopy(original); self.result[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.invoke()

    def test_overlap_must_have_successful_private_cold_update_and_bounded_wait(self):
        valid = {'updateSucceeded': True, 'privateColdDatabase': True,
                 'updateTimeoutSeconds': 600, 'waitAfterInventorySeconds': 0}
        self.assertEqual(self.invoke('overlap', valid)['overlap'], valid)
        for field, value in [('updateSucceeded', False), ('privateColdDatabase', False),
                             ('updateTimeoutSeconds', 1800), ('waitAfterInventorySeconds', 601)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.invoke('overlap', {**valid, field: value})
        with self.assertRaises(ValueError): self.invoke('serial', valid)


class Comparisons(unittest.TestCase):
    def compare(self, reports, jobs):
        with patch.dict(os.environ, environment(), clear=True): return M.comparison(reports, jobs)

    def test_six_reversed_order_pairs_measure_scans_not_separate_whole_jobs(self):
        reports, jobs = reports_and_jobs()
        result = self.compare(reports, jobs)
        self.assertEqual(result['status'], 'matched-scanner-observations')
        self.assertEqual(len(result['pairs']), 6)
        self.assertEqual(result['scanWallMedianSavedSeconds'], 20)
        self.assertEqual(result['armWallMedianSavedSeconds'], 20)
        self.assertEqual(result['orderMedians'], {'serial-first': 20, 'overlap-first': 20})
        self.assertFalse(result['releaseEligibilityEstablished'])
        self.assertFalse(result['productionChangeRecommended'])
        self.assertNotIn('wholeJobSavedSeconds', result)
        self.assertEqual(result['pairs'][0]['wholePairJobSeconds'], 300)

    def test_missing_duplicate_wrong_order_and_failed_pairs_reject(self):
        for mutation in (lambda r: r.pop(), lambda r: r.__setitem__(-1, copy.deepcopy(r[0])),
                         lambda r: r[0]['arms'].reverse(), lambda r: r[0].update(status='error'),
                         lambda r: r[0].update(repetition=4)):
            reports, jobs = reports_and_jobs(); mutation(reports)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.compare(reports, jobs)

    def test_pair_rejects_failed_cleanup_timeout_inventory_and_nonzero_exit(self):
        for mutate in (lambda a: a.update(exitCode=1), lambda a: a.update(timedOut=True),
                       lambda a: a.update(serviceQuiescent=False), lambda a: a.update(workspaceRemoved=False),
                       lambda a: a['worker'].update(nativeTemporaryCleanupVerified=False),
                       lambda a: a['worker'].update(lane='serial'),
                       lambda a: a['worker']['native'].update(nativeInventoryVerified=False)):
            values = [arm('serial'), arm('overlap')]; mutate(values[1])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): M.pair_valid(values)

    def test_receipts_require_canonical_types_and_complete_native_identity(self):
        reports, jobs = reports_and_jobs(); reports[0]['repetition'] = True
        with self.assertRaises(ValueError): self.compare(reports, jobs)
        for key in ('scanner', 'scannerReportedDatabaseIdentity', 'policyResultSha256', 'coverage',
                    'databaseCoverageRecords', 'platformDigest', 'inventoryGeneration'):
            values = [arm('serial'), arm('overlap')]
            for value in values: del value['worker']['native'][key]
            with self.subTest(key=key), self.assertRaises(ValueError): M.pair_valid(values)

    def test_pair_rejects_database_provider_policy_coverage_and_generation_drift(self):
        mutations = [lambda n: n['scannerReportedDatabaseIdentity']['status'].update(built='2026-10-28T13:00:00Z'),
                     lambda n: n['scannerReportedDatabaseIdentity']['status'].update(**{'from': 'new source'}),
                     lambda n: n['scannerReportedDatabaseIdentity']['providers']['fedora'].update(input='new input'),
                     lambda n: n['scannerReportedDatabaseIdentity']['providers']['kev'].update(captured='2026-10-28T13:00:00Z'),
                     lambda n: n.update(policyResultSha256='1' * 64), lambda n: n['coverage'].update(rpmCount=999),
                     lambda n: n.update(databaseCoverageRecords=0), lambda n: n.update(platformDigest='sha256:' + '2' * 64),
                     lambda n: n['inventoryGeneration'].update(platform='linux/arm64'), lambda n: n.update(scanner='0.120.2')]
        for mutation in mutations:
            arms = [arm('serial'), arm('overlap')]; mutation(arms[1]['worker']['native'])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): M.pair_valid(arms)

    def test_repeated_pairs_require_same_snapshot_even_if_each_pair_matches(self):
        reports, jobs = reports_and_jobs()
        for value in reports[-1]['arms']:
            value['worker']['native']['scannerReportedDatabaseIdentity']['providers']['fedora']['input'] = 'new publication'
        with self.assertRaisesRegex(ValueError, 'publication|observation'): self.compare(reports, jobs)

    def test_source_image_tool_policy_runner_and_caps_cohorts_cannot_mix(self):
        mutations = [lambda r: r.update(revision='d' * 40), lambda r: r.update(runId='101'),
                     lambda r: r.update(attempt='2'), lambda r: r.update(lockSha256='1' * 64),
                     lambda r: r.update(policySha256='1' * 64), lambda r: r.update(platform='linux/arm64'),
                     lambda r: r['tools'].update(grype='grype 0.121.0'), lambda r: r.update(nixVersion='different'),
                     lambda r: r['runner'].update(ImageVersion='different'),
                     lambda r: r['runnerHardware'].update(logicalCPUs=8),
                     lambda r: r['binding'].update(image='ghcr.io/closure-labs/finite@sha256:' + '1' * 64),
                     lambda r: r['policy'].update(memoryMaxBytes=M.MEMORY + 1)]
        for mutate in mutations:
            reports, jobs = reports_and_jobs(); mutate(reports[-1])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): self.compare(reports, jobs)

    def test_job_metadata_requires_complete_exact_successful_attempt(self):
        for mutation in ({'status': 'in_progress'}, {'conclusion': 'failure'}, {'run_id': 101},
                         {'run_attempt': 2}, {'head_sha': 'd' * 40},
                         {'name': 'wrong pair'}, {'completed_at': '2026-10-28T12:00:01Z'}):
            reports, jobs = reports_and_jobs(); jobs[0]['jobs'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.compare(reports, jobs)
        for mutate in (lambda p: p[0].update(total_count=100), lambda p: p[0]['jobs'].pop(),
                       lambda p: p[0]['jobs'].append(copy.deepcopy(p[0]['jobs'][0]))):
            reports, jobs = reports_and_jobs(); mutate(jobs)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): self.compare(reports, jobs)

    def test_metrics_cannot_relabel_or_sum_overlap_phases_as_wall_time(self):
        reports, jobs = reports_and_jobs()
        reports[0]['comparison']['scanWallSavedSeconds'] = 500
        with self.assertRaises(ValueError): self.compare(reports, jobs)
        reports, jobs = reports_and_jobs(); reports[0]['setupPlusPairSeconds'] += 1
        with self.assertRaises(ValueError): self.compare(reports, jobs)
        reports, jobs = reports_and_jobs(); reports[0]['pairWallSeconds'] = 100
        reports[0]['setupPlusPairSeconds'] = 130
        with self.assertRaises(ValueError): self.compare(reports, jobs)
        reports, jobs = reports_and_jobs()
        # Concurrent phase sums can exceed elapsed scan time; no sum-as-wall assumption.
        for report in reports:
            for value in report['arms']:
                if value['lane'] == 'overlap':
                    for phase in value['worker']['native']['phases']: phase['seconds'] = 50
        self.assertEqual(self.compare(reports, jobs)['scanWallMedianSavedSeconds'], 20)


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke_arm(self, *, fail_wait=False, quiescent=True, reader_start_failure=False, failed_native=False, launch_failure=False):
        output = self.root / 'output'
        private = self.root / 'private'; private.mkdir()
        context = self.root / 'context.json'; M.save(context, {})
        process = Mock(stdout=io.BytesIO(b'fixture-log'))
        if fail_wait: process.wait.side_effect = subprocess.TimeoutExpired('fixture-service', 1)
        else: process.wait.return_value = 0
        process.poll.return_value = 0
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == '/proc/meminfo': return 'MemAvailable: 20000000 kB\n'
            return original_read(path, *args, **kwargs)
        def launch(command, **_):
            self.command = command
            if launch_failure: raise InterruptedError('fixture uncertain launch interruption')
            M.save(output / 'worker.json', resources())
            if failed_native:
                M.save(private / 'evidence/security-result.json', {'status': 'scanner-error', 'error': 'fixture updater failure'})
            return process
        def stop(_unit, _process, _reader, record):
            record['cleanupAttempted'] = True
            record['serviceQuiescent'] = quiescent
        thread = Mock()
        if reader_start_failure: thread.start.side_effect = InterruptedError('fixture reader startup interruption')
        with patch.dict(os.environ, {**environment(), 'RUNNER_TEMP': str(self.root)}, clear=True), \
             patch.object(M.tempfile, 'mkdtemp', return_value=str(private)), \
             patch.object(Path, 'read_text', read), patch.object(M.subprocess, 'Popen', side_effect=launch), \
             patch.object(M.threading, 'Thread', return_value=thread), patch.object(M, 'stop_owned_service', side_effect=stop) as stopper:
            if fail_wait or not quiescent or reader_start_failure or launch_failure:
                with self.assertRaises((ValueError, subprocess.TimeoutExpired, InterruptedError)):
                    M.measured_arm('serial', IMAGE, output, context)
                result = json.loads((output / 'arm.json').read_text())
            else:
                result = M.measured_arm('serial', IMAGE, output, context)
        return result, private, stopper

    def test_owned_service_is_stopped_before_workspace_deleted(self):
        result, private, stopper = self.invoke_arm()
        self.assertTrue(result['workspaceRemoved']); self.assertFalse(private.exists())
        self.assertTrue(result['serviceQuiescent']); self.assertEqual(stopper.call_count, 1)
        for value in ('MemoryMax=' + str(M.MEMORY), 'MemorySwapMax=0', 'OOMPolicy=stop',
                      'KillMode=control-group', 'SendSIGKILL=yes', 'TasksMax=256', 'NoNewPrivileges=yes',
                      'CapabilityBoundingSet=', 'ProtectControlGroups=yes'):
            self.assertIn('--property=' + value, self.command)
        self.assertFalse(any('GH_TOKEN' in part or 'COSIGN_PRIVATE_KEY' in part for part in self.command))

    def test_timeout_stops_owned_service_and_records_failure(self):
        result, private, stopper = self.invoke_arm(fail_wait=True)
        self.assertTrue(result['timedOut']); self.assertTrue(result['workspaceRemoved'])
        self.assertFalse(private.exists()); self.assertGreaterEqual(stopper.call_count, 1)
        self.assertIn('error', result)

    def test_unconfirmed_service_retains_workspace_for_runner_disposal(self):
        result, private, stopper = self.invoke_arm(quiescent=False)
        self.assertFalse(result['serviceQuiescent']); self.assertFalse(result['workspaceRemoved'])
        self.assertTrue(private.exists()); self.assertGreaterEqual(stopper.call_count, 1)

    def test_launch_interruption_cleans_known_unit_and_restores_signal_mask(self):
        before = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        result, private, stopper = self.invoke_arm(launch_failure=True)
        after = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        self.assertEqual(after, before)
        self.assertTrue(result['launchAttempted']); self.assertFalse(result['serviceStarted'])
        self.assertTrue(result['serviceQuiescent'])
        self.assertTrue(result['workspaceRemoved']); self.assertFalse(private.exists())
        self.assertGreaterEqual(stopper.call_count, 1)
        self.assertIsNone(stopper.call_args.args[1])
        self.assertIsNone(stopper.call_args.args[2])
        self.assertIn('uncertain launch interruption', result['error'])

    def test_reader_start_interruption_still_stops_owned_service(self):
        result, private, stopper = self.invoke_arm(reader_start_failure=True)
        self.assertTrue(result['serviceStarted']); self.assertTrue(result['serviceQuiescent'])
        self.assertTrue(result['workspaceRemoved']); self.assertFalse(private.exists())
        self.assertGreaterEqual(stopper.call_count, 1)
        self.assertIn('reader startup interruption', result['error'])

    def test_failure_retains_available_native_diagnostic_after_quiescence(self):
        result, private, _ = self.invoke_arm(fail_wait=True, failed_native=True)
        self.assertTrue(result['serviceQuiescent']); self.assertFalse(private.exists())
        retained = self.root / 'output/native/security-result.json'
        self.assertEqual(json.loads(retained.read_text())['error'], 'fixture updater failure')
        self.assertTrue(result['failedNativeEvidence']['security-result.json']['retained'])
        self.assertTrue(result['timedOut'])

    def test_failure_does_not_read_native_evidence_while_service_may_be_live(self):
        result, private, _ = self.invoke_arm(fail_wait=True, failed_native=True, quiescent=False)
        self.assertFalse(result['serviceQuiescent']); self.assertTrue(private.exists())
        self.assertFalse((self.root / 'output/native').exists())
        self.assertNotIn('failedNativeEvidence', result)

    def test_cleanup_handles_missing_process_and_unstarted_log_reader(self):
        unit = 'finite-db-benchmark-' + 'e' * 16
        for reader in (None, Mock(ident=None)):
            record = {'serviceQuiescent': False}
            def command(argv, **_):
                self.assertIn(unit + '.service', argv)
                if 'show' in argv:
                    return subprocess.CompletedProcess(argv, 0, 'LoadState=not-found\nActiveState=inactive\n')
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(M.subprocess, 'run', side_effect=command) as commands:
                M.stop_owned_service(unit, None, reader, record)
            self.assertTrue(record['cleanupAttempted']); self.assertTrue(record['serviceQuiescent'])
            self.assertEqual(commands.call_count, 2)
            if reader is not None: reader.join.assert_not_called()

    def test_cleanup_does_not_claim_quiescence_after_stop_or_log_error(self):
        unit = 'finite-db-benchmark-' + 'e' * 16
        def command(argv, **_):
            if 'stop' in argv: raise subprocess.TimeoutExpired(argv, 15)
            return subprocess.CompletedProcess(argv, 0, 'LoadState=loaded\nActiveState=inactive\n')
        record = {'serviceQuiescent': False}
        with patch.object(M.subprocess, 'run', side_effect=command):
            M.stop_owned_service(unit, None, None, record)
        self.assertFalse(record['serviceQuiescent']); self.assertTrue(record['shutdownErrors'])

    def test_first_cancellation_during_cleanup_is_deferred_until_quiescent(self):
        code = """
import importlib.util, os, signal, subprocess, sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('fixture_overlap', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
number = int(sys.argv[2]); before = signal.pthread_sigmask(signal.SIG_BLOCK, set())
record = {'serviceQuiescent': False}; calls = []
def command(argv, **kwargs):
    calls.append(argv)
    if 'stop' in argv:
        os.kill(os.getpid(), number)
        assert number in signal.sigpending()
        return subprocess.CompletedProcess(argv, 0)
    return subprocess.CompletedProcess(argv, 0, 'LoadState=loaded\\nActiveState=inactive\\n')
try:
    with m.cancellation(), patch.object(m.subprocess, 'run', side_effect=command):
        m.stop_owned_service('finite-db-benchmark-' + 'e' * 16, None, None, record)
except InterruptedError:
    assert record['serviceQuiescent'] and record['cleanupAttempted'] and len(calls) == 2
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == before
    print('quiescent before cancellation')
else:
    raise AssertionError('pending cancellation did not propagate')
"""
        for signum in (signal.SIGINT, signal.SIGTERM):
            result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts/ci/benchmark-database-overlap.py'), str(signum)],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.stdout.strip(), 'quiescent before cancellation')

    def test_signals_interrupt_actual_small_child_and_restore_handlers(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            code = """
import importlib.util, os, signal, sys
spec = importlib.util.spec_from_file_location('fixture_overlap', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
number = int(sys.argv[2]); before = signal.getsignal(number)
try:
    with m.cancellation():
        os.kill(os.getpid(), number)
except InterruptedError:
    assert signal.getsignal(number) == before
    print('cancelled and restored')
else:
    raise AssertionError('signal did not interrupt')
"""
            result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts/ci/benchmark-database-overlap.py'), str(signum)],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.stdout.strip(), 'cancelled and restored')


class Workflow(unittest.TestCase):
    def test_manual_main_read_only_reversed_matrix_and_bounded_artifacts(self):
        path = ROOT / '.github/workflows/benchmark-database-overlap.yml'
        raw = path.read_text(); value = yaml.safe_load(raw)
        triggers = value.get('on', value.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        self.assertEqual(value['permissions'], {'contents': 'read', 'actions': 'read', 'packages': 'read'})
        self.assertFalse(value['concurrency']['cancel-in-progress'])
        pair = value['jobs']['pair']; summary = value['jobs']['summarize']
        for job in (pair, summary):
            self.assertIn("github.ref == 'refs/heads/main'", job['if'])
            self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
            self.assertIn("github.repository == 'closure-labs/finite'", job['if'])
        self.assertEqual(pair['runs-on'], 'ubuntu-24.04')
        self.assertEqual(pair['timeout-minutes'], 120)
        self.assertEqual(pair['strategy']['max-parallel'], 1)
        self.assertTrue(pair['strategy']['fail-fast'])
        matrix = pair['strategy']['matrix']['include']
        self.assertEqual({(r['order'], r['repetition']) for r in matrix},
                         {(order, rep) for order in M.ORDERS for rep in (1, 2, 3)})
        self.assertEqual(len(matrix), 6)
        self.assertIn('cache-mode: none', raw)
        self.assertNotIn('secrets.', raw); self.assertNotIn('cache-nix-action', raw)
        self.assertIn('finite-ci-secrets-run repository-read --', raw)
        self.assertIn('actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT/jobs?per_page=100', raw)
        self.assertIn('--paginate --slurp', raw)
        uploads = [step for step in pair['steps'] if 'upload-artifact@' in step.get('uses', '')]
        self.assertEqual(uploads[0]['if'], 'always()')
        self.assertEqual(uploads[0]['with']['retention-days'], 14)
        for workflow in (ROOT / '.github/workflows').glob('*.yml'):
            if workflow != path: self.assertNotIn('--experimental-database-overlap', workflow.read_text())

    def test_impact_preserves_checks_without_image_rebuilds(self):
        sys.path.insert(0, str(ROOT / 'scripts/ci'))
        try:
            spec = importlib.util.spec_from_file_location('overlap_impact', ROOT / 'scripts/ci/impact.py')
            impact = importlib.util.module_from_spec(spec); spec.loader.exec_module(impact)
            self.assertEqual(impact.classify(['scripts/ci/benchmark-database-overlap.py',
                                             '.github/workflows/benchmark-database-overlap.yml']),
                             {'checks': True, 'nix': False, 'profiles': []})
        finally:
            sys.path.pop(0)


if __name__ == '__main__':
    unittest.main()
