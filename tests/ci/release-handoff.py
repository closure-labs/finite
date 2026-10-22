#!/usr/bin/env python3
"""Metadata signing retains native preparation, authority and exact-byte joins."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import release_handoff as handoff
spec = importlib.util.spec_from_file_location('handoff_execution', ROOT / 'scripts/ci/execute-release-set.py')
execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'prepared'
        self.output.mkdir()
        self.reference = 'ghcr.io/closure-labs/finite-decisions@sha256:' + 'f' * 64
        self.document = {'schema': 1, 'payload': {'version': '1.2.3-dev', 'sourceRevision': 'a' * 40, 'channels': {}}}
        for channel in handoff.CHANNELS:
            core = hashlib.sha256(channel.encode()).hexdigest()
            self.document['payload']['channels'][channel] = {'assets': {'product.iso': core}}
            scan = self.output / ('security-' + channel)
            scan.mkdir()
            (scan / 'security-result.json').write_text('{}')
            (scan / 'sbom.spdx.json').write_text('{}')
        self.proposal = {'schema': 1, 'kind': 'release-set', 'payload': self.document['payload']}
        (self.output / 'release-set.json').write_text(json.dumps(self.document))
        for channel in handoff.CHANNELS:
            directory = self.output / 'signed' / channel
            directory.mkdir(parents=True)
            (directory / 'product.iso').write_bytes(channel.encode())
            (directory / 'release-set.json').write_text(json.dumps(self.document))
            for name in ('security-result.json', 'sbom.spdx.json', 'security-admission.json'):
                (directory / name).write_text('{}')
        self.identity = {'repository': handoff.REPOSITORY, 'workflow': 'publish-release-set.yml',
                         'runId': 5, 'runAttempt': 1, 'headSha': 'b' * 40}
        self.run = {'id': 5, 'run_attempt': 1, 'head_sha': 'b' * 40,
                    'path': handoff.WORKFLOW, 'head_branch': 'main', 'event': 'workflow_dispatch',
                    'head_repository': {'full_name': handoff.REPOSITORY}}
        self.job = {'name': 'prepare', 'run_id': 5, 'run_attempt': 1, 'head_sha': 'b' * 40,
                    'status': 'completed', 'conclusion': 'success'}
        with patch.dict(os.environ, GITHUB_RUN_ID='5', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='b' * 40):
            self.request = self.root / 'request'
            handoff.create(self.output, self.request, self.proposal, self.reference)

    def test_request_contains_no_product_and_signer_covers_approved_core_hashes(self):
        self.assertFalse(list(self.request.rglob('*.iso')))
        with patch.dict(os.environ, COSIGN_PRIVATE_KEY='test'), \
                patch.object(execution, 'payload_digest', return_value='approved'), \
                patch.object(execution.subprocess, 'run') as cosign:
            def sign(command, **kwargs):
                if command[1] == 'sign-blob':
                    Path(command[command.index('--bundle') + 1]).write_text('{}')
            cosign.side_effect = sign
            execution.sign(self.request, self.document, metadata_only=True)
        for channel in handoff.CHANNELS:
            directory = self.request / 'signed' / channel
            self.assertIn(hashlib.sha256(channel.encode()).hexdigest() + '  product.iso',
                          (directory / 'SHA256SUMS').read_text())
            self.assertFalse((directory / 'product.iso').exists())

    def test_preparation_requires_exact_native_success_and_repository(self):
        handoff.native_preparation(self.identity, lambda _: self.run, lambda *_: [self.job])
        for changes in ({'head_sha': 'c' * 40}, {'run_attempt': 2}, {'event': 'pull_request'},
                        {'head_repository': {'full_name': 'foreign/finite'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                handoff.native_preparation(self.identity, lambda _: {**self.run, **changes}, lambda *_: [self.job])
        for jobs in ([], [self.job, self.job], [{**self.job, 'conclusion': 'failure'}],
                     [{**self.job, 'status': 'in_progress'}], [{**self.job, 'run_attempt': 2}]):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                handoff.native_preparation(self.identity, lambda _: self.run, lambda *_: jobs)

    def test_current_approval_and_original_immutable_reference_cannot_be_substituted(self):
        for field, value in (('proposalHash', '0' * 64), ('payloadDigest', '0' * 64),
                             ('productReference', self.reference.replace('f' * 64, 'e' * 64))):
            record = json.loads((self.request / 'handoff.json').read_text())
            original = record.copy()
            record[field] = value
            (self.request / 'handoff.json').write_text(json.dumps(record))
            with self.subTest(field=field), self.assertRaises(ValueError):
                handoff.validate(self.request, self.proposal, self.reference)
            (self.request / 'handoff.json').write_text(json.dumps(original))
        forged = copy.deepcopy(self.proposal)
        forged['payload']['channels']['finite']['assets']['product.iso'] = '0' * 64
        with self.assertRaises(ValueError):
            handoff.validate(self.request, forged, self.reference)

    def test_products_are_hydrated_once_and_tampering_fails_before_upload(self):
        def fetch(reference, packet, **kwargs):
            self.assertEqual(reference, self.reference)
            packet.mkdir(parents=True)
            shutil.copyfile(self.output / 'release-set.json', packet / 'release-set.json')
            for channel in handoff.CHANNELS:
                directory = packet / ('release-' + channel)
                directory.mkdir()
                shutil.copyfile(self.output / 'signed' / channel / 'product.iso', directory / 'product.iso')
        for corrupt in (False, True):
            output = self.root / ('bad' if corrupt else 'good')
            shutil.copytree(self.request, output)
            def modified_fetch(*args, **kwargs):
                fetch(*args, **kwargs)
                if corrupt:
                    (args[1] / 'release-finite/product.iso').write_bytes(b'forged')
            with patch.object(handoff.decision_packets, 'fetch', side_effect=modified_fetch) as read, \
                    patch.object(execution, 'signed_inventory') as signed:
                def hydrate():
                    handoff.hydrate(output, self.proposal, self.reference, api=lambda _: self.run,
                                    collection=lambda *_: [self.job], verify_signed=signed)
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'signed approved hash'):
                        hydrate()
                else:
                    hydrate()
                    self.assertEqual(signed.call_count, 2)
                    for channel in handoff.CHANNELS:
                        self.assertEqual((output / 'signed' / channel / 'product.iso').read_bytes(), channel.encode())
                self.assertEqual(read.call_count, 1)

    def test_forged_signature_stops_before_fetching_products(self):
        with patch.object(handoff.decision_packets, 'fetch') as fetch:
            def reject(*args, **kwargs):
                raise ValueError('invalid signature')
            with self.assertRaisesRegex(ValueError, 'invalid signature'):
                handoff.hydrate(self.request, self.proposal, self.reference, api=lambda _: self.run,
                                collection=lambda *_: [self.job], verify_signed=reject)
            fetch.assert_not_called()

    def test_metadata_archive_reuses_native_prepare_attempt_and_authenticates_zip(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            for path in self.request.rglob('*'):
                if path.is_file():
                    zipped.writestr(path.relative_to(self.request).as_posix(), path.read_bytes())
        raw = archive.getvalue()
        artifact = {'id': 12, 'name': 'release-signing-request-5-1', 'expired': False,
                    'workflow_run': {'id': 5, 'head_sha': 'b' * 40}, 'size_in_bytes': len(raw),
                    'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
        def collection(endpoint, key):
            return [artifact] if key == 'artifacts' else [self.job]
        def download(command, **kwargs):
            kwargs['stdout'].write(raw)
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), \
                    patch.dict(os.environ, GITHUB_RUN_ID='5', GITHUB_RUN_ATTEMPT='2', GITHUB_SHA='b' * 40), \
                    patch.object(execution.controller, 'collection', side_effect=collection), \
                    patch.object(execution.subprocess, 'run', side_effect=download):
                target = self.root / ('bad-zip' if corrupt else 'good-zip')
                if corrupt:
                    artifact['digest'] = 'sha256:' + '0' * 64
                    with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                        execution.download_execution(target, signed=False, github=lambda _: self.run, metadata_only=True)
                else:
                    execution.download_execution(target, signed=False, github=lambda _: self.run, metadata_only=True)
                    record = handoff.validate(target, self.proposal, self.reference)
                    self.assertEqual(record['preparation']['runAttempt'], 1)
                    self.assertFalse(list(target.rglob('*.iso')))

    def test_expanded_metadata_size_is_bounded_before_writing_a_large_member(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr('large.json', b'X' * 4096)
        archive.seek(0)
        destination = self.root / 'expanded'
        with self.assertRaisesRegex(ValueError, 'Unsafe Actions ZIP member'):
            execution.archive_read.extract(archive, destination, max_bytes=1024)
        self.assertFalse((destination / 'large.json').exists())

    def test_metadata_cannot_contain_products_links_or_exceed_size_limit(self):
        path = self.request / 'signed/finite/product.iso'
        path.write_bytes(b'finite')
        with self.assertRaisesRegex(ValueError, 'metadata only'):
            handoff.validate(self.request, self.proposal, self.reference)
        path.unlink()
        path.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            handoff.validate(self.request, self.proposal, self.reference)
        path.unlink()
        with patch.object(handoff, 'MAX_BYTES', 1), self.assertRaisesRegex(ValueError, '2 GiB'):
            handoff.inventory(self.request)


if __name__ == '__main__':
    unittest.main()
