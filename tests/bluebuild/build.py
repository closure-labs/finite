#!/usr/bin/env python3
"""Exercise the direct CLI's publication boundary without building an image."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]


class BuildInvocation(unittest.TestCase):
    def invoke(self, publish='false', profile='finite', **extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir = root / 'bin'
            bindir.mkdir()
            script = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open('calls.jsonl', 'a') as output:
    print(json.dumps({'command': [name, *sys.argv[1:]],
                      'key': os.environ.get('COSIGN_PRIVATE_KEY'),
                      'push': os.environ.get('BB_BUILD_PUSH'),
                      'no_sign': os.environ.get('BB_BUILD_NO_SIGN'),
                      'source_date_epoch': os.environ.get('SOURCE_DATE_EPOCH')}), file=output)
sys.exit(int(os.environ.get('BUILD_STATUS' if name == 'bluebuild' else 'LOGOUT_STATUS', '0')))
'''
            for name in ('bluebuild', 'docker'):
                tool = bindir / name
                tool.write_text('#!' + sys.executable + '\n' + script)
                tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'],
                   'BB_USERNAME': 'ci-test', 'BB_PASSWORD': 'test-token',
                   'COSIGN_PRIVATE_KEY': 'test-key',
                   'BB_BUILD_PUSH': 'true', 'BB_BUILD_NO_SIGN': 'true', **extra}
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/build.sh'), profile, publish],
                                    cwd=root, env=env, capture_output=True, text=True)
            calls_path = root / 'calls.jsonl'
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
            return result, calls

    def test_validation_never_pushes_or_receives_the_signing_key(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call['command'][:2], ['bluebuild', 'build'])
        self.assertEqual(call['command'][-1], 'recipes/finite.yml')
        self.assertNotIn('--push', call['command'])
        self.assertIsNone(call['push'])
        self.assertIsNone(call['key'])

    def test_publication_is_unsigned_and_keeps_cache_and_registry_cleanup(self):
        result, calls = self.invoke(publish='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = calls[0]
        self.assertIn('--push', call['command'])
        self.assertIn('--cache-layers', call['command'])
        self.assertIn('--retry-push', call['command'])
        self.assertIn('--no-sign', call['command'])
        self.assertIsNone(call['no_sign'])
        self.assertIsNone(call['key'])
        self.assertEqual(calls[-1]['command'], ['docker', 'logout', 'ghcr.io'])

    def test_missing_credentials_prevent_any_build(self):
        for missing in ('BB_USERNAME', 'BB_PASSWORD'):
            with self.subTest(missing=missing):
                result, calls = self.invoke(publish='true', **{missing: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_nix_epoch_does_not_backdate_validation_or_published_images(self):
        for publish in ('false', 'true'):
            with self.subTest(publish=publish):
                result, calls = self.invoke(publish=publish, SOURCE_DATE_EPOCH='315532800')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(calls[0]['source_date_epoch'])

    def test_cleanup_preserves_build_failure_even_when_logout_fails(self):
        result, calls = self.invoke(publish='true', BUILD_STATUS='42', LOGOUT_STATUS='1')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(calls[-1]['command'], ['docker', 'logout', 'ghcr.io'])

    def test_invalid_inputs_prevent_any_build(self):
        for args in ({'publish': 'yes'}, {'profile': '../../recipe'}):
            with self.subTest(args=args):
                result, calls = self.invoke(**args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


class PublicationPreparation(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('build_test_publication', ROOT / 'scripts/bluebuild/publication.py')
        self.publication = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.publication)
        self.upstream = self.publication.upstream
        spec = importlib.util.spec_from_file_location('build_test_cosign', ROOT / 'scripts/ci/cosign-runtime.py')
        self.cosign = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cosign)
        mock = patch.object(self.cosign, 'authenticate', return_value={'status': 'publisher-authenticated'})
        mock.start()
        self.addCleanup(mock.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'recipes', self.root / 'recipes')
        for target, name, value in ((self.upstream, 'image_identity', 'v1:' + 'a' * 64),
                                    (self.upstream, 'inspect', None)):
            mock = patch.object(target, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        env = patch.dict(os.environ, GITHUB_OUTPUT='', GITHUB_SHA='b' * 40,
                         FINITE_QUALIFICATION_MODE='enforce')
        env.start()
        self.addCleanup(env.stop)
        workflow = yaml.safe_load((ROOT / '.github/workflows/image.yml').read_text())
        self.steps = workflow['jobs']['build']['steps']

    def prepare_from_workflow(self, profile, publish):
        operations = []
        for step in self.steps:
            command = step.get('run', '')
            if 'scripts/ci/bluefin-upstream.py verify' in command:
                self.assertNotIn('if', step)
                self.assertFalse(step.get('continue-on-error', False))
                operations.append('verify')
                self.upstream.verify(self.root)
            if 'scripts/ci/cosign-runtime.py' in command:
                self.assertNotIn('if', step)
                self.assertFalse(step.get('continue-on-error', False))
                operations.append('verify-cosign')
                policy = self.cosign.policy(ROOT)
                self.cosign.recipe_pins(policy, self.root)
                self.cosign.authenticate(policy)
            if 'scripts/bluebuild/publication.py prepare' in command:
                operations.append('prepare')
                self.publication.prepare(profile, publish, self.root)
        self.assertEqual(operations, ['verify', 'verify-cosign', 'prepare'])

    def test_workflow_authenticates_pins_before_publication_mutates_tags(self):
        originals = {path: path.read_bytes() for path in (self.root / 'recipes').glob('*.yml')}
        for profile, (_, tags) in self.upstream.PROFILES.items():
            for publish in (False, True):
                with self.subTest(profile=profile, publish=publish):
                    for path, content in originals.items():
                        path.write_bytes(content)
                    with patch.object(self.upstream, 'authenticate') as authenticate:
                        self.prepare_from_workflow(profile, publish)
                    self.assertEqual(authenticate.call_count, 2)
                    for call in authenticate.call_args_list:
                        self.assertRegex(call.args[1], r'^sha256:[0-9a-f]{64}$')
                    recipe = yaml.safe_load((self.root / 'recipes' / (profile + '.yml')).read_text())
                    self.assertEqual(recipe['alt-tags'], ['candidate-' + profile] if publish else tags)

    def test_authentication_failure_stops_before_candidate_preparation(self):
        before = {path: path.read_bytes() for path in (self.root / 'recipes').glob('*.yml')}
        with patch.object(self.upstream, 'authenticate', side_effect=subprocess.CalledProcessError(1, 'cosign')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.prepare_from_workflow('finite', True)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((self.root / '.bluebuild').exists())

    def test_strict_recipe_validation_still_rejects_candidate_and_foreign_tags(self):
        for profile in self.upstream.PROFILES:
            path = self.root / 'recipes' / (profile + '.yml')
            original = path.read_text()
            for tags in (['candidate-' + profile], ['unreviewed-channel']):
                with self.subTest(profile=profile, tags=tags):
                    recipe = yaml.safe_load(original)
                    recipe['alt-tags'] = tags
                    path.write_text(yaml.safe_dump(recipe))
                    with patch.object(self.upstream, 'authenticate') as authenticate:
                        with self.assertRaisesRegex(ValueError, 'Unexpected recipe identity: ' + profile):
                            self.upstream.verify(self.root)
                        authenticate.assert_not_called()
                    path.write_text(original)


    def test_runtime_cosign_failure_stops_before_candidate_preparation(self):
        before = {path: path.read_bytes() for path in (self.root / 'recipes').glob('*.yml')}
        with patch.object(self.upstream, 'authenticate'), \
                patch.object(self.cosign, 'authenticate', side_effect=RuntimeError('publisher rejected')):
            with self.assertRaisesRegex(RuntimeError, 'publisher rejected'):
                self.prepare_from_workflow('finite', True)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((self.root / '.bluebuild').exists())


if __name__ == '__main__':
    unittest.main()
