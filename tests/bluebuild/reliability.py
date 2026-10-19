#!/usr/bin/env python3
"""Regression coverage for identities, release evidence and authenticated updates."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest
import yaml
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


identity = load('image_identity_test', 'scripts/ci/image_identity.py')
release = load('release_test', 'scripts/bluebuild/release-evidence.py')
publication = load('publication_reliability', 'scripts/bluebuild/publication.py')
unlock = load('unlock_vm_test', 'scripts/bluebuild/unlock-vm.py')
redact = load('redact_vm_test', 'scripts/bluebuild/redact-vm-logs.py')
scan = load('scanner_identity_test', 'scripts/bluebuild/security-scan.py')


class ScannerSourceIdentity(unittest.TestCase):
    def test_original_source_is_bound_independently_of_current_policy_revision(self):
        image = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
        source = 'b' * 40
        labels = {'org.opencontainers.image.revision': source,
                  'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                  'io.finite.profile': 'finite', 'io.finite.build-inputs': 'v1:' + 'c' * 64}
        metadata = {'Digest': 'sha256:' + 'a' * 64, 'Labels': labels}
        with patch.dict(os.environ, GITHUB_SHA='d' * 40):
            scan.candidate_identity(metadata, image, 'finite', labels['io.finite.build-inputs'], source)
            for key in labels:
                with self.subTest(label=key), self.assertRaises(ValueError):
                    scan.candidate_identity({**metadata, 'Labels': {**labels, key: 'wrong'}},
                                            image, 'finite', labels['io.finite.build-inputs'], source)
            for bad in ('invalid', 'd' * 40):
                with self.subTest(revision=bad), self.assertRaises(ValueError):
                    scan.candidate_identity(metadata, image, 'finite', labels['io.finite.build-inputs'], bad)
            with self.assertRaises(ValueError):
                scan.candidate_identity({**metadata, 'Digest': 'sha256:' + 'e' * 64},
                                        image, 'finite', labels['io.finite.build-inputs'], source)


class ImageIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ('recipes', 'files', 'sources', 'scripts', '.github'):
            shutil.copytree(ROOT / directory, self.root / directory,
                            ignore=shutil.ignore_patterns('payload', '__pycache__'))
        shutil.copy2(ROOT / 'cosign.pub', self.root / 'cosign.pub')

    def value(self, profile='finite', payload='/nix/store/fixture.drv'):
        return identity.identity(profile, self.root, payload)

    def test_docs_do_not_change_identity(self):
        before = self.value()
        (self.root / 'README.md').write_text('New docs\n')
        self.assertEqual(before, self.value())

    def test_policy_changes_requalify_without_changing_filesystem_identity(self):
        directory = self.root / 'automation/security'
        directory.mkdir(parents=True)
        policy = directory / 'image-policy.json'
        policy.write_text('{"mode":"strict"}\n')
        for profile in ('finite', 'finite-dev'):
            with self.subTest(profile=profile):
                before = self.value(profile)
                policy.write_text('{"mode":"upstream-maintained-risk"}\n')
                scanner = self.root / 'scripts/bluebuild/security-policy.py'
                scanner.write_text(scanner.read_text() + '\n# Changed risk review\n')
                publication_gate = self.root / '.github/workflows/publication.yml'
                publication_gate.write_text(publication_gate.read_text() + '\n# Changed qualification\n')
                self.assertEqual(before, self.value(profile))

    def test_publisher_trust_changes_still_change_image_identity(self):
        before = self.value()
        trust = self.root / 'sources/bluefin-trust.json'
        trust.write_text(trust.read_text() + '\n')
        self.assertNotEqual(before, self.value())

    def test_payload_and_runtime_changes_do_change_identity(self):
        before = self.value()
        self.assertNotEqual(before, self.value(payload='/nix/store/other.drv'))
        path = self.root / 'files/scripts/nix-install.sh'
        path.write_text(path.read_text() + '\n')
        self.assertNotEqual(before, self.value())


    def test_mode_changes_are_image_inputs(self):
        before = self.value()
        path = self.root / 'files/scripts/nix-install.sh'
        path.chmod(path.stat().st_mode ^ 0o111)
        self.assertNotEqual(before, self.value())




class ReleaseEvidence(unittest.TestCase):
    def setUp(self):
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
        self.installation = {'image': self.image, 'profile': 'finite',
                             'updateChannel': 'ghcr.io/closure-labs/finite:finite',
                             'installer': {'finiteRevision': 'd' * 40}}
        self.acceptance = {'candidate': self.image, 'profile': 'finite',
                           'accepted': True, 'secureBoot': True, 'encryptedRoot': True, 'revision': 'd' * 40,
                           'buildIdentity': 'identity', 'previousDigest': 'previous'}
        self.publication = {'revision': 'd' * 40, 'profile': 'finite',
                            'buildIdentity': 'identity', 'previousDigest': 'previous'}

    def test_exact_evidence_is_accepted(self):
        self.assertEqual(release.validate_evidence(self.installation, self.acceptance,
                                                   self.publication, 'finite', 'd' * 40), self.image)

    def test_mismatched_or_unsuccessful_evidence_is_rejected(self):
        for field in self.acceptance:
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_evidence(self.installation, {**self.acceptance, field: None},
                                          self.publication, 'finite', 'd' * 40)

    def test_only_matching_successful_main_runs_are_trusted(self):
        run = {'conclusion': 'success', 'head_branch': 'main', 'head_sha': 'd' * 40,
               'path': '.github/workflows/build.yml', 'head_repository': {'full_name': 'closure-labs/finite'}}
        release.validate_run(run, 'build.yml', 'd' * 40)
        for field in ('conclusion', 'head_branch', 'head_sha', 'path'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                release.validate_run({**run, field: 'wrong'}, 'build.yml', 'd' * 40)

    def test_reruns_can_reuse_successful_jobs_from_earlier_attempts(self):
        prefix = 'image-finite-123-'
        artifacts = [{'name': prefix + '1', 'expired': False},
                     {'name': prefix + '2', 'expired': False},
                     {'name': 'image-finite-dev-123-3', 'expired': False}]
        self.assertEqual(release.latest_artifact(artifacts, prefix), prefix + '2')
        with self.assertRaises(ValueError):
            release.latest_artifact([{'name': prefix + '1', 'expired': True}], prefix)


    def test_policy_revision_can_qualify_an_unchanged_older_source(self):
        source = 'b' * 40
        publication = {**self.publication, 'sourceRevision': source}
        acceptance = {**self.acceptance, 'sourceRevision': source}
        self.assertEqual(release.validate_evidence(self.installation, acceptance,
                         publication, 'finite', 'd' * 40), self.image)
        for bad in ('c' * 40, 'invalid', None):
            with self.subTest(source=bad), self.assertRaises(ValueError):
                release.validate_evidence(self.installation,
                    {**acceptance, 'sourceRevision': bad}, publication, 'finite', 'd' * 40)
        with self.assertRaises(ValueError):
            release.validate_evidence(self.installation, self.acceptance,
                                     publication, 'finite', 'd' * 40)

class PromotionQualification(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.evidence = self.root / '.bluebuild'
        self.evidence.mkdir()
        self.profile = 'finite'
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
        self.record = {'publish': True, 'profile': self.profile, 'tags': ['finite', 'latest'],
                       'revision': 'd' * 40, 'publishedDigest': '', 'previousDigest': '',
                       'recoveryReason': '', 'buildIdentity': 'identity',
                       'qualificationMode': 'enforce', 'qualify': False}
        self.acceptance = {'accepted': True, 'candidate': self.image, 'previousDigest': '',
                           'profile': self.profile, 'revision': 'd' * 40, 'buildIdentity': 'identity',
                           'secureBoot': True, 'encryptedRoot': True}
        (self.evidence / (self.profile + '-publication.json')).write_text(json.dumps(self.record))
        (self.evidence / (self.profile + '-image-ref.txt')).write_text(self.image)

    def promote(self):
        with patch.dict(os.environ, {'GITHUB_SHA': 'd' * 40, 'FINITE_QUALIFICATION_MODE': 'enforce'}):
            publication.promote(self.profile, self.root)

    def test_daily_rebuild_with_unchanged_inputs_requires_fresh_qualification(self):
        recipes = self.root / 'recipes'
        recipes.mkdir()
        recipe = recipes / (self.profile + '.yml')
        previous = {'Digest': 'sha256:' + 'b' * 64,
                    'Labels': {'io.finite.build-inputs': 'identity'}}
        acceptance_path = self.evidence / (self.profile + '-acceptance.json')
        for event in ('schedule', 'schedule', 'push', 'workflow_dispatch'):
            with self.subTest(event=event):
                recipe.write_text('alt-tags: [finite, latest]\nlabels:\n  test: fixture\n')
                # Yesterday's failed or successful run must never qualify today's
                # digest, including the first schedule after weekly failure.
                acceptance_path.write_text(json.dumps(self.acceptance))
                with patch.dict(os.environ, GITHUB_EVENT_NAME=event, FORCE_QUALIFICATION='false'), \
                        patch.object(publication.upstream, 'recipes', return_value={
                            self.profile: {'tags': ['finite', 'latest']}}), \
                        patch.object(publication.upstream, 'image_identity', return_value='identity'), \
                        patch.object(publication.upstream, 'inspect', return_value=previous), \
                        patch.object(publication.subprocess, 'run'):
                    publication.prepare(self.profile, True, self.root)
                record = json.loads((self.evidence / (self.profile + '-publication.json')).read_text())
                self.assertIs(record['qualify'], True)
                self.assertFalse(acceptance_path.exists())

    def test_workflow_requires_successful_qualification_and_always_downloads_evidence(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())
        self.assertNotIn('if', workflow['jobs']['qualification'])
        promote = workflow['jobs']['promote']
        self.assertIn("needs.qualification.result == 'success'", promote['if'])
        self.assertNotIn("'skipped'", promote['if'])
        self.assertIn('!cancelled()', promote['if'])
        download = next(step for step in promote['steps'] if step.get('name') ==
                        'Download candidate and qualification evidence')
        self.assertNotIn('QUALIFY', download['env'])
        self.assertNotIn('if ', download['run'])
        self.assertIn('--name "$QUALIFICATION_ARTIFACT"', download['run'])

    def test_false_qualify_flag_cannot_bypass_missing_acceptance(self):
        with patch.object(publication.subprocess, 'run') as copy_image, self.assertRaises(ValueError):
            self.promote()
        copy_image.assert_not_called()

    def test_every_acceptance_identity_and_security_field_is_required(self):
        for field in self.acceptance:
            for replacement in (None, False, 'wrong'):
                with self.subTest(field=field, replacement=replacement):
                    (self.evidence / (self.profile + '-acceptance.json')).write_text(
                        json.dumps({**self.acceptance, field: replacement}))
                    with patch.object(publication.subprocess, 'run') as copy_image, self.assertRaises(ValueError):
                        self.promote()
                    copy_image.assert_not_called()

    def test_missing_vm_security_receipt_blocks_before_registry_mutation(self):
        (self.evidence / (self.profile + '-acceptance.json')).write_text(json.dumps(self.acceptance))
        with patch.object(publication.subprocess, 'run') as command, self.assertRaisesRegex(ValueError, 'VM security receipt'):
            self.promote()
        command.assert_not_called()

    def test_exact_qualified_digest_is_promoted_even_with_legacy_flag(self):
        (self.evidence / (self.profile + '-acceptance.json')).write_text(json.dumps(self.acceptance))
        with patch.object(publication.subprocess, 'run') as copy_image, \
                patch.object(publication.security, 'verify'), \
                patch.object(publication.desktop, 'verify') as desktop_verify, \
                patch.object(publication, 'github', return_value={'ref': 'refs/heads/main',
                        'object': {'type': 'commit', 'sha': 'd' * 40}}), \
                patch.object(publication.upstream, 'inspect', side_effect=[None,
                    {'Digest': 'sha256:' + 'a' * 64}, {'Digest': 'sha256:' + 'a' * 64}]):
            self.promote()
        desktop_verify.assert_called_once_with(self.evidence, self.acceptance)
        self.assertEqual(copy_image.call_count, 3)
        self.assertEqual(copy_image.call_args_list[0].args[0][0:2], ['cosign', 'verify'])
        for call in copy_image.call_args_list[1:]:
            self.assertIn('docker://' + self.image, call.args[0])


class EncryptedVmConsole(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.marker = Path(temporary.name) / 'unlock.log'
        # Public synthetic sentinel: never a credential. Raw fixture writes below
        # exercise redaction and exclusion before any diagnostics are exported.
        self.secret = b'a1' * 32

    def run_console(self, chunks):
        connection = Mock()
        connection.recv.side_effect = [*chunks, b'']
        log, output = io.BytesIO(), io.BytesIO()
        unlock.relay(connection, self.secret, log, self.marker, output)
        self.assertEqual(log.getvalue(), output.getvalue())
        self.assertNotIn(self.secret, log.getvalue())
        return connection, log.getvalue()

    def test_fragmented_prompt_unlocks_once_and_redacts_fragmented_echo(self):
        connection, log = self.run_console([
            b'Booting\nPlease enter passphrase for di', b'sk QEMU (luks-test): ',
            self.secret[:17], self.secret[17:] + b'\n',
            b'Please enter passphrase for disk QEMU (luks-test): ', b'Booted\n'])
        connection.sendall.assert_called_once_with(self.secret + b'\r')
        self.assertTrue(self.marker.exists())
        self.assertIn(b'[REDACTED]', log)

    def test_login_prompt_never_receives_disk_key(self):
        connection = Mock()
        connection.recv.side_effect = [b'finite login: ', b'']
        with self.assertRaisesRegex(RuntimeError, 'never requested'):
            unlock.relay(connection, self.secret, io.BytesIO(), self.marker, io.BytesIO())
        connection.sendall.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_long_unbroken_output_does_not_leak_key_at_buffer_boundary(self):
        connection, log = self.run_console([
            b'Please enter passphrase for disk QEMU (luks-test):\n',
            b'x' * 16380 + self.secret[:32], self.secret[32:] + b'y' * 17000])
        connection.sendall.assert_called_once()
        self.assertIn(b'[REDACTED]', log)

    def test_retained_installer_and_journal_artifacts_are_redacted(self):
        state = self.marker.parent
        (state / 'nested').mkdir()
        for name in ('install.log', 'final-journal.log', 'nested/diagnostics.json'):
            (state / name).write_bytes(b'passphrase=' + self.secret + b'\n' + self.secret)
        public = state / 'acceptance.json'
        public.write_text('{"accepted": true}')
        redact.redact_logs(state, self.secret)
        for path in state.rglob('*'):
            if path.is_file():
                self.assertNotIn(self.secret, path.read_bytes())
        self.assertEqual(public.read_text(), '{"accepted": true}')
        self.assertIn(b'[REDACTED]', (state / 'install.log').read_bytes())

    def test_export_failure_never_exposes_raw_diagnostics(self):
        state = self.marker.parent / 'private'
        state.mkdir()
        (state / 'install.log').write_bytes(b'passphrase=' + self.secret)
        destination = self.marker.parent / '.bluebuild/vm-fresh'
        with patch.object(redact, 'redact_logs', side_effect=RuntimeError('redactor failed')):
            with self.assertRaisesRegex(RuntimeError, 'redactor failed'):
                redact.export_logs(state, self.secret, destination)
        self.assertFalse(destination.exists())
        with patch.object(redact, 'redact_logs'):
            with self.assertRaisesRegex(ValueError, 'still contain'):
                redact.export_logs(state, self.secret, destination)
        self.assertFalse(destination.exists())

    def test_export_only_includes_sanitized_diagnostics(self):
        state = self.marker.parent / 'private'
        state.mkdir()
        (state / 'install.log').write_bytes(b'passphrase=' + self.secret)
        (state / 'acceptance.json').write_text('{"accepted": true}')
        (state / 'ssh-key').write_bytes(self.secret)
        (state / 'ks.cfg').write_bytes(self.secret)
        (state / 'disk.qcow2').write_bytes(self.secret)
        destination = self.marker.parent / '.bluebuild/vm-fresh'
        redact.export_logs(state, self.secret, destination)
        self.assertEqual({path.name for path in destination.iterdir()}, {'install.log', 'acceptance.json'})
        self.assertNotIn(self.secret, (destination / 'install.log').read_bytes())
        self.assertEqual((destination / 'acceptance.json').read_text(), '{"accepted": true}')

    def test_encryption_checks_real_backing_devices_and_luks_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, body in {
                'findmnt': 'echo "$MOUNT_SOURCE"',
                'lsblk': '[ "$5" = /dev/mapper/luks-root ] || exit 1; echo "$TOPOLOGY"',
                'cryptsetup': 'echo "  type: $CRYPT_TYPE"',
            }.items():
                path = root / name
                path.write_text('#!' + shutil.which('bash') + '\n' + body + '\n')
                path.chmod(0o755)
            for kind, crypt_type, source, success in [
                    ('crypt', 'LUKS2', '/dev/mapper/luks-root', True),
                    ('crypt', 'LUKS2', '/dev/mapper/luks-root[/root]', True),
                    ('part', 'LUKS2', '/dev/mapper/luks-root', False),
                    ('crypt', 'PLAIN', '/dev/mapper/luks-root', False),
                    ('crypt', 'LUKS2', 'composefs', False)]:
                topology = {'blockdevices': [{'name': 'root', 'type': 'lvm',
                                              'children': [{'name': 'luks-root', 'type': kind}]}]}
                with self.subTest(kind=kind, crypt_type=crypt_type, source=source):
                    result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/check-vm-encryption.sh')],
                        env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                             'TOPOLOGY': json.dumps(topology), 'CRYPT_TYPE': crypt_type, 'MOUNT_SOURCE': source},
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, success, result.stderr)


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
        self.assertEqual(calls[0][:3], ['cosign', 'verify', '--new-bundle-format=false'])
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
