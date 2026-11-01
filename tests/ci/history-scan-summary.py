"""Fixed-count output and fail-closed history audit diagnostics; no network."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('history_summary', ROOT / 'scripts/ci/history_scan_summary.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class Summary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report = self.root / 'report.json'
        self.canary = 'PRIVATE_CANARY_NEVER_EMIT'
        self.finding = {'RuleID': 'generic-api-key', 'Commit': 'a' * 40, 'StartLine': 2,
                        'File': self.canary + '\n::error::path', 'Secret': self.canary,
                        'Match': self.canary, 'Message': self.canary, 'Fingerprint': self.canary}

    def run_summary(self, status, findings=None, raw=None):
        if findings is not None:
            self.report.write_text(json.dumps(findings))
        if raw is not None:
            self.report.write_bytes(raw)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/ci/history_scan_summary.py'),
                                 '--status', str(status), '--report', str(self.report)], capture_output=True, text=True)
        self.assertNotIn(self.canary, result.stdout + result.stderr)
        self.assertNotIn('::error::path', result.stdout + result.stderr)
        return result, json.loads(result.stdout)

    def test_clean_and_findings_are_distinct_and_only_counts_are_emitted(self):
        result, value = self.run_summary(0, [])
        self.assertEqual((result.returncode, value['verdict'], value['findingCount']), (0, 'clean', 0))
        other = dict(self.finding, RuleID='github-pat', Commit='b' * 40)
        result, value = self.run_summary(2, [self.finding, self.finding, other])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(value, {'schema': 1, 'verdict': 'findings', 'findingCount': 3,
            'genericApiKeyCount': 2, 'otherRuleFindingCount': 1, 'distinctRuleCount': 2,
            'distinctCommitCount': 2, 'distinctPathCount': 1})

    def test_errors_timeouts_and_unknown_exits_ignore_partial_reports(self):
        for status, verdict, code in [(1, 'scanner-error', 1), (124, 'timeout', 124),
                                     (137, 'interrupted', 1), (143, 'interrupted', 1), (7, 'unexpected-exit', 1)]:
            with self.subTest(status=status):
                result, value = self.run_summary(status, raw=self.canary.encode())
                self.assertEqual((result.returncode, value['verdict']), (code, verdict))
                self.assertIsNone(value['findingCount'])

    def test_missing_malformed_duplicate_and_contradictory_reports_fail_closed(self):
        result, value = self.run_summary(0)
        self.assertEqual((result.returncode, value['verdict']), (1, 'invalid-report'))
        for status, raw in [(0, b'null'), (2, b'[]'), (0, json.dumps([self.finding]).encode()),
                            (2, b'{'), (2, b'[{"RuleID":"one","RuleID":"two"}]'),
                            (2, b'[[NaN]]'), (2, b'\xff')]:
            with self.subTest(status=status, raw=raw[:20]):
                result, value = self.run_summary(status, raw=raw)
                self.assertEqual((result.returncode, value['verdict']), (1, 'invalid-report'))

    def test_arbitrary_rule_names_and_metadata_are_not_echoed(self):
        for changes in ({'RuleID': self.canary}, {'Commit': self.canary}, {'StartLine': True}, {'File': ''}):
            result, value = self.run_summary(2, [dict(self.finding, **changes)])
            self.assertEqual((result.returncode, value['verdict']), (1, 'invalid-report'))

    def test_byte_and_finding_budgets_are_enforced(self):
        self.report.write_text(json.dumps([self.finding]))
        with patch.object(summary, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            summary.summarize(2, self.report)
        with patch.object(summary, 'MAX_FINDINGS', 0), self.assertRaises(ValueError):
            summary.summarize(2, self.report)

    def test_workflow_keeps_full_default_scan_and_private_report_cleanup(self):
        job = yaml.safe_load((ROOT / '.github/workflows/repository-secret-history.yml').read_text())['jobs']['history']
        run = next(s['run'] for s in job['steps'] if 'log_opts=' in s.get('run', ''))
        for expected in ('--all --full-history --diff-merges=first-parent --text --no-ext-diff --no-textconv',
                         'useDefault = true', '--ignore-gitleaks-allow', '--redact=100', '--exit-code=2',
                         'umask 077', 'trap', '--report-path="$report"', 'history_scan_summary.py'):
            self.assertIn(expected, run)
        for forbidden in ('continue-on-error', '--baseline', 'allowlists'):
            self.assertNotIn(forbidden, yaml.safe_dump(job))
        uploads = [s for s in job['steps'] if 'upload-artifact@' in s.get('uses', '')]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]['with']['path'], '${{ runner.temp }}/finite-history-evidence/')
        self.assertNotIn('report', uploads[0]['with']['path'])
        self.assertEqual(run.count('--candidate . --check'), 2)
        self.assertIn('history_identifiers.py', run)
        self.assertIn('--require-complete-baseline', run)
        self.assertIn('history_frozen_refs.py', run)
        self.assertIn('>/dev/null 2>&1', run)
        engine = (ROOT / '.github/workflows/finding-id-fixtures.yml').read_text()
        self.assertIn('python3 tests/ci/history-scan-summary.py', engine)
        self.assertEqual(engine.count('      - scripts/ci/history_scan_summary.py'), 2)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached 8.30.1 engine unavailable')
    def test_real_engine_clean_and_synthetic_finding(self):
        binary = shutil.which('gitleaks')
        self.assertEqual(subprocess.check_output([binary, 'version'], text=True).strip(), '8.30.1')
        repository = self.root / 'repo'
        repository.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(repository), *args], check=True, capture_output=True)
        git('init', '-q');git('config', 'user.name', 'Fixture');git('config', 'user.email', 'fixture@example.invalid')
        (repository / 'file').write_text('ordinary data\n');git('add', '.');git('commit', '-qm', 'fixture')
        config = self.root / 'default.toml';config.write_text('[extend]\nuseDefault = true\n')
        ignore = self.root / 'ignore';ignore.write_text('')
        for expected in (0, 2):
            if expected:
                (repository / 'file').write_text('api_key = "' + 'AbcD0123efGH4567ijKL8901mnOP2345qrST6789' + '"\n')
                git('add', '.');git('commit', '-qm', 'synthetic')
            result = subprocess.run([binary, 'git', str(repository), '--config', str(config),
                '--gitleaks-ignore-path', str(ignore), '--ignore-gitleaks-allow', '--redact=100',
                '--no-banner', '--log-level=error', '--exit-code=2', '--report-format=json',
                '--report-path', str(self.report), '--log-opts=--all --full-history --text --no-ext-diff --no-textconv'],
                capture_output=True)
            self.assertEqual(result.returncode, expected)
            checked, value = self.run_summary(expected)
            self.assertEqual(checked.returncode, expected)
            self.assertEqual(value['verdict'], 'findings' if expected else 'clean')


if __name__ == '__main__':
    unittest.main()
