#!/usr/bin/env python3
"""Decision monitoring cannot grant authority or hide unavailable GitHub data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
import sys
import contextlib
import io
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('decision_health', ROOT / 'scripts/ci/decision-health.py')
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
BOT = 'finite-maintainer-decisions[bot]'
REPO = health.REPOSITORY


class Health(unittest.TestCase):
    def setUp(self):
        self.runs = [self.run_record(100, 'success', 1)]
        self.pulls = []
        self.files = {}
        self.issues = []
        self.writes = []

    def run_record(self, run_id, conclusion, hours):
        return {'id': run_id, 'status': 'completed', 'conclusion': conclusion,
                'head_branch': 'main', 'event': 'schedule', 'head_repository': {'full_name': REPO},
                'updated_at': (NOW - timedelta(hours=hours)).isoformat()}

    def pull(self, pr=12, hours=73, bot=BOT):
        return {'number': pr, 'user': {'login': bot, 'type': 'Bot'}, 'base': {'ref': 'main'},
                'head': {'repo': {'full_name': REPO}}, 'created_at': (NOW - timedelta(hours=hours)).isoformat()}

    def issue(self, number=9, bot=BOT):
        return {'number': number, 'title': health.TITLE, 'body': health.MARKER,
                'user': {'login': bot, 'type': 'Bot'}}

    def api(self, endpoint, method='GET', payload=None):
        if method != 'GET':
            self.writes.append((endpoint, method, payload))
            return {'number': 9}
        path = endpoint.split('?')[0]
        if path.endswith('/actions/workflows/image-security.yml/runs'):
            return {'workflow_runs': deepcopy(self.runs)}
        if path.endswith('/pulls'): return deepcopy(self.pulls)
        if path.endswith('/issues'): return deepcopy(self.issues)
        if '/pulls/' in path and path.endswith('/files'):
            return deepcopy(self.files.get(int(path.split('/')[-2]), []))
        raise AssertionError('Unexpected API endpoint: ' + endpoint)

    def inspect(self):
        return health.inspect(REPO, BOT, self.api, NOW)

    def test_healthy_closes_only_owned_health_issues(self):
        self.issues = [self.issue(), self.issue(10, 'other[bot]'), dict(self.issue(11), body='unowned')]
        report, issues = self.inspect()
        self.assertTrue(report['healthy'])
        health.reconcile(REPO, report, issues, self.api)
        self.assertEqual(len(self.writes), 1)
        self.assertTrue(self.writes[0][0].endswith('/issues/9'))
        self.assertEqual(self.writes[0][2]['state'], 'closed')

    def test_latest_failed_audit_alerts_despite_recent_success(self):
        self.runs.insert(0, self.run_record(101, 'failure', 0))
        report, issues = self.inspect()
        self.assertFalse(report['healthy'])
        self.assertIn('concluded failure', report['problems'][0])
        health.reconcile(REPO, report, issues, self.api)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0][1], 'POST')
        self.assertEqual(self.writes[0][2]['title'], health.TITLE)
        self.assertIn('/actions/runs/101', self.writes[0][2]['body'])

    def test_missing_and_stale_scan_fail_at_36_hour_boundary(self):
        for runs in ([], [self.run_record(100, 'success', 36)], [self.run_record(101, 'cancelled', 1)]):
            with self.subTest(runs=runs):
                self.runs = runs
                self.assertFalse(self.inspect()[0]['healthy'])

    def test_foreign_or_untrusted_runs_do_not_satisfy_freshness(self):
        for changed in ({'head_branch': 'branch'}, {'event': 'pull_request'},
                        {'head_repository': {'full_name': 'fork/finite'}}):
            self.runs = [{**self.run_record(100, 'success', 1), **changed}]
            self.assertFalse(self.inspect()[0]['healthy'])

    def test_only_stale_configured_bot_decision_prs_alert(self):
        self.pulls = [self.pull(), self.pull(13, 1), self.pull(14, 73, 'other[bot]'), self.pull(15)]
        self.files = {12: [{'filename': 'automation/decisions/security/' + 'a' * 64 + '.json'}],
                      15: [{'filename': 'flake.lock'}]}
        report, _ = self.inspect()
        self.assertEqual(report['pendingDecisionPRs'], [12])
        self.assertFalse(report['healthy'])

    def test_stale_release_decision_and_72_hour_boundary(self):
        self.pulls = [self.pull(12, 72)]
        self.files = {12: [{'filename': 'automation/decisions/releases/' + 'b' * 64 + '.json'}]}
        self.assertEqual(self.inspect()[0]['pendingDecisionPRs'], [12])

    def test_repeated_unhealthy_report_does_not_create_or_update_issue(self):
        self.runs = []
        report, _ = self.inspect()
        health.reconcile(REPO, report, [], self.api)
        body = self.writes[0][2]['body']
        self.writes.clear()
        health.reconcile(REPO, report, [dict(self.issue(), body=body)], self.api)
        self.assertEqual(self.writes, [])

    def test_duplicate_owned_issues_are_closed_without_changing_decisions(self):
        self.runs = []
        report, _ = self.inspect()
        health.reconcile(REPO, report, [self.issue(), self.issue(10)], self.api)
        self.assertEqual([method for _, method, _ in self.writes], ['PATCH', 'PATCH'])
        self.assertEqual(self.writes[-1][2]['state'], 'closed')
        self.assertTrue(all('/issues/' in endpoint for endpoint, _, _ in self.writes))

    def test_api_errors_never_produce_healthy_status_or_mutations(self):
        for failing_suffix in ('/runs', '/pulls', '/issues', '/files'):
            self.pulls = [self.pull()]
            def broken(endpoint, method='GET', payload=None):
                if endpoint.split('?')[0].endswith(failing_suffix):
                    raise health.HealthError('unavailable')
                return self.api(endpoint, method, payload)
            with self.subTest(endpoint=failing_suffix), self.assertRaises(health.HealthError):
                health.inspect(REPO, BOT, broken, NOW)
            self.assertEqual(self.writes, [])

    def test_collection_paginates_and_exhaustion_is_fatal(self):
        api_calls = []
        def api(endpoint):
            api_calls.append(endpoint)
            return [{}] * 100 if len(api_calls) == 1 else []
        self.assertEqual(len(health.collection(api, 'endpoint?state=open')), 100)
        self.assertIn('&per_page=100&page=2', api_calls[-1])
        with self.assertRaises(health.HealthError):
            health.collection(lambda endpoint: [{}] * 100, 'endpoint')

    def test_malformed_api_and_future_timestamps_are_fatal(self):
        with self.assertRaises(health.HealthError):
            health.collection(lambda endpoint: {'unexpected': []}, 'endpoint')
        self.runs = [self.run_record(100, 'success', -1)]
        with self.assertRaises(health.HealthError): self.inspect()

    def test_context_requires_main_repository_and_explicit_bot(self):
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': REPO}
        with patch.dict(os.environ, environment, clear=True):
            health.context(REPO, BOT)
            with self.assertRaises(health.HealthError): health.context(REPO, None)
            with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/branch'}):
                with self.assertRaises(health.HealthError): health.context(REPO, BOT)

    def test_cli_logs_only_fixed_health_status(self):
        report = {'healthy': False, 'problems': ['fixture-sensitive-value'], 'futureMetadata': 'fixture-sensitive-value'}
        output = io.StringIO()
        with patch.object(health, 'context'), patch.object(health, 'inspect', return_value=(report, [])), \
                patch.object(health, 'reconcile'), patch.object(sys, 'argv', ['decision-health.py']), \
                contextlib.redirect_stdout(output):
            self.assertEqual(health.main(), 0)
        self.assertNotIn('fixture-sensitive-value', output.getvalue())
        self.assertIn('needs attention', output.getvalue())

    def test_github_api_failure_timeout_and_invalid_json_are_fatal(self):
        for result in (subprocess.CompletedProcess([], 1, '', 'secret error'),
                       subprocess.CompletedProcess([], 0, 'invalid', '')):
            with patch.object(health.subprocess, 'run', return_value=result), self.assertRaises(health.HealthError):
                health.github('endpoint')
        with patch.object(health.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 60)), self.assertRaises(health.HealthError):
            health.github('endpoint')


if __name__ == '__main__':
    unittest.main()
