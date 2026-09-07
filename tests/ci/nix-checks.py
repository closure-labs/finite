#!/usr/bin/env python3
"""Exercise recovery from fetch failures and prompt failure for broken checks."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('nix_checks', ROOT / 'scripts/ci/nix-checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class RetryChecks(unittest.TestCase):
    def test_only_transport_errors_are_retriable(self):
        for error in ('unable to download archive: HTTP error 504',
                      'HTTP error 429', 'connection reset by peer',
                      "Couldn't resolve host name", 'TLS connect error'):
            with self.subTest(error=error):
                self.assertTrue(checks.transient(error))
        for error in ('error: builder for /nix/store/test.drv failed with exit code 1',
                      'Reason: builder failed with exit code 1', 'hash mismatch',
                      "error: attribute 'package' missing", 'syntax error',
                      'HTTP error 401', 'HTTP error 403', 'HTTP error 404',
                      'Permission denied'):
            with self.subTest(error=error):
                self.assertFalse(checks.transient('warning: HTTP error 503\n' + error))
        self.assertFalse(checks.transient('unknown failure'))

    def invoke(self, failures):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'command.py'
            script.write_text('''
import json, pathlib, sys
state = pathlib.Path(__file__).with_suffix('.json')
failures = json.loads(state.read_text())
if failures:
    message = failures.pop(0)
    state.write_text(json.dumps(failures))
    print(message)
    sys.exit(1)
print('checks passed')
''')
            import json
            script.with_suffix('.json').write_text(json.dumps(failures))
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(checks.time, 'sleep') as sleep:
                result = checks.build([sys.executable, str(script)])
            return result, output.getvalue(), sleep.call_args_list

    def test_transient_fetch_can_recover(self):
        result, output, sleeps = self.invoke(['error: HTTP error 504'])
        self.assertEqual(result, 0)
        self.assertIn('checks passed', output)
        self.assertEqual([call.args[0] for call in sleeps], [30])

    def test_retry_budget_is_bounded(self):
        result, output, sleeps = self.invoke(['error: HTTP error 503'] * 4)
        self.assertEqual(result, 1)
        self.assertEqual(output.count('error: HTTP error 503'), 3)
        self.assertEqual([call.args[0] for call in sleeps], [30, 60])

    def test_deterministic_failure_is_not_repeated(self):
        result, output, sleeps = self.invoke(['Reason: builder failed with exit code 1'])
        self.assertEqual(result, 1)
        self.assertNotIn('retrying', output)
        self.assertEqual(sleeps, [])


if __name__ == '__main__':
    unittest.main()
