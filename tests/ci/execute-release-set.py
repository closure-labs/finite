#!/usr/bin/env python3
"""Official publication verifies human authority, signed bytes and producer identities."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('execute_release_set', ROOT / 'scripts/ci/execute-release-set.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from release_set import prepare


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        payload = {'version': '1.2.3', 'sourceRevision': 'a' * 40, 'channels': {}}
        evidence = {}
        for channel in ('finite', 'finite-dev'):
            directory = self.root / ('release-' + channel)
            directory.mkdir()
            (directory / 'image.iso').write_bytes(channel.encode())
            digest = hashlib.sha256(channel.encode()).hexdigest()
            payload['channels'][channel] = {'tag': channel + '-1.2.3', 'imageDigest': 'sha256:' + digest,
                                          'isoSha256': digest, 'assets': {'image.iso': digest}}
            evidence[channel] = {'status': 'qualified', 'sourceRevision': 'a' * 40,
                                 'imageDigest': 'sha256:' + digest, 'isoSha256': digest}
        self.document = prepare(payload, evidence)
        (self.root / 'release-set.json').write_text(json.dumps(self.document))
        self.proposal = {'schema': 1, 'kind': 'release-set', 'payload': payload}
        self.manifest = {'producer': {'repository': 'closure-labs/finite', 'workflow': 'release-set.yml',
                                      'runId': 5, 'runAttempt': 1, 'headSha': 'a' * 40, 'artifacts': []}, 'files': {}}
        self.artifact = {'id': 10, 'name': 'release-set-packet-5-1', 'digest': 'sha256:' + 'b' * 64}
        self.manifest['producer']['artifacts'] = [self.artifact.copy()]
        self.binding = patch.object(module.release_artifact, 'bound_artifact', return_value=self.artifact)
        self.archive_check = patch.object(module.release_artifact, 'verify_archive')
        self.binding.start()
        self.archive_check.start()
        self.addCleanup(self.binding.stop)
        self.addCleanup(self.archive_check.stop)
        self.run = {'id': 5, 'run_attempt': 1, 'head_sha': 'a' * 40, 'head_branch': 'main',
                    'head_repository': {'full_name': 'closure-labs/finite'}, 'status': 'completed',
                    'conclusion': 'success', 'event': 'workflow_dispatch', 'path': '.github/workflows/release-set.yml'}

    def test_initial_product_requires_exact_approved_payload_and_trusted_producer(self):
        document = module.check_product(self.root, self.proposal, self.manifest, github=lambda _: self.run)
        self.assertEqual(document, self.document)
        self.run['head_repository']['full_name'] = 'attacker/repo'
        with self.assertRaises(ValueError):
            module.check_product(self.root, self.proposal, self.manifest, github=lambda _: self.run)
        self.run['head_repository']['full_name'] = 'closure-labs/finite'
        (self.root / 'release-finite/image.iso').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'asset mismatch'):
            module.check_product(self.root, self.proposal, self.manifest, github=lambda _: self.run)

    def test_known_real_producer_cannot_authorize_forged_packet_product_bytes(self):
        original = io.BytesIO()
        with zipfile.ZipFile(original, 'w') as zipped:
            for path in self.root.rglob('*'):
                if path.is_file():
                    zipped.writestr(path.relative_to(self.root).as_posix(), path.read_bytes())
        raw = original.getvalue()
        self.artifact.update(size_in_bytes=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
        self.manifest['producer']['artifacts'] = [{k: self.artifact[k] for k in ('id', 'name', 'digest')}]
        # Forge both the claimed approved core and matching packet bytes. The
        # successful real run is unchanged; its actual ZIP disproves the claim.
        fake = b'forged product'
        digest = hashlib.sha256(fake).hexdigest()
        (self.root / 'release-finite/image.iso').write_bytes(fake)
        self.document['payload']['channels']['finite']['assets']['image.iso'] = digest
        (self.root / 'release-set.json').write_text(json.dumps(self.document))
        self.archive_check.stop()
        def download(*args, **kwargs):
            kwargs['stdout'].write(raw)
        try:
            with patch.object(module.release_artifact.subprocess, 'run', side_effect=download):
                with self.assertRaisesRegex(ValueError, 'authenticated original Actions archive'):
                    module.check_product(self.root, self.proposal, self.manifest, github=lambda _: self.run)
        finally:
            self.archive_check.start()

    def test_automatic_push_resolves_one_canonical_new_release_and_rejects_ambiguous_diff(self):
        identity = module.canonical_hash(self.proposal)
        path = 'automation/decisions/releases/' + identity + '.json'
        (self.root / path).parent.mkdir(parents=True)
        (self.root / path).write_text(json.dumps(self.proposal))
        comparison = {'status': 'ahead', 'files': [{'filename': path, 'status': 'added'}]}
        with patch.object(module, 'ROOT', self.root), patch.dict(os.environ, GITHUB_EVENT_NAME='push', GITHUB_SHA='b' * 40):
            self.assertEqual(module.proposal_from_push(github=lambda _: comparison, event={'before': 'a' * 40}), identity)
            comparison['files'].append({'filename': path, 'status': 'added'})
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                module.proposal_from_push(github=lambda _: comparison, event={'before': 'a' * 40})
            comparison['files'].pop()
            comparison['files'][0]['status'] = 'modified'
            with self.assertRaises(ValueError):
                module.proposal_from_push(github=lambda _: comparison, event={'before': 'a' * 40})

    def test_signed_checksums_cover_every_core_and_derived_byte_and_require_cosign(self):
        directory = self.root / 'release-finite'
        core = self.document['payload']['channels']['finite']['assets']
        (directory / 'report.json').write_text('{}')
        report_hash = module.sha256(directory / 'report.json')
        (directory / 'release-set.json').write_text(json.dumps(self.document))
        manifest_hash = module.sha256(directory / 'release-set.json')
        (directory / 'SHA256SUMS').write_text(core['image.iso'] + '  image.iso\n' + report_hash + '  report.json\n' + manifest_hash + '  release-set.json\n')
        (directory / 'SHA256SUMS.bundle.json').write_text('{}')
        def inventory():
            return {p.name: module.sha256(p) for p in directory.iterdir() if p.name not in core}
        with patch.object(module.subprocess, 'run') as cosign:
            module.validate_signed('finite', directory, core, inventory(), self.document)
            self.assertEqual(cosign.call_args.args[0][:2], ['cosign', 'verify-blob'])
            (directory / 'SHA256SUMS').write_text(report_hash + '  report.json\n')
            with self.assertRaisesRegex(ValueError, 'exact approved products'):
                module.validate_signed('finite', directory, core, inventory(), self.document)
        with patch.object(module.subprocess, 'run', side_effect=RuntimeError('invalid cryptographic signature')):
            with self.assertRaises(RuntimeError):
                module.validate_signed('finite', directory, core, inventory(), self.document)

    def test_valid_old_signature_cannot_authorize_rewritten_unsigned_outer_release_payload(self):
        directory = self.root / 'release-finite'
        core = self.document['payload']['channels']['finite']['assets']
        # Reuse old signed release metadata while an attacker claims a different
        # image digest in the unsigned outer recovery document.
        (directory / 'release-set.json').write_text(json.dumps(self.document))
        (directory / 'SHA256SUMS').write_text('not reached')
        (directory / 'SHA256SUMS.bundle.json').write_text('{}')
        derived = {p.name: module.sha256(p) for p in directory.iterdir() if p.name not in core}
        forged = json.loads(json.dumps(self.document))
        forged['payload']['channels']['finite']['imageDigest'] = 'sha256:' + 'f' * 64
        with patch.object(module.subprocess, 'run') as cosign:
            with self.assertRaisesRegex(ValueError, 'different approved payload'):
                module.validate_signed('finite', directory, core, derived, forged)
            cosign.assert_not_called()

    def test_initial_packet_reference_is_advisory_not_authority(self):
        identity = module.canonical_hash(self.proposal)
        record = self.root / 'automation/decisions/releases'
        record.mkdir(parents=True)
        (record / (identity + '.json')).write_text(json.dumps(self.proposal))
        body = 'Initial durable product packet: `ghcr.io/closure-labs/finite-decisions@sha256:' + 'b' * 64 + '`'
        with patch.object(module, 'ROOT', self.root), patch.dict(os.environ, FINITE_REVIEW_BOT_LOGIN='review[bot]'), \
                patch.object(module.controller.authority, 'find_origin_pr', return_value=9), \
                patch.object(module.controller.authority, 'verify_proposal', return_value={'status': 'authorized'}) as authority:
            self.assertTrue(module.approved(identity, github=lambda _: {'body': body})[2].endswith('b' * 64))
            self.assertTrue(authority.call_args.kwargs['require_merged'])
            with self.assertRaisesRegex(ValueError, 'one unambiguous'):
                module.approved(identity, github=lambda _: {'body': body + '\n' + body})
            authority.side_effect = ValueError('Maintainer dismissed approval')
            with self.assertRaisesRegex(ValueError, 'dismissed'):
                module.approved(identity, github=lambda _: {'body': body})

    def test_retry_download_uses_authenticated_prior_signing_attempt_and_rejects_zip_traversal(self):
        for bad_path in (False, True):
            with self.subTest(bad_path=bad_path):
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, 'w') as zipped:
                    zipped.writestr('../escape' if bad_path else 'signed/finite/image.iso', b'product')
                raw = archive.getvalue()
                artifact = {'id': 12, 'name': 'signed-release-execution-5-1', 'expired': False,
                            'workflow_run': {'id': 5, 'head_sha': 'a' * 40}, 'size_in_bytes': len(raw),
                            'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
                run = {**self.run, 'path': '.github/workflows/publish-release-set.yml'}
                def download(*args, **kwargs):
                    kwargs['stdout'].write(raw)
                destination = self.root / ('download-bad' if bad_path else 'download-good')
                with patch.dict(os.environ, GITHUB_RUN_ID='5', GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='a' * 40), \
                        patch.object(module.controller, 'collection', return_value=[artifact]), \
                        patch.object(module.subprocess, 'run', side_effect=download):
                    if bad_path:
                        with self.assertRaisesRegex(ValueError, 'Unsafe packet'):
                            module.download_execution(destination, github=lambda _: run)
                    else:
                        selected = module.download_execution(destination, github=lambda _: run)
                        self.assertEqual(selected['name'], 'signed-release-execution-5-1')
                        self.assertEqual((destination / 'signed/finite/image.iso').read_bytes(), b'product')

    def test_recovery_packet_requires_completed_signer_and_crypto_validation(self):
        manifest = {'producer': {**self.manifest['producer'], 'workflow': 'publish-release-set.yml'}}
        run = {**self.run, 'path': '.github/workflows/publish-release-set.yml', 'conclusion': 'failure'}
        with patch.object(module.controller, 'collection', return_value=[{'name': 'sign', 'conclusion': 'success'}]), \
                patch.object(module, 'signed_inventory') as signatures:
            self.assertEqual(module.check_signed_packet(self.root, self.proposal, manifest, github=lambda _: run), self.document)
            signatures.assert_called_once()
            with patch.object(module.controller, 'collection', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'isolated signing'):
                    module.check_signed_packet(self.root, self.proposal, manifest, github=lambda _: run)


if __name__ == '__main__':
    unittest.main()
