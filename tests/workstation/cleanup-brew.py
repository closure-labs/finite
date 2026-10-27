#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cleanup', ROOT / 'scripts/workstation/cleanup-brew.py')
cleanup = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(cleanup)


class Cleanup(unittest.TestCase):
    def test_stock_user_requested_dependencies_and_uncertainty_are_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); bundle = directory / 'cli.Brewfile'; bundle.write_text('brew "stock"\n')
            policy = {'packages': [{'formula': name} for name in ('stock', 'personal', 'dependency', 'finite-only')]}
            installed = {'formulae': [{'name': name, 'installed': [{'installed_on_request': requested}],
                                      'dependencies': ['dependency'] if name == 'personal' else []}
                                     for name, requested in (('stock', False), ('personal', True),
                                                              ('dependency', False), ('finite-only', False))]}
            proof = {'schema': 1, 'installer': 'finite-brew-bootstrap', 'before': {'formulae': []}, 'after': installed}
            self.assertEqual(cleanup.inventory(policy, directory, installed)['removals'], [])
            preview = cleanup.inventory(policy, directory, installed, proof)
            self.assertEqual(preview['removals'], ['finite-only'])
            self.assertIn('upstream-bundle', preview['formulae'][0]['protectedBecause'])
            bundle.write_text('eval dynamic_ruby\n')
            self.assertEqual(cleanup.inventory(policy, directory, installed)['removals'], [])

    def test_empty_removal_list_is_valid_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); (directory / 'cli.Brewfile').write_text('brew "stock"\n')
            result = cleanup.inventory({'packages': [{'formula': 'stock'}]}, directory,
                {'formulae': [{'name': 'stock', 'installed': [{'installed_on_request': False}]}]})
            self.assertEqual(result['removals'], [])


if __name__ == '__main__': unittest.main()
