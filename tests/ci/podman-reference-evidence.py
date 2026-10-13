#!/usr/bin/env python3
"""Tiny reference fixtures; all archive downloads and package tools are mocked."""
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
SPEC = importlib.util.spec_from_file_location('podman_reference', ROOT / 'scripts/ci/podman-reference-evidence.py')
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)
SIGNATURE = ('Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: ' + reference.FINGERPRINT
             + ': OK\nHeader SHA256 digest: OK\nPayload SHA256 digest: OK\n')


class PodmanReference(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.mapping_path = self.directory / 'mapping.json'
        self.key_path = self.directory / 'fedora-44.pub'
        self.key_path.write_bytes((ROOT / 'files/security/fedora-44.pub').read_bytes())
        self.mapping = json.loads((ROOT / 'docs/podman-reference-mapping-2026-10-12.json').read_text())
        self.contents = {path: b'\x7fELF' + path.encode() for path in reference.REFERENCE_PATHS}
        self.archive = b'tiny Podman reference RPM fixture'
        patch = mock.patch.object(reference, 'RPM_SPEC', {**reference.RPM_SPEC, 'signedBytes': len(self.archive)})
        patch.start()
        self.addCleanup(patch.stop)
        self.mapping['rpmBytes'] = len(self.archive)
        for entry in self.mapping['matches']:
            raw = self.contents[entry['referencePath']]
            entry.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_mapping()
        self.calls = []

    def write_mapping(self):
        self.mapping_path.write_text(json.dumps(self.mapping))

    def downloader(self, url, destination, size):
        self.assertEqual(size, len(self.archive))
        destination.write_bytes(self.archive)
        return {'url': url, 'bytes': len(self.archive), 'sha256': hashlib.sha256(self.archive).hexdigest()}

    def runner(self, argv):
        self.calls.append(argv)
        if '--import' in argv:
            return ''
        if '--checksig' in argv:
            return SIGNATURE
        fmt = argv[argv.index('--qf') + 1]
        if fmt.startswith('%{NAME}'):
            return '\t'.join(['podman', '5', '5.8.7', '1.fc44', 'x86_64', reference.SOURCE_RPM, '8', 'Fedora Project']) + '\n'
        return ''.join('\t'.join([path, str(len(raw)), hashlib.sha256(raw).hexdigest(), str(0o100755)]) + '\n'
                       for path, raw in sorted(self.contents.items()))

    def extractor(self, archive, directory, paths):
        for path in paths:
            output = directory / path.removeprefix('/')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.contents[path])
            output.chmod(0o755)

    def collect(self, **kwargs):
        return reference.collect(self.mapping_path, self.key_path, self.directory / 'proof',
            runner=kwargs.get('runner', self.runner), downloader=kwargs.get('downloader', self.downloader),
            extractor=kwargs.get('extractor', self.extractor))

    def test_positive_proof_authenticates_three_files_and_six_claimed_selectors_only(self):
        report = self.collect()
        self.assertEqual(report['status'], 'signed-reference-bytes-proven')
        self.assertEqual(len(report['matches']), 6)
        self.assertEqual(report['packages'][0]['selectedFileCount'], 3)
        self.assertEqual(report['packages'][0]['rpm']['epoch'], 5)
        self.assertTrue(report['packages'][0]['signatureVerified'])
        self.assertTrue(all(v['signedReferenceByteMatch'] for v in report['matches']))
        self.assertTrue(report['candidateBindingUnproven'])
        self.assertFalse(report['releaseEligible'])
        self.assertEqual(report['dispositionsGranted'], [])
        self.assertEqual(report['vulnerabilityClearance'], 'not-assessed')
        self.assertTrue(all(not v['actualCandidateBytesIndependentlyObserved'] for v in report['matches']))
        self.assertEqual(report['mappingSha256'], hashlib.sha256(self.mapping_path.read_bytes()).hexdigest())
        self.assertFalse(any('--install' in call or '-i' in call for call in self.calls))
        self.assertNotIn('freerdp', report['sourceUrl'])

    def test_exact_mapping_source_package_signature_selectors_and_aliases_are_required(self):
        changes = [('kojiBuild', 1), ('kojiRpm', 1), ('epoch', True), ('version', '5.8.8'),
                   ('sourceCommit', 'e' * 40), ('upstreamCommit', 'e' * 40), ('sourceRpm', 'other.src.rpm'),
                   ('rpmUrl', 'https://other.invalid/package.rpm'), ('rpmBytes', 1), ('architecture', 'i686'),
                   ('selectorImage', 'finite:latest'), ('advisories', []), ('component', 'pkg:generic/other@1')]
        for key, value in changes:
            with self.subTest(key=key):
                mapping = copy.deepcopy(self.mapping)
                mapping[key] = value
                with self.assertRaises(ValueError):
                    reference.validate_mapping(mapping)
        for key, value in [('path', '/../outside'), ('referencePath', '/usr/bin/../outside'),
                           ('sha256', 'invalid'), ('size', True), ('size', reference.MAX_FILE + 1), ('mode', 0o120777)]:
            mapping = copy.deepcopy(self.mapping)
            mapping['matches'][0][key] = value
            with self.assertRaises(ValueError):
                reference.validate_mapping(mapping)

    def test_duplicate_or_missing_selector_and_disagreeing_retained_bytes_fail(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['matches'].pop()
        with self.assertRaises(ValueError):
            reference.validate_mapping(mapping)
        mapping = copy.deepcopy(self.mapping)
        mapping['matches'][1] = copy.deepcopy(mapping['matches'][0])
        with self.assertRaises(ValueError):
            reference.validate_mapping(mapping)
        mapping = copy.deepcopy(self.mapping)
        mapping['matches'][0]['sha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'disagree'):
            reference.validate_mapping(mapping)

    def test_wrong_public_key_blocks_before_tools_or_output_creation(self):
        self.key_path.write_bytes(b'wrong publisher key')
        runner = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'exact reviewed Fedora44'):
            self.collect(runner=runner)
        runner.assert_not_called()
        self.assertFalse((self.directory / 'proof').exists())

    def test_signature_key_algorithm_and_payload_authentication_fail_closed(self):
        for text in (SIGNATURE.replace(reference.FINGERPRINT, 'e' * 40),
                     SIGNATURE.replace('RSA/SHA256', 'RSA/SHA512'),
                     SIGNATURE.replace('Payload SHA256 digest: OK', 'Payload SHA256 digest: BAD'),
                     'Header SHA256 digest: OK\nPayload SHA256 digest: OK\n',
                     SIGNATURE.replace(': OK', ': NOKEY')):
            extractor = mock.Mock()
            with self.subTest(text=text):
                def runner(argv):
                    return text if '--checksig' in argv else self.runner(argv)
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaises(ValueError):
                        reference.collect(self.mapping_path, self.key_path, Path(temporary) / 'proof',
                            runner=runner, downloader=self.downloader, extractor=extractor)
                    extractor.assert_not_called()

    def test_wrong_signed_package_metadata_never_extracts(self):
        for index, value in ((0, 'other'), (1, '0'), (2, '5.8.6'), (3, '2.fc44'),
                             (4, 'i686'), (5, 'other.src.rpm'), (6, '2'), (7, 'other publisher')):
            with self.subTest(index=index):
                def runner(argv):
                    output = self.runner(argv)
                    if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('%{NAME}'):
                        fields = output.strip().split('\t'); fields[index] = value
                        return '\t'.join(fields)
                    return output
                with self.assertRaisesRegex(ValueError, 'identity/epoch'):
                    reference.rpm_metadata(Path('/reference.rpm'), Path('/rpmdb'), runner)

    def test_file_manifest_wrong_hash_size_mode_duplicate_or_missing_rejects(self):
        original = self.runner(['rpm', '--qf', '[', 'archive'])
        rows = original.splitlines()
        for raw in (original.replace(hashlib.sha256(next(iter(self.contents.values()))).hexdigest(), 'e' * 64),
                    original.replace('\t' + str(len(self.contents[sorted(self.contents)[0]])) + '\t', '\t1\t', 1),
                    original.replace('\t' + str(0o100755), '\t' + str(0o120777)),
                    '\n'.join(rows[:-1]) + '\n', original + rows[0] + '\n'):
            with self.subTest(raw=raw):
                def runner(argv):
                    return raw if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('[') else self.runner(argv)
                extractor = mock.Mock()
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaises(ValueError):
                        reference.collect(self.mapping_path, self.key_path, Path(temporary) / 'proof',
                            runner=runner, downloader=self.downloader, extractor=extractor)
                    extractor.assert_not_called()

    def test_extracted_changed_hash_size_mode_or_symlink_never_proves_bytes(self):
        for change in ('hash', 'size', 'mode', 'symlink'):
            with self.subTest(change=change):
                def extractor(archive, directory, paths):
                    self.extractor(archive, directory, paths)
                    target = directory / paths[0].removeprefix('/')
                    if change == 'hash': target.write_bytes(b'!' * target.stat().st_size)
                    if change == 'size': target.write_bytes(b'!')
                    if change == 'mode': target.chmod(0o644)
                    if change == 'symlink': target.unlink(); target.symlink_to(self.key_path)
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, 'payload bytes/mode/size'):
                        reference.collect(self.mapping_path, self.key_path, Path(temporary) / 'proof',
                            runner=self.runner, downloader=self.downloader, extractor=extractor)

    def test_archive_changed_during_extract_is_rejected(self):
        def extractor(archive, directory, paths):
            self.extractor(archive, directory, paths)
            archive.write_bytes(b'!' * archive.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            self.collect(extractor=extractor)

    def test_download_binding_wrong_url_hash_or_size_rejected_before_signature(self):
        for key, value in [('url', 'https://other.invalid/rpm'), ('sha256', 'e' * 64), ('bytes', 1)]:
            with self.subTest(key=key):
                def downloader(url, destination, size):
                    result = self.downloader(url, destination, size); result[key] = value
                    return result
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, 'binding changed'):
                        reference.collect(self.mapping_path, self.key_path, Path(temporary) / 'proof',
                            runner=self.runner, downloader=downloader, extractor=self.extractor)

    def test_input_symlink_duplicate_keys_and_existing_output_fail_closed(self):
        self.mapping_path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.collect()
        self.mapping_path.unlink(); self.mapping_path.symlink_to(self.key_path)
        with self.assertRaises(OSError):
            self.collect()
        self.mapping_path.unlink(); self.write_mapping()
        self.collect()
        with self.assertRaises(FileExistsError):
            self.collect()

    def test_download_enforces_exact_host_length_count_redirect_and_no_overwrite(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'Content-Length': str(len(self.archive))}
            def geturl(self): return reference.RPM_URL
        opener = mock.Mock()
        destination = self.directory / 'download.rpm'
        with mock.patch.object(reference.urllib.request, 'build_opener', return_value=opener):
            opener.open.return_value = Response(self.archive)
            self.assertEqual(reference.download(reference.RPM_URL, destination, len(self.archive))['bytes'], len(self.archive))
            opener.open.return_value = Response(self.archive)
            with self.assertRaises(FileExistsError): reference.download(reference.RPM_URL, destination, len(self.archive))
            destination.unlink()
            for response in (Response(self.archive[:-1]), Response(self.archive + b'!')):
                opener.open.return_value = response
                with self.assertRaises(ValueError): reference.download(reference.RPM_URL, destination, len(self.archive))
                destination.unlink()
            response = Response(self.archive); response.headers = {'Content-Length': '1'}
            opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'content length'):
                reference.download(reference.RPM_URL, destination, len(self.archive))
            response = Response(self.archive); response.geturl = lambda: 'http://other.invalid/rpm'
            opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'exact approved'):
                reference.download(reference.RPM_URL, destination, len(self.archive))

    def test_extraction_allows_only_exact_three_paths_and_closes_pipe(self):
        with mock.patch.object(reference.subprocess, 'Popen') as process:
            with self.assertRaises(ValueError): reference.extract(Path('/reference.rpm'), self.directory, ['/usr/../outside'])
            process.assert_not_called()
        producer, consumer = mock.Mock(), mock.Mock()
        producer.stdout = mock.Mock(); producer.returncode = consumer.returncode = 0
        producer.poll.return_value = consumer.poll.return_value = 0
        def done(timeout):
            self.assertIsNone(producer.stdout)
            return None, b''
        producer.communicate.side_effect = done; consumer.communicate.return_value = b'', b''
        with mock.patch.object(reference.subprocess, 'Popen', side_effect=[producer, consumer]) as process:
            reference.extract(Path('/reference.rpm'), self.directory, sorted(reference.REFERENCE_PATHS))
        args = process.call_args_list[1].args[0]
        self.assertEqual(args[args.index('--') + 1:], ['.' + p for p in sorted(reference.REFERENCE_PATHS)])
        self.assertIn('--no-absolute-filenames', args)
        self.assertIn('--no-preserve-owner', args)

    def test_cli_is_hosted_only_before_read_or_download(self):
        argv = ['--mapping', str(self.mapping_path), '--key', str(self.key_path), '--directory', str(self.directory / 'proof')]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(reference, 'collect') as collect:
            with self.assertRaises(SystemExit) as stopped:
                reference.main(argv)
            self.assertEqual(stopped.exception.code, 2)
            collect.assert_not_called()


class LockedReferenceMetadata(unittest.TestCase):
    def test_reviewed_real_mapping_preserves_verified_signed_size_and_three_payloads(self):
        mapping = json.loads((ROOT / 'docs/podman-reference-mapping-2026-10-12.json').read_text())
        targets, references = reference.validate_mapping(mapping)
        self.assertEqual(mapping['rpmBytes'], 16107978)
        self.assertEqual(reference.RPM_SPEC['unsignedKojiBytes'], 16065018)
        self.assertEqual(len(targets), 6)
        self.assertEqual(len(references), 3)
        self.assertEqual(references['/usr/bin/podman']['size'], 45362352)
        self.assertEqual(references['/usr/bin/podman']['digest']['value'],
                         'a844579b16612e6d0fd513bac59e27d82bb1220a34820f1e1e1e4c683b2f1454')


if __name__ == '__main__':
    unittest.main()
