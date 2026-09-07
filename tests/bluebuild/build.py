#!/usr/bin/env python3
"""Exercise the direct CLI's publication boundary without building an image."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BuildInvocation(unittest.TestCase):
    def invoke(self, publish='false', profile='bluefin-generic', **extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir = root / 'bin'
            bindir.mkdir()
            script = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open('calls.jsonl', 'a') as output:
    print(json.dumps({'command': [name, *sys.argv[1:]],
                      'key': os.environ.get('COSIGN_PRIVATE_KEY'),
                      'push': os.environ.get('BB_BUILD_PUSH'),
                      'no_sign': os.environ.get('BB_BUILD_NO_SIGN')}), file=output)
sys.exit(int(os.environ.get('BUILD_STATUS' if name == 'bluebuild' else 'LOGOUT_STATUS', '0')))
'''
            for name in ('bluebuild', 'docker'):
                tool = bindir / name
                tool.write_text('#!' + sys.executable + '\n' + script)
                tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'],
                   'BB_USERNAME': 'ci-test', 'BB_PASSWORD': 'test-token',
                   'COSIGN_PRIVATE_KEY': 'test-key',
                   'BB_BUILD_PUSH': 'true', 'BB_BUILD_NO_SIGN': 'true', **extra}
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/build.sh'), profile, publish],
                                    cwd=root, env=env, capture_output=True, text=True)
            calls_path = root / 'calls.jsonl'
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
            return result, calls

    def test_validation_never_pushes_or_receives_the_signing_key(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call['command'][:2], ['bluebuild', 'build'])
        self.assertEqual(call['command'][-1], 'recipes/bluefin-generic.yml')
        self.assertNotIn('--push', call['command'])
        self.assertIsNone(call['push'])
        self.assertIsNone(call['key'])

    def test_publication_keeps_caching_signing_and_registry_cleanup(self):
        result, calls = self.invoke(publish='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = calls[0]
        self.assertIn('--push', call['command'])
        self.assertIn('--cache-layers', call['command'])
        self.assertIn('--retry-push', call['command'])
        self.assertNotIn('--no-sign', call['command'])
        self.assertIsNone(call['no_sign'])
        self.assertEqual(call['key'], 'test-key')
        self.assertEqual(calls[-1]['command'], ['docker', 'logout', 'ghcr.io'])

    def test_missing_credentials_prevent_any_build(self):
        for missing in ('BB_USERNAME', 'BB_PASSWORD', 'COSIGN_PRIVATE_KEY'):
            with self.subTest(missing=missing):
                result, calls = self.invoke(publish='true', **{missing: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_cleanup_preserves_build_failure_even_when_logout_fails(self):
        result, calls = self.invoke(publish='true', BUILD_STATUS='42', LOGOUT_STATUS='1')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(calls[-1]['command'], ['docker', 'logout', 'ghcr.io'])

    def test_invalid_inputs_prevent_any_build(self):
        for args in ({'publish': 'yes'}, {'profile': '../../recipe'}):
            with self.subTest(args=args):
                result, calls = self.invoke(**args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
