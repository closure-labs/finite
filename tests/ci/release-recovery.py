#!/usr/bin/env python3
"""Offline receipt/ZIP/credential fixtures; no native tools or GitHub calls."""
import argparse
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('release_recovery', ROOT / 'scripts/ci/release-recovery.py')
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        # Release fixtures use a stable source version independently of the
        # checkout's next-cycle prerelease VERSION.
        self.release_root = self.directory / 'release-source'
        self.release_root.mkdir()
        for relative in (*M.POLICY_INPUTS, 'VERSION'):
            destination = self.release_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'0.8.1\n' if relative == 'VERSION' else (ROOT / relative).read_bytes())
        root_patch = patch.object(M, 'ROOT', self.release_root)
        root_patch.start(); self.addCleanup(root_patch.stop)
        self.source, self.execution = 'a' * 40, 'b' * 40
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.time = self.now.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.run = {'id': 10, 'run_attempt': 1, 'head_sha': self.source, 'head_branch': 'main',
            'path': '.github/workflows/release.yml', 'event': 'workflow_dispatch', 'status': 'completed',
            'conclusion': 'failure', 'created_at': self.time,
            **{key: {'full_name': M.REPO, 'id': M.REPO_ID} for key in ('repository', 'head_repository')}}
        self.prep = {'id': 100, 'name': 'release', 'run_id': 10, 'run_attempt': 1, 'head_sha': self.source,
            'status': 'completed', 'conclusion': 'success', 'completed_at': self.time,
            'steps': [{'name': name, 'status': 'completed', 'conclusion': 'success', 'completed_at': self.time} for name in M.PREP_STEPS]}
        self.signer = dict(self.prep, id=101, name='sign-release', conclusion='failure', steps=[
            {'name': 'Create draft release with durable evidence', 'conclusion': 'failure'}])
        self.artifact = {'id': 8, 'name': 'unsigned-release-10-1', 'expired': False, 'size_in_bytes': 100,
            'digest': 'sha256:' + 'c' * 64, 'expires_at': (self.now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'workflow_run': {'id': 10, 'head_sha': self.source, 'head_branch': 'main',
                'repository_id': M.REPO_ID, 'head_repository_id': M.REPO_ID}}

    def test_requires_exact_original_main_manual_workflow_and_successful_preparation(self):
        M.preparation(self.run, [self.prep, self.signer], self.now)
        for key, value in [('head_branch', 'topic'), ('path', '.github/workflows/build.yml'), ('event', 'push'),
                           ('conclusion', 'success'), ('created_at', '2020-01-01T00:00:00Z')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                M.preparation(dict(self.run, **{key: value}), [self.prep, self.signer], self.now)
        for change in ({'conclusion': 'cancelled'}, {'run_attempt': 2}, {'head_sha': self.execution}, {'steps': []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                M.preparation(self.run, [dict(self.prep, **change), self.signer], self.now)

    def test_only_known_publication_failure_or_cancelled_signer_can_recover(self):
        cancelled = dict(self.run, conclusion='cancelled')
        M.preparation(cancelled, [self.prep, dict(self.signer, conclusion='cancelled')], self.now)
        M.preparation(dict(self.run, status='in_progress', conclusion=None), [self.prep], self.now)
        wrong = dict(self.signer, steps=[{'name': 'Sign release manifest in an isolated job', 'conclusion': 'failure'}])
        with self.assertRaises(ValueError): M.preparation(self.run, [self.prep, wrong], self.now)
        with self.assertRaises(ValueError): M.preparation(cancelled, [self.prep, self.signer], self.now)
        with self.assertRaises(ValueError): M.preparation(self.run, [self.prep, self.signer, dict(self.signer, name='unexpected')], self.now)

    def test_fresh_scan_must_be_successful_and_within_day(self):
        bad = copy.deepcopy(self.prep)
        bad['steps'][2]['completed_at'] = '2020-01-01T00:00:00Z'
        with self.assertRaises(ValueError): M.preparation(self.run, [bad, self.signer], self.now)
        bad['steps'][2]['completed_at'] = self.time; bad['steps'][2]['conclusion'] = 'failure'
        with self.assertRaises(ValueError): M.preparation(self.run, [bad, self.signer], self.now)

    def test_artifact_is_unique_current_attempt_exact_source_size_digest_and_expiry(self):
        M.artifact([self.artifact], self.artifact['name'], self.run, self.now)
        for change in ({'expired': True}, {'size_in_bytes': M.ARCHIVE + 1}, {'digest': 'bad'}, {'expires_at': '2020-01-01T00:00:00Z'},
                       {'workflow_run': dict(self.artifact['workflow_run'], head_sha=self.execution)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                M.artifact([dict(self.artifact, **change)], self.artifact['name'], self.run, self.now)
        with self.assertRaises(ValueError): M.artifact([self.artifact] * 2, self.artifact['name'], self.run, self.now)

    def zip(self, extra=None, duplicate=False):
        stream = io.BytesIO()
        with M.zipfile.ZipFile(stream, 'w') as archive:
            for name in ('installation.json', 'signature.json', 'SHA256SUMS', 'provenance.json', 'acceptance.json',
                         'publication.json', 'security-result.json', 'sbom.syft.json', 'vulnerabilities.json',
                         'finite-desktop-acceptance.json', 'finite.iso'):
                archive.writestr(name, b'fixture')
            if extra is not None: archive.writestr(*extra)
            if duplicate:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore'); archive.writestr('installation.json', b'duplicate')
        stream.seek(0); return stream

    def test_archive_requires_flat_regular_unique_complete_bounded_packet(self):
        M.extract_archive(self.zip(), self.directory / 'valid', 'finite')
        for number, name in enumerate(('../escape.json', '/absolute.json', 'nested/file.json', 'payload.sh', 'other.iso',
                                       'SHA256SUMS.bundle.json', 'release-recovery.json')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                M.extract_archive(self.zip((name, b'fixture')), self.directory / str(number), 'finite')
        with self.assertRaises(ValueError): M.extract_archive(self.zip(duplicate=True), self.directory / 'dup', 'finite')
        link = M.zipfile.ZipInfo('link.json'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError): M.extract_archive(self.zip((link, b'target')), self.directory / 'link', 'finite')

    def test_reupload_requires_recovery_receipt_and_still_rejects_unsigned_signature(self):
        with self.assertRaises(ValueError): M.extract_archive(self.zip(), self.directory / 'no-receipt', 'finite', recovery=True)
        M.extract_archive(self.zip(('release-recovery.json', b'{}')), self.directory / 'recovery', 'finite', recovery=True)

    def test_extraction_requires_declared_bytes_plus_free_disk_reserve(self):
        destination = self.directory / 'no-space'
        with patch.object(M.shutil, 'disk_usage', return_value=argparse.Namespace(free=0)), \
                self.assertRaisesRegex(ValueError, 'Insufficient free disk'):
            M.extract_archive(self.zip(), destination, 'finite')
        self.assertEqual(list(destination.iterdir()), [])

    def test_zip_directory_is_bounded_before_zipfile_allocates_and_zip64_is_supported(self):
        for count, size in ((257, 1), (1, 1024**2 + 1)):
            raw = M.struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, count, count, size, 0, 0)
            with patch.object(M.zipfile, 'ZipFile') as parser, self.assertRaises(ValueError):
                M.extract_archive(io.BytesIO(raw), self.directory / str(count), 'finite')
            parser.assert_not_called()
        record = M.struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 1, 1, 1, 0)
        locator = M.struct.pack('<4sLQL', b'PK\x06\x07', 0, 1, 1)
        end = M.struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 0xffff, 0xffff, 0xffffffff, 0xffffffff, 0)
        M.bound_directory(io.BytesIO(b'x' + record + locator + end))

    def test_archive_bytes_are_authenticated_before_extraction(self):
        raw = self.zip().getvalue()
        value = dict(self.artifact, size_in_bytes=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
        def fetch(command, **kwargs): kwargs['stdout'].write(raw)
        with patch.object(M.subprocess, 'run', side_effect=fetch), patch.object(M, 'extract_archive') as extract:
            M.download(value, self.directory / 'packet', 'finite')
            extract.assert_called_once()
        for change in ({'size_in_bytes': len(raw) + 1}, {'digest': 'sha256:' + '0' * 64}):
            with patch.object(M.subprocess, 'run', side_effect=fetch), patch.object(M, 'extract_archive') as extract, self.assertRaises(ValueError):
                M.download(dict(value, **change), self.directory / 'packet', 'finite')
            extract.assert_not_called()

    def packet(self):
        image = 'ghcr.io/closure-labs/finite@sha256:' + 'c' * 64
        installer = {'finiteRevision': self.source}
        installation = {'image': image, 'profile': 'finite', 'updateChannel': 'ghcr.io/closure-labs/finite:finite', 'installer': installer}
        self.inputs = {'fixture': {'sha256': 'd' * 64, 'executable': False, 'symlink': None}}
        context = {'schema': 2, 'platform': 'linux/amd64', 'inputs': self.inputs}
        (self.directory / 'finite.iso').write_bytes(b'synthetic fixture, not an image')
        (self.directory / 'installation.json').write_text(json.dumps(installation))
        acceptance = {'schema': 2, 'candidate': image, 'profile': 'finite', 'revision': self.source,
            'sourceRevision': self.source, 'buildIdentity': 'v1:' + 'e' * 64, 'previousDigest': 'sha256:' + 'f' * 64,
            'accepted': True, 'secureBoot': True, 'encryptedRoot': True, 'bootstrap': False,
            'qualificationContext': context, 'qualificationContextSha256': M.CONTEXT.identity(context),
            'qualifiedIso': {'name': 'finite.iso', 'sha256': M.sha(self.directory / 'finite.iso'),
                'installationSha256': M.sha(self.directory / 'installation.json'), 'installer': installer},
            'qualifiedIsoOrigin': {'run': 50, 'attempt': 1, 'revision': self.source}}
        publication = {key: acceptance[key] for key in ('profile', 'revision', 'sourceRevision', 'buildIdentity', 'previousDigest')}
        provenance = {'schema': 1, 'image': image, 'revision': self.source, 'sourceRevision': self.source,
            'buildIdentity': acceptance['buildIdentity'], 'qualification': acceptance, 'installer': installer,
            'buildRun': 'https://github.com/closure-labs/finite/actions/runs/50',
            'isoRun': 'https://github.com/closure-labs/finite/actions/runs/50', 'isoMatchesQualification': True}
        security = {'status': 'pass', 'image': image, 'scannedAt': self.time,
            'database': {'status': {'valid': True, 'built': self.time},
                         'providers': {provider: {'captured': self.time} for provider in ('fedora', 'kev')}},
            'policySha256': M.sha(ROOT / 'automation/security/image-policy.json'), 'scanner': 'fixture'}
        for name, value in (('acceptance.json', acceptance), ('publication.json', publication), ('provenance.json', provenance),
                            ('security-result.json', security), ('finite-desktop-acceptance.json', {})):
            (self.directory / name).write_text(json.dumps(value))
        return acceptance

    def verify_packet(self):
        build = dict(self.run, id=50, path='.github/workflows/build.yml', conclusion='success')
        with patch.object(M, 'github', return_value=build), patch.object(M.EVIDENCE.desktop, 'verify') as desktop, \
                patch.object(M, 'source_file', side_effect=lambda path, revision: (self.release_root / path).read_bytes()):
            result = M.packet(self.directory, 'finite', self.source, 10, inputs=self.inputs)
        desktop.assert_called_once()
        return result

    def test_preserves_original_source_and_exact_qualified_iso_and_security_provenance(self):
        self.packet(); result = self.verify_packet()
        self.assertEqual(result['sourceRevision'], self.source)
        self.assertEqual(result['buildRun'], 50)
        self.assertIn('security-result.json', result['receiptSha256'])

    def test_packet_rejects_context_drift_diagnostics_old_schema_stale_scan_or_changed_iso(self):
        original = self.packet()
        for name, changes in [('acceptance.json', {'schema': 1}), ('acceptance.json', {'validationOnly': True}),
                              ('acceptance.json', {'qualificationContext': {}}), ('security-result.json', {'status': 'blocked'}),
                              ('security-result.json', {'scannedAt': '2020-01-01T00:00:00Z'}),
                              ('security-result.json', {'database': {'status': {'valid': False}}}),
                              ('provenance.json', {'sourceRevision': self.execution})]:
            path = self.directory / name; saved = path.read_bytes()
            value = json.loads(saved); value.update(changes); path.write_text(json.dumps(value))
            with self.subTest(name=name, changes=changes), self.assertRaises((ValueError, KeyError)):
                self.verify_packet()
            path.write_bytes(saved)
        (self.directory / original['qualifiedIso']['name']).write_bytes(b'changed')
        with self.assertRaises(ValueError): self.verify_packet()

    def test_source_blob_size_sha_and_policy_drift_are_checked(self):
        raw = b'fixture'; blob = {'type': 'file', 'path': 'VERSION', 'encoding': 'base64', 'size': len(raw),
            'content': base64.b64encode(raw).decode(), 'sha': hashlib.sha1(b'blob 7\0' + raw).hexdigest()}
        with patch.object(M, 'github', return_value=blob): self.assertEqual(M.source_file('VERSION', self.source), raw)
        with patch.object(M, 'github', return_value=dict(blob, sha='0' * 40)), self.assertRaises(ValueError): M.source_file('VERSION', self.source)
        self.packet()
        with patch.object(M, 'source_file', return_value=b'0.8.1'), patch.object(M, 'github', return_value=dict(self.run, id=50, path='.github/workflows/build.yml', conclusion='success')), \
                patch.object(M.EVIDENCE.desktop, 'verify'), self.assertRaisesRegex(ValueError, 'drifted'):
            M.packet(self.directory, 'finite', self.source, 10, inputs=self.inputs)

    def test_previous_version_cannot_be_recovered_as_current_release(self):
        self.packet()
        build = dict(self.run, id=50, path='.github/workflows/build.yml', conclusion='success')
        with patch.object(M, 'github', return_value=build), patch.object(M.EVIDENCE.desktop, 'verify'), \
                patch.object(M, 'source_file', side_effect=lambda path, revision:
                    b'0.8.0\n' if path == 'VERSION' else (self.release_root / path).read_bytes()), \
                self.assertRaisesRegex(ValueError, 'VERSION differs'):
            M.packet(self.directory, 'finite', self.source, 10, inputs=self.inputs)

    def test_unused_tag_and_read_endpoint_allowlist_fail_closed(self):
        with patch.object(M, 'github', return_value=[{'ref': 'refs/tags/finite-0.8.1'}]), self.assertRaises(ValueError):
            M.unused_tag('finite-0.8.1')
        with patch.object(M.subprocess, 'run') as command:
            for path in ('git/refs', 'actions/artifacts/9/zip', 'contents/../../secret?ref=bad'):
                with self.subTest(path=path), self.assertRaises(ValueError): M.github(path)
        command.assert_not_called()

    def test_existing_draft_without_ref_is_rejected_before_any_creation(self):
        with patch.object(M, 'github', side_effect=[[], [{'draft': True, 'tag_name': 'finite-0.8.1'}]]) as request:
            with self.assertRaisesRegex(ValueError, 'existing draft'):
                M.unused_tag('finite-0.8.1')
        self.assertEqual(request.call_args_list[-1].args[0], 'releases?per_page=100&page=1')

    def test_release_listing_denials_nonjson_and_total_metadata_budget_fail_closed(self):
        path = 'releases?per_page=100&page=1'
        def response(raw, status):
            def run(command, **kwargs):
                kwargs['stdout'].write(raw)
                return argparse.Namespace(returncode=status)
            return run
        for raw, status in ((b'{"status":"403","message":"Forbidden"}', 1), (b'network failure', 1),
                            (b'', 1), (b'x' * (M.META + 1), 1), (b'{"status":"404","message":"Not Found"}', 2)):
            with self.subTest(raw=raw[:30], status=status), \
                    patch.object(M.subprocess, 'run', side_effect=response(raw, status)), self.assertRaises(ValueError):
                M.github(path)
        with patch.object(M.subprocess, 'run', side_effect=response(b'[]', 0)):
            self.assertEqual(M.github(path, budget={'remaining': 2}), [])
            with self.assertRaisesRegex(ValueError, 'total metadata'): M.github(path, budget={'remaining': 1})

    def test_release_absence_requires_complete_bounded_pagination(self):
        full = [{'tag_name': 'unrelated-' + str(number)} for number in range(100)]
        with patch.object(M, 'github', side_effect=[[], full, []]) as request:
            M.unused_tag('finite-0.8.1')
        self.assertEqual(request.call_count, 3)
        with patch.object(M, 'github', side_effect=[[], *([full] * 10)]) as request, self.assertRaisesRegex(ValueError, 'pagination budget'):
            M.unused_tag('finite-0.8.1')
        self.assertEqual(request.call_count, 11)
        with patch.object(M, 'github', side_effect=[[], full, [{'tag_name': 'finite-0.8.1', 'draft': True}]]), self.assertRaisesRegex(ValueError, 'existing draft'):
            M.unused_tag('finite-0.8.1')

    def test_nonhosted_or_nonmanual_execution_never_contacts_github(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(M, 'github') as github, self.assertRaises(ValueError): M.hosted()
        github.assert_not_called()

    def environment(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': M.REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': self.execution,
                'GITHUB_RUN_ID': '20', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_OUTPUT': str(self.directory / 'outputs')}

    def test_prepare_keeps_old_qualified_source_separate_from_new_recovery_execution(self):
        self.packet()
        build = dict(self.run, id=50, path='.github/workflows/build.yml', conclusion='success')
        def request(path, **kwargs):
            if path.startswith('git/matching-refs/'): return []
            if path.startswith('releases?'): return []
            if path == 'actions/runs/10': return self.run
            if path == 'actions/runs/50': return build
            if '/jobs?' in path: return [{'jobs': [self.prep, self.signer]}]
            if '/artifacts?' in path: return [{'artifacts': [self.artifact]}]
            if path.startswith('compare/'): return {'status': 'ahead', 'merge_base_commit': {'sha': self.source}}
            raise AssertionError(path)
        args = argparse.Namespace(channel='finite', tag='finite-0.8.1', prepared_run=10, output=self.directory)
        with patch.dict(os.environ, self.environment()), patch.object(M, 'github', side_effect=request), \
                patch.object(M, 'download') as download, patch.object(M.CONTEXT, 'source_inputs', return_value=self.inputs), \
                patch.object(M, 'source_file', side_effect=lambda path, revision: (self.release_root / path).read_bytes()), \
                patch.object(M.EVIDENCE.desktop, 'verify'):
            M.prepare(args)
        download.assert_called_once()
        receipt = json.loads((self.directory / 'release-recovery.json').read_text())
        self.assertEqual(receipt['sourceRevision'], self.source)
        self.assertEqual(receipt['recoveryExecutionRevision'], self.execution)
        self.assertEqual(receipt['originalUnsignedArtifact']['digest'], self.artifact['digest'])
        self.assertEqual(receipt['preparedAttempt'], 1)
        self.assertEqual((self.directory / 'outputs').read_text(), 'source=' + self.source + '\n')

    def test_signer_authenticates_exact_reupload_before_any_download(self):
        run = dict(self.run, id=20, head_sha=self.execution, path='.github/workflows/release-recovery.yml')
        value = dict(self.artifact, name='verified-unsigned-release-20-1',
            workflow_run=dict(self.artifact['workflow_run'], id=20, head_sha=self.execution))
        def request(path, **kwargs):
            if path == 'actions/runs/20': return run
            if '/artifacts?' in path: return [{'artifacts': [value]}]
            raise AssertionError(path)
        args = argparse.Namespace(channel='finite', tag='finite-0.8.1', artifact_id=value['id'],
            artifact_digest='sha256:' + '0' * 64, artifact_size=value['size_in_bytes'], output=self.directory)
        with patch.dict(os.environ, self.environment()), patch.object(M, 'github', side_effect=request), \
                patch.object(M, 'download') as download, self.assertRaisesRegex(ValueError, 'reupload differs'):
            M.signer(args)
        download.assert_not_called()

    def test_signer_keeps_provenance_bytes_and_signs_both_ends_of_archive_handoff(self):
        self.packet(); receipt = self.verify_packet()
        receipt.update(schema=1, channel='finite', tag='finite-0.8.1', preparedAttempt=1,
            preparationJob=100, securityScanCompletedAt=self.time,
            originalUnsignedArtifact=self.artifact, recoveryRun=20, recoveryAttempt=1,
            recoveryExecutionRevision=self.execution)
        (self.directory / 'release-recovery.json').write_text(json.dumps(receipt))
        original_provenance = (self.directory / 'provenance.json').read_bytes()
        run = dict(self.run, id=20, head_sha=self.execution, path='.github/workflows/release-recovery.yml')
        build = dict(self.run, id=50, path='.github/workflows/build.yml', conclusion='success')
        value = dict(self.artifact, name='verified-unsigned-release-20-1',
            workflow_run=dict(self.artifact['workflow_run'], id=20, head_sha=self.execution))
        def request(path, **kwargs):
            if path == 'actions/runs/20': return run
            if path == 'actions/runs/50': return build
            if '/artifacts?' in path: return [{'artifacts': [value]}]
            if path.startswith('git/matching-refs/'): return []
            if path.startswith('releases?'): return []
            raise AssertionError(path)
        args = argparse.Namespace(channel='finite', tag='finite-0.8.1', artifact_id=value['id'],
            artifact_digest=value['digest'], artifact_size=value['size_in_bytes'], output=self.directory)
        with patch.dict(os.environ, self.environment()), patch.object(M, 'github', side_effect=request), \
                patch.object(M, 'download') as download, patch.object(M.CONTEXT, 'source_inputs', return_value=self.inputs), \
                patch.object(M, 'source_file', side_effect=lambda path, revision: (self.release_root / path).read_bytes()), \
                patch.object(M.EVIDENCE.desktop, 'verify'):
            M.signer(args)
        download.assert_called_once_with(value, self.directory, 'finite', recovery=True)
        signed = json.loads((self.directory / 'release-recovery-signing.json').read_text())
        self.assertEqual(signed['verifiedUnsignedArtifact']['digest'], value['digest'])
        self.assertEqual(signed['originalRecoveryReceiptSha256'], M.sha(self.directory / 'release-recovery.json'))
        self.assertEqual((self.directory / 'provenance.json').read_bytes(), original_provenance)

    def test_nonancestor_source_is_rejected_before_native_archive_download(self):
        def request(path, **kwargs):
            if path.startswith('git/matching-refs/'): return []
            if path.startswith('releases?'): return []
            if path == 'actions/runs/10': return self.run
            if '/jobs?' in path: return [{'jobs': [self.prep, self.signer]}]
            if path.startswith('compare/'): return {'status': 'diverged', 'merge_base_commit': {'sha': '0' * 40}}
            raise AssertionError(path)
        args = argparse.Namespace(channel='finite', tag='finite-0.8.1', prepared_run=10, output=self.directory)
        with patch.dict(os.environ, self.environment()), patch.object(M, 'github', side_effect=request), \
                patch.object(M, 'download') as download, self.assertRaisesRegex(ValueError, 'ancestor'):
            M.prepare(args)
        download.assert_not_called()

    def test_workflow_scopes_evidence_signing_and_publishing_separately(self):
        workflow = (ROOT / '.github/workflows/release-recovery.yml').read_text()
        before_sign = workflow.split('  sign-release:', 1)[0]
        self.assertNotIn('secrets.', before_sign)
        self.assertIn('environment: release', workflow)
        self.assertNotIn('contents: write', workflow)
        self.assertIn('finite-ci-secrets-run release-publishing -- bash scripts/ci/create-release-draft.sh', workflow)
        publisher = (ROOT / 'scripts/ci/create-release-draft.sh').read_text()
        self.assertIn('sha=$RELEASE_SOURCE_SHA', publisher)
        self.assertNotIn('sha=$GITHUB_SHA', publisher)
        self.assertIn('--draft --verify-tag', publisher)
        self.assertNotIn('--clobber', publisher)

    def test_controlled_publisher_creates_only_exact_new_tag_and_stops_before_draft_on_failure(self):
        for case, expected_calls, success in (('success', 4, True), ('post-failure', 2, False),
                ('foreign-ref', 3, False), ('existing-draft', 1, False), ('forbidden', 1, False), ('network', 1, False),
                ('paged-success', 5, True), ('paged-draft', 2, False), ('pagination-exhausted', 10, False),
                ('changed-provenance', 0, False), ('wrong-tag', 0, False), ('duplicated-prefix', 0, False), ('missing-notes', 0, False), ('dev-success', 4, True)):
            with self.subTest(case=case):
                root = self.directory / case; root.mkdir(); (root / '.bluebuild/release').mkdir(parents=True)
                (root / 'VERSION').write_text('0.8.1\n')
                (root / 'CHANGELOG.md').write_text('## [0.8.1] - 2026-10-15\n\n### Changed\n\n- New OS and measured reuse.\n')
                for name in ('SHA256SUMS', 'SHA256SUMS.bundle.json'): (root / '.bluebuild/release' / name).write_text('fixture')
                (root / '.bluebuild/release/provenance.json').write_text(json.dumps({'revision': self.execution if case == 'changed-provenance' else self.source}))
                if case == 'missing-notes': (root / 'CHANGELOG.md').write_text('## [Unreleased]\n')
                binary = root / 'bin'; binary.mkdir(); gh = binary / 'gh'
                gh.write_text('#!' + sys.executable + '\n'
                    'import json,os,sys\n'
                    'assert "MERGE_QUEUE_TOKEN" not in os.environ and "COSIGN_PRIVATE_KEY" not in os.environ\n'
                    'args=sys.argv[1:]; log=os.environ["FIXTURE_CALLS"]\n'
                    'with open(log,"a") as output: output.write(json.dumps(args)+"\\n")\n'
                    'if args[0] == "api" and "/releases?" in args[1]:\n'
                    ' mode=os.environ["FIXTURE_CASE"]\n'
                    ' page=int(args[1].rsplit("=",1)[1])\n'
                    ' if mode == "existing-draft" or (mode == "paged-draft" and page==2): print(json.dumps([{"draft":True,"tag_name":os.environ["RELEASE_TAG"]}])); raise SystemExit(0)\n'
                    ' if mode == "network": print("not JSON"); raise SystemExit(1)\n'
                    ' if mode == "forbidden": print(json.dumps({"status":"403"})); raise SystemExit(1)\n'
                    ' if mode == "pagination-exhausted" or (mode in ("paged-success","paged-draft") and page==1): print(json.dumps([{"tag_name":"unrelated-"+str(n)} for n in range(100)])); raise SystemExit(0)\n'
                    ' print("[]"); raise SystemExit(0)\n'
                    'if "POST" in args:\n'
                    ' assert "sha="+os.environ["RELEASE_SOURCE_SHA"] in args\n'
                    ' if os.environ["FIXTURE_CASE"] == "post-failure": raise SystemExit(1)\n'
                    'elif args[0] == "api":\n'
                    ' print(json.dumps({"ref":"refs/tags/"+os.environ["RELEASE_TAG"],"object":{"type":"commit","sha":"0"*40 if os.environ["FIXTURE_CASE"] == "foreign-ref" else os.environ["RELEASE_SOURCE_SHA"]}}))\n'
                    'else:\n'
                    ' assert args[:2] == ["release","create"] and "--draft" in args and "--verify-tag" in args\n'
                    ' assert args[args.index("--title")+1] == os.environ["RELEASE_TAG"]\n'
                    ' assert "New OS and measured reuse." in open(args[args.index("--notes-file")+1]).read()\n')
                gh.chmod(0o755)
                env = {**os.environ, **self.environment(), 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                    'RELEASE_SOURCE_SHA': self.source, 'RELEASE_TAG': {'wrong-tag': 'v0.8.1', 'duplicated-prefix': 'finite-finite-0.8.1', 'dev-success': 'finite-dev-0.8.1'}.get(case, 'finite-0.8.1'),
                    'FIXTURE_CASE': case, 'FIXTURE_CALLS': str(root / 'calls'),
                    'MERGE_QUEUE_TOKEN': 'excluded-fixture', 'COSIGN_PRIVATE_KEY': 'excluded-fixture'}
                result = subprocess.run([shutil.which('bash'), str(ROOT / 'scripts/ci/create-release-draft.sh')],
                    cwd=root, env=env, capture_output=True, timeout=10)
                calls = (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []
                self.assertEqual(len(calls), expected_calls, result.stderr.decode())
                self.assertEqual(result.returncode == 0, success, result.stderr.decode())


if __name__ == '__main__': unittest.main()
