#!/usr/bin/env python3
"""Reference proof fixtures use tiny files and mock all remote/tool operations."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('freerdp_reference', ROOT / 'scripts/ci/freerdp-reference-evidence.py')
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)
SIGNATURE = ('    Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: '
             + reference.FINGERPRINT + ': OK\n    Header SHA256 digest: OK\n    Payload SHA256 digest: OK\n')


class ReferenceEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.mapping_path = self.directory / 'mapping.json'
        self.key = self.directory / 'fedora-44.pub'
        self.key.write_bytes((ROOT / 'files/security/fedora-44.pub').read_bytes())
        self.mapping = {'schema': 1, 'kojiBuild': reference.KOJI_BUILD, 'epoch': 2,
            'sourceCommit': reference.SOURCE_COMMIT, 'selectorImage': 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64,
            'sourceSummarySha256': 'b' * 64, 'sbomSha256': 'c' * 64, 'matches': []}
        self.contents = {}
        for index, (path, rpm) in enumerate(reference.REFERENCE_PATHS.items()):
            data = b'\x7fELF' + path.encode()
            self.contents[path] = data
            digest = hashlib.sha256(data).hexdigest()
            self.mapping['matches'].append({'path': '/sysroot/ostree/repo/objects/' + format(index, '02x') + '/' + 'd' * 62 + '.file',
                'size': len(data), 'sha256': digest, 'officialMetadataMatches': [{'rpm': rpm,
                    'referencePath': path, 'expectedSha256': digest, 'expectedSize': len(data), 'expectedMode': 0o100755}]})
        specs = {name: {**spec, 'size': len(self.archive_bytes(name))} for name, spec in reference.RPMS.items()}
        patch = mock.patch.object(reference, 'RPMS', specs)
        patch.start()
        self.addCleanup(patch.stop)
        self.write_mapping()
        self.calls = []

    def write_mapping(self):
        self.mapping_path.write_text(json.dumps(self.mapping))

    @staticmethod
    def archive_bytes(name):
        return b'tiny mock RPM ' + name.encode()

    def downloader(self, url, destination, expected_size):
        name = next(n for n in reference.RPMS if destination.name.startswith(n + '-3.31.1-'))
        data = self.archive_bytes(name)
        destination.write_bytes(data)
        return {'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def runner(self, argv):
        self.calls.append(argv)
        if '--import' in argv:
            return ''
        if '--checksig' in argv:
            return SIGNATURE
        name = next(n for n in reference.RPMS if Path(argv[-1]).name.startswith(n + '-3.31.1-'))
        if argv[argv.index('--qf') + 1].startswith('%{NAME}'):
            return '\t'.join([name, '2', '3.31.1', '1.fc44', 'x86_64', reference.SOURCE_RPM, '8']) + '\n'
        rows = []
        for path, rpm in reference.REFERENCE_PATHS.items():
            if rpm == name:
                data = self.contents[path]
                rows.append('\t'.join([path, str(len(data)), hashlib.sha256(data).hexdigest(), str(0o100755)]))
        return '\n'.join(rows) + '\n'

    def extractor(self, archive, directory, paths):
        for path in paths:
            destination = directory / path.removeprefix('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.contents[path])
            destination.chmod(0o755)

    def collect(self, **kwargs):
        return reference.collect(self.mapping_path, self.key, self.directory / 'proof',
            runner=kwargs.get('runner', self.runner), downloader=kwargs.get('downloader', self.downloader),
            extractor=kwargs.get('extractor', self.extractor))

    def test_success_authenticates_reference_bytes_and_retains_no_candidate_clearance(self):
        report = self.collect()
        self.assertEqual(report['status'], 'signed-reference-bytes-proven')
        self.assertEqual(len(report['matches']), 12)
        self.assertEqual([p['selectedFileCount'] for p in report['packages']], [10, 2])
        self.assertTrue(all(p['signatureVerified'] and p['rpm']['epoch'] == 2 for p in report['packages']))
        self.assertTrue(all(m['signedReferenceByteMatch'] for m in report['matches']))
        self.assertTrue(all(not m['actualCandidateBytesIndependentlyObserved'] for m in report['matches']))
        self.assertFalse(report['releaseEligible'])
        self.assertEqual(report['dispositionsGranted'], [])
        self.assertEqual(report['mappingSha256'], hashlib.sha256(self.mapping_path.read_bytes()).hexdigest())
        self.assertFalse(any('--install' in command or '-i' in command for command in self.calls))

    def test_malformed_mapping_identity_counts_alias_paths_and_modes_reject_before_tools(self):
        changes = [lambda d: d.update(kojiBuild=1), lambda d: d.update(epoch=True),
            lambda d: d.update(sourceCommit='e' * 40), lambda d: d.update(selectorImage='finite:latest'),
            lambda d: d['matches'].pop(), lambda d: d['matches'][0].update(path='/../outside'),
            lambda d: d['matches'][0]['officialMetadataMatches'][0].update(referencePath='/usr/lib64/../outside'),
            lambda d: d['matches'][0]['officialMetadataMatches'][0].update(rpm='other'),
            lambda d: d['matches'][0]['officialMetadataMatches'][0].update(expectedMode=0o120777),
            lambda d: d['matches'][0]['officialMetadataMatches'][0].update(expectedSha256='0' * 64)]
        for change in changes:
            with self.subTest(change=change):
                document = copy.deepcopy(self.mapping)
                change(document)
                with self.assertRaises(ValueError):
                    reference.validate_mapping(document)

    def test_duplicate_native_and_reference_locations_are_rejected(self):
        document = copy.deepcopy(self.mapping)
        document['matches'][1]['path'] = document['matches'][0]['path']
        with self.assertRaises(ValueError):
            reference.validate_mapping(document)
        document = copy.deepcopy(self.mapping)
        document['matches'][1]['officialMetadataMatches'] = document['matches'][0]['officialMetadataMatches']
        with self.assertRaises(ValueError):
            reference.validate_mapping(document)

    def test_wrong_key_hash_never_imports_or_creates_output(self):
        self.key.write_bytes(b'unapproved key')
        runner = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'public key differs'):
            self.collect(runner=runner)
        runner.assert_not_called()
        self.assertFalse((self.directory / 'proof').exists())

    def test_digest_only_wrong_key_algorithm_and_failed_signature_reject(self):
        for output in ['Header SHA256 digest: OK\nPayload SHA256 digest: OK\n',
                       SIGNATURE.replace(reference.FINGERPRINT, '0' * 40),
                       SIGNATURE.replace('RSA/SHA256', 'RSA/SHA512'),
                       SIGNATURE.replace('Payload SHA256 digest: OK', 'Payload SHA256 digest: BAD'),
                       SIGNATURE.replace(': OK', ': NOKEY')]:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    reference.verify_signature(output)

    def test_older_key_id_signature_format_and_full_fingerprint_both_verify(self):
        reference.verify_signature(SIGNATURE)
        reference.verify_signature('Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: OK\nPayload SHA256 digest: OK\n')

    def test_wrong_epoch_source_arch_and_digest_algorithm_block_extraction(self):
        for index, value in [(1, '0'), (2, '3.32.1'), (4, 'i686'), (5, 'other.src.rpm'), (6, '2')]:
            with self.subTest(index=index):
                def wrong(argv):
                    output = self.runner(argv)
                    if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('%{NAME}'):
                        fields = output.strip().split('\t')
                        fields[index] = value
                        return '\t'.join(fields)
                    return output
                with self.assertRaisesRegex(ValueError, 'identity/epoch'):
                    reference.rpm_metadata('freerdp-libs', Path('/reference.rpm'), Path('/rpmdb'),
                        lambda argv: wrong(argv[:-1] + ['freerdp-libs-3.31.1-1.fc44.x86_64.rpm']))

    def test_authenticated_file_manifest_mismatch_blocks_before_extraction(self):
        def mismatch(argv):
            output = self.runner(argv)
            if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('['):
                digest = hashlib.sha256(next(iter(self.contents.values()))).hexdigest()
                return output.replace(digest, '0' * 64)
            return output
        extractor = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'file manifest does not match'):
            self.collect(runner=mismatch, extractor=extractor)
        extractor.assert_not_called()

    def test_extracted_hash_difference_never_produces_reference_proof(self):
        def different(archive, directory, paths):
            self.extractor(archive, directory, paths)
            path = directory / paths[0].removeprefix('/')
            path.write_bytes(b'!' * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'file bytes/mode/size'):
            self.collect(extractor=different)

    def test_extracted_symlink_is_rejected_without_reading_outside(self):
        def symlink(archive, directory, paths):
            self.extractor(archive, directory, paths)
            path = directory / paths[0].removeprefix('/')
            path.unlink()
            path.symlink_to(self.key)
        with self.assertRaisesRegex(ValueError, 'file bytes/mode/size'):
            self.collect(extractor=symlink)

    def test_archive_modification_after_authentication_is_rejected(self):
        def changing(archive, directory, paths):
            self.extractor(archive, directory, paths)
            archive.write_bytes(b'!' * archive.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            self.collect(extractor=changing)

    def test_input_symlink_duplicate_json_and_read_bound_reject(self):
        self.mapping_path.unlink()
        self.mapping_path.symlink_to(self.key)
        with self.assertRaises(OSError):
            reference.read_regular(self.mapping_path, reference.MAX_METADATA)
        self.mapping_path.unlink()
        self.mapping_path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.collect()
        with self.assertRaisesRegex(ValueError, 'bounded'):
            reference.read_regular(self.key, 1)

    def test_existing_directory_cannot_overwrite_retained_proof(self):
        self.collect()
        retained = self.directory / 'proof/freerdp-libs-3.31.1-1.fc44.x86_64.rpm'
        data = retained.read_bytes()
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertEqual(retained.read_bytes(), data)

    def test_download_bound_content_length_redirect_and_existing_file(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'Content-Length': '4'}
            def geturl(self):
                return reference.BASE_URL + 'fixture.rpm'
        destination = self.directory / 'download.rpm'
        opener = mock.Mock()
        with mock.patch.object(reference.urllib.request, 'build_opener', return_value=opener):
            opener.open.return_value = Response(b'data')
            result = reference.download(reference.BASE_URL + 'fixture.rpm', destination, 4)
            self.assertEqual(result['sha256'], hashlib.sha256(b'data').hexdigest())
            opener.open.return_value = Response(b'data')
            with self.assertRaises(FileExistsError):
                reference.download(reference.BASE_URL + 'fixture.rpm', destination, 4)
            destination.unlink()
            opener.open.return_value = Response(b'data')
            with mock.patch.object(reference, 'MAX_RPM', 3):
                with self.assertRaisesRegex(ValueError, 'download bound'):
                    reference.download(reference.BASE_URL + 'fixture.rpm', destination, 4)
            destination.unlink()
            response = Response(b'data')
            response.headers = {'Content-Length': '5'}
            opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'content length'):
                reference.download(reference.BASE_URL + 'fixture.rpm', destination, 4)
            response = Response(b'data')
            response.geturl = lambda: 'http://other.invalid/payload.rpm'
            opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'exact approved HTTPS'):
                reference.download(reference.BASE_URL + 'fixture.rpm', destination, 4)

    def test_extraction_rejects_unapproved_path_before_spawning(self):
        with mock.patch.object(reference.subprocess, 'Popen') as process:
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                reference.extract(Path('/reference.rpm'), self.directory, ['/usr/lib64/../outside'])
            process.assert_not_called()

    def test_pipeline_closes_parent_pipe_without_reading_closed_stdout(self):
        producer, consumer = mock.Mock(), mock.Mock()
        producer.stdout = mock.Mock()
        producer.returncode = consumer.returncode = 0
        producer.poll.return_value = consumer.poll.return_value = 0
        def producer_done(timeout):
            self.assertIsNone(producer.stdout)
            return None, b''
        producer.communicate.side_effect = producer_done
        consumer.communicate.return_value = b'', b''
        selected = list(reference.REFERENCE_PATHS)[:2]
        with mock.patch.object(reference.subprocess, 'Popen', side_effect=[producer, consumer]) as process:
            reference.extract(Path('/reference.rpm'), self.directory, selected)
        args = process.call_args_list[1].args[0]
        self.assertEqual(args[args.index('--') + 1:], ['.' + p for p in sorted(selected)])
        self.assertIn('--no-absolute-filenames', args)
        self.assertIn('--no-preserve-owner', args)

    def test_cli_guard_prevents_input_read_and_external_actions(self):
        argv = ['--mapping', str(self.mapping_path), '--key', str(self.key), '--directory', str(self.directory / 'proof')]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(reference, 'collect') as collect:
            with self.assertRaises(SystemExit) as stopped:
                reference.main(argv)
            self.assertEqual(stopped.exception.code, 2)
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
