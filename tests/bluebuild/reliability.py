#!/usr/bin/env python3
"""Regression coverage for identities, release evidence and authenticated updates."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


identity = load('image_identity_test', 'scripts/ci/image_identity.py')
kernel = load('kernel_update_test', 'scripts/ci/kernel-update.py')
release = load('release_test', 'scripts/bluebuild/release-evidence.py')


class ImageIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ('recipes', 'files', 'sources', 'scripts', '.github'):
            shutil.copytree(ROOT / directory, self.root / directory,
                            ignore=shutil.ignore_patterns('payload', '__pycache__'))
        shutil.copy2(ROOT / 'cosign.pub', self.root / 'cosign.pub')

    def value(self, profile='bluefin-generic', payload='/nix/store/fixture.drv'):
        return identity.identity(profile, self.root, payload)

    def test_docs_do_not_change_identity(self):
        before = self.value()
        (self.root / 'README.md').write_text('New docs\n')
        self.assertEqual(before, self.value())

    def test_payload_and_runtime_changes_do_change_identity(self):
        before = self.value()
        self.assertNotEqual(before, self.value(payload='/nix/store/other.drv'))
        path = self.root / 'files/scripts/nix-install.sh'
        path.write_text(path.read_text() + '\n')
        self.assertNotEqual(before, self.value())

    def test_next_recipe_script_does_not_change_generic_identity(self):
        generic, next_image = self.value(), self.value('bluefin-next')
        path = self.root / 'files/scripts/kernel-next.sh'
        path.write_text(path.read_text() + '\n')
        self.assertEqual(generic, self.value())
        self.assertNotEqual(next_image, self.value('bluefin-next'))

    def test_mode_changes_are_image_inputs(self):
        before = self.value()
        path = self.root / 'files/scripts/nix-install.sh'
        path.chmod(path.stat().st_mode ^ 0o111)
        self.assertNotEqual(before, self.value())


class KernelUpdates(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / 'sources/kernel-policy.json').read_text())
        self.current = json.loads((ROOT / 'sources/kernel-next.json').read_text())
        self.build = {'version': '7.2.1', 'release': '62.fc45'}

    def test_complete_candidate_uses_signed_source(self):
        proposed = kernel.candidate(self.policy, self.current, self.build)
        self.assertIn('/data/signed/f577861e/x86_64', proposed['baseUrl'])
        self.assertEqual([package['name'] for package in proposed['packages']], kernel.PACKAGES)
        self.assertEqual(proposed['requiredModules'], self.current['requiredModules'])

    def test_no_change_is_noop(self):
        self.assertIsNone(kernel.candidate(self.policy, self.current, {'version': '7.2.0', 'release': '61.fc45'}))

    def test_stream_changes_downgrades_and_incomplete_locks_fail(self):
        for build in ({'version': '7.3.0', 'release': '62.fc45'},
                      {'version': '7.2.1', 'release': '62.fc46'},
                      {'version': '7.2.0', 'release': '60.fc45'},
                      {'version': '../7.2.1', 'release': '62.fc45'}):
            with self.subTest(build=build), self.assertRaises(ValueError):
                kernel.candidate(self.policy, self.current, build)
        self.current['packages'].pop()
        with self.assertRaises(ValueError):
            kernel.candidate(self.policy, self.current, self.build)

    def test_authentication_requires_signatures_and_package_identity(self):
        proposed = kernel.candidate(self.policy, self.current, self.build)
        def download(_url, path):
            path.write_bytes(b'RPM fixture')
        for signature in ('Header SHA256 digest: OK', 'RSA signature: NOKEY'):
            with patch.object(kernel, 'download', side_effect=download), patch.object(kernel.subprocess, 'run'), \
                    patch.object(kernel.subprocess, 'check_output', return_value=signature), self.assertRaises(ValueError):
                kernel.authenticate(copy.deepcopy(proposed), self.policy, ROOT)
        with patch.object(kernel, 'download', side_effect=download), patch.object(kernel.subprocess, 'run'), \
                patch.object(kernel.subprocess, 'check_output', side_effect=['RSA signature: OK', 'wrong identity']), self.assertRaises(ValueError):
            kernel.authenticate(copy.deepcopy(proposed), self.policy, ROOT)

    def test_successful_authentication_hashes_every_package(self):
        proposed = kernel.candidate(self.policy, self.current, self.build)
        responses = []
        for package in proposed['packages']:
            responses.extend(['RSA signature: OK', package['name'] + '\t' + proposed['release']])
        with patch.object(kernel, 'download', side_effect=lambda _url, path: path.write_bytes(b'RPM fixture')), \
                patch.object(kernel.subprocess, 'run'), patch.object(kernel.subprocess, 'check_output', side_effect=responses):
            authenticated = kernel.authenticate(proposed, self.policy, ROOT)
        for package in authenticated['packages']:
            self.assertEqual(package['sha256'], hashlib.sha256(b'RPM fixture').hexdigest())

    def test_failed_download_does_not_write_lock(self):
        before = (ROOT / 'sources/kernel-next.json').read_bytes()
        proposed = kernel.candidate(self.policy, self.current, self.build)
        with patch.object(kernel.subprocess, 'run'), patch.object(kernel, 'download', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                kernel.authenticate(proposed, self.policy, ROOT)
        self.assertEqual(before, (ROOT / 'sources/kernel-next.json').read_bytes())


class ReleaseEvidence(unittest.TestCase):
    def setUp(self):
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
        self.installation = {'image': self.image, 'profile': 'bluefin-generic',
                             'updateChannel': 'ghcr.io/closure-labs/finite:finite',
                             'installer': {'finiteRevision': 'revision'}}
        self.acceptance = {'candidate': self.image, 'profile': 'bluefin-generic',
                           'accepted': True, 'secureBoot': True, 'revision': 'revision',
                           'buildIdentity': 'identity', 'previousDigest': 'previous'}
        self.publication = {'revision': 'revision', 'profile': 'bluefin-generic',
                            'buildIdentity': 'identity', 'previousDigest': 'previous'}

    def test_exact_evidence_is_accepted(self):
        self.assertEqual(release.validate_evidence(self.installation, self.acceptance,
                                                   self.publication, 'finite', 'revision'), self.image)

    def test_mismatched_or_unsuccessful_evidence_is_rejected(self):
        for field in self.acceptance:
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_evidence(self.installation, {**self.acceptance, field: None},
                                          self.publication, 'finite', 'revision')

    def test_only_matching_successful_main_runs_are_trusted(self):
        run = {'conclusion': 'success', 'head_branch': 'main', 'head_sha': 'revision',
               'path': '.github/workflows/build.yml', 'head_repository': {'full_name': 'closure-labs/finite'}}
        release.validate_run(run, 'build.yml', 'revision')
        for field in ('conclusion', 'head_branch', 'head_sha', 'path'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_run({**run, field: 'wrong'}, 'build.yml', 'revision')

    def test_reruns_can_reuse_successful_jobs_from_earlier_attempts(self):
        prefix = 'image-bluefin-generic-123-'
        artifacts = [{'name': prefix + '1', 'expired': False},
                     {'name': prefix + '2', 'expired': False},
                     {'name': 'image-bluefin-next-123-3', 'expired': False}]
        self.assertEqual(release.latest_artifact(artifacts, prefix), prefix + '2')
        with self.assertRaises(ValueError):
            release.latest_artifact([{'name': prefix + '1', 'expired': True}], prefix)


class CliBootstrap(unittest.TestCase):
    def invoke(self, **extra):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(ROOT / 'sources', root / 'sources')
        bindir = root / 'bin'
        bindir.mkdir()
        script = '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open('calls.jsonl', 'a') as output:
    print(json.dumps([name, *args]), file=output)
if name == 'cosign' and os.environ.get('BAD_SIGNATURE'):
    sys.exit(1)
if name == 'docker' and args[0] == 'cp':
    version = os.environ.get('CLI_VERSION', '0.9.37')
    binary = pathlib.Path(args[-1])
    output = 'BlueBuild ' + version + '\\ntag:v' + version + '\\ncommit_hash:513065f9\\nbuild_time:2026-08-13 04:38:18 +00:00\\nbuild_env:rustc 1.97.1 (8bab26f4f 2026-07-14),'
    binary.write_text('#!' + sys.executable + '\\nprint(' + repr(output) + ')\\n')
    binary.chmod(0o755)
'''
        for name in ('cosign', 'docker', 'sudo'):
            tool = bindir / name
            tool.write_text('#!' + sys.executable + '\n' + script)
            tool.chmod(0o755)
        result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/install-cli.sh')], cwd=root,
                                env={**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'], **extra},
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        return result, calls

    def test_signature_precedes_extraction_and_digest_is_used(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0][0], 'cosign')
        created = next(call for call in calls if call[:2] == ['docker', 'create'])
        self.assertRegex(created[-1], r'^ghcr.io/blue-build/cli@sha256:[a-f0-9]{64}$')
        self.assertTrue(any(call[0] == 'sudo' for call in calls))

    def test_bad_signature_prevents_extraction(self):
        result, calls = self.invoke(BAD_SIGNATURE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == 'docker' for call in calls))

    def test_wrong_version_prevents_installation(self):
        for version in ('0.9.38', '0.9.370', '0.9.37-rc1'):
            with self.subTest(version=version):
                result, calls = self.invoke(CLI_VERSION=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Expected BlueBuild 0.9.37', result.stderr)
                self.assertFalse(any(call[0] == 'sudo' for call in calls))


if __name__ == '__main__':
    unittest.main()
