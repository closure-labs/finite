#!/usr/bin/env python3
"""Keep maintenance and publication outside the full Home Manager evaluation."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class Toolchain(unittest.TestCase):
    def test_cachix_actions_and_runners_are_retired(self):
        def inspect(value):
            if isinstance(value, dict):
                if 'uses' in value:
                    self.assertFalse(value['uses'].lower().startswith('cachix/'), value['uses'])
                if 'runs-on' in value:
                    self.assertNotIn('cachix', json.dumps(value['runs-on']).lower())
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        for path in sorted((ROOT / '.github').rglob('*.yml')):
            with self.subTest(path=path.relative_to(ROOT)):
                inspect(yaml.safe_load(path.read_text()))

    def test_scanner_profile_is_optional_and_requires_actual_native_tools(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/image.yml').read_text())
        step = next(s for s in workflow['jobs']['build']['steps']
                    if 'scanner-tools --no-link' in s.get('run', ''))
        self.assertEqual(step['if'], 'inputs.diagnostic_security')
        self.assertNotIn('nix develop', step['run'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host, tools = root / 'host', root / 'tools'
            host.mkdir()
            (tools / 'bin').mkdir(parents=True)
            shell = shutil.which('bash')
            (host / 'nix').write_text('#!' + shell + '\nprintf "%s\\n" "$TEST_TOOLS"\n')
            (host / 'nix').chmod(0o755)
            for tool in ('python3', 'umoci', 'syft', 'grype'):
                p = tools / 'bin' / tool
                p.write_text('#!' + shell + '\nexit 0\n')
                p.chmod(0o755)
            env = {**os.environ, 'PATH': str(host) + os.pathsep + os.environ['PATH'],
                   'TEST_TOOLS': str(tools), 'GITHUB_PATH': str(root / 'path')}
            run = lambda: subprocess.run([shell, '-euo', 'pipefail', '-c', step['run']],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(run().returncode, 0)
            (tools / 'bin/umoci').unlink()
            self.assertNotEqual(run().returncode, 0)

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
                        for tool in ['ci-github-actions-secrets', 'ci-queue-dependabot', 'ci-trusted-update',
                                     'ci-source-update', 'ci-lock-validate']:
                            if tool in command:
                                self.assertTrue(('nix shell --file lib/ci-tools.nix ' + tool) in command or ('nix build --file lib/ci-tools.nix ' + tool) in command)

    def test_lightweight_updates_reuse_existing_implementations(self):
        entry = (ROOT / 'lib/ci-tools.nix').read_text()
        for tool, filename in [('ci-source-update', 'update-determinate-nix.nix'),
                               ('ci-lock-validate', 'validate-locks.nix')]:
            self.assertIn(f'{tool} = import ./ci-applications/{filename} {{inherit pkgs;}};', entry)
        # The lock updater retains its exact flake-provided devenv package and
        # transitive input graph; do not silently substitute nixpkgs.devenv.
        workflow = (ROOT / '.github/workflows/update-flake-lock.yml').read_text()
        self.assertIn('nix shell --accept-flake-config .#ci-update-locks', workflow)
        self.assertNotIn('ci-update-locks =', entry)

    def test_image_tools_are_realized_once_without_development_shells(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/image.yml').read_text())
        steps = workflow['jobs']['build']['steps']
        preparations = [step for step in steps if 'image-tools --no-link' in step.get('run', '')]
        self.assertEqual(len(preparations), 1)
        prepare_index = steps.index(preparations[0])
        self.assertLess(prepare_index, next(i for i, step in enumerate(steps) if step.get('id') == 'prepare'))
        self.assertFalse(any('nix develop' in step.get('run', '') for step in steps))
        packages = (ROOT / 'lib/ci-shells.nix').read_text()
        self.assertIn('packages = ciPackages;', packages)
        self.assertIn('paths = ciPackages;', packages)
        self.assertIn('pathsToLink = ["/bin"];', packages)
        self.assertIn('[bash coreutils cosign file git gh jq ripgrep skopeo]', packages)

    def test_tool_path_preserves_host_nix_and_installed_bluebuild(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/image.yml').read_text())
        step = next(s for s in workflow['jobs']['build']['steps']
                    if 'image-tools --no-link' in s.get('run', ''))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = root / 'host'
            tools = root / 'tools'
            host.mkdir()
            (tools / 'bin').mkdir(parents=True)
            path_file = root / 'github-path'
            shell = shutil.which('bash')
            for path, body in [(host / 'nix', 'printf "%s\\n" "$TEST_TOOLS"'),
                               (host / 'bluebuild', 'exit 0'),
                               (tools / 'bin/python3', 'exit 0')]:
                path.write_text('#!' + shell + '\n' + body + '\n')
                path.chmod(0o755)
            env = {**os.environ, 'PATH': str(host) + os.pathsep + os.environ['PATH'],
                   'TEST_TOOLS': str(tools), 'GITHUB_PATH': str(path_file)}
            result = subprocess.run([shell, '-euo', 'pipefail', '-c', step['run']], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path_file.read_text().splitlines(), [str(tools / 'bin')])
            env['PATH'] = str(tools / 'bin') + os.pathsep + env['PATH']
            for command in ('nix', 'bluebuild'):
                self.assertEqual(shutil.which(command, path=env['PATH']), str(host / command))
            # An accidentally exported replacement client/CLI must fail setup.
            for command in ('nix', 'bluebuild'):
                shadow = tools / 'bin' / command
                shadow.write_text('unexpected bundled client')
                result = subprocess.run([shell, '-euo', 'pipefail', '-c', step['run']], env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                shadow.unlink()

    def test_store_cache_preserves_sources_and_only_full_checks_save(self):
        action = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())
        cache = next(s for s in action['runs']['steps']
                     if s.get('uses', '').startswith('nix-community/cache-nix-action@'))
        self.assertEqual(set(cache['with']['paths'].splitlines()), {
            '~/.cache/nix/tarball-cache-v2', '~/.cache/nix/gitv3',
            '~/.cache/nix/fetcher-cache-v4.sqlite*',
        })
        self.assertNotEqual(cache['with'].get('nix'), 'false')
        self.assertIn('gc-max-store-size-linux', cache['with'])
        self.assertEqual(cache['with']['save'], "${{ github.job == 'checks' && github.repository == 'closure-labs/finite' && github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') }}")
        self.assertIn("hashFiles('flake.lock'", cache['with']['primary-key'])
        self.assertIn('nix-checks-v3-', cache['with']['primary-key'])
        self.assertIn("inputs.cache-mode == 'baseline'", cache['with']['primary-key'])
        self.assertNotIn('github.sha', cache['with']['primary-key'].split("|| format('nix-checks-v3-")[1])
        self.assertIn("format('nix-checks-v3-", cache['with']['restore-prefixes-first-match'])
        self.assertIn("inputs.cache-mode != 'baseline'", cache['with']['restore-prefixes-first-match'])
        source_cache = next(s for s in action['runs']['steps'] if s.get('id') == 'source-cache')
        self.assertIs(source_cache['with']['nix'], False)
        self.assertNotIn('/nix', source_cache['with']['paths'].splitlines())
        self.assertIn("inputs.cache-mode == 'optimized'", source_cache['if'])
        self.assertNotIn('FINITE_OPTIMIZED_CACHES', source_cache['if'])

    def test_gen_hub_locks_one_revision_per_library(self):
        hubs = []
        for name in ['flake.lock']:
            lock = json.loads((ROOT / name).read_text())
            nodes = lock['nodes']
            hub = nodes[nodes[lock['root']]['inputs']['gen']]
            hubs.append(hub['locked'])
            self.assertEqual(hub['inputs']['nixpkgs'], ['nixpkgs'])
            reachable = set()
            def visit(name):
                if not isinstance(name, str) or name in reachable:
                    return
                reachable.add(name)
                for child in nodes[name].get('inputs', {}).values():
                    visit(child)
            visit(nodes[lock['root']]['inputs']['gen'])
            libraries = [nodes[name]['locked']['repo'] for name in reachable
                         if nodes[name].get('locked', {}).get('owner') == 'sini']
            with self.subTest(lock=name):
                self.assertGreater(len(libraries), 1)
                self.assertEqual(len(libraries), len(set(libraries)))
        self.assertEqual(len(hubs), 1)

    def test_full_checks_remain_required_and_kernel_follows_bluefin(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        self.assertTrue(any(s.get('run') == 'python3 scripts/ci/nix-checks.py'
                            for s in workflow['jobs']['checks']['steps']))
        self.assertFalse(workflow['jobs']['checks'].get('continue-on-error', False))
        self.assertFalse((ROOT / '.github/workflows/update-kernel.yml').exists())
        self.assertFalse((ROOT / 'sources/kernel-next.json').exists())



if __name__ == '__main__':
    unittest.main()
