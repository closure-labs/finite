#!/usr/bin/env python3
"""Transport retries preserve authorization failure semantics and sanitized logs."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/ci'))
import github_api as api

ENDPOINT = 'repos/closure-labs/finite/git/ref/heads/main'


def reply(status=200, body=None, **headers):
    value = f'HTTP/2.0 {status} Result\r\nX-GitHub-Request-Id: 1234:ABCD\r\n'
    value += ''.join(key.replace('_', '-') + ': ' + str(val) + '\r\n' for key, val in headers.items())
    return subprocess.CompletedProcess([], 0 if status == 200 else 1,
                                       value + '\r\n' + json.dumps(body or {'ok': True}), 'secret fixture stderr')


class Reads(unittest.TestCase):
    def call(self, responses):
        self.run = self.enterContext(patch.object(api.subprocess, 'run', side_effect=responses))
        self.sleep = self.enterContext(patch.object(api.time, 'sleep'))
        self.output = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        return api.get_json(ENDPOINT)

    def test_transient_failure_and_timeout_recover_without_logging_response(self):
        self.assertEqual(self.call([reply(502, {'secret': 'sensitive'}), subprocess.TimeoutExpired([], 30), reply()]), {'ok': True})
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [2, 4])
        self.assertIn('request=1234:ABCD', self.output.getvalue())
        self.assertNotIn('sensitive', self.output.getvalue())
        self.assertNotIn('secret fixture', self.output.getvalue())
        for call in self.run.call_args_list:
            self.assertEqual(call.args[0][2:4], ['--method', 'GET'])
            self.assertIn('Cache-Control: no-cache', call.args[0])
            self.assertLessEqual(call.kwargs['timeout'], 30)

    def test_permission_and_authentication_fail_once(self):
        for status in (401, 403, 404, 422):
            with self.subTest(status=status), patch.object(api.subprocess, 'run', return_value=reply(status)) as run:
                with self.assertRaisesRegex(api.GitHubReadError, f'HTTP {status}.*not retrying'):
                    api.get_json(ENDPOINT)
                self.assertEqual(run.call_count, 1)

    def test_rate_limit_retry_after_and_primary_reset(self):
        self.assertEqual(self.call([reply(403, Retry_After=3), reply(429), reply()]), {'ok': True})
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [3, 4])
        with patch.object(api.time, 'time', return_value=100):
            self.assertEqual(api.delay_seconds({'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '108'}, 2), 8)

    def test_long_server_wait_exhausts_budget_without_sleeping(self):
        with patch.object(api.subprocess, 'run', return_value=reply(429, Retry_After=3600)) as run, \
                patch.object(api.time, 'sleep') as sleep:
            with self.assertRaisesRegex(api.GitHubReadError, 'budget exhausted'):
                api.get_json(ENDPOINT)
            self.assertEqual(run.call_count, 1)
            sleep.assert_not_called()

    def test_exhaustion_is_not_authorization(self):
        with self.assertRaisesRegex(api.GitHubReadError, 'attempt=3/3.*exhausted'):
            self.call([reply(503)] * 3)

    def test_missing_is_only_an_explicit_http_404(self):
        with patch.object(api.subprocess, 'run', return_value=reply(404)):
            self.assertIsNone(api.get_json(ENDPOINT, missing=True))
        with patch.object(api.subprocess, 'run', return_value=reply(401)):
            with self.assertRaises(api.GitHubReadError): api.get_json(ENDPOINT, missing=True)

    def test_malformed_or_oversized_success_is_never_retried(self):
        for output in ('HTTP/2.0 200 OK\n\ninvalid', '{}', 'HTTP/2.0 200 OK\n\n' + 'x' * (8 * 1024 * 1024)):
            with patch.object(api.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
                with self.assertRaises(api.GitHubReadError): api.get_json(ENDPOINT)
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
