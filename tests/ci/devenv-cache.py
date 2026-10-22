#!/usr/bin/env python3
"""Check native cache root selection, credential boundaries and upload verdicts."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_cache', ROOT / 'scripts/ci/devenv_cache.py')
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)
STORE = '/nix/store/' + 'a' * 32 + '-proof'
HASH = 'sha256-' + 'a' * 43 + '='


class NativeCache(unittest.TestCase):
    def test_native_build_receives_only_validated_roots_and_backend_secret(self):
        captures = []

        def build(command, **kwargs):
            directory = Path(kwargs['cwd'])
            captures.append(directory)
            self.assertEqual(command, ['devenv', '--no-tui', '--no-eval-cache', 'build', 'outputs.root0'])
            module = (directory / 'devenv.nix').read_text()
            self.assertIn('outputs.root0 = { outPath = builtins.storePath "' + STORE + '"; };', module)
            self.assertIn('cachix.push = "finite-os";', module)
            self.assertNotIn('fixture-secret', module)
            self.assertNotIn('fixture-secret', (directory / 'devenv.yaml').read_text())
            self.assertIn('"cachix_auth_token": "FINITE_CACHIX_TOKEN"', (directory / 'devenv.yaml').read_text())
            self.assertFalse((directory / 'secretspec.toml').exists())
            runtime = Path(kwargs['env']['XDG_RUNTIME_DIR'])
            self.assertEqual(runtime.parent, directory)
            self.assertEqual(kwargs['env']['TMPDIR'], str(directory))
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / 'devenv.lock').read_bytes(), (ROOT / 'devenv.lock').read_bytes())
            self.assertEqual(kwargs['env']['FINITE_CACHIX_TOKEN'], 'fixture-secret')
            self.assertNotIn('CACHIX_AUTH_TOKEN', kwargs['env'])
            self.assertNotIn('COSIGN_PRIVATE_KEY', kwargs['env'])
            self.assertNotIn('SECRETSPEC_PROVIDER', kwargs['env'])
            self.assertNotIn('SECRETSPEC_PROFILE', kwargs['env'])

        with patch.dict(os.environ, {'FINITE_CACHIX_TOKEN': 'fixture-secret', 'CACHIX_AUTH_TOKEN': 'legacy',
                                    'COSIGN_PRIVATE_KEY': 'signing', 'SECRETSPEC_PROVIDER': 'file:/tmp/wrong',
                                    'SECRETSPEC_PROFILE': 'image-signing'}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                patch.object(cache, 'metadata', return_value={STORE: HASH}) as metadata, \
                patch.object(cache, 'run_devenv', side_effect=build):
            cache.publish([STORE], provider='env')
        self.assertEqual(metadata.call_count, 2)
        self.assertFalse(captures[0].exists())

    def test_local_keyring_request_has_no_exported_token(self):
        def build(command, **kwargs):
            configuration = (Path(kwargs['cwd']) / 'devenv.yaml').read_text()
            self.assertIn('provider: keyring', configuration)
            self.assertIn('cachix_auth_token: true', configuration)
            self.assertFalse(set(cache.CREDENTIALS) & kwargs['env'].keys())
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                patch.object(cache, 'metadata', return_value={STORE: HASH}), \
                patch.object(cache, 'run_devenv', side_effect=build):
            cache.publish([STORE])

    def test_local_custom_secret_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('flake.lock', 'devenv.lock', 'devenv.yaml'):
                (directory / name).write_bytes((ROOT / name).read_bytes())
            configuration = (directory / 'devenv.yaml').read_text().replace(
                'provider: keyring', 'provider: openbao').replace(
                'cachix_auth_token: true', 'cachix_auth_token: TEAM_CACHIX_TOKEN')
            (directory / 'devenv.yaml').write_text(configuration)
            def build(command, **kwargs):
                self.assertEqual((Path(kwargs['cwd']) / 'devenv.yaml').read_text(), configuration)
            with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'ROOT', directory), \
                    patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                    patch.object(cache, 'metadata', return_value={STORE: HASH}), \
                    patch.object(cache, 'run_devenv', side_effect=build):
                cache.publish([STORE])

    def test_invalid_roots_and_missing_ci_credentials_never_launch_devenv(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'run_devenv') as build:
            for roots in ([], ['/tmp/private'], [STORE + '.drv'], [STORE] * 129):
                if len(roots) == 129:
                    roots = [STORE + str(index) for index in range(129)]
                with self.subTest(roots=roots[:2]), self.assertRaises(ValueError):
                    cache.publish(roots)
            with self.assertRaisesRegex(ValueError, 'credential is unavailable'):
                cache.publish([STORE], provider='env')
            build.assert_not_called()

    def test_missing_secret_or_failed_build_cleans_temporary_environment(self):
        captures = []
        def fail(command, **kwargs):
            captures.append(Path(kwargs['cwd']))
            raise subprocess.CalledProcessError(1, command)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                patch.object(cache, 'metadata', return_value={STORE: HASH}) as metadata, \
                patch.object(cache, 'run_devenv', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
            cache.publish([STORE])
        self.assertEqual(metadata.call_count, 1)
        self.assertFalse(captures[0].exists())

    def test_zero_exit_with_missing_or_wrong_remote_closure_fails(self):
        for observed in ({}, {STORE: 'different-hash'}, {STORE: HASH, STORE + '-extra': HASH}):
            with self.subTest(observed=observed), patch.dict(os.environ, {}, clear=True), \
                    patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                    patch.object(cache, 'metadata', side_effect=[{STORE: HASH}, observed]), \
                    patch.object(cache, 'run_devenv'), self.assertRaisesRegex(ValueError, 'complete matching closure'):
                cache.publish([STORE])

    def test_remote_transport_failure_is_bounded(self):
        failure = subprocess.CalledProcessError(1, ['nix', 'path-info'])
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='devenv 2.2.2'), \
                patch.object(cache, 'metadata', side_effect=[{STORE: HASH}, failure, failure, failure]) as metadata, \
                patch.object(cache, 'run_devenv'), patch.object(cache.time, 'sleep') as sleep, \
                self.assertRaises(subprocess.CalledProcessError):
            cache.publish([STORE])
        self.assertEqual(metadata.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_wrong_cli_is_rejected_before_credentials_or_builds(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='devenv 2.4.0'), \
                patch.object(cache, 'run_devenv') as build, self.assertRaisesRegex(ValueError, 'repository-pinned'):
            cache.publish([STORE])
        build.assert_not_called()

    def test_timeout_terminates_owned_devenv_process_group(self):
        with patch.object(cache.subprocess, 'Popen') as spawn, patch.object(cache.os, 'killpg') as kill:
            process = spawn.return_value
            process.pid = 12345
            process.wait.side_effect = [subprocess.TimeoutExpired('devenv', 1800),
                                        subprocess.TimeoutExpired('devenv', 10), 0]
            with self.assertRaises(subprocess.TimeoutExpired):
                cache.run_devenv(['devenv', 'build'], cwd=Path('/tmp/fixture'), env={})
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual([call.args for call in kill.call_args_list],
                             [(12345, cache.signal.SIGTERM), (12345, cache.signal.SIGKILL)])

    def test_local_upload_rechecks_proof_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary) / 'proofs'
            proof.write_text(STORE + '\n')
            with patch.object(cache.subprocess, 'check_output', return_value=json.dumps({STORE: {'closureSize': 10}})), \
                    patch.object(cache, 'publish') as publish:
                cache.local_proofs(proof)
                publish.assert_called_once_with([STORE])
            with patch.object(cache.subprocess, 'check_output', return_value=json.dumps({STORE: {'closureSize': 1024 ** 2 + 1}})), \
                    patch.object(cache, 'publish') as publish, self.assertRaises(ValueError):
                cache.local_proofs(proof)
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
