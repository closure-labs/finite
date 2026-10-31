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
    def setUp(self):
        proof = patch.object(cache, 'proof_closure', return_value={
            'bytes': 112, 'pathCount': 1, 'paths': {STORE: {'narHash': HASH, 'narSize': 112, 'references': []}}})
        self.policy = proof.start()
        self.addCleanup(proof.stop)

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
                patch.object(cache, 'metadata', return_value={STORE: HASH}) as metadata, \
                patch.object(cache, 'run_devenv', side_effect=build):
            cache.publish([STORE], provider='env')
        self.assertEqual(metadata.call_count, 1)
        self.assertFalse(captures[0].exists())

    def test_local_keyring_request_has_no_exported_token(self):
        def build(command, **kwargs):
            configuration = (Path(kwargs['cwd']) / 'devenv.yaml').read_text()
            self.assertIn('provider: keyring', configuration)
            self.assertIn('cachix_auth_token: true', configuration)
            self.assertFalse(set(cache.CREDENTIALS) & kwargs['env'].keys())
        with patch.dict(os.environ, {}, clear=True), \
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
                patch.object(cache, 'metadata', return_value={STORE: HASH}) as metadata, \
                patch.object(cache, 'run_devenv', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
            cache.publish([STORE])
        self.assertEqual(metadata.call_count, 0)
        self.assertFalse(captures[0].exists())

    def test_zero_exit_with_missing_or_wrong_remote_closure_fails(self):
        for observed in ({}, {STORE: 'different-hash'}, {STORE: HASH, STORE + '-extra': HASH}):
            with self.subTest(observed=observed), patch.dict(os.environ, {}, clear=True), \
                    patch.object(cache, 'metadata', side_effect=[observed]), \
                    patch.object(cache, 'run_devenv'), self.assertRaisesRegex(ValueError, 'complete matching closure'):
                cache.publish([STORE])

    def test_remote_transport_failure_is_bounded(self):
        failure = subprocess.CalledProcessError(1, ['nix', 'path-info'])
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache, 'metadata', side_effect=[failure, failure, failure]) as metadata, \
                patch.object(cache, 'run_devenv'), patch.object(cache.time, 'sleep') as sleep, \
                self.assertRaises(subprocess.CalledProcessError):
            cache.publish([STORE])
        self.assertEqual(metadata.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_available_cli_is_used_without_an_exact_version_probe(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache.subprocess, 'check_output', side_effect=AssertionError('No CLI version probe')), \
                patch.object(cache, 'metadata', return_value={STORE: HASH}), \
                patch.object(cache, 'run_devenv') as build:
            cache.publish([STORE])
        self.assertEqual(build.call_args.args[0][0], 'devenv')

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

    def test_local_handoff_is_owned_private_and_still_runs_publication_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary) / 'proofs'
            proof.write_text(STORE + '\n')
            proof.chmod(0o600)
            with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'metadata', return_value={STORE: HASH}), \
                    patch.object(cache, 'run_devenv') as upload:
                cache.local_proofs(proof)
                upload.assert_called_once()
            self.policy.side_effect = ValueError('Proof union exceeds 1 MiB')
            with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'run_devenv') as upload, self.assertRaises(ValueError):
                cache.local_proofs(proof)
            upload.assert_not_called()
            self.policy.reset_mock()
            proof.chmod(0o644)
            with patch.object(cache, 'publish') as publish, self.assertRaises(ValueError):
                cache.local_proofs(proof)
            publish.assert_not_called()


class ProofPolicy(unittest.TestCase):
    def identities(self, count=2):
        return {f'check{index}': {'drvPath': '/nix/store/' + f'{index:032d}' + '-proof.drv',
                                'outputPath': '/nix/store/' + f'{index:032d}' + '-proof'}
                for index in range(count)}

    def records(self, identities):
        return {identity['outputPath']: {'narHash': HASH, 'narSize': 112, 'references': []}
                for identity in identities.values()}

    def test_useful_tiny_check_result_needs_no_proof_label_or_crypto_content(self):
        identities = {'ci-summary': {'drvPath': STORE + '-summary.drv', 'outputPath': STORE + '-summary'}}
        path = identities['ci-summary']['outputPath']
        records = self.records(identities)
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cache, 'proof_identities', return_value=identities), \
                patch.object(cache, 'query', return_value=json.dumps(records)), \
                patch.object(cache, 'run_devenv') as upload, \
                patch.object(cache, 'metadata', return_value={path: HASH}):
            cache.publish([path])
        upload.assert_called_once()

    def test_shared_reference_is_counted_once_in_recursive_union(self):
        identities = self.identities(3)
        paths = [item['outputPath'] for item in identities.values()]
        records = self.records(identities)
        records[paths[0]]['references'] = [paths[2]]
        records[paths[1]]['references'] = [paths[2]]
        with patch.object(cache, 'proof_identities', return_value=identities), \
                patch.object(cache, 'query', return_value=json.dumps(records)) as query:
            receipt = cache.proof_closure(paths[:2])
        self.assertEqual((receipt['bytes'], receipt['pathCount']), (336, 3))
        self.assertIn('--recursive', query.call_args.args[0])

    def test_unknown_tool_roots_fail_before_closure_query(self):
        with patch.object(cache, 'proof_identities', return_value=self.identities()), \
                patch.object(cache, 'query') as query:
            for paths in ([STORE], [STORE + '-scanner-tools'], [], [STORE] * 129, [STORE, STORE]):
                with self.subTest(paths=paths[:2]), self.assertRaises(ValueError):
                    cache.proof_closure(paths)
            query.assert_not_called()

    def test_nonproof_references_union_overflow_and_malformed_metadata_never_upload(self):
        import copy
        identities = self.identities()
        paths = [item['outputPath'] for item in identities.values()]
        valid = self.records(identities)
        variants = [{}, [], {**valid, STORE: valid[paths[0]]}]
        for field, value in [('narSize', True), ('narSize', 0), ('narSize', -1), ('narSize', cache.PROOF_BYTES + 1),
                             ('narHash', 'unknown'), ('references', [STORE]), ('references', [paths[1], paths[1]])]:
            records = copy.deepcopy(valid);records[paths[0]][field] = value;variants.append(records)
        records = copy.deepcopy(valid)
        for record in records.values():record['narSize'] = cache.PROOF_BYTES // 2 + 1
        variants.append(records)
        for records in variants:
            with self.subTest(records=records), patch.dict(os.environ, {}, clear=True), \
                    patch.object(cache, 'proof_identities', return_value=identities), \
                    patch.object(cache, 'query', return_value=json.dumps(records)), \
                    patch.object(cache, 'run_devenv') as upload, self.assertRaises(ValueError):
                cache.publish(paths)
            upload.assert_not_called()
        # A valid-size metadata superset must still be reachable from selected roots.
        with patch.object(cache, 'proof_identities', return_value=identities), \
                patch.object(cache, 'query', return_value=json.dumps(valid)), self.assertRaisesRegex(ValueError, 'Unreachable'):
            cache.proof_closure(paths[:1])

    def test_exact_union_byte_and_path_limits_and_query_errors(self):
        identities = self.identities(128)
        paths = [item['outputPath'] for item in identities.values()]
        records = self.records(identities)
        records[paths[0]]['narSize'] = cache.PROOF_BYTES - 112 * 127
        with patch.object(cache, 'proof_identities', return_value=identities), \
                patch.object(cache, 'query', return_value=json.dumps(records)):
            self.assertEqual(cache.proof_closure(paths)['bytes'], cache.PROOF_BYTES)
            with patch.object(cache, 'PROOF_PATHS', 127), self.assertRaises(ValueError):
                cache.proof_closure(paths)
        with patch.object(cache, 'proof_identities', return_value=identities), \
                patch.object(cache, 'query', side_effect=subprocess.TimeoutExpired('nix', 300)), \
                patch.object(cache, 'run_devenv') as upload, self.assertRaises(subprocess.TimeoutExpired):
            cache.publish(paths)
        upload.assert_not_called()

    def test_identity_evaluation_is_exact_noncoercing_and_credential_free(self):
        valid = self.identities()
        with patch.object(cache, 'query', side_effect=['x86_64-linux', json.dumps(valid)]) as query:
            self.assertEqual(cache.proof_identities(), valid)
        command = query.call_args.args[0]
        self.assertIn('.#checks.x86_64-linux', command)
        self.assertIn('outputPath = check.outPath;', command[-1])
        for metadata in ({}, {'unknown': 'collapsed-output'}, {'check': {'drvPath': STORE, 'outputPath': STORE}},
                         {**valid, 'alias': next(iter(valid.values()))}):
            with patch.object(cache, 'query', side_effect=['x86_64-linux', json.dumps(metadata)]), self.assertRaises(ValueError):
                cache.proof_identities()
        with patch.dict(os.environ, {'FINITE_CACHIX_TOKEN': 'secret', 'CACHIX_AUTH_TOKEN': 'secret', 'SAFE': 'yes'}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value='fixture') as query:
            cache.query(['fixture'])
        self.assertEqual(query.call_args.kwargs['env'], {'SAFE': 'yes'})
        with self.assertRaises(ValueError):cache.decode('{"narSize": 1, "narSize": 2}')


if __name__ == '__main__':
    unittest.main()
