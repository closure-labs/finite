#!/usr/bin/env python3
"""Tiny HTTPD reference fixtures; all network and RPM tools are mocked."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('httpd_reference', ROOT / 'scripts/ci/httpd-reference-evidence.py')
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)
SIGNATURE = ('Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: '
             + reference.FINGERPRINT + ': OK\nHeader SHA256 digest: OK\nPayload SHA256 digest: OK\n')


class ProductionMapping(unittest.TestCase):
    def test_reviewed_mapping_covers_exact_five_packages_and_392_regular_files(self):
        document = json.loads((ROOT / 'docs/httpd-reference-mapping-2026-10-12.json').read_text())
        selected = reference.validate_mapping(document)
        self.assertEqual(sum(len(files) for files in selected.values()), 392)
        self.assertEqual(sum(f['size'] for files in selected.values() for f in files.values()), 4503701)
        self.assertEqual(sum(s['size'] for s in reference.RPMS.values()), 1706755)
        self.assertEqual(selected['httpd-core']['/usr/bin/httpd']['digest']['value'],
                         '0d7703d22550e640484a21b5f8da138be8a907651b81c0d2db98c287dcddd1ce')


class HttpdReferenceEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.mapping_path = self.directory / 'mapping.json'
        self.key = self.directory / 'fedora-44.pub'
        self.key.write_bytes((ROOT / 'files/security/fedora-44.pub').read_bytes())
        self.mapping = json.loads((ROOT / 'docs/httpd-reference-mapping-2026-10-12.json').read_text())
        self.contents = {}
        specs = copy.deepcopy(reference.RPMS)
        for package in self.mapping['packages']:
            name = package['name']
            path = '/usr/lib64/' + name + '-fixture'
            data = b'bounded reference bytes: ' + name.encode()
            self.contents[path] = data
            package['files'] = [{'path': path, 'size': len(data), 'mode': 0o100644,
                                 'sha256': hashlib.sha256(data).hexdigest()}]
            specs[name]['size'] = len(self.archive_bytes(name))
            specs[name]['files'] = 1
            package['signedSize'] = specs[name]['size']
        patch = mock.patch.object(reference, 'RPMS', specs)
        patch.start()
        self.addCleanup(patch.stop)
        self.write_mapping()
        self.calls = []

    @staticmethod
    def archive_bytes(name):
        return b'mock authenticated RPM ' + name.encode()

    def write_mapping(self):
        self.mapping_path.write_text(json.dumps(self.mapping))

    def downloader(self, url, destination, expected_size):
        name = next(n for n in reference.RPMS if destination.name == reference.filename(n))
        data = self.archive_bytes(name)
        self.assertEqual(expected_size, len(data))
        destination.write_bytes(data)
        return {'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def runner(self, argv):
        self.calls.append(argv)
        if '--import' in argv:
            return ''
        if '--checksig' in argv:
            return SIGNATURE
        name = next(n for n in reference.RPMS if Path(argv[-1]).name == reference.filename(n))
        fmt = argv[argv.index('--qf') + 1]
        if fmt.startswith('%{NAME}'):
            return '\t'.join([name, '0', '2.4.68', '1.fc44', reference.RPMS[name]['arch'], reference.SOURCE_RPM, '8']) + '\n'
        package = next(p for p in self.mapping['packages'] if p['name'] == name)
        rows = ['\t'.join([e['path'], str(e['size']), e['sha256'], str(e['mode']), '0']) for e in package['files']]
        rows += ['/etc/httpd/' + name + '.conf\t4\t' + 'a' * 64 + '\t33188\t17',
                 '/usr/lib64/' + name + '-symlink\t4\t\t41471\t0']
        return '\n'.join(rows) + '\n'

    def extractor(self, archive, directory, paths):
        for path in paths:
            destination = directory / path.removeprefix('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.contents[path])
            destination.chmod(0o644)

    def collect(self, **kwargs):
        return reference.collect(self.mapping_path, self.key, self.directory / 'proof',
            runner=kwargs.get('runner', self.runner), downloader=kwargs.get('downloader', self.downloader),
            extractor=kwargs.get('extractor', self.extractor))

    def test_success_authenticates_all_reference_packages_without_candidate_clearance(self):
        report = self.collect()
        self.assertEqual(report['status'], 'signed-reference-bytes-proven')
        self.assertEqual(len(report['packages']), 5)
        self.assertEqual(len(report['matches']), 5)
        self.assertTrue(all(p['signatureVerified'] and p['rpm']['epoch'] == 0 for p in report['packages']))
        self.assertTrue(all(m['signedReferenceByteMatch'] for m in report['matches']))
        self.assertTrue(all(not m['actualCandidateBytesIndependentlyObserved'] for m in report['matches']))
        self.assertEqual(report['currentCandidateJoin'], 'unproven')
        self.assertFalse(report['releaseEligible'])
        self.assertEqual(report['dispositionsGranted'], [])
        self.assertEqual(report['mappingSha256'], hashlib.sha256(self.mapping_path.read_bytes()).hexdigest())
        self.assertEqual(report['packages'][2]['rpm']['architecture'], 'noarch')
        self.assertTrue(all(len(p['excludedManifestEntries']) == 2 for p in report['packages']))
        self.assertFalse(any('--install' in call or '-i' in call for call in self.calls))

    def test_mapping_wrong_identity_urls_sizes_components_aliases_and_locations_reject(self):
        changes = [lambda d: d.update(kojiBuild=1), lambda d: d.update(epoch=True),
            lambda d: d.update(sourceCommit='e' * 40), lambda d: d.update(selectorImage='finite:latest'),
            lambda d: d.update(advisories=['CVE-2026-29167']), lambda d: d['packages'].pop(),
            lambda d: d['packages'][0].update(component='pkg:rpm/httpd@2.4.67'),
            lambda d: d['packages'][0].update(signedUrl='https://kojipkgs.fedoraproject.org/unsigned.rpm'),
            lambda d: d['packages'][0].update(signedSize=1),
            lambda d: d['packages'][0].update(architecture='i686'),
            lambda d: d['packages'][0].update(kojiRpmId=True),
            lambda d: d['packages'][0].update(locations=['/unknown']),
            lambda d: d['packages'][0].update(observedAliases=[])]
        for change in changes:
            with self.subTest(change=change):
                document = copy.deepcopy(self.mapping)
                change(document)
                with self.assertRaises(ValueError):
                    reference.validate_mapping(document)

    def test_mapping_unsafe_duplicate_missing_and_oversized_regular_files_reject(self):
        changes = [lambda d: d['packages'][0]['files'][0].update(path='/usr/lib64/../outside'),
            lambda d: d['packages'][0]['files'][0].update(path='/usr/lib64/*'),
            lambda d: d['packages'][0]['files'][0].update(path='/etc/config'),
            lambda d: d['packages'][0]['files'][0].update(mode=0o120777),
            lambda d: d['packages'][0]['files'][0].update(size=True),
            lambda d: d['packages'][0]['files'][0].update(size=reference.MAX_SELECTED_BYTES + 1),
            lambda d: d['packages'][0]['files'][0].update(sha256='not-a-digest'),
            lambda d: d['packages'][0]['files'].clear(),
            lambda d: d['packages'][1].update(name=d['packages'][0]['name']),
            lambda d: d['packages'][1]['files'][0].update(path=d['packages'][0]['files'][0]['path'])]
        for change in changes:
            with self.subTest(change=change):
                document = copy.deepcopy(self.mapping)
                change(document)
                with self.assertRaises(ValueError):
                    reference.validate_mapping(document)

    def test_wrong_key_never_creates_output_or_imports(self):
        self.key.write_bytes(b'unapproved key')
        runner = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'public key differs'):
            self.collect(runner=runner)
        runner.assert_not_called()
        self.assertFalse((self.directory / 'proof').exists())

    def test_signature_digest_only_wrong_signer_or_bad_payload_never_extracts(self):
        outputs = ['Header SHA256 digest: OK\nPayload SHA256 digest: OK\n',
            SIGNATURE.replace(reference.FINGERPRINT, '0' * 40), SIGNATURE.replace('RSA/SHA256', 'RSA/SHA512'),
            SIGNATURE.replace('Payload SHA256 digest: OK', 'Payload SHA256 digest: BAD'),
            SIGNATURE + 'Header V4 RSA/SHA256 signature, key ID deadbeef: OK\n']
        for index, output in enumerate(outputs):
            with self.subTest(output=output):
                runner = lambda argv: output if '--checksig' in argv else self.runner(argv)
                extractor = mock.Mock()
                with self.assertRaises(ValueError):
                    reference.collect(self.mapping_path, self.key, self.directory / str(index),
                        runner=runner, downloader=self.downloader, extractor=extractor)
                extractor.assert_not_called()

    def test_exact_epoch_source_version_arch_algorithm_required_before_extraction(self):
        for index, value in [(1, '2'), (2, '2.4.67'), (3, '2.fc44'), (4, 'i686'), (5, 'other.src.rpm'), (6, '2')]:
            with self.subTest(index=index):
                def wrong(argv):
                    output = self.runner(argv)
                    if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('%{NAME}'):
                        fields = output.strip().split('\t')
                        fields[index] = value
                        return '\t'.join(fields)
                    return output
                with self.assertRaisesRegex(ValueError, 'identity/epoch'):
                    reference.rpm_metadata('httpd', Path(reference.filename('httpd')), Path('/rpmdb'), wrong)

    def test_signed_manifest_requires_complete_selection_not_just_chosen_subset(self):
        for extra in [True, False]:
            with self.subTest(extra=extra):
                def changed(argv):
                    output = self.runner(argv)
                    if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('['):
                        return (output + '/usr/lib64/extra\t1\t' + 'b' * 64 + '\t33188\t0\n'
                                if extra else '\n'.join(output.splitlines()[1:]) + '\n')
                    return output
                with self.assertRaisesRegex(ValueError, 'complete regular-file coverage'):
                    reference.rpm_metadata('httpd', Path(reference.filename('httpd')), Path('/rpmdb'), changed)

    def test_manifest_duplicate_traversal_malformed_hash_and_flagged_target_reject(self):
        alterations = [lambda s: s + s.splitlines()[0] + '\n',
            lambda s: s.replace('/usr/lib64/httpd-fixture', '/usr/lib64/../escape'),
            lambda s: s.replace(self.mapping['packages'][0]['files'][0]['sha256'], 'bad'),
            lambda s: s.replace('\t33188\t0', '\t33188\t17', 1)]
        for alter in alterations:
            with self.subTest(alter=alter):
                def changed(argv):
                    output = self.runner(argv)
                    return alter(output) if '--qf' in argv and argv[argv.index('--qf') + 1].startswith('[') else output
                with self.assertRaises(ValueError):
                    reference.rpm_metadata('httpd', Path(reference.filename('httpd')), Path('/rpmdb'), changed)

    def test_manifest_output_and_selected_byte_bounds_reject(self):
        with mock.patch.object(reference, 'MAX_COMMAND_OUTPUT', 1):
            with self.assertRaisesRegex(ValueError, 'metadata bound'):
                reference.rpm_metadata('httpd', Path(reference.filename('httpd')), Path('/rpmdb'), self.runner)
        with mock.patch.object(reference, 'MAX_SELECTED_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'complete regular-file coverage'):
                reference.rpm_metadata('httpd', Path(reference.filename('httpd')), Path('/rpmdb'), self.runner)

    def test_matching_count_but_wrong_signed_digest_fails_before_extraction(self):
        def changed(argv):
            output = self.runner(argv)
            return output.replace(self.mapping['packages'][0]['files'][0]['sha256'], 'f' * 64)
        extractor = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'manifest does not match'):
            self.collect(runner=changed, extractor=extractor)
        extractor.assert_not_called()

    def test_extracted_hash_mode_and_symlink_mismatches_cannot_produce_proof(self):
        for index, action in enumerate(['hash', 'mode', 'symlink', 'parent-symlink']):
            with self.subTest(action=action):
                def changed(archive, directory, paths):
                    self.extractor(archive, directory, paths)
                    target = directory / paths[0].removeprefix('/')
                    if action == 'hash': target.write_bytes(b'!' * target.stat().st_size)
                    elif action == 'mode': target.chmod(0o755)
                    elif action == 'symlink':
                        target.unlink(); target.symlink_to(self.key)
                    else:
                        target.unlink(); target.parent.rmdir(); target.parent.symlink_to(self.directory)
                with self.assertRaisesRegex(ValueError, 'bytes/mode/size'):
                    reference.collect(self.mapping_path, self.key, self.directory / str(index),
                        runner=self.runner, downloader=self.downloader, extractor=changed)

    def test_download_binding_and_authenticated_archive_changes_reject(self):
        def wrong(url, destination, size):
            result = self.downloader(url, destination, size)
            result['sha256'] = '0' * 64
            return result
        extractor = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'download binding'):
            self.collect(downloader=wrong, extractor=extractor)
        extractor.assert_not_called()
        def changing(archive, directory, paths):
            self.extractor(archive, directory, paths)
            archive.write_bytes(b'!' * archive.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            reference.collect(self.mapping_path, self.key, self.directory / 'other',
                runner=self.runner, downloader=self.downloader, extractor=changing)

    def test_input_symlink_duplicate_json_and_existing_directory_reject(self):
        self.mapping_path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.collect()
        self.mapping_path.unlink(); self.mapping_path.symlink_to(self.key)
        with self.assertRaises(OSError):
            self.collect()
        self.mapping_path.unlink(); self.write_mapping()
        self.collect()
        retained = (self.directory / 'proof' / reference.filename('httpd')).read_bytes()
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertEqual((self.directory / 'proof' / reference.filename('httpd')).read_bytes(), retained)

    def test_extraction_rejects_globs_traversal_duplicates_and_too_many_before_tools(self):
        for paths in [['/usr/lib64/*'], ['/usr/lib64/../outside'], ['/etc/config'],
                      ['/usr/lib64/file', '/usr/lib64/file'], ['/usr/lib64/' + str(i) for i in range(513)]]:
            with self.subTest(paths=paths[:2]), mock.patch.object(reference.subprocess, 'Popen') as process:
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    reference.extract(Path('/reference.rpm'), self.directory, paths)
                process.assert_not_called()

    def test_exact_pipeline_arguments_and_producer_stdout_close(self):
        producer, consumer = mock.Mock(), mock.Mock()
        producer.stdout = mock.Mock()
        producer.returncode = consumer.returncode = 0
        producer.poll.return_value = consumer.poll.return_value = 0
        def done(timeout):
            self.assertIsNone(producer.stdout)
            return None, b''
        producer.communicate.side_effect = done
        consumer.communicate.return_value = b'', b''
        with mock.patch.object(reference.subprocess, 'Popen', side_effect=[producer, consumer]) as process:
            reference.extract(Path('/reference.rpm'), self.directory, ['/usr/lib64/b', '/usr/lib64/a'])
        argv = process.call_args_list[1].args[0]
        self.assertEqual(argv[argv.index('--') + 1:], ['./usr/lib64/a', './usr/lib64/b'])
        self.assertIn('--no-absolute-filenames', argv)
        self.assertIn('--no-preserve-owner', argv)

    def test_cli_host_guard_prevents_file_reads_and_external_operations(self):
        argv = ['--mapping', str(self.mapping_path), '--key', str(self.key), '--directory', str(self.directory / 'proof')]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(reference, 'collect') as collect:
            with self.assertRaises(SystemExit) as stopped:
                reference.main(argv)
            self.assertEqual(stopped.exception.code, 2)
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
