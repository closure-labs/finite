#!/usr/bin/env python3
"""Small offline fixtures; never execute Nix, VM, package or registry tools."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qualification_reuse_benchmark', ROOT / 'scripts/ci/benchmark-qualification-reuse.py')
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class Benchmark(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.old_cwd = Path.cwd(); os.chdir(self.directory); self.addCleanup(os.chdir, self.old_cwd)
        self.source, self.execution = 'a' * 40, 'b' * 40
        self.args = argparse.Namespace(operation='restore', profile='bluefin-generic', origin_run=10, repetition=1,
            source=self.source, identity='v1:' + 'c' * 64, candidate='sha256:' + 'd' * 64,
            previous='sha256:' + 'e' * 64, output=self.directory / 'restore')
        self.now = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.context = {'schema': 2, 'platform': 'linux/amd64', 'inputs': {'fixture': {'sha256': 'f' * 64}}}
        self.acceptance = {'schema': 2, 'candidate': 'ghcr.io/closure-labs/finite@' + self.args.candidate,
            'previousDigest': self.args.previous, 'profile': self.args.profile, 'sourceRevision': self.source,
            'revision': self.source, 'buildIdentity': self.args.identity, 'accepted': True, 'secureBoot': True,
            'encryptedRoot': True, 'bootstrap': False, 'qualifiedAt': self.now.isoformat(),
            'qualificationContext': self.context, 'qualificationContextSha256': M.REUSE.qualification.identity(self.context),
            'qualifiedIsoOrigin': {'run': 10, 'attempt': 1, 'revision': self.source},
            'qualifiedIso': {'name': 'finite-bluefin-generic.iso', 'sha256': '1' * 64, 'installationSha256': '2' * 64, 'installer': {}}}
        self.run = {'id': 10, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
            'head_branch': 'main', 'head_sha': self.source, 'path': '.github/workflows/build.yml', 'event': 'push',
            **{key: {'full_name': M.REPO, 'id': M.REPO_ID} for key in ('repository', 'head_repository')}}
        self.artifact = {'id': 11, 'name': 'qualification-bluefin-generic-10-1', 'size_in_bytes': 100,
            'digest': 'sha256:' + '3' * 64, 'expired': False,
            'expires_at': (self.now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'workflow_run': {'id': 10, 'head_sha': self.source, 'head_branch': 'main',
                'repository_id': M.REPO_ID, 'head_repository_id': M.REPO_ID}}
        self.origin = {'run': 10, 'attempt': 1, 'job': 104, 'artifactId': 11,
            'artifactSha256': self.artifact['digest'], 'qualificationRevision': self.source}

    def environment(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': M.REPO, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF': M.REPO + '/.github/workflows/benchmark-vm-reuse.yml@refs/heads/main',
            'GITHUB_SHA': self.execution, 'GITHUB_RUN_ID': '20', 'GITHUB_RUN_ATTEMPT': '1', 'ImageVersion': 'fixture'}

    def job(self, name, number, start, end, run=None):
        run = run or self.run
        return {'id': number, 'name': name, 'status': 'completed', 'conclusion': 'success',
            'run_id': run['id'], 'run_attempt': run['run_attempt'], 'head_sha': run['head_sha'],
            'started_at': '2026-10-15T' + start + 'Z', 'completed_at': '2026-10-15T' + end + 'Z'}

    def baseline(self):
        prefix = 'Publish (bluefin-generic) / qualification / '
        jobs = [self.job(prefix + name, 101 + index, start, end) for index, (name, start, end) in enumerate((
            ('prepare', '14:00:00', '14:01:00'), ('phase (fresh)', '14:01:00', '14:31:00'),
            ('phase (upgrade)', '14:01:00', '14:21:00'), ('aggregate', '14:31:00', '14:32:00')))]
        class API:
            def read(api, path, paginated=False):
                if '/jobs?' in path: return [{'jobs': jobs}]
                if '/artifacts?' in path: return [{'artifacts': [self.artifact]}]
                return self.run
        return M.baseline(API(), self.args)

    def test_authentic_original_baseline_uses_parallel_criticalpath_and_all_four_jobs(self):
        result = self.baseline()
        self.assertEqual(result['summedRunnerSeconds'], 3120)
        self.assertEqual(result['criticalPathServiceSeconds'], 1920)
        self.assertEqual(result['elapsedIncludingQueueSeconds'], 1920)
        self.assertEqual(result['artifact']['id'], 11)

    def test_wrong_source_or_failed_original_jobs_cannot_supply_baseline(self):
        for changes in ({'head_branch': 'topic'}, {'head_sha': self.execution}, {'conclusion': 'failure'}, {'path': '.github/workflows/benchmark-vm-reuse.yml'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): M.origin_run(dict(self.run, **changes), 10, self.source)
        good = self.job('fixture', 1, '14:00:00', '14:01:00')
        for changes in ({'conclusion': 'failure'}, {'run_attempt': 2}, {'head_sha': self.execution}, {'completed_at': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): M.job_receipt([dict(good, **changes)], 'fixture', self.run)
        with self.assertRaises(ValueError): M.job_receipt([good, good], 'fixture', self.run)

    def test_artifact_requires_exact_name_size_digest_source_and_repository(self):
        M.artifact_metadata([self.artifact], self.artifact['name'], self.run)
        for changes in ({'size_in_bytes': M.ARCHIVE + 1}, {'expired': True}, {'digest': 'bad'},
                        {'workflow_run': dict(self.artifact['workflow_run'], repository_id=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                M.artifact_metadata([dict(self.artifact, **changes)], self.artifact['name'], self.run)
        with self.assertRaises(ValueError): M.artifact_metadata([self.artifact] * 2, self.artifact['name'], self.run)

    def test_actual_production_validation_rejects_changed_candidate_context_age_and_diagnostics(self):
        directory = self.directory / 'receipts'; directory.mkdir()
        path = directory / (self.args.profile + '-acceptance.json')
        with patch.object(M.REUSE.qualification.desktop, 'verify'):
            path.write_text(json.dumps(self.acceptance))
            M.REUSE.validate(directory, self.args.profile, self.acceptance['candidate'], self.args.previous,
                self.source, self.args.identity, self.context)
            for changes in ({'validationOnly': True}, {'candidate': 'ghcr.io/closure-labs/finite@sha256:' + '0' * 64},
                            {'qualificationContext': {}}, {'qualifiedAt': (self.now - timedelta(days=2)).isoformat()}):
                path.write_text(json.dumps(dict(self.acceptance, **changes)))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    M.REUSE.validate(directory, self.args.profile, self.acceptance['candidate'], self.args.previous,
                        self.source, self.args.identity, self.context)

    def test_actual_revalidation_does_not_refresh_qualification_age(self):
        value = dict(self.acceptance, qualificationReuse=self.origin)
        with patch.object(M.REUSE.qualification, 'source_inputs', return_value=self.context['inputs']), \
                patch.object(M.REUSE.qualification, 'validate_certificate') as certificate:
            M.REUSE.verify_reused_acceptance(value)
            certificate.assert_called_once()
            with self.assertRaises(M.REUSE.Unavailable): M.REUSE.verify_reused_acceptance(value, now=self.now + timedelta(hours=25))
        self.assertEqual(value['qualifiedAt'], self.acceptance['qualifiedAt'])

    def test_production_extract_authenticates_handoff_hash_size_and_required_files(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr(self.args.profile + '-acceptance.json', json.dumps(self.acceptance))
            zipped.writestr(self.args.profile + '-desktop-acceptance.json', '{}')
            zipped.writestr('benchmark.json', '{}')
        raw = archive.getvalue()
        value = dict(self.artifact, size_in_bytes=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
        output = self.directory / 'extract'; output.mkdir()
        M.REUSE.extract(io.BytesIO(raw), value, output, self.args.profile)
        self.assertEqual(len(list(output.iterdir())), 2)
        for changes in ({'size_in_bytes': len(raw) + 1}, {'digest': 'sha256:' + '0' * 64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                M.REUSE.extract(io.BytesIO(raw), dict(value, **changes), output, self.args.profile)

    def test_retry_only_idempotent_transient_gets_and_discard_partial_downloads(self):
        events = []; calls = []
        def run(command, **kwargs):
            calls.append(command)
            kwargs['stdout'].write(b'partial' if len(calls) == 1 else b'complete')
            if len(calls) == 1: kwargs['stderr'].write(b'gh: Service Unavailable (HTTP 503)')
            return argparse.Namespace(returncode=1 if len(calls) == 1 else 0)
        with tempfile.TemporaryFile() as output, patch.object(M.subprocess, 'run', side_effect=run), patch.object(M.time, 'sleep'):
            M.get_with_retries(['gh', 'api', 'repos/fixture'], events=events, stdout=output, timeout=1)
            output.seek(0); self.assertEqual(output.read(), b'complete')
        self.assertEqual(len(calls), 2); self.assertEqual(events[0]['attempt'], 1)
        with tempfile.TemporaryFile() as output, self.assertRaises(ValueError):
            M.get_with_retries(['gh', 'api', '--method', 'POST'], events=[], stdout=output)

    def test_denied_gets_never_retry_and_metadata_endpoints_are_bounded(self):
        def denied(command, **kwargs):
            kwargs['stderr'].write(b'HTTP 403'); return argparse.Namespace(returncode=1)
        with tempfile.TemporaryFile() as output, patch.object(M.subprocess, 'run', side_effect=denied) as run, self.assertRaises(subprocess.CalledProcessError):
            M.get_with_retries(['gh', 'api', 'repos/fixture'], events=[], stdout=output)
        run.assert_called_once()
        with patch.object(M.subprocess, 'run') as run, self.assertRaises(ValueError): M.API().read('actions/artifacts/1/zip')
        run.assert_not_called()

    def test_local_or_branch_guard_precedes_any_native_context_or_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(M.PREFLIGHT, 'require_eligible') as preflight, self.assertRaises(ValueError): M.execute(self.args)
        preflight.assert_not_called()
        with patch.dict(os.environ, dict(self.environment(), GITHUB_REF='refs/heads/topic')), self.assertRaises(ValueError): M.hosted(self.args)

    def execute_restore(self, *, wrong_origin=False):
        original = self.baseline()
        class API:
            calls, bytes, retries = 0, 0, []
            def read(api, *args, **kwargs): raise AssertionError('Unexpected external request')
        def resolver(profile, output):
            output.mkdir()
            value = dict(self.acceptance, revision=self.execution, qualificationReuse=self.origin)
            (output / (profile + '-acceptance.json')).write_text(json.dumps(value))
            (output / (profile + '-desktop-acceptance.json')).write_text('{}')
            return dict(self.origin, run=99) if wrong_origin else self.origin
        with patch.dict(os.environ, self.environment()), patch.object(M, 'API', API), patch.object(M, 'baseline', return_value=original), \
                patch.object(M.PREFLIGHT, 'require_eligible'), patch.object(M.REUSE.qualification, 'context', return_value=self.context), \
                patch.object(M.REUSE, 'reuse', side_effect=resolver), patch.object(M.REUSE.qualification, 'source_inputs', return_value=self.context['inputs']), \
                patch.object(M.REUSE.qualification, 'validate_certificate'), patch.object(M.REUSE.qualification.desktop, 'verify'):
            if wrong_origin:
                with self.assertRaisesRegex(ValueError, 'another qualification origin'): M.execute(self.args)
            else: M.execute(self.args)
        return json.loads((self.args.output / 'benchmark.json').read_text())

    def test_restore_success_records_actual_context_origin_and_two_receipt_hashes(self):
        report = self.execute_restore()
        self.assertEqual(report['status'], 'success'); self.assertFalse(report['publicationClearance'])
        self.assertEqual(report['origin'], self.origin); self.assertEqual(len(report['receiptSha256']), 2)
        self.assertEqual(report['qualifiedAt'], self.acceptance['qualifiedAt'])

    def test_resolver_selecting_another_eligible_origin_is_failure_with_receipt(self):
        report = self.execute_restore(wrong_origin=True)
        self.assertEqual(report['status'], 'error'); self.assertIn('another qualification origin', report['error'])

    def test_workflow_uses_three_independent_pairs_readonly_and_diagnostic_names_only(self):
        workflow = (ROOT / '.github/workflows/benchmark-vm-reuse.yml').read_text()
        self.assertEqual(workflow.count('sample: [1, 2, 3]'), 2)
        self.assertEqual(workflow.count('max-parallel: 2'), 2)
        self.assertNotIn('packages: write', workflow); self.assertNotIn('secrets.', workflow)
        self.assertNotIn('force_qualification:', workflow)
        self.assertIn('qualification-benchmark-handoff-', workflow)
        self.assertNotIn('FINITE_QUALIFICATION_REUSE: "true"', workflow)
        self.assertNotIn('uses: ./.github/workflows/qualification.yml', workflow)

    def summary_fixture(self):
        original = self.baseline()
        current = dict(self.run, id=20, head_sha=self.execution, path='.github/workflows/benchmark-vm-reuse.yml')
        jobs = []
        for repetition in (1, 2, 3):
            for operation in ('restore', 'aggregate'):
                folder = self.directory / f'{operation}-{repetition}'; folder.mkdir()
                report = {'status': 'success', 'operation': operation, 'repetition': repetition, 'profile': self.args.profile,
                    'run': 20, 'attempt': 1, 'revision': self.execution, 'candidate': self.args.candidate, 'previous': self.args.previous,
                    'sourceRevision': self.source, 'buildIdentity': self.args.identity, 'baseline': original, 'origin': self.origin,
                    'productionReuseSourceSha256': '1' * 64, 'contextSourceSha256': '2' * 64, 'lockSha256': '3' * 64,
                    'qualificationContextSha256': M.REUSE.qualification.identity(self.context), 'publicationClearance': False,
                    'receiptSha256': {'fixture-acceptance.json': '4' * 64}, 'runnerImage': 'fixture'}
                (folder / 'benchmark.json').write_text(json.dumps(report))
                jobs.append(self.job(f'{operation}-{repetition}', 200 + len(jobs),
                    '15:00:00' if operation == 'restore' else '15:01:00',
                    '15:00:10' if operation == 'restore' else '15:01:20', current))
        class API:
            def read(api, path, paginated=False):
                return [{'jobs': jobs}] if '/jobs?' in path else current
        return API

    def test_summary_requires_complete_jobs_and_counts_setup_transport_and_postjobs(self):
        api = self.summary_fixture()
        args = argparse.Namespace(directory=self.directory, output=self.directory / 'summary.json')
        with patch.dict(os.environ, self.environment()), patch.object(M, 'API', api): M.summarize(args)
        result = json.loads(args.output.read_text())
        self.assertEqual(result['medianSummedRunnerSeconds'], 30)
        self.assertEqual(result['medianCriticalPathServiceSeconds'], 30)
        self.assertEqual(result['samples'][0]['elapsedIncludingQueueSeconds'], 80)
        self.assertEqual(result['baseline']['summedRunnerSeconds'], 3120)
        self.assertFalse(result['adoptionRecommended']); self.assertFalse(result['publicationClearance'])

    def test_summary_rejects_failure_changed_handoff_or_another_attempt(self):
        api = self.summary_fixture(); path = self.directory / 'aggregate-3/benchmark.json'
        saved = json.loads(path.read_text())
        for change in ({'status': 'error'}, {'attempt': 2}, {'receiptSha256': {'changed': '0' * 64}}):
            path.write_text(json.dumps(dict(saved, **change)))
            with patch.dict(os.environ, self.environment()), patch.object(M, 'API', api), self.assertRaises(ValueError):
                M.summarize(argparse.Namespace(directory=self.directory, output=self.directory / 'summary.json'))

    def test_summary_cli_keeps_explicit_failure_receipt_when_a_pair_is_missing(self):
        api = self.summary_fixture()
        (self.directory / 'aggregate-3/benchmark.json').unlink()
        output = self.directory / 'summary.json'
        with patch.dict(os.environ, self.environment()), patch.object(M, 'API', api), \
                patch.object(sys, 'argv', ['benchmark', 'summarize', str(self.directory), str(output)]), self.assertRaises(ValueError):
            M.main()
        failure = json.loads(output.read_text())
        self.assertEqual(failure['status'], 'error'); self.assertFalse(failure['adoptionRecommended'])
        self.assertFalse(failure['publicationClearance'])


if __name__ == '__main__': unittest.main()
