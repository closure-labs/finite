#!/usr/bin/env python3
"""Verify public cache settings without printing Nix credentials."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('nix_cache', ROOT / 'scripts/ci/nix-cache.py')
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)
CONFIG = {'extra-substituters': ['https://finite-os.cachix.org'],
          'extra-trusted-public-keys': ['finite-os.cachix.org-1:AAA=']}


class CachePolicy(unittest.TestCase):
    def test_verification_prints_no_credentials(self):
        actual = {'substituters': {'value': CONFIG['extra-substituters']},
                  'trusted-public-keys': {'value': CONFIG['extra-trusted-public-keys']},
                  'access-tokens': {'value': 'very-secret'}}
        output = io.StringIO()
        with patch.object(cache.subprocess, 'check_output', return_value=json.dumps(actual)), redirect_stdout(output):
            cache.verify(CONFIG)
        self.assertNotIn('very-secret', output.getvalue())

    def test_missing_applied_cache_is_fatal(self):
        with patch.object(cache.subprocess, 'check_output', return_value='{}'), self.assertRaises(ValueError):
            cache.verify(CONFIG)

    def test_policy_rejects_injected_private_settings(self):
        broken = dict(CONFIG, **{'extra-substituters': ['https://finite-os.cachix.org\naccess-tokens = secret']})
        with patch.object(cache.subprocess, 'check_output', return_value=json.dumps(broken)), self.assertRaises(ValueError):
            cache.policy()


if __name__ == '__main__':
    unittest.main()
