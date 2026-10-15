#!/usr/bin/env python3
"""Retain upstream PAM profile/features while adding Finite authentication."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MOCK = '''#!PYTHON
import json, pathlib, os, sys
path=pathlib.Path(os.environ['AUTH_STATE'])
state=json.loads(path.read_text())
args=sys.argv[1:]
state['calls'].append(args)
if args==['current','--raw']: print(' '.join(state['selected']))
elif args[:1]==['list-features']: print('\\n'.join(state['available']))
elif args[:1]==['enable-feature']: state['selected'].append(args[1])
elif args!=['check']: raise RuntimeError('Unexpected authselect mutation')
path.write_text(json.dumps(state))
'''


class Authentication(unittest.TestCase):
    def invoke(self, missing=None):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            mock = directory / 'authselect'
            mock.write_text(MOCK.replace('PYTHON', sys.executable, 1))
            mock.chmod(0o755)
            path = directory / 'state.json'
            features = ['with-silent-lastlog', 'with-mdns4', 'with-fingerprint', 'with-pam-u2f']
            path.write_text(json.dumps({'selected': ['custom/bluefin', 'with-faillock', 'with-fingerprint'],
                'available': [feature for feature in features if feature != missing], 'calls': []}))
            environment = dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'], AUTH_STATE=str(path))
            result = subprocess.run(['bash', str(ROOT / 'files/scripts/authselect.sh')], env=environment,
                                    text=True, capture_output=True, timeout=10)
            return result, json.loads(path.read_text())

    def test_preserves_custom_upstream_profile_and_existing_features(self):
        result, state = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state['selected'][0], 'custom/bluefin')
        self.assertIn('with-faillock', state['selected'])
        self.assertEqual(state['selected'].count('with-fingerprint'), 1)
        self.assertIn('with-pam-u2f', state['selected'])
        self.assertFalse(any(call[0] == 'select' or '--force' in call for call in state['calls']))

    def test_unsupported_required_feature_fails_before_any_mutation(self):
        result, state = self.invoke('with-pam-u2f')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not support required feature', result.stderr)
        self.assertFalse(any(call[0] == 'enable-feature' for call in state['calls']))


if __name__ == '__main__':
    unittest.main()
