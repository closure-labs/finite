#!/usr/bin/env python3
"""Official publication verifies human authority, signed bytes and producer identities."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
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


class ArchiveDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'product.iso').write_bytes(b'qualified product')
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('product.iso', b'qualified product')
        self.raw = archive.getvalue()
        self.artifact = {'id': 10, 'size_in_bytes': len(self.raw),
                         'digest': 'sha256:' + hashlib.sha256(self.raw).hexdigest()}

    def test_partial_transport_failures_restart_clean_and_still_authenticate_bytes(self):
        errors = [subprocess.TimeoutExpired(['gh', 'api'], 1800),
                  subprocess.CalledProcessError(1, ['gh', 'api'], stderr='read tcp: read: connection timed out'),
                  subprocess.CalledProcessError(1, ['gh', 'api'], stderr='HTTP 503')]
        for error in errors:
            attempts = []
            def download(command, **kwargs):
                output = kwargs['stdout']
                output.seek(0, 2)
                self.assertEqual(output.tell(), 0, 'Partial bytes must be discarded before each request')
                attempts.append(command)
                if len(attempts) == 1:
                    output.write(b'partial bytes that must not survive the retry')
                    raise error
                output.write(self.raw)
            with self.subTest(error=str(error)), patch.object(module.release_artifact.subprocess, 'run', side_effect=download), \
                    patch.object(module.release_artifact.time, 'sleep') as sleep:
                files = module.release_artifact.verify_archive(self.root, self.artifact)
                self.assertEqual(files['product.iso']['sha256'], hashlib.sha256(b'qualified product').hexdigest())
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0], attempts[1])
                self.assertEqual(attempts[0][:2], ['gh', 'api'])
                sleep.assert_called_once_with(2)

    def test_persistent_transport_failure_exhausts_three_attempts(self):
        error = subprocess.CalledProcessError(1, ['gh', 'api'], stderr='read tcp: read: connection timed out')
        with patch.object(module.release_artifact.subprocess, 'run', side_effect=error) as run, \
                patch.object(module.release_artifact.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                module.release_artifact.verify_archive(self.root, self.artifact)
            self.assertEqual(run.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_authorization_missing_artifact_and_other_command_errors_never_retry(self):
        for stderr in ('HTTP 401', 'HTTP 403: connection timed out', 'HTTP 404', 'authentication required'):
            error = subprocess.CalledProcessError(1, ['gh', 'api'], stderr=stderr)
            with self.subTest(stderr=stderr), patch.object(module.release_artifact.subprocess, 'run', side_effect=error) as run, \
                    patch.object(module.release_artifact.time, 'sleep') as sleep:
                with self.assertRaises(subprocess.CalledProcessError):
                    module.release_artifact.verify_archive(self.root, self.artifact)
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_size_digest_and_product_mismatches_never_retry(self):
        for mismatch in ('size', 'digest', 'product'):
            artifact = self.artifact.copy()
            (self.root / 'product.iso').write_bytes(b'forged' if mismatch == 'product' else b'qualified product')
            if mismatch == 'size':
                artifact['size_in_bytes'] += 1
            if mismatch == 'digest':
                artifact['digest'] = 'sha256:' + '0' * 64
            def download(command, **kwargs):
                kwargs['stdout'].write(self.raw)
            with self.subTest(mismatch=mismatch), patch.object(module.release_artifact.subprocess, 'run', side_effect=download) as run, \
                    patch.object(module.release_artifact.time, 'sleep') as sleep:
                with self.assertRaises(ValueError):
                    module.release_artifact.verify_archive(self.root, artifact)
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_retried_download_still_rejects_changed_archive_without_a_third_request(self):
        attempts = []
        def download(command, **kwargs):
            attempts.append(command)
            if len(attempts) == 1:
                kwargs['stdout'].write(b'partial')
                raise subprocess.CalledProcessError(1, command, stderr='HTTP 502')
            kwargs['stdout'].write(b'X' + self.raw[1:])
        with patch.object(module.release_artifact.subprocess, 'run', side_effect=download), \
                patch.object(module.release_artifact.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                module.release_artifact.verify_archive(self.root, self.artifact)
            self.assertEqual(len(attempts), 2)
            sleep.assert_called_once_with(2)

    def test_staged_archive_reuses_transport_but_rechecks_size_digest_and_product_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            cached = Path(directory) / 'original.zip'
            def download(command, **kwargs):
                kwargs['stdout'].write(self.raw)
            with patch.object(module.release_artifact.subprocess, 'run', side_effect=download) as run:
                module.release_artifact.verify_archive(self.root, self.artifact, cached_archive=cached)
                module.release_artifact.verify_archive(self.root, self.artifact, cached_archive=cached)
                self.assertEqual(run.call_count, 1)
                (self.root / 'product.iso').write_bytes(b'forged product')
                with self.assertRaisesRegex(ValueError, 'authenticated original Actions archive'):
                    module.release_artifact.verify_archive(self.root, self.artifact, cached_archive=cached)
                cached.write_bytes(b'X' + self.raw[1:])
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    module.release_artifact.verify_archive(self.root, self.artifact, cached_archive=cached)
                cached.write_bytes(self.raw + b'extra')
                with self.assertRaisesRegex(ValueError, 'size mismatch'):
                    module.release_artifact.verify_archive(self.root, self.artifact, cached_archive=cached)
                self.assertEqual(run.call_count, 1, 'Invalid staged bytes must fail rather than be replaced')


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

    def test_transport_outliving_app_token_uses_job_reads_then_fresh_live_authority(self):
        files = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.manifest['files'] = {name: {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                                  for name, raw in files.items()}
        blobs = files.copy()
        # Bind the producer's actual uploaded ZIP before producing the OCI manifest.
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            for name, raw in files.items():
                zipped.writestr(name, raw)
        raw_zip = archive.getvalue()
        self.artifact.update(size_in_bytes=len(raw_zip), digest='sha256:' + hashlib.sha256(raw_zip).hexdigest())
        self.manifest['producer']['artifacts'] = [{k: self.artifact[k] for k in ('id', 'name', 'digest')}]
        blobs['decision-packet.json'] = json.dumps({'schema': 1, **self.manifest}).encode()
        layers = [{'annotations': {'org.opencontainers.image.title': name}, 'size': len(raw),
                   'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()} for name, raw in blobs.items()]
        raw_manifest = json.dumps({'schemaVersion': 2, 'artifactType': module.decision_packets.TYPE, 'layers': layers}).encode()
        reference = module.decision_packets.REGISTRY + '@sha256:' + hashlib.sha256(raw_manifest).hexdigest()
        by_digest = {hashlib.sha256(raw).hexdigest(): raw for raw in blobs.values()}
        identity = module.canonical_hash(self.proposal)
        self.archive_check.stop()
        try:
            for revoked in (False, True):
                with self.subTest(revoked=revoked):
                    output = self.root / ('execution-revoked' if revoked else 'execution-good')
                    elapsed, scans, downloads, blob_reads = [0], [], [], []
                    def authority(_):
                        token = os.environ['GH_TOKEN']
                        if token == 'old-app' and elapsed[0] >= 3600:
                            raise ValueError('HTTP 401: expired App token')
                        if token == 'fresh-app' and revoked:
                            raise ValueError('Maintainer dismissed approval')
                        self.assertIn(token, ('old-app', 'fresh-app'))
                        return self.proposal, {'tokenGeneration': token}, reference
                    def registry(command, **kwargs):
                        if command[1:3] == ['manifest', 'fetch']:
                            return raw_manifest
                        blob_reads.append(command)
                        Path(command[-1]).write_bytes(by_digest[command[3].split(':')[-1]])
                        return b''
                    def github(_):
                        self.assertIn(os.environ['GH_TOKEN'], ('job-reader', 'fresh-app'))
                        return self.run
                    def run(command, **kwargs):
                        if command[:2] == ['gh', 'api']:
                            self.assertEqual(os.environ['GH_TOKEN'], 'job-reader')
                            downloads.append(command)
                            kwargs['stdout'].write(raw_zip)
                            elapsed[0] = 3700
                        else:
                            self.assertEqual(command[0], 'bash')
                            self.assertEqual(os.environ['GH_TOKEN'], 'fresh-app')
                            self.assertNotIn('ARTIFACT_READ_TOKEN', os.environ)
                            scans.append(command)
                    with patch.object(module.controller, 'trusted_context'), patch.object(module, 'approved', side_effect=authority), \
                            patch.object(module.controller, 'api', side_effect=github), \
                            patch.object(module.decision_packets, 'command', side_effect=registry), \
                            patch.object(module.subprocess, 'run', side_effect=run), \
                            patch.object(module, 'verify_scans', return_value={'finite': {}, 'finite-dev': {}}), \
                            patch.object(module, 'stage_signing') as signing:
                        with patch.dict(os.environ, GH_TOKEN='old-app', ARTIFACT_READ_TOKEN='job-reader'), \
                                patch.object(sys, 'argv', ['execute', 'stage', '--proposal-hash', identity, '--directory', str(output)]):
                            module.main()
                            self.assertEqual(os.environ['GH_TOKEN'], 'old-app')
                        transferred = len(blob_reads)
                        with patch.dict(os.environ, GH_TOKEN='fresh-app'), \
                                patch.object(sys, 'argv', ['execute', 'prepare', '--staged', '--proposal-hash', identity,
                                                          '--directory', str(output)]):
                            if revoked:
                                with self.assertRaisesRegex(ValueError, 'dismissed'):
                                    module.main()
                                signing.assert_not_called()
                            else:
                                module.main()
                                signing.assert_called_once()
                                self.assertFalse((output / 'transport/original.zip').exists())
                        self.assertEqual(len(downloads), 1)
                        self.assertEqual(len(blob_reads), transferred)
                        self.assertEqual(len(scans), 0 if revoked else 2)
        finally:
            self.archive_check.start()

    def test_artifact_reader_token_is_restored_on_staging_failure(self):
        with patch.dict(os.environ, GH_TOKEN='app', ARTIFACT_READ_TOKEN='job'):
            with self.assertRaisesRegex(RuntimeError, 'transport failed'):
                with module.artifact_reader_credentials():
                    self.assertEqual(os.environ['GH_TOKEN'], 'job')
                    raise RuntimeError('transport failed')
            self.assertEqual(os.environ['GH_TOKEN'], 'app')
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
