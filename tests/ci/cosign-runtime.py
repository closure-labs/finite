#!/usr/bin/env python3
"""Reject drift and unauthenticated runtime sources without registry access."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cosign_runtime', ROOT / 'scripts/ci/cosign-runtime.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
POLICY = mod.policy(ROOT)


class CosignRuntime(unittest.TestCase):
    def fixtures(self, mutation=None):
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                    'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                   'digest': POLICY['platformDigest'], 'platform': POLICY['platform']} ]}
        if mutation:
            mutation(manifest)
        raw = json.dumps(manifest).encode()
        value = copy.deepcopy(POLICY)
        value['indexDigest'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
        signatures = [{'critical': {'image': {'docker-manifest-digest': value['indexDigest']}},
                       'optional': value['annotations']}]
        return value, raw, json.dumps(signatures).encode()

    def exercise(self, value=None, raw=None, signatures=None, failure=None):
        default_value, default_raw, default_signatures = self.fixtures()
        value = default_value if value is None else value
        raw = default_raw if raw is None else raw
        signatures = default_signatures if signatures is None else signatures
        calls = []
        def runner(args, timeout):
            calls.append((args, timeout))
            if failure and args[0] == failure:
                raise RuntimeError('rejected publisher signature')
            return raw if args[0] == 'skopeo' else signatures
        return mod.authenticate(value, runner), calls

    def test_source_policy_and_four_recipe_pins(self):
        self.assertEqual(mod.recipe_pins(POLICY, ROOT), POLICY['version'] + '@' + POLICY['indexDigest'])
        self.assertEqual(POLICY['annotations']['GIT_VERSION'], 'v3.1.3')

    def test_verified_index_platform_and_signed_annotations(self):
        report, calls = self.exercise()
        self.assertEqual(report['status'], 'publisher-authenticated')
        self.assertEqual(report['platformDigest'], POLICY['platformDigest'])
        self.assertIn('clearance require separate evidence', report['note'])
        inspect, verify = calls
        self.assertEqual(inspect[0][:5], ['skopeo', '--command-timeout', '30s', 'inspect', '--raw'])
        self.assertEqual(inspect[1], 35)
        self.assertEqual(verify[1], 150)
        self.assertIn(POLICY['certificateIdentity'], verify[0])
        self.assertIn(POLICY['certificateOidcIssuer'], verify[0])
        self.assertIn('--new-bundle-format=true', verify[0])
        self.assertIn('GIT_HASH=' + POLICY['annotations']['GIT_HASH'], verify[0])
        self.assertIn('GIT_VERSION=v3.1.3', verify[0])
        self.assertEqual(verify[0][-1], report['image'])
        for arg in verify[0]:
            self.assertNotIn('insecure', arg)
            self.assertNotIn('ignore-tlog', arg)
            self.assertNotIn('offline', arg)
            self.assertNotIn('regexp', arg)
            self.assertNotEqual(arg, '--new-bundle-format=false')

    def test_registry_bytes_must_match_locked_index(self):
        with self.assertRaisesRegex(ValueError, 'index digest mismatch'):
            self.exercise(raw=b'changed registry bytes')

    def test_wrong_child_or_platform_or_duplicate_is_rejected(self):
        mutations = [lambda d: d['manifests'][0].update(digest='sha256:' + 'f' * 64),
                     lambda d: d['manifests'][0]['platform'].update(architecture='arm64'),
                     lambda d: d['manifests'][0]['platform'].update(os='windows'),
                     lambda d: d['manifests'][0]['platform'].update(variant='v2'),
                     lambda d: d['manifests'].append(copy.deepcopy(d['manifests'][0])),
                     lambda d: d['manifests'].clear(),
                     lambda d: d['manifests'][0].update(mediaType='unreviewed')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value, raw, signatures = self.fixtures(mutation)
                with self.assertRaisesRegex(ValueError, 'descriptor'):
                    self.exercise(value, raw, signatures)

    def test_non_index_or_malformed_manifest_is_rejected(self):
        for mutation in (lambda d: d.update(schemaVersion=True),
                         lambda d: d.update(mediaType='application/vnd.oci.image.manifest.v1+json'),
                         lambda d: d.update(manifests={}),
                         lambda d: d['manifests'][0].update(platform='linux/amd64')):
            value, raw, signatures = self.fixtures(mutation)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'OCI index'):
                self.exercise(value, raw, signatures)

    def test_failed_publisher_authentication_propagates(self):
        for tool in ('skopeo', 'cosign'):
            with self.subTest(tool=tool), self.assertRaises(RuntimeError):
                self.exercise(failure=tool)

    def test_verified_claims_cannot_drift(self):
        value, raw, signature = self.fixtures()
        for change in (lambda d: d[0]['critical']['image'].update({'docker-manifest-digest': 'sha256:' + 'e' * 64}),
                       lambda d: d[0]['optional'].update(GIT_VERSION='v3.1.1'),
                       lambda d: d[0]['optional'].update(GIT_HASH='e' * 40),
                       lambda d: d[0]['optional'].pop('GIT_HASH')):
            data = json.loads(signature)
            change(data)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'claims'):
                self.exercise(value, raw, json.dumps(data).encode())

    def test_empty_signature_or_invalid_json_is_rejected(self):
        for data in (b'[]', b'{}', b'null', b'not JSON'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.exercise(signatures=data)

    def test_source_policy_rejects_unreviewed_trust(self):
        mutations = [lambda p: p.update(schema=True), lambda p: p.update(extra='field'),
                     lambda p: p.update(version='latest'), lambda p: p.update(repository='ghcr.io/other/cosign'),
                     lambda p: p.update(indexDigest='sha256:' + 'f' * 63),
                     lambda p: p.update(platformDigest='mutable-tag'),
                     lambda p: p.update(platform={'os': 'linux', 'architecture': 'arm64'}),
                     lambda p: p.update(certificateIdentity='attacker@example.com'),
                     lambda p: p.update(certificateOidcIssuer='https://token.actions.githubusercontent.com'),
                     lambda p: p['annotations'].update(GIT_VERSION='v3.1.1'),
                     lambda p: p['annotations'].update(GIT_HASH='wrong'),
                     lambda p: p['annotations'].update(extra='field')]
        for mutation in mutations:
            value = copy.deepcopy(POLICY)
            mutation(value)
            with self.subTest(mutation=mutation), patch.object(Path, 'read_text', return_value=json.dumps(value)):
                with self.assertRaisesRegex(ValueError, 'publisher policy'):
                    mod.policy(ROOT)

    def test_recipe_mutable_wrong_or_duplicate_pins_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'recipes', root / 'recipes')
            target = root / 'recipes/finite.yml'
            original = target.read_text()
            expected = mod.recipe_pins(POLICY, ROOT)
            for text in (original.replace(expected, '3.1.3'), original.replace(expected, '3.1.1@' + POLICY['indexDigest']),
                         original.replace(expected, '3.1.3@sha256:' + 'f' * 64),
                         original + '\ncosign-version: ' + expected + '\n',
                         original.replace('cosign-version:', 'not-cosign-version:')):
                target.write_text(text)
                with self.subTest(text=text[:60]), self.assertRaisesRegex(ValueError, 'immutable pin'):
                    mod.recipe_pins(POLICY, root)

    def test_bounded_command_errors_and_timeout(self):
        with self.assertRaisesRegex(RuntimeError, 'verification failed'):
            mod.run([sys.executable, '-c', 'import sys; sys.stderr.write("rejected"); sys.exit(1)'], timeout=3)
        with self.assertRaisesRegex(ValueError, 'size limit'):
            mod.run([sys.executable, '-c', 'print("x" * 2097153)'], timeout=3)
        with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('cosign', 150)):
            with self.assertRaises(subprocess.TimeoutExpired):
                mod.run(['cosign', 'verify'], timeout=150)


if __name__ == '__main__':
    unittest.main()
