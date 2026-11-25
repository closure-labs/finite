#!/usr/bin/env python3
"""Validate matched whole-job writer preparation evidence without running Nix."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('writer_benchmark', ROOT / 'scripts/ci/benchmark-cache-writer.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
SHA = 'a' * 40
ENV = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
       'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': SHA,
       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}


def roots(mode):
    tools = [{'kind': 'tool', 'name': name, 'path': '/nix/store/' + str(index) * 32 + '-tool', 'bytes': 100}
             for index, name in enumerate(benchmark.cache.TOOLS, 1)]
    return tools + ([{'kind': 'proof', 'name': 'check', 'path': '/nix/store/' + 'b' * 32 + '-proof', 'bytes': 10}]
                    if mode == 'legacy' else [])


def fixtures():
    reports, jobs = [], []
    for mode in benchmark.MODES:
        for repetition in (1, 2, 3):
            reports.append({'schema': 1, 'mode': mode, 'repetition': repetition, 'status': 'success',
                            'revision': SHA, 'lockSha256': 'c' * 64, 'runId': '123', 'runAttempt': '2',
                            'nixVersion': 'nix fixture',
                            'runner': {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageVersion': 'fixture'},
                            'passes': [{'phase': phase, 'seconds': 5 if mode == 'candidate' else 20,
                                        'transport': {'receivedBytes': 100}, 'roots': roots(mode)}
                                       for phase in ('cold', 'warm')]})
            jobs.append({'name': f'writer-{mode}-{repetition}', 'status': 'completed', 'conclusion': 'success',
                         'run_id': 123, 'run_attempt': 2, 'head_sha': SHA,
                         'started_at': '2026-10-14T21:00:00Z', 'completed_at': '2026-10-14T21:01:00Z'})
    return reports, [{'jobs': jobs}]


class Receipts(unittest.TestCase):
    def summarize(self, reports, jobs):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, report in enumerate(reports):
                folder = directory / str(index)
                folder.mkdir()
                (folder / 'benchmark.json').write_text(json.dumps(report))
            jobs_file = directory / 'jobs.json'
            jobs_file.write_text(json.dumps(jobs))
            output = directory / 'summary.md'
            with patch.dict(os.environ, {}, clear=True):
                benchmark.summarize(directory, jobs_file, output)
            return output.read_text()

    def test_matching_tools_and_successful_whole_jobs_summarize(self):
        content = self.summarize(*fixtures())
        self.assertIn('| candidate | 60.00 | 5.00 | 5.00 |', content)
        self.assertIn('| legacy | 60.00 | 20.00 | 20.00 |', content)
        self.assertIn('cannot authorize automatic writing', content)
        self.assertIn('queue wait is excluded', content)

    def test_missing_duplicate_failed_and_changed_source_reports_rejected(self):
        reports, jobs = fixtures()
        variants = [reports[:-1], reports + reports[:1]]
        for field, value in [('status', 'error'), ('revision', 'd' * 40), ('lockSha256', 'd' * 64),
                             ('nixVersion', 'other'), ('runAttempt', '1'), ('repetition', True)]:
            altered = copy.deepcopy(reports)
            altered[0][field] = value
            variants.append(altered)
        for altered in variants:
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                self.summarize(altered, jobs)

    def test_different_tool_output_size_and_extra_proof_rejected(self):
        reports, jobs = fixtures()
        for field, value in [('path', '/nix/store/' + 'e' * 32 + '-tool'), ('bytes', 101)]:
            altered = copy.deepcopy(reports)
            altered[-1]['passes'][1]['roots'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.summarize(altered, jobs)
        altered = copy.deepcopy(reports)
        altered[-1]['passes'][0]['roots'].append(roots('legacy')[-1])
        with self.assertRaises(ValueError):
            self.summarize(altered, jobs)

    def test_incomplete_or_invalid_passes_rejected(self):
        reports, jobs = fixtures()
        for passes in ([], reports[0]['passes'][1:], list(reversed(reports[0]['passes']))):
            altered = copy.deepcopy(reports)
            altered[0]['passes'] = passes
            with self.subTest(passes=passes), self.assertRaises(ValueError):
                self.summarize(altered, jobs)
        for seconds in (-1, True, float('nan'), float('inf')):
            altered = copy.deepcopy(reports)
            altered[0]['passes'][0]['seconds'] = seconds
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.summarize(altered, jobs)

    def test_whole_job_receipt_must_be_unique_successful_matching_attempt(self):
        reports, jobs = fixtures()
        variants = [[{'jobs': jobs[0]['jobs'][:-1]}], [{'jobs': jobs[0]['jobs'] + jobs[0]['jobs'][:1]}]]
        for field, value in [('status', 'in_progress'), ('conclusion', 'failure'),
                             ('head_sha', 'd' * 40), ('run_attempt', 1), ('run_id', 124)]:
            altered = copy.deepcopy(jobs)
            altered[0]['jobs'][0][field] = value
            variants.append(altered)
        for altered in variants:
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                self.summarize(reports, altered)

    def test_hosted_boundary_and_credentials_precede_all_realization(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(benchmark.subprocess, 'check_output', return_value=SHA):
            benchmark.hosted()
        for env in ({**ENV, 'GITHUB_ACTIONS': 'false'}, {**ENV, 'GITHUB_REPOSITORY': 'fork/finite'},
                    {**ENV, 'GITHUB_EVENT_NAME': 'pull_request'}, {**ENV, 'CACHIX_AUTH_TOKEN': 'fixture'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), \
                    patch.object(benchmark.subprocess, 'check_output') as command, self.assertRaises(ValueError):
                benchmark.hosted()
            command.assert_not_called()
        with patch.dict(os.environ, ENV, clear=True), patch.object(benchmark.subprocess, 'check_output', return_value='b' * 40), \
                self.assertRaises(ValueError):
            benchmark.hosted()

    def test_candidate_benchmark_does_not_call_publication_or_push(self):
        with tempfile.TemporaryDirectory() as temporary:
            start, output = Path(temporary) / 'start.json', Path(temporary) / 'benchmark.json'
            start.write_text('{}')
            with patch.dict(os.environ, ENV, clear=True), patch.object(benchmark, 'hosted'), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='nix fixture'), \
                    patch.object(benchmark.metrics, 'snapshot', return_value={}), \
                    patch.object(benchmark.metrics, 'delta', return_value={'seconds': 1}), \
                    patch.object(benchmark.cache, 'diagnostic_roots', return_value=roots('candidate')) as realize, \
                    patch.object(benchmark.cache, 'push') as push, patch.object(benchmark.cache, 'boundary') as publication:
                benchmark.benchmark('candidate', 1, start, output)
            self.assertEqual(realize.call_count, 2)
            realize.assert_called_with(include_proofs=False, batch=True)
            push.assert_not_called()
            publication.assert_not_called()
            self.assertEqual(json.loads(output.read_text())['status'], 'success')

    def test_benchmark_retains_failure_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            start, output = Path(temporary) / 'start.json', Path(temporary) / 'benchmark.json'
            start.write_text('{}')
            with patch.dict(os.environ, ENV, clear=True), patch.object(benchmark, 'hosted'), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='nix fixture'), \
                    patch.object(benchmark.metrics, 'snapshot', return_value={}), \
                    patch.object(benchmark.metrics, 'delta', return_value={'seconds': 1}), \
                    patch.object(benchmark.cache, 'diagnostic_roots', side_effect=ValueError('bad output')), self.assertRaises(ValueError):
                benchmark.benchmark('legacy', 1, start, output)
            record = json.loads(output.read_text())
            self.assertEqual(record['status'], 'error')
            self.assertEqual(record['error'], 'bad output')


    def test_benchmark_retains_sanitized_identity_shape_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            start, output = Path(temporary) / 'start.json', Path(temporary) / 'benchmark.json'
            start.write_text('{}')
            diagnostics = {'metadataType': 'dict', 'tools': {'image-tools': {
                'recordType': 'str', 'stringLength': 65, 'stringIsStorePath': True,
                'problems': ['record-not-object']}}}
            with patch.dict(os.environ, ENV, clear=True), patch.object(benchmark, 'hosted'), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='nix fixture'), \
                    patch.object(benchmark.metrics, 'snapshot', return_value={}), \
                    patch.object(benchmark.metrics, 'delta', return_value={'seconds': 1}), \
                    patch.object(benchmark.cache, 'diagnostic_roots', side_effect=benchmark.cache.ToolIdentityError(diagnostics)), \
                    self.assertRaises(benchmark.cache.ToolIdentityError):
                benchmark.benchmark('candidate', 1, start, output)
            record = json.loads(output.read_text())
            self.assertEqual(record['status'], 'error')
            self.assertEqual(record['identityDiagnostics'], diagnostics)
            self.assertEqual(record['passes'], [])


if __name__ == '__main__':
    unittest.main()
