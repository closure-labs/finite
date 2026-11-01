#!/usr/bin/env python3
"""Transport retries preserve authorization failure semantics and sanitized logs."""
from datetime import datetime, timezone
from email.utils import format_datetime
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
import github_retry as retry

ENDPOINT = 'repos/closure-labs/finite/git/ref/heads/main'


def reply(status=200, body=None, **headers):
    value = f'HTTP/2.0 {status} Result\r\nX-GitHub-Request-Id: 1234:ABCD\r\n'
    value += ''.join(key.replace('_', '-') + ': ' + str(val) + '\r\n' for key, val in headers.items())
    return subprocess.CompletedProcess([], 0 if status == 200 else 1,
                                       value + '\r\n' + json.dumps(body or {'ok': True}), 'secret fixture stderr')


def deterministic_clock(test):
    test.clock = Clock()
    test.enterContext(patch.object(api.time, 'monotonic', test.clock.monotonic))
    test.enterContext(patch.object(api.time, 'time', test.clock.wall))
    test.sleep = test.enterContext(patch.object(api.time, 'sleep', side_effect=test.clock.sleep))
    random = test.enterContext(patch.object(retry.random, 'SystemRandom'))
    random.return_value.uniform.return_value = .1


class Reads(unittest.TestCase):
    def setUp(self):
        deterministic_clock(self)

    def call(self, responses):
        self.run = self.enterContext(patch.object(api.subprocess, 'run', side_effect=responses))
        self.output = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        return api.get_json(ENDPOINT)

    def test_transient_failure_and_timeout_recover_without_logging_response(self):
        self.assertEqual(self.call([reply(502, {'secret': 'sensitive'}), subprocess.TimeoutExpired([], 30), reply()]), {'ok': True})
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1.1, 2.1])
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
                with self.assertRaisesRegex(api.GitHubReadError, f'HTTP {status}.*not retrying') as caught:
                    api.get_json(ENDPOINT)
                self.assertFalse(caught.exception.transient)
                self.assertEqual(run.call_count, 1)

    def test_rate_limit_retry_after_and_primary_reset(self):
        self.assertEqual(self.call([reply(403, Retry_After=3), reply(429, Retry_After=2), reply()]), {'ok': True})
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [3.1, 2.1])

    def test_secondary_without_server_delay_defers_without_another_call(self):
        with patch.object(api.subprocess, 'run', return_value=reply(429)) as run:
            with self.assertRaises(api.GitHubReadError) as caught:
                api.get_json(ENDPOINT)
            self.assertTrue(caught.exception.rate_limited)
            self.assertTrue(caught.exception.transient)
            self.assertEqual(run.call_count, 1)
            self.sleep.assert_not_called()

    def test_transport_timeout_shrinks_to_remaining_operation_budget(self):
        calls = []
        def transport(*args, **kwargs):
            calls.append(kwargs['timeout'])
            if len(calls) == 1:
                self.clock.now += 30
                raise subprocess.TimeoutExpired([], 30)
            return reply()
        with patch.object(api.subprocess, 'run', side_effect=transport):
            self.assertEqual(api.get_json(ENDPOINT), {'ok': True})
        self.assertEqual(calls[0], 30)
        self.assertAlmostEqual(calls[1], 13.9)

    def test_enclosing_operation_deadline_cannot_be_extended(self):
        with patch.object(api.subprocess, 'run', return_value=reply(503)) as run:
            with self.assertRaises(api.GitHubReadError):
                api.get_json(ENDPOINT, deadline=1)
            self.assertEqual(run.call_args.kwargs['timeout'], 1)
            self.sleep.assert_not_called()

    def test_signals_and_duplicate_retry_metadata_fail_without_retry(self):
        responses = [subprocess.CompletedProcess([], -15, '', 'PRIVATE_TOKEN'),
                     subprocess.CompletedProcess([], 1, 'HTTP/2 429 Limited\nRetry-After: 2\nRetry-After: 3\n\n{}', '')]
        for response in responses:
            with self.subTest(response=response.returncode), patch.object(api.subprocess, 'run', return_value=response) as run:
                with self.assertRaises(api.GitHubReadError) as caught:
                    api.get_json(ENDPOINT)
                self.assertFalse(caught.exception.transient)
                self.assertNotIn('PRIVATE_TOKEN', str(caught.exception))
                self.assertEqual(run.call_count, 1)

    def test_safe_rate_metadata_is_visible_without_raw_headers_or_body(self):
        with patch.object(api.subprocess, 'run', return_value=reply(403, {'secret': 'PRIVATE_BODY'},
                X_Ratelimit_Remaining=0, X_Ratelimit_Reset=1800003600)):
            with self.assertRaises(api.GitHubReadError) as caught:
                api.get_json(ENDPOINT)
            self.assertIn('rate-remaining=0', str(caught.exception))
            self.assertIn('rate-reset=1800003600', str(caught.exception))
            self.assertNotIn('PRIVATE_BODY', str(caught.exception))
            self.assertTrue(caught.exception.rate_limited)

    def test_late_success_cannot_escape_the_monotonic_budget(self):
        def late(*args, **kwargs):
            self.clock.now = 46
            return reply()
        with patch.object(api.subprocess, 'run', side_effect=late) as run:
            with self.assertRaises(api.GitHubReadError):
                api.get_json(ENDPOINT)
            self.assertEqual(run.call_count, 1)

    def test_valid_json_parse_crossing_deadline_is_classified_as_deadline(self):
        original = api.json.loads
        response = reply()
        def parse(raw):
            value = original(raw)
            self.clock.now = 46
            return value
        with patch.object(api.subprocess, 'run', return_value=response) as run, \
                patch.object(api.json, 'loads', side_effect=parse):
            with self.assertRaisesRegex(api.GitHubReadError, 'deadline') as caught:
                api.get_json(ENDPOINT)
            self.assertTrue(caught.exception.transient)
            self.assertEqual(run.call_count, 1)
            self.sleep.assert_not_called()

    def test_long_server_wait_exhausts_budget_without_sleeping(self):
        with patch.object(api.subprocess, 'run', return_value=reply(429, Retry_After=3600)) as run, \
                patch.object(api.time, 'sleep', side_effect=self.clock.sleep) as sleep:
            with self.assertRaisesRegex(api.GitHubReadError, 'budget exhausted'):
                api.get_json(ENDPOINT)
            self.assertEqual(run.call_count, 1)
            sleep.assert_not_called()

    def test_exhaustion_is_not_authorization(self):
        with self.assertRaisesRegex(api.GitHubReadError, 'attempt=3/3.*exhausted') as caught:
            self.call([reply(503)] * 3)
        self.assertTrue(caught.exception.transient)

    def test_missing_is_only_an_explicit_http_404(self):
        with patch.object(api.subprocess, 'run', return_value=reply(404)):
            self.assertIsNone(api.get_json(ENDPOINT, missing=True))
        with patch.object(api.subprocess, 'run', return_value=reply(401)):
            with self.assertRaises(api.GitHubReadError): api.get_json(ENDPOINT, missing=True)

    def test_malformed_or_oversized_success_is_never_retried(self):
        for output in ('HTTP/2.0 200 OK\n\ninvalid', '{}', 'HTTP/2.0 200 OK\n\n' + 'x' * (8 * 1024 * 1024)):
            with patch.object(api.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
                with self.assertRaises(api.GitHubReadError) as caught: api.get_json(ENDPOINT)
                self.assertEqual(run.call_count, 1)
                self.assertFalse(caught.exception.transient)


class PublicReads(unittest.TestCase):
    def setUp(self):
        deterministic_clock(self)

    def test_explicit_public_mode_preserves_status_checks(self):
        with patch.object(api, 'public_response', return_value=reply()) as read:
            self.assertEqual(api.get_json(ENDPOINT, public=True), {'ok': True})
            read.assert_called_once_with(ENDPOINT, timeout=30)

    def test_public_auth_failures_never_fall_back_or_retry(self):
        for status in (301, 302, 401, 403, 404):
            with self.subTest(status=status), \
                    patch.object(api, 'public_response', return_value=reply(status)) as read, \
                    patch.object(api.subprocess, 'run') as run:
                with self.assertRaises(api.GitHubReadError):
                    api.get_json(ENDPOINT, public=True)
                self.assertEqual(read.call_count, 1)
                run.assert_not_called()

    def test_public_transport_retries_bounded_and_keeps_response_private(self):
        with patch.object(api, 'public_response', side_effect=[subprocess.TimeoutExpired([], 30), reply()]), \
                patch.object(api.time, 'sleep', side_effect=self.clock.sleep) as sleep:
            self.assertEqual(api.get_json(ENDPOINT, public=True), {'ok': True})
            sleep.assert_called_once_with(1.1)

    def test_public_request_fixed_origin_no_auth_no_redirect_and_wall_limit(self):
        with patch.object(api.subprocess, 'run', return_value=reply()) as run:
            api.public_response(ENDPOINT)
            command = run.call_args.args[0]
            self.assertEqual(command[:2], ['curl', '--disable'])
            self.assertEqual(command[-1], 'https://api.github.com/' + ENDPOINT)
            self.assertEqual(command[command.index('--request') + 1], 'GET')
            self.assertNotIn('--location', command)
            self.assertNotIn('--user', command)
            self.assertIn('--suppress-connect-headers', command)
            self.assertIn('Cache-Control: no-cache', command)
            self.assertEqual(command[command.index('--proto') + 1], '=https')
            self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_public_oversized_and_invalid_json_fail_closed(self):
        for body in ['invalid', 'x' * (8 * 1024 * 1024 + 1)]:
            response = subprocess.CompletedProcess([], 0, 'HTTP/2 200 OK\n\n' + body, '')
            with patch.object(api, 'public_response', return_value=response):
                with self.assertRaises(api.GitHubReadError):
                    api.get_json(ENDPOINT, public=True)


# Portable policy contract from XO #212 at 109656e3767982c4adf9f766d1b7d719975e37ff.
class Clock:
    def __init__(self):
        self.now, self.epoch, self.delays = 0., 1800000000., []
    def monotonic(self):
        return self.now
    def wall(self):
        return self.epoch
    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay
    def budget(self, **kwargs):
        return retry.RetryBudget(clock=self.monotonic, wall=self.wall, sleep=self.sleep,
                                 jitter=lambda: .1, **kwargs)


class RetryContract(unittest.TestCase):
    def test_seconds_and_http_date_not_before(self):
        for value in [b'7', format_datetime(datetime.fromtimestamp(1800000007, timezone.utc), usegmt=True).encode()]:
            clock = Clock(); budget = clock.budget()
            self.assertTrue(budget.wait(1, 429, {b'retry-after': value}))
            self.assertEqual(clock.delays, [7.1])
            self.assertGreaterEqual(clock.now, 7)

    def test_primary_reset_and_retry_after_both_respected(self):
        clock = Clock(); budget = clock.budget()
        self.assertTrue(budget.wait(1, 403, {b'x-ratelimit-remaining': b'0',
            b'x-ratelimit-reset': b'1800000010', b'retry-after': b'3'}))
        self.assertEqual(clock.delays, [10.1])

    def test_primary_long_missing_malformed_or_stale_reset_never_sleeps(self):
        for reset in [None, b'invalid PRIVATE_TOKEN', b'1800000000', b'1800003600']:
            clock = Clock(); budget = clock.budget()
            headers = {b'x-ratelimit-remaining': b'0', b'x-ratelimit-reset': reset}
            self.assertFalse(budget.wait(1, 403, headers))
            self.assertEqual(clock.delays, [])
            self.assertNotIn('PRIVATE_TOKEN', budget.reason)

    def test_secondary_403_requires_throttle_or_server_delay(self):
        clock = Clock(); budget = clock.budget()
        self.assertTrue(budget.wait(1, 403, {b'retry-after': b'2'}, 'secondary-rate-limit'))
        self.assertEqual(clock.delays, [2.1])
        for status, category in [(403, 'secondary-rate-limit'), (429, None)]:
            clock = Clock(); budget = clock.budget()
            self.assertFalse(budget.wait(1, status, {}, category))  # >=60s cannot fit45s.
            self.assertEqual(clock.delays, [])

    def test_missing_throttle_header_uses_documented_minimum_with_larger_explicit_budget(self):
        clock = Clock(); budget = clock.budget(total=70)
        self.assertTrue(budget.wait(1, 429))
        self.assertEqual(clock.delays, [60.1])

    def test_permission_denial_and_unrelated_4xx_never_retry(self):
        for status in [301, 400, 401, 403, 404, 409, 422]:
            clock = Clock(); budget = clock.budget()
            self.assertFalse(budget.wait(1, status, {}, 'permission-denied'))
            self.assertEqual(clock.delays, [])

    def test_malformed_duplicate_negative_and_oversized_retry_after_fail_closed(self):
        for value in [None, b'-1', b'1.5', b'nan', b'PRIVATE_TOKEN', b'x' * 129, b'9' * 12,
                      b'Wed, 21 Oct 2015 07:28:00']:
            clock = Clock(); budget = clock.budget()
            self.assertFalse(budget.wait(1, 429, {b'retry-after': value}))
            self.assertEqual(clock.delays, [])

    def test_total_deadline_and_request_timeout_shrink_monotonically(self):
        clock = Clock(); budget = clock.budget(total=5)
        self.assertEqual(budget.remaining(), 5)
        clock.now = 2
        self.assertEqual(budget.remaining(), 3)
        self.assertFalse(budget.wait(1, 503, {b'retry-after': b'3'}))
        self.assertEqual(clock.delays, [])
        clock.now = 5
        with self.assertRaises(retry.RetryDeadline):
            budget.remaining()

    def test_wait_leaves_budget_and_attempts_are_bounded(self):
        clock = Clock(); budget = clock.budget(total=4)
        self.assertTrue(budget.wait(1, 503))
        self.assertTrue(budget.wait(2, 503))
        self.assertFalse(budget.wait(3, 503))
        self.assertEqual(clock.delays, [1.1, 2.1])
        self.assertGreater(budget.remaining(), 0)

    def test_positive_jitter_is_bounded_and_never_subtracts_server_delay(self):
        for injected, expected in [(-100, 2.05), (0, 2.05), (100, 2.25)]:
            clock = Clock(); budget = clock.budget(); budget.jitter = lambda: injected
            self.assertTrue(budget.wait(1, 503, {b'retry-after': b'2'}))
            self.assertEqual(clock.delays, [expected])
        clock = Clock(); budget = clock.budget(); budget.jitter = lambda: float('nan')
        self.assertFalse(budget.wait(1, 503))
        self.assertEqual(clock.delays, [])

    def test_wall_clock_jump_cannot_move_monotonic_deadline(self):
        clock = Clock(); budget = clock.budget()
        clock.epoch += 3600
        self.assertTrue(budget.wait(1, 429, {b'retry-after': b'2'}))
        self.assertEqual(budget.deadline, 45)
        self.assertAlmostEqual(budget.remaining(300), 42.9)

    def test_budget_arguments_and_no_transport_cap_expansion(self):
        for total in [0, -1, float('nan'), float('inf'), 301]:
            with self.assertRaises(ValueError):
                Clock().budget(total=total)
        budget = Clock().budget(total=100)
        self.assertEqual(budget.remaining(), 30)

class MetadataDiscovery(unittest.TestCase):
    endpoint = 'repos/closure-labs/finite/actions/runs/10/artifacts?per_page=100'

    def setUp(self):
        deterministic_clock(self)

    def page(self, start, count, total):
        return {'total_count': total, 'artifacts': [{'id': n} for n in range(start, start + count)]}

    def test_complete_pagination_uses_count_and_fixed_relative_endpoints(self):
        pages = [self.page(1, 100, 101), self.page(101, 1, 101)]
        with patch.object(api, 'get_json', side_effect=pages) as get:
            self.assertEqual(api.get_metadata(self.endpoint, collection='artifacts'), pages)
        self.assertEqual([c.args[0] for c in get.call_args_list],
                         [self.endpoint + '&page=1', self.endpoint + '&page=2'])
        self.assertEqual([c.kwargs['deadline'] for c in get.call_args_list], [150, 150])
        with patch.object(api, 'get_json', return_value=self.page(1, 100, 100)) as get:
            api.get_metadata(self.endpoint, collection='artifacts')
        self.assertEqual(get.call_count, 1, 'No redundant terminal empty-page request')

    def test_transient_page_retry_uses_existing_transport_then_continues(self):
        responses = [reply(502), reply(body=self.page(1, 100, 101)), reply(body=self.page(101, 1, 101))]
        with patch.object(api.subprocess, 'run', side_effect=responses) as run:
            result = api.get_metadata(self.endpoint, collection='artifacts')
        self.assertEqual(len(result), 2)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([c.args[0][-1] for c in run.call_args_list],
                         [self.endpoint + '&page=1', self.endpoint + '&page=1', self.endpoint + '&page=2'])
        self.assertEqual(self.sleep.call_count, 1)
        self.assertTrue(all(c.kwargs['timeout'] <= 30 for c in run.call_args_list))

    def test_jobs_and_caches_share_complete_listing_policy(self):
        for key in ('jobs', 'actions_caches', 'workflow_runs'):
            with self.subTest(collection=key), patch.object(api, 'get_json', return_value={'total_count': 0, key: []}) as get:
                self.assertEqual(api.get_metadata(self.endpoint, collection=key), [{'total_count': 0, key: []}])
            self.assertEqual(get.call_count, 1)

    def test_empty_page_is_complete_only_for_zero_native_count(self):
        with patch.object(api, 'get_json', return_value=self.page(1, 0, 0)):
            self.assertEqual(len(api.get_metadata(self.endpoint, collection='artifacts')), 1)
        with patch.object(api, 'get_json', return_value=self.page(1, 0, 1)), \
                self.assertRaisesRegex(api.GitHubReadError, 'incomplete'):
            api.get_metadata(self.endpoint, collection='artifacts')

    def test_count_drift_duplicates_and_truncated_pages_fail_closed(self):
        malformed = [self.page(1, 99, 100), {'total_count': True, 'artifacts': []},
                     {'total_count': 1, 'artifacts': [{'id': '1'}]},
                     {'total_count': 0, 'artifacts': [{'id': 1}]},
                     {'total_count': 101, 'artifacts': [{'id': n} for n in range(101)]}]
        for page in malformed:
            with self.subTest(page=page), patch.object(api, 'get_json', return_value=page), \
                    self.assertRaises(api.GitHubReadError):
                api.get_metadata(self.endpoint, collection='artifacts')
        for second in (self.page(101, 1, 102), self.page(1, 1, 101)):
            with patch.object(api, 'get_json', side_effect=[self.page(1, 100, 101), second]), \
                    self.assertRaises(api.GitHubReadError):
                api.get_metadata(self.endpoint, collection='artifacts')

    def test_page_cap_rejects_partial_inventory(self):
        with patch.object(api, 'get_json', side_effect=[self.page(1, 100, 201), self.page(101, 100, 201)]) as get:
            with api.metadata_operation() as operation, self.assertRaisesRegex(api.GitHubReadError, 'page limit'):
                operation.pages(self.endpoint, 'artifacts', max_pages=2)
        self.assertEqual(get.call_count, 2)

    def test_nested_scopes_share_read_limit_and_deadline_without_cross_operation_cache(self):
        with patch.object(api, 'get_json', return_value={'ok': True}) as get:
            with api.metadata_operation(total=50, max_reads=2) as parent:
                api.get_metadata(ENDPOINT)
                with api.metadata_operation(total=150, max_reads=120) as child:
                    self.assertIs(child, parent)
                    api.get_metadata(ENDPOINT)
                with self.assertRaisesRegex(api.GitHubReadError, 'read limit'):
                    api.get_metadata(ENDPOINT)
            api.get_metadata(ENDPOINT)
        self.assertEqual(get.call_count, 3, 'Repeat endpoints are fresh reads, not cached conclusions')
        self.assertEqual([c.kwargs['deadline'] for c in get.call_args_list], [50, 50, 150])
        self.assertIsNone(api._METADATA_OPERATION.get())

    def test_deadline_before_next_page_and_exception_cleanup(self):
        def first(*args, **kwargs):
            self.clock.now = 150
            return self.page(1, 100, 101)
        with patch.object(api, 'get_json', side_effect=first) as get, \
                self.assertRaisesRegex(api.GitHubReadError, 'deadline'):
            api.get_metadata(self.endpoint, collection='artifacts')
        self.assertEqual(get.call_count, 1)
        self.assertIsNone(api._METADATA_OPERATION.get())

    def test_paginated_throttle_cannot_outwait_enclosing_deadline(self):
        responses = [reply(body=self.page(1, 100, 101)), reply(429, Retry_After=2)]
        with patch.object(api.subprocess, 'run', side_effect=responses) as run, \
                api.metadata_operation(total=1), self.assertRaises(api.GitHubReadError) as caught:
            api.get_metadata(self.endpoint, collection='artifacts')
        self.assertTrue(caught.exception.rate_limited)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(c.kwargs['timeout'] <= 1 for c in run.call_args_list))
        self.sleep.assert_not_called()

    def test_plain_forbidden_on_page_one_is_terminal(self):
        with patch.object(api.subprocess, 'run', return_value=reply(403)) as run, \
                self.assertRaises(api.GitHubReadError) as caught:
            api.get_metadata(self.endpoint, collection='artifacts')
        self.assertFalse(caught.exception.transient)
        self.assertEqual(run.call_count, 1)
        self.sleep.assert_not_called()

    def test_untrusted_or_ambiguous_pagination_request_is_not_executed(self):
        invalid = ['https://evil.invalid/items?per_page=100', self.endpoint + '&page=2',
                   self.endpoint + '&per_page=100', self.endpoint.replace('100', '20')]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint), patch.object(api, 'get_json') as get, self.assertRaises(ValueError):
                api.get_metadata(endpoint, collection='artifacts')
            get.assert_not_called()
        for total, reads in ((0, 1), (float('nan'), 1), (301, 1), (150, True), (150, 0), (150, 301)):
            with self.assertRaises(ValueError): api.MetadataOperation(total, reads)


if __name__ == '__main__':
    unittest.main()
