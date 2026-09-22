#!/usr/bin/env python3
"""Keep maintenance and publication outside the full Home Manager evaluation."""
from pathlib import Path
import json
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class Toolchain(unittest.TestCase):
    def test_registry_jobs_and_secret_mapping_use_the_lightweight_entry(self):
        for path in [ROOT / '.github/actions/setup-nix/action.yml',
                     *sorted((ROOT / '.github/workflows').glob('*.yml'))]:
            document = yaml.safe_load(path.read_text())
            jobs = document.get('jobs', {'action': document.get('runs', {})})
            for job in jobs.values():
                for step in job.get('steps', []):
                    command = step.get('run', '')
                    with self.subTest(path=path.name, step=step.get('name')):
                        self.assertNotIn('nix develop .#ci', command)
                        self.assertNotIn('nix develop .#release', command)
                        for tool in ['ci-github-actions-secrets', 'ci-queue-dependabot', 'ci-trusted-update']:
                            if tool in command:
                                self.assertIn('nix shell --file lib/ci-tools.nix ' + tool, command)

    def test_store_cache_preserves_sources_and_only_full_checks_save(self):
        action = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())
        cache = next(s for s in action['runs']['steps']
                     if s.get('uses', '').startswith('nix-community/cache-nix-action@'))
        self.assertEqual(set(cache['with']['paths'].splitlines()), {
            '~/.cache/nix/tarball-cache-v2', '~/.cache/nix/gitv3',
            '~/.cache/nix/fetcher-cache-v4.sqlite*',
        })
        self.assertNotEqual(cache['with'].get('nix'), 'false')
        self.assertNotIn('gc-max-store-size', cache['with'])
        self.assertEqual(cache['with']['save'], "${{ github.job == 'checks' }}")
        self.assertIn("hashFiles('flake.lock'", cache['with']['primary-key'])
        self.assertTrue(cache['with']['primary-key'].startswith(
            cache['with']['restore-prefixes-first-match']))

    def test_gen_hub_locks_one_revision_per_library(self):
        hubs = []
        for name in ['flake.lock', 'templates/home-manager/flake.lock']:
            lock = json.loads((ROOT / name).read_text())
            nodes = lock['nodes']
            hub = nodes[nodes[lock['root']]['inputs']['gen']]
            hubs.append(hub['locked'])
            self.assertEqual(hub['inputs']['nixpkgs'], ['nixpkgs'])
            libraries = [node['locked']['repo'] for node in nodes.values()
                         if node.get('locked', {}).get('owner') == 'sini']
            with self.subTest(lock=name):
                self.assertGreater(len(libraries), 1)
                self.assertEqual(len(libraries), len(set(libraries)))
        self.assertEqual(*hubs)

    def test_full_checks_and_kernel_freshness_remain_required(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        self.assertTrue(any(s.get('run') == 'python3 scripts/ci/nix-checks.py'
                            for s in workflow['jobs']['checks']['steps']))
        self.assertFalse(workflow['jobs']['checks'].get('continue-on-error', False))
        kernel = yaml.safe_load((ROOT / '.github/workflows/update-kernel.yml').read_text())
        self.assertTrue(any(s.get('run') == 'python3 scripts/ci/kernel-update.py --check'
                            for s in kernel['jobs']['freshness']['steps']))


if __name__ == '__main__':
    unittest.main()
