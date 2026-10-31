#!/usr/bin/env python3
"""Protected check corpus for the advisory selector's fail-closed boundary."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('selector', ROOT / 'scripts/ci/functional-selection.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def lock():
    return {'root': 'root', 'nodes': {'root': {'inputs': {'foundation': 'f'}},
        'f': {'locked': {'narHash': 'sha256-' + 'A' * 43 + '=', 'type': 'github', 'owner': 'closure-labs', 'repo': 'foundation', 'rev': 'a' * 40}, 'inputs': {'home-manager': 'hm'}},
        'hm': {'locked': {'narHash': 'sha256-' + 'B' * 43 + '=', 'type': 'github', 'owner': 'nix-community', 'repo': 'home-manager', 'rev': 'b' * 40}}}}

class Selection(unittest.TestCase):
    def test_current_lock_resolves_and_no_change_selects_none(self):
        current = json.loads((ROOT / 'flake.lock').read_text())
        self.assertIn('foundation', m.snapshot(current))
        self.assertTrue(any(p.endswith('/home-manager') for p in m.snapshot(current)))
        self.assertEqual(m.select([], current, current)['suites'], [])

    def test_home_manager_version_does_not_select_homebrew(self):
        before = lock(); after = copy.deepcopy(before)
        after['nodes']['hm']['locked']['rev'] = 'c' * 40
        value = m.select(['flake.lock'], before, after)
        self.assertEqual(value['suites'], ['home-manager'])
        self.assertEqual(value['resolvedInputs']['after']['foundation/home-manager']['rev'], 'c' * 40)

    def test_foundation_actual_export_boundaries(self):
        before = lock(); after = copy.deepcopy(before)
        after['nodes']['f']['locked']['rev'] = 'c' * 40
        for paths, expected in [(['modules/aspects/base/browser.nix'], m.ALL),
            (['modules/providers/homebrew/_assets/brew-packages.json'], m.ALL),
            (['scripts/home.py'], m.ALL), (['lib/new-export.nix'], m.ALL), (None, m.ALL)]:
            with self.subTest(paths=paths):
                self.assertEqual(set(m.select(['flake.lock'], before, after, paths)['suites']), expected)

    def test_missing_hash_or_replaced_input_identity_selects_all(self):
        for change in ({'owner': 'other'}, {'repo': 'other'}, {'narHash': None}, {'narHash': 'invalid'}):
            before = lock(); after = copy.deepcopy(before)
            after['nodes']['hm']['locked'].update(change)
            self.assertEqual(set(m.select(['flake.lock'], before, after)['suites']), m.ALL)
        before = lock(); after = copy.deepcopy(before)
        after['nodes']['hm']['locked'].update(type='tarball', url='https://api.flakehub.com/f/pinned/nix-community/home-manager/0.2605.1/01234567-89ab-cdef-0123-456789abcdef/source.tar.gz')
        self.assertEqual(m.select(['flake.lock'], before, after)['suites'], ['home-manager'])
        after['nodes']['hm']['locked']['url'] = 'https://api.flakehub.com/f/pinned/nix-community/home-manager/../../other/source.tar.gz'
        self.assertEqual(set(m.select(['flake.lock'], before, after)['suites']), m.ALL)
        malformed = lock(); malformed['nodes']['hm']['locked'] = {}
        self.assertEqual(set(m.select([], malformed, malformed)['suites']), m.ALL)
        before = lock(); after = copy.deepcopy(before)
        after['nodes']['f']['locked']['owner'] = 'other'
        self.assertEqual(set(m.select(['flake.lock'], before, after, ['modules/aspects/base/browser.nix'])['suites']), m.ALL)

    def test_shared_scripts_base_image_unknown_and_renames_fail_closed(self):
        for path in ('files/system/usr/lib/systemd/system/firstboot.service', 'sources/bluefin.json',
                     'scripts/ci/functional-selection.py', 'unknown', 'files/scripts/new-startup.sh'):
            self.assertEqual(set(m.select([path], lock(), lock())['suites']), m.ALL)

    def test_nix_runtime_and_manual_full_option(self):
        self.assertEqual(set(m.select(['sources/determinate-nix.json'], lock(), lock())['suites']), {'home-manager', 'nix-lifecycle'})
        self.assertEqual(set(m.select([], lock(), lock(), full=True)['suites']), m.ALL)
        self.assertEqual(m.select([], lock(), lock())['bootability'], 'always-independent')

    def test_follows_node_rename_and_opaque_graph(self):
        before = lock(); after = copy.deepcopy(before)
        after['nodes']['renamed'] = after['nodes'].pop('hm')
        after['nodes']['f']['inputs']['home-manager'] = 'renamed'
        self.assertEqual(m.select(['flake.lock'], before, after)['suites'], [])
        after['nodes']['root']['inputs']['alias'] = ['foundation', 'home-manager']
        self.assertEqual(m.snapshot(after)['alias'], after['nodes']['renamed']['locked'])
        for broken in ({}, {'root': 'missing', 'nodes': {}}, {'root': 'r', 'nodes': {'r': {'inputs': {'x': ['x']}}}}):
            self.assertEqual(set(m.select(['flake.lock'], before, broken)['suites']), m.ALL)

    def test_additions_removals_and_malformed_evidence(self):
        before = lock(); after = copy.deepcopy(before)
        del after['nodes']['f']['inputs']['home-manager']
        self.assertEqual(m.select(['flake.lock'], before, after)['suites'], ['home-manager'])
        after = copy.deepcopy(before); after['nodes']['hm']['locked'] = None
        self.assertEqual(set(m.select(['flake.lock'], before, after)['suites']), m.ALL)

if __name__ == '__main__': unittest.main()
