#!/usr/bin/env python3
"""Exercise retry policy without network access or real delays."""
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('http_get', Path(__file__).resolve().parents[2] / 'scripts/ci/http-get.py')
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)
URL = 'https://api.github.com/repos/example/release'


def failure(code, headers=None):
    return HTTPError(URL, code, 'fixture', headers or {}, None)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.sleep = patch.object(http.time, 'sleep').start()
        patch.object(http.signal, 'alarm').start()
        self.addCleanup(patch.stopall)

    def test_transient_recovery_and_rate_limit(self):
        with patch.object(http, 'urlopen', side_effect=[failure(503), failure(429, {'Retry-After': '5'}), io.BytesIO(b'ok')]) as request:
            self.assertEqual(http.fetch(URL), b'ok')
            self.assertEqual(request.call_count, 3)
            self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 5])

    def test_exhaustion_and_transport_failure(self):
        for error in [URLError('offline'), TimeoutError(), failure(500)]:
            with self.subTest(error=error), patch.object(http, 'urlopen', side_effect=error) as request:
                with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                    http.fetch(URL)
                self.assertEqual(request.call_count, 4)

    def test_permanent_errors_and_missing_release(self):
        for code in [401, 403, 404]:
            with patch.object(http, 'urlopen', side_effect=failure(code)) as request:
                with self.assertRaisesRegex(RuntimeError, 'not retrying'):
                    http.fetch(URL)
                self.assertEqual(request.call_count, 1)
        with patch.object(http, 'urlopen', side_effect=failure(404)):
            with self.assertRaises(http.MissingRelease):
                http.fetch(URL, allow_missing=True)

    def test_rate_limit_cannot_exceed_budget(self):
        with patch.object(http, 'urlopen', side_effect=failure(429, {'Retry-After': '3600'})) as request:
            with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                http.fetch(URL)
            self.assertEqual(request.call_count, 1)
            self.sleep.assert_not_called()

    def test_redirects_do_not_forward_credentials_to_other_hosts(self):
        request = http.Request(URL, headers={'Authorization': 'Bearer fixture'})
        redirect = http.ScopedRedirect()
        for target in ['https://example.com/file', 'http://api.github.com/file']:
            with self.assertRaises(ValueError):
                redirect.redirect_request(request, None, 302, 'redirect', {}, target)

    def test_retry_after_parsing(self):
        self.assertEqual(http.retry_delay('nonsense', 2), 2)
        self.assertEqual(http.retry_delay('inf', 2), 2)
        self.assertEqual(http.retry_delay('-5', 2), 2)

    def test_credentials_are_explicit_and_scoped(self):
        with patch.dict(http.os.environ, {}, clear=True), patch.object(http, 'urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'requires GH_TOKEN'):
                http.fetch(URL, github=True)
            request.assert_not_called()
        with patch.dict(http.os.environ, {'GH_TOKEN': 'fixture'}), patch.object(http, 'urlopen', return_value=io.BytesIO(b'ok')) as request:
            self.assertEqual(http.fetch(URL, github=True), b'ok')
            self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer fixture')
            with self.assertRaises(ValueError):
                http.fetch('https://example.com/', github=True)


if __name__ == '__main__':
    unittest.main()
