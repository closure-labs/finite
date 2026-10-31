#!/usr/bin/env python3
"""Keep maintenance and publication outside the full Home Manager evaluation."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
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

    def test_flakehub_publishing_is_disabled_in_every_workflow_and_installer(self):
        installers = 0
        for path in sorted((ROOT / '.github').rglob('*.yml')):
            def inspect(value):
                nonlocal installers
                if isinstance(value, dict):
                    uses = value.get('uses', '').lower()
                    self.assertNotIn('flakehub-push', uses, str(path))
                    self.assertNotIn('flakehub-cache', uses, str(path))
                    command = value.get('run', '').lower()
                    self.assertNotRegex(command, r'\b(?:fh|flakehub)\s+(?:push|publish)\b')
                    if uses.startswith('determinatesystems/determinate-nix-action@'):
                        installers += 1
                        for key in ('ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN'):
                            self.assertEqual(value['env'][key], '')
                    for item in value.values():
                        inspect(item)
                elif isinstance(value, list):
                    for item in value:
                        inspect(item)
            inspect(yaml.safe_load(path.read_text()))
        self.assertEqual(installers, 2)

    def test_publication_record_gate_precedes_reuse_and_both_vm_phases(self):
        publication = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())['jobs']
        self.assertNotIn('preflight', publication)
        qualification = publication['qualification']
        self.assertEqual(qualification['needs'], ['build', 'sign'])
        self.assertEqual(qualification['with']['build_evidence'], '${{ needs.build.outputs.evidence }}')
        self.assertEqual(publication['sign']['needs'], ['security', 'attest'])
        self.assertEqual(publication['promote']['needs'], ['build', 'security', 'sign', 'qualification'])
        jobs = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())['jobs']
        steps = jobs['prepare']['steps']
        gate = next(s for s in steps if s.get('name') == 'Reject obsolete publication before reuse or VM work')
        self.assertEqual(gate['if'], '${{ !inputs.validation_only }}')
        self.assertLess(steps.index(gate), next(i for i, s in enumerate(steps) if s.get('id') == 'reuse'))
        reuse = next(s for s in steps if s.get('id') == 'reuse')
        self.assertIn('--prepare-context', reuse['run'])
        self.assertNotIn('$/.github/actions/setup-vm-tools', [s.get('uses') for s in steps])
        self.assertEqual(jobs['phase']['needs'], 'prepare')
        # Exercise missing/mismatched artifacts, interrupted download, and a
        # rejected publication record. Each must prevent downstream VM work.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool in ('gh', 'nix'):
                script = root / tool
                script.write_text('#!/bin/sh\nprintf "%s\\n" "' + tool + '" >>"$CALLS"\nexit "$' + tool.upper() + '_STATUS"\n')
                script.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'CALLS': str(root / 'calls'), 'GH_STATUS': '0', 'NIX_STATUS': '0',
                   'PROFILE': 'finite', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                   'GITHUB_REPOSITORY': 'closure-labs/finite'}
            for artifact, gh_status, nix_status, expected in (
                ('', '0', '0', []), ('image-finite-123-1', '0', '0', []),
                ('image-finite-123-2', '1', '0', ['gh']),
                ('image-finite-123-2', '0', '1', ['gh', 'nix']),
                ('image-finite-123-2', '0', '0', ['gh', 'nix'])):
                with self.subTest(artifact=artifact, gh=gh_status, nix=nix_status):
                    (root / 'calls').unlink(missing_ok=True)
                    result = subprocess.run(['bash', '-c', gate['run']], cwd=root,
                        env={**env, 'IMAGE_ARTIFACT': artifact, 'GH_STATUS': gh_status, 'NIX_STATUS': nix_status},
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0,
                                     artifact == 'image-finite-123-2' and gh_status == nix_status == '0')
                    self.assertEqual((root / 'calls').read_text().splitlines() if (root / 'calls').exists() else [], expected)

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
        self.assertIn('nix build --accept-flake-config .#ci-update-locks', workflow)
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
        self.assertEqual(cache['with']['save'], "${{ inputs.job-profile == 'checks' && github.repository == 'closure-labs/finite' && github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') }}")
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

    def test_source_proof_lookup_gets_a_step_scoped_read_only_native_token(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        checks = workflow['jobs']['checks']
        self.assertEqual(checks['permissions'], {'contents': 'read', 'actions': 'read'})
        command = next(s for s in checks['steps'] if s.get('run') == 'python3 scripts/ci/nix-checks.py')
        self.assertEqual(command['env']['GH_TOKEN'], "${{ github.repository == 'closure-labs/finite' && github.event_name == 'push' && github.ref == 'refs/heads/main' && github.token || '' }}")
        self.assertNotIn('GH_TOKEN', workflow.get('env', {}))
        self.assertNotIn('GH_TOKEN', checks.get('env', {}))
        for step in checks['steps']:
            if step is not command:
                self.assertNotIn('GH_TOKEN', step.get('env', {}))




class CheckLauncher(unittest.TestCase):
    def invoke(self, mode):
        source = (ROOT / 'lib/ci-applications/repository-operations.nix').read_text()
        wrapper = source.split('  ciCheck =', 1)[1].split("    text = ''\n", 1)[1].split("    '';", 1)[0]
        wrapper = wrapper.replace("''${", '${')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'flake.nix').write_text('{}')
            tools = root / 'tools'
            tools.mkdir()
            log = root / 'calls'
            proof_file = root / 'proofs'
            proof_file.touch(mode=0o600)
            fixture = '#!' + sys.executable + '\n' + r'''
import json, os, pathlib, sys
mode = os.environ['FIXTURE_MODE']
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as output:
    output.write(json.dumps([pathlib.Path(sys.argv[0]).name, *args]) + '\n')
proof = sys.executable
if pathlib.Path(sys.argv[0]).name == 'readlink':
    print('/missing-proof' if mode == 'missing-proof' else proof)
elif 'eval' in args:
    names = ['first', 'second']
    if mode == 'empty-inventory': names = []
    if mode == 'duplicate-inventory': names = ['first', 'first']
    if mode == 'unsafe-inventory': names = ['../outside']
    drv = '/nix/store/' + 'a' * 32 + '-finite-ci-checks.drv'
    if mode == 'invalid-derivation': drv += '\n/nix/store/other.drv'
    print(json.dumps({'derivation': drv, 'names': names}))
elif 'build' in args:
    if mode == 'failed-build': sys.exit(1)
    print('/nix/store/' + 'b' * 32 + '-finite-ci-checks')
elif 'flake' in args:
    if mode == 'invalid-standard-output': sys.exit(1)
elif 'path-info' in args:
    print(json.dumps({proof: {'closureSize': 2**21 if mode == 'large-proof' else 1}}))
else:
    sys.exit(99)
'''
            for name in ('nix', 'readlink'):
                script = tools / name
                script.write_text(fixture)
                script.chmod(0o755)
            result = subprocess.run([shutil.which('bash'), '-euo', 'pipefail', '-c', wrapper],
                env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                     'FINITE_SOURCE_ROOT': directory, 'FINITE_CHECK_PROOFS_FILE': str(proof_file),
                     'GITHUB_ACTIONS': 'false', 'FIXTURE_MODE': mode, 'FIXTURE_LOG': str(log)},
                text=True, capture_output=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls, proof_file.read_text()

    def test_inventory_and_derivation_share_one_evaluation_and_all_proofs_are_checked(self):
        result, calls, proofs = self.invoke('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        evaluations = [call for call in calls if 'eval' in call]
        self.assertEqual(len(evaluations), 1)
        self.assertIn('checks.checkNames', evaluations[0][-1])
        self.assertEqual([call[1] for call in calls if call[0] == 'readlink'], ['-f', '-f'])
        self.assertEqual(len(proofs.splitlines()), 2)
        self.assertTrue(any('flake' in call and '--no-build' in call for call in calls))
        self.assertTrue(any('path-info' in call and '--closure-size' in call for call in calls))

    def test_invalid_inventory_and_failed_proofs_never_publish_a_handoff(self):
        for mode in ('empty-inventory', 'duplicate-inventory', 'unsafe-inventory', 'invalid-derivation',
                     'failed-build', 'missing-proof', 'large-proof', 'invalid-standard-output'):
            with self.subTest(mode=mode):
                result, calls, proofs = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(proofs, '')
                if mode.endswith('inventory') or mode == 'invalid-derivation':
                    self.assertFalse(any('build' in call for call in calls))


if __name__ == '__main__':
    unittest.main()
