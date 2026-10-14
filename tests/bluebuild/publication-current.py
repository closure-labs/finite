#!/usr/bin/env python3
"""Avoid expensive obsolete qualification without weakening final promotion."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('current', ROOT / 'scripts/bluebuild/publication-current.py')
current = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(current)


def reference(sha):
    return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': sha}}


class Preflight(unittest.TestCase):
    def test_exact_main_remains_eligible(self):
        with patch.object(current.publication, 'github', return_value=reference('a' * 40)):
            self.assertEqual(current.require_current('a' * 40), 'a' * 40)

    def test_runtime_changes_stop_work(self):
        with patch.object(current.publication, 'github', return_value=reference('b' * 40)), \
                patch.object(current.publication, 'documentation_only_advance', return_value=False), self.assertRaises(ValueError):
            current.require_current('a' * 40)

    def test_docs_only_requires_a_stable_ref(self):
        with patch.object(current.publication, 'github', side_effect=[reference('b' * 40), reference('c' * 40)]), \
                patch.object(current.publication, 'documentation_only_advance', return_value=True), self.assertRaises(ValueError):
            current.require_current('a' * 40)

    def test_malformed_reference_is_fatal(self):
        for value in [None, {}, {'object': None}, {'ref': 'refs/heads/main', 'object': {'sha': 'main'}}]:
            with self.subTest(value=value), patch.object(current.publication, 'github', return_value=value), \
                    self.assertRaises(ValueError):
                current.require_current('a' * 40)


if __name__ == '__main__':
    unittest.main()
