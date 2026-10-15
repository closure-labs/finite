#!/usr/bin/env python3
"""Exercise SecretSpec profiles with fixture env values and a fake pass backend."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = tomllib.loads((ROOT / 'secretspec.toml').read_text())
FLAGS = {'FINITE_OPTIMIZED_CACHES', 'FINITE_CACHIX_WRITER', 'FINITE_REUSE_INVENTORY',
         'FINITE_GRYPE_DB_CACHE', 'FINITE_QUALIFICATION_REUSE', 'FINITE_QUALIFIED_ISO_PRESERVATION'}
SELECTOR = 'FINITE_QUALIFIED_ISO_CHANNELS'
PUBLIC_OPTIONS = FLAGS | {SELECTOR}
SPEC = importlib.util.spec_from_file_location('scoped_ci_options', ROOT / 'scripts/ci/ci-options.py')
OPTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OPTIONS)
DECLARED = {name for profile in MANIFEST['profiles'].values() for name in profile if name != 'defaults'}
CLI = os.environ.get('FINITE_TEST_SECRETSPEC') or shutil.which('secretspec')


class Manifest(unittest.TestCase):
    def test_current_workflow_and_catalog_choices_include_only_active_variants(self):
        channels = {'finite', 'finite-dev'}
        profiles = {'finite', 'finite-dev'}
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            inputs = (workflow.get(True, {}).get('workflow_dispatch') or {}).get('inputs', {})
            for name, value in inputs.items():
                choices = value.get('options', [])
                if set(choices) & channels:
                    with self.subTest(workflow=path.name, input=name):
                        self.assertEqual(set(choices) - {'automatic'}, channels)
                if set(choices) & profiles and name != 'target':
                    with self.subTest(workflow=path.name, input=name):
                        self.assertEqual(set(choices), profiles)
        audit = yaml.safe_load((ROOT / '.github/workflows/image-security.yml').read_text())
        self.assertEqual(set(audit['jobs']['audit']['strategy']['matrix']['channel']), channels)
        catalog = (ROOT / 'lib/domain-catalog.nix').read_text()
        for retired in ('bluefin-next', 'bluefin-dx-next', 'next-x86_64'):
            self.assertNotIn(retired, catalog)
        self.assertEqual(set(OPTIONS.CHANNEL_PROFILES), channels)
        self.assertEqual(set(OPTIONS.CHANNEL_PROFILES.values()), profiles)
        self.assertEqual(json.loads((ROOT / 'automation/qualification-recovery.json').read_text())['profiles'], {})

    def test_workflows_bootstrap_options_without_unsupported_composite_context(self):
        action = (ROOT / '.github/actions/setup-nix/action.yml').read_text()
        self.assertNotRegex(action, r'\bvars\.')
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            source = path.read_text()
            if './.github/actions/setup-nix' not in source:
                continue
            with self.subTest(workflow=path.name):
                values = yaml.safe_load(source).get('env', {})
                self.assertEqual({key: values.get(key) for key in PUBLIC_OPTIONS},
                                 {key: '${{ vars.' + key + ' }}' for key in PUBLIC_OPTIONS})

    def test_repository_pat_reaches_only_existing_updater_and_publishing_mappings(self):
        pat = '${{ secrets.MERGE_QUEUE_PAT }}'
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            with self.subTest(workflow=path.name):
                self.assertNotIn('secrets.MERGE_QUEUE_TOKEN', path.read_text())
        for name in ('update-home-release', 'update-flake-lock', 'update-determinate-nix',
                     'update-bluefin', 'queue-dependabot'):
            data = yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())
            steps = [step for job in data['jobs'].values() for step in job['steps']]
            setups = [step for step in steps if step.get('uses') == './.github/actions/setup-nix'
                      and 'merge-queue-token' in step.get('with', {})]
            with self.subTest(updater=name):
                self.assertEqual(len(setups), 1)
                setup = setups[0]
                self.assertEqual(setup['with']['merge-queue-token'], pat)
                self.assertEqual(setup['with']['require-merge-queue-token'], 'true')
        self.assertFalse((ROOT / '.github/workflows/update-kernel.yml').exists())
        for name in ('release', 'release-recovery'):
            data = yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())
            steps = data['jobs']['sign-release']['steps']
            publisher = next(step for step in steps if step.get('name') == 'Create draft release with durable evidence')
            signer = next(step for step in steps if step.get('name') == 'Sign release manifest in an isolated job')
            with self.subTest(publisher=name):
                self.assertEqual(publisher['env']['MERGE_QUEUE_TOKEN'], pat)
                self.assertIn('finite-ci-secrets-run release-publishing --', publisher['run'])
                self.assertNotIn('MERGE_QUEUE_TOKEN', signer.get('env', {}))
                self.assertNotIn('MERGE_QUEUE_PAT', signer.get('env', {}))
                self.assertNotIn('MERGE_QUEUE_PAT', data.get('env', {}))
                self.assertNotIn('MERGE_QUEUE_TOKEN', data.get('env', {}))

    def test_default_devenv_profile_contains_no_signing_or_github_credentials(self):
        self.assertEqual(set(MANIFEST['profiles']['default']), PUBLIC_OPTIONS | {'CACHIX_AUTH_TOKEN'})
        self.assertFalse(MANIFEST['profiles']['default']['CACHIX_AUTH_TOKEN']['required'])
        self.assertEqual(MANIFEST['providers']['local'], 'pass://')
        self.assertEqual(MANIFEST['providers']['github-actions'], 'env')
        self.assertNotIn('file:', (ROOT / 'secretspec.toml').read_text())
        for name in FLAGS:
            self.assertEqual(MANIFEST['profiles']['default'][name]['default'], 'false')
        self.assertEqual(MANIFEST['profiles']['default'][SELECTOR]['default'], 'finite')

    def test_iso_pilot_requires_enablement_and_the_exact_selected_channel(self):
        enabled = {'FINITE_QUALIFIED_ISO_PRESERVATION': 'true'}
        for channel, profile in OPTIONS.CHANNEL_PROFILES.items():
            with self.subTest(channel=channel):
                self.assertFalse(OPTIONS.iso_preservation_enabled(channel, {}))
                self.assertEqual(OPTIONS.iso_preservation_enabled(profile, enabled), channel == 'finite')
        selected = {**enabled, SELECTOR: 'finite-dev'}
        self.assertEqual(OPTIONS.options(selected)[SELECTOR], 'finite-dev')
        self.assertFalse(OPTIONS.iso_preservation_enabled('finite', selected))
        self.assertTrue(OPTIONS.iso_preservation_enabled('finite-dev', selected))
        for channel in OPTIONS.CHANNEL_PROFILES:
            self.assertTrue(OPTIONS.iso_preservation_enabled(channel, {**enabled, SELECTOR: 'all'}))

    def test_invalid_or_ambiguous_iso_scope_fails_before_export(self):
        for value in ('finite-next', 'finite-dev-next', 'finite,finite', 'finite-preview', 'all,finite', ',',
                      'finite-next\nCOSIGN_PRIVATE_KEY=injected'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OPTIONS.options({SELECTOR: value})
        for value in ('unknown', 'finite-next', 'finite-dev-next', 'bluefin-next', 'bluefin-dx-next'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OPTIONS.iso_preservation_enabled(value, {})

    def test_new_profiles_are_standalone_canonical_and_narrow(self):
        for profile in ('ci-options', 'cache-writer', 'image-signing', 'release-signing', 'release-publishing',
                        'repository-audit', 'repository-read', 'updater'):
            values = MANIFEST['profiles'][profile]
            self.assertFalse(values['defaults']['inherit'])
            self.assertEqual(set(values) - {'defaults'}, set(MANIFEST['scopes'][profile]['secrets']))
            self.assertTrue(all('ref' not in value for key, value in values.items() if key != 'defaults'))
        self.assertTrue(MANIFEST['profiles']['cache-writer']['CACHIX_AUTH_TOKEN']['required'])
        self.assertTrue(MANIFEST['profiles']['image-signing']['COSIGN_PRIVATE_KEY']['required'])
        self.assertTrue(MANIFEST['profiles']['release-signing']['COSIGN_PRIVATE_KEY']['required'])
        self.assertTrue(MANIFEST['profiles']['repository-read']['GH_TOKEN']['required'])
        self.assertTrue(MANIFEST['profiles']['repository-audit']['SECAUDIT_PEM']['required'])
        self.assertEqual(MANIFEST['profiles']['github-actions']['MERGE_QUEUE_TOKEN']['ref']['item'],
                         'GITHUB_ACTIONS_MERGE_QUEUE_TOKEN')

    def test_compatible_cli_is_pinned_without_replacing_committed_locks(self):
        package = (ROOT / 'lib/secretspec.nix').read_text()
        pin = json.loads((ROOT / 'sources/secretspec.json').read_text())
        self.assertGreaterEqual(tuple(map(int, pin['version'].split('.')[:2])), (0, 19))
        self.assertIn('github.com/cachix/secretspec/releases/download/v' + pin['version'] + '/', pin['url'])
        self.assertRegex(pin['sha256'], r'^(?:[0-9a-f]{64}|sha256-[A-Za-z0-9+/]{43}=)$')
        self.assertIn('inherit (pin) url sha256;', package)
        self.assertNotIn('latest', pin['url'])

    def test_tasks_keep_realization_secret_free_and_signing_explicit(self):
        tasks = (ROOT / 'devenv-tasks.nix').read_text()
        self.assertIn('env -u CACHIX_AUTH_TOKEN -u COSIGN_PRIVATE_KEY', tasks)
        self.assertIn('FINITE_CACHE_PUSH=false', tasks)
        self.assertIn('#local-cache', tasks)
        self.assertIn('"ci:cache:benchmark"', tasks)
        self.assertIn('IMAGE_REFERENCE:?set IMAGE_REFERENCE to the immutable image to sign', tasks)
        self.assertIn('"ci-repository-security-audit" "repository-read"', tasks)
        self.assertIn('"scanner-tools" "image-signing"', tasks)
        self.assertIn('"scanner-tools" "release-signing"', tasks)


@unittest.skipUnless(CLI, 'SecretSpec CLI is supplied by the packaged contract check')
class Resolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        version = subprocess.check_output([CLI, '--version'], text=True, timeout=10).strip().split()[-1]
        if tuple(map(int, version.split('.')[:2])) < (0, 19):
            raise AssertionError('Manifest scopes and standalone profiles require SecretSpec >= 0.19')

    def run_cli(self, directory, profile, *, values=None, provider='github-actions', command=None):
        env = {key: value for key, value in os.environ.items()
               if key not in DECLARED and not key.startswith(('SECRETSPEC_', 'PASSWORD_STORE_', 'GITHUB_ACTIONS_'))}
        env.update(HOME=str(directory), XDG_CONFIG_HOME=str(directory / 'config'),
                   PASSWORD_STORE_DIR=str(directory / 'empty-password-store'))
        env.update(values or {})
        if command is None:
            command = [sys.executable, '-c',
                       'import json,os; print(json.dumps({k:os.environ[k] for k in ' + repr(sorted(DECLARED)) + ' if k in os.environ}))']
        return subprocess.run([CLI, 'run', '--file', str(ROOT / 'secretspec.toml'), '--profile', profile,
                               '--scope', profile, '--provider', provider, '--reason', 'Finite fixture test',
                               '--', *command], env=env, text=True, capture_output=True, timeout=30)

    def test_options_default_false_without_credentials_and_strip_inherited_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_cli(Path(temporary), 'ci-options', values={
                'COSIGN_PRIVATE_KEY': 'fixture-only-private-key', 'SECAUDIT_PEM': 'fixture-only-app-key',
                'CACHIX_AUTH_TOKEN': 'fixture-only-cache-token', 'MERGE_QUEUE_TOKEN': 'fixture-only-updater'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {**{name: 'false' for name in FLAGS}, SELECTOR: 'finite'})
            self.assertNotIn('fixture-only', result.stdout)

    def test_signing_and_read_scopes_never_inherit_other_task_credentials(self):
        values = {'COSIGN_PRIVATE_KEY': 'fixture-key', 'CACHIX_AUTH_TOKEN': 'fixture-cache',
                  'GH_TOKEN': 'fixture-read', 'MERGE_QUEUE_TOKEN': 'fixture-updater', 'SECAUDIT_PEM': 'fixture-audit'}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            signed = self.run_cli(directory, 'release-signing', values=values)
            self.assertEqual(signed.returncode, 0, signed.stderr)
            self.assertEqual(set(json.loads(signed.stdout)), {'COSIGN_PRIVATE_KEY', 'COSIGN_PASSWORD'})
            read = self.run_cli(directory, 'repository-read', values=values)
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(json.loads(read.stdout), {'GH_TOKEN': 'fixture-read'})

    def test_updater_derives_github_cli_token_only_inside_updater_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_cli(Path(temporary), 'updater', values={
                'MERGE_QUEUE_TOKEN': 'fixture-updater', 'GH_TOKEN': 'wrong-parent-token',
                'COSIGN_PRIVATE_KEY': 'excluded-key'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'MERGE_QUEUE_TOKEN': 'fixture-updater', 'GH_TOKEN': 'fixture-updater'})

    def test_release_publishing_derives_cli_token_without_signing_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_cli(Path(temporary), 'release-publishing', values={
                'MERGE_QUEUE_TOKEN': 'fixture-publisher', 'GH_TOKEN': 'wrong-parent-token',
                'COSIGN_PRIVATE_KEY': 'excluded-key'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'MERGE_QUEUE_TOKEN': 'fixture-publisher', 'GH_TOKEN': 'fixture-publisher'})

    def test_missing_required_credentials_prevent_child_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / 'child-ran'
            command = [sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()']
            for profile in ('cache-writer', 'image-signing', 'release-signing', 'release-publishing', 'repository-read', 'repository-audit', 'updater'):
                result = self.run_cli(directory, profile, command=command)
                self.assertNotEqual(result.returncode, 0, profile)
                self.assertFalse(marker.exists())

    def test_local_alias_and_pass_provider_use_the_same_profile_key_without_real_store_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            mock = directory / 'bin'
            mock.mkdir()
            log = directory / 'pass-requests.jsonl'
            script = mock / 'pass'
            script.write_text('#!' + sys.executable + '\n'
                'import json,os,sys\n'
                'with open(os.environ["FIXTURE_PASS_LOG"],"a") as log: log.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'if sys.argv[1:] == ["show", "secretspec/finite/cache-writer/CACHIX_AUTH_TOKEN"]:\n'
                ' print("fixture-pass-cache"); raise SystemExit(0)\n'
                'raise SystemExit(1)\n')
            script.chmod(0o755)
            values = {'PATH': str(mock) + os.pathsep + os.environ['PATH'], 'FIXTURE_PASS_LOG': str(log)}
            for provider in ('local', 'pass'):
                result = self.run_cli(directory, 'cache-writer', values=values, provider=provider)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'CACHIX_AUTH_TOKEN': 'fixture-pass-cache'})
            requests = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(requests, [['show', 'secretspec/finite/cache-writer/CACHIX_AUTH_TOKEN']] * 2)

    def test_options_only_github_export_does_not_mask_or_persist_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            github_env = directory / 'github-env'
            result = self.run_cli(directory, 'ci-options', values={
                'FINITE_REUSE_INVENTORY': 'true', 'COSIGN_PRIVATE_KEY': 'fixture-private',
                'GITHUB_ACTIONS': 'true', 'GITHUB_ENV': str(github_env)},
                command=[sys.executable, str(ROOT / 'scripts/ci/ci-options.py'), '--github-env'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['FINITE_REUSE_INVENTORY'], 'true')
            self.assertEqual({line.split('=')[0] for line in github_env.read_text().splitlines()}, PUBLIC_OPTIONS)
            self.assertNotIn('add-mask', result.stdout)
            self.assertNotIn('fixture-private', github_env.read_text())
            invalid = self.run_cli(directory, 'ci-options', values={'FINITE_REUSE_INVENTORY': 'true\nCOSIGN_PRIVATE_KEY=bad'},
                                   command=[sys.executable, str(ROOT / 'scripts/ci/ci-options.py')])
            self.assertNotEqual(invalid.returncode, 0)
            before = github_env.read_text()
            invalid_scope = self.run_cli(directory, 'ci-options', values={
                SELECTOR: 'finite-next\nCOSIGN_PRIVATE_KEY=injected', 'GITHUB_ACTIONS': 'true',
                'GITHUB_ENV': str(github_env)},
                command=[sys.executable, str(ROOT / 'scripts/ci/ci-options.py'), '--github-env'])
            self.assertNotEqual(invalid_scope.returncode, 0)
            self.assertEqual(github_env.read_text(), before)


class PublishingWrapper(unittest.TestCase):
    def test_actual_resolver_wrapper_removes_provider_variable_before_publisher(self):
        source = (ROOT / 'lib/ci-applications/repository-operations.nix').read_text()
        wrapper = source.split('  ciSecretsRun = ', 1)[1].split("    text = ''\n", 1)[1].split("    '';", 1)[0].replace("''${", '${')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); tool = directory / 'secretspec'
            tool.write_text('#!' + sys.executable + '\n'
                'import os,sys\n'
                'if sys.argv[1:] == ["--version"]: print("secretspec 0.19.2"); raise SystemExit\n'
                'args=sys.argv[1:]; assert args[args.index("--profile")+1] == "release-publishing"\n'
                'assert args[args.index("--scope")+1] == "release-publishing"\n'
                'os.environ["GH_TOKEN"]=os.environ["MERGE_QUEUE_TOKEN"]\n'
                'child=args[args.index("--")+1:]; os.execvp(child[0],child)\n')
            tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                   'GITHUB_ACTIONS': 'true', 'FINITE_SOURCE_ROOT': str(ROOT),
                   'MERGE_QUEUE_TOKEN': 'fixture-publisher', 'GH_TOKEN': 'wrong-parent'}
            result = subprocess.run([shutil.which('bash'), '-euo', 'pipefail', '-c', wrapper, 'fixture-wrapper',
                'release-publishing', '--', sys.executable, '-c',
                'import os; assert "MERGE_QUEUE_TOKEN" not in os.environ; assert os.environ["GH_TOKEN"] == "fixture-publisher"'],
                env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


class LocalCache(unittest.TestCase):
    def wrapper(self):
        # Evaluate the wrapper's shell behavior with fixture commands, without
        # realizing the Nix package, running checks, resolving pass or pushing.
        source = (ROOT / 'lib/ci-applications/repository-operations.nix').read_text()
        return source.split('  mkLocalCache = ciApplication:', 1)[1].split("      text = ''\n", 1)[1].split("      '';", 1)[0]

    def test_check_proof_handoff_is_written_after_successful_size_checks(self):
        source = (ROOT / 'lib/ci-applications/repository-operations.nix').read_text()
        checks = source.split('  mkCheck = checks:', 1)[1].split('  mkLocalCache', 1)[0]
        self.assertLess(checks.index('closure_size > max_closure_size'), checks.index('printf \'%s\\n\''))
        self.assertIn('! -L "$FINITE_CHECK_PROOFS_FILE"', checks)
        self.assertIn('-O "$FINITE_CHECK_PROOFS_FILE"', checks)
        self.assertIn("$(stat -c '%a' \"$FINITE_CHECK_PROOFS_FILE\") == 600", checks)

    def test_local_cache_resolves_credentials_only_after_success_and_cleans_proof_file(self):
        shell = shutil.which('bash')
        proof = str(Path(sys.executable).parents[1])
        if not proof.startswith('/nix/store/'):
            self.skipTest('The Nix contract check supplies an existing fixture store root')
        for outcome in ('success', 'check-failure', 'bad-path', 'empty', 'upload-failure'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                tools = directory / 'tools'
                (tools / 'bin').mkdir(parents=True)
                (directory / 'flake.nix').write_text('{}')
                log = directory / 'calls.jsonl'
                check = tools / 'bin/finite-ci-check'
                check.write_text('#!' + sys.executable + '\n'
                    'import json,os,pathlib,sys\n'
                    'keys=(' + ','.join(repr(key) for key in ('CACHIX_AUTH_TOKEN','COSIGN_PRIVATE_KEY','GH_TOKEN','SECAUDIT_PEM')) + ')\n'
                    'assert not any(key in os.environ for key in keys)\n'
                    'assert os.environ["FINITE_CACHE_PUSH"] == "false"\n'
                    'path=pathlib.Path(os.environ["FINITE_CHECK_PROOFS_FILE"])\n'
                    'assert path.stat().st_mode & 0o777 == 0o600\n'
                    'with open(os.environ["FIXTURE_LOG"],"a") as log: log.write(json.dumps({"stage":"check","proofFile":str(path)})+"\\n")\n'
                    'mode=os.environ["FIXTURE_OUTCOME"]\n'
                    'if mode == "check-failure": raise SystemExit(7)\n'
                    'if mode != "empty": path.write_text(("/tmp/not-a-proof" if mode=="bad-path" else os.environ["FIXTURE_PROOF"])+"\\n")\n')
                check.chmod(0o755)
                spec = tools / 'bin/secretspec'
                spec.write_text('#!' + sys.executable + '\n'
                    'import json,os,sys\n'
                    'args=sys.argv[1:]\n'
                    'assert args[0]=="run" and args[args.index("--profile")+1]=="local-cache"\n'
                    'assert args[args.index("--scope")+1]=="cachix"\n'
                    'assert "CACHIX_AUTH_TOKEN" not in os.environ\n'
                    'assert args[args.index("--")+1:] == ["cachix","push","--omit-deriver","finite-os",os.environ["FIXTURE_PROOF"]]\n'
                    'with open(os.environ["FIXTURE_LOG"],"a") as log: log.write(json.dumps({"stage":"upload"})+"\\n")\n'
                    'raise SystemExit(8 if os.environ["FIXTURE_OUTCOME"]=="upload-failure" else 0)\n')
                spec.chmod(0o755)
                wrapper = self.wrapper().replace('${ciApplication}', str(tools)).replace(
                    '${pkgs.lib.escapeShellArg cacheName}', "'finite-os'").replace("''${", '${')
                env = {**os.environ, 'PATH': str(tools / 'bin') + os.pathsep + os.environ['PATH'],
                       'FINITE_SOURCE_ROOT': str(directory), 'TMPDIR': str(directory),
                       'FIXTURE_LOG': str(log), 'FIXTURE_OUTCOME': outcome, 'FIXTURE_PROOF': proof,
                       'CACHIX_AUTH_TOKEN': 'inherited-fixture', 'COSIGN_PRIVATE_KEY': 'inherited-fixture',
                       'GH_TOKEN': 'inherited-fixture', 'SECAUDIT_PEM': 'inherited-fixture',
                       'FINITE_SECRETS_PROVIDER': 'local'}
                result = subprocess.run([shell, '-euo', 'pipefail', '-c', wrapper], env=env,
                                        text=True, capture_output=True, timeout=30)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(calls[0]['stage'], 'check')
                self.assertFalse(Path(calls[0]['proofFile']).exists())
                if outcome in ('success', 'upload-failure'):
                    self.assertEqual([call['stage'] for call in calls], ['check', 'upload'])
                    self.assertEqual(result.returncode, 0 if outcome == 'success' else 8, result.stderr)
                else:
                    self.assertEqual(len(calls), 1)
                    self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
