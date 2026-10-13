#!/usr/bin/env python3
"""Small filesystem regressions; never read a real SBOM or image locally."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('rpm_bytes', ROOT / 'scripts/ci/rpm-file-evidence.py')
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64


class RpmFileEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.rootfs = self.directory / 'rootfs'
        (self.rootfs / 'usr/sbin').mkdir(parents=True)
        self.binary = self.rootfs / 'usr/sbin/httpd'
        self.binary.write_bytes(b'\x7fELF' + b'fixture contents')
        self.binary.chmod(0o755)
        self.document = {'source': {'type': 'directory', 'metadata': {'path': str(self.rootfs)}},
                         'artifacts': [self.package()]}

    def declared(self, path='/usr/sbin/httpd', flags=''):
        data = self.binary.read_bytes()
        return {'path': path, 'mode': stat.S_IFREG | 0o755, 'size': len(data),
                'digest': {'algorithm': 'sha256', 'value': hashlib.sha256(data).hexdigest()},
                'flags': flags, 'userName': 'root', 'groupName': 'root'}

    def package(self):
        return {'id': 'httpd-id', 'name': 'httpd-core', 'version': '2.4.68-1.fc44',
                'purl': 'pkg:rpm/bluefin/httpd-core@2.4.68-1.fc44?arch=x86_64',
                'type': 'rpm', 'foundBy': 'rpm-db-cataloger', 'metadataType': 'rpm-db-entry',
                'metadata': {'name': 'httpd-core', 'version': '2.4.68', 'release': '1.fc44',
                    'epoch': None, 'architecture': 'x86_64', 'sourceRpm': 'httpd-2.4.68-1.fc44.src.rpm',
                    'vendor': 'Fedora Project', 'signatures': [{'algo': 'RSA', 'hash': 'SHA256',
                        'issuer': 'dbfcf71c6d9f90a6'}], 'files': [self.declared()]}}

    def collect(self, document=None):
        return collector.collect(self.rootfs, document or self.document, IMAGE, 'b' * 64)

    def file(self, report=None):
        return (report or self.collect())['targetRpmPackages'][0]['files'][0]

    def test_success_preserves_binding_and_independent_bytes_without_clearance(self):
        report = self.collect()
        package, file = report['targetRpmPackages'][0], self.file(report)
        self.assertEqual(file['status'], 'matches-rpm-manifest')
        self.assertEqual(file['actualSha256'], self.declared()['digest']['value'])
        self.assertEqual(file['observedStat'], file['afterStat'])
        self.assertEqual(file['elfHeader'], self.binary.read_bytes()[:20].hex())
        self.assertEqual(package['rpm']['sourceRpm'], 'httpd-2.4.68-1.fc44.src.rpm')
        self.assertEqual(package['metadataStatus'], 'catalog-binding-recorded')
        self.assertFalse(package['rpmSignatureCryptographicallyVerified'])
        self.assertFalse(report['releaseEligible'])
        self.assertEqual(report['dispositionsGranted'], [])
        self.assertEqual(report['sbomSha256'], 'b' * 64)

    def test_digest_mismatch_records_actual_hash_and_remains_unknown(self):
        data = self.binary.read_bytes()
        self.binary.write_bytes(data[:-1] + b'!')
        file = self.file()
        self.assertEqual(file['reason'], 'digest-mismatch')
        self.assertFalse(file['actualFileIntegrityVerified'])
        self.assertEqual(file['actualSha256'], hashlib.sha256(self.binary.read_bytes()).hexdigest())

    def test_size_mismatch_never_reads_already_disproven_payload(self):
        self.binary.write_bytes(b'x')
        with mock.patch.object(collector.os, 'read', side_effect=AssertionError('must not read')):
            file = self.file()
        self.assertEqual(file['reason'], 'size-mismatch')

    def test_same_size_write_during_hashing_invalidates_stable_observation(self):
        original_read = os.read
        changed = False
        def changing(fd, size):
            nonlocal changed
            result = original_read(fd, size)
            if result and not changed:
                changed = True
                self.binary.write_bytes(b'!' * len(result))
            return result
        with mock.patch.object(collector.os, 'read', side_effect=changing):
            file = self.file()
        self.assertEqual(file['reason'], 'file-or-path-changed-during-observation')
        self.assertFalse(file['actualFileIntegrityVerified'])

    def test_replaced_path_same_bytes_fails_inode_binding(self):
        original_read = os.read
        changed = False
        def replacing(fd, size):
            nonlocal changed
            result = original_read(fd, size)
            if result and not changed:
                changed = True
                replacement = self.binary.with_name('replacement')
                replacement.write_bytes(self.binary.read_bytes())
                replacement.chmod(0o755)
                replacement.replace(self.binary)
            return result
        with mock.patch.object(collector.os, 'read', side_effect=replacing):
            file = self.file()
        self.assertEqual(file['reason'], 'file-or-path-changed-during-observation')

    def test_final_symlink_cannot_follow_host_file(self):
        outside = self.directory / 'outside'
        outside.write_bytes(self.binary.read_bytes())
        self.binary.unlink()
        self.binary.symlink_to(outside)
        file = self.file()
        self.assertEqual(file['status'], 'unknown')
        self.assertNotIn('actualSha256', file)
        self.assertEqual(outside.read_bytes(), b'\x7fELFfixture contents')

    def test_parent_symlink_cannot_escape_root(self):
        (self.rootfs / 'usr/sbin').rename(self.directory / 'outside')
        (self.rootfs / 'usr/sbin').symlink_to(self.directory / 'outside', target_is_directory=True)
        file = self.file()
        self.assertEqual(file['status'], 'unknown')
        self.assertNotIn('actualSha256', file)

    def test_hardlinked_regular_file_is_supported(self):
        os.link(self.binary, self.rootfs / 'second-link')
        file = self.file()
        self.assertTrue(file['actualFileIntegrityVerified'])
        self.assertEqual(file['observedStat']['linkCount'], 2)

    def test_missing_file_and_fifo_are_unknown_without_blocking(self):
        self.binary.unlink()
        self.assertEqual(self.file()['status'], 'unknown')
        os.mkfifo(self.binary)
        self.assertEqual(self.file()['reason'], 'actual-file-not-regular')

    def test_config_difference_is_not_mistaken_for_success(self):
        self.document['artifacts'][0]['metadata']['files'][0]['flags'] = 'cn'
        data = self.binary.read_bytes()
        self.binary.write_bytes(data[:-1] + b'!')
        self.assertEqual(self.file()['reason'], 'config-digest-difference')

    def test_ghost_and_declared_symlink_remain_explicit_unknown(self):
        item = self.document['artifacts'][0]['metadata']['files'][0]
        item['flags'] = 'g'
        self.assertEqual(self.file()['reason'], 'ghost-file-not-byte-qualified')
        item['flags'] = ''
        item['mode'] = stat.S_IFLNK | 0o777
        self.assertEqual(self.file()['reason'], 'declared-symlink-or-nonregular-file')

    def test_malformed_expected_mode_size_digest_remain_unknown(self):
        for key, value in [('mode', True), ('size', True), ('size', -1),
                           ('digest', {'algorithm': 'sha1', 'value': '0' * 40}),
                           ('digest', {'algorithm': 'sha256', 'value': 'not-a-hash'}),
                           ('flags', [])]:
            with self.subTest(key=key, value=value):
                document = copy.deepcopy(self.document)
                document['artifacts'][0]['metadata']['files'][0][key] = value
                self.assertFalse(self.file(self.collect(document))['actualFileIntegrityVerified'])

    def test_traversal_relative_and_noncanonical_paths_never_read(self):
        for path in ['/../outside', '/usr/../outside', 'usr/sbin/httpd', '//usr/sbin/httpd',
                     '/usr//sbin/httpd', '/usr/./sbin/httpd', '/usr/sbin/httpd\x00']:
            with self.subTest(path=path):
                document = copy.deepcopy(self.document)
                document['artifacts'][0]['metadata']['files'][0]['path'] = path
                self.assertEqual(self.file(self.collect(document))['reason'], 'noncanonical-declared-path')

    def test_sbom_source_and_immutable_manifest_binding_are_required(self):
        for source in [{'type': 'image', 'metadata': {'path': str(self.rootfs)}},
                       {'type': 'directory', 'metadata': {'path': '/other'}}]:
            document = copy.deepcopy(self.document)
            document['source'] = source
            with self.assertRaisesRegex(ValueError, 'directory source'):
                self.collect(document)
        for image in ['ghcr.io/closure-labs/finite:latest', 'ghcr.io/other/finite@sha256:' + 'a' * 64]:
            with self.assertRaisesRegex(ValueError, 'immutable Finite'):
                collector.collect(self.rootfs, self.document, image, 'b' * 64)

    def test_root_and_root_parent_symlinks_reject(self):
        link = self.directory / 'link'
        link.symlink_to(self.rootfs, target_is_directory=True)
        document = copy.deepcopy(self.document)
        document['source']['metadata']['path'] = str(link)
        with self.assertRaises(OSError):
            collector.collect(link, document, IMAGE, 'b' * 64)
        with self.assertRaisesRegex(ValueError, 'not the host root'):
            collector.root_descriptor('/')

    def test_regular_file_count_and_total_byte_bounds_preflight_before_reading(self):
        for name, limit in [('MAX_FILES', 0), ('MAX_TOTAL_BYTES', 0), ('MAX_MANIFEST_ROWS', 0)]:
            with self.subTest(bound=name), mock.patch.object(collector, name, limit), mock.patch.object(
                    collector.os, 'read', side_effect=AssertionError('must not read')):
                with self.assertRaises(ValueError):
                    self.collect()

    def test_actual_and_declared_file_size_bounds_prevent_large_reads(self):
        with mock.patch.object(collector, 'MAX_FILE', 4):
            self.assertEqual(self.file()['reason'], 'unsupported-or-unbounded-expected-digest-size')
            self.document['artifacts'][0]['metadata']['files'][0]['size'] = 3
            self.assertEqual(self.file()['reason'], 'actual-file-exceeds-size-bound')

    def test_duplicate_package_or_file_manifest_is_rejected(self):
        document = copy.deepcopy(self.document)
        document['artifacts'].append(copy.deepcopy(document['artifacts'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.collect(document)
        files = self.document['artifacts'][0]['metadata']['files']
        files.append(copy.deepcopy(files[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.collect()

    def test_missing_signature_wrong_source_or_purl_never_claims_package_trust(self):
        for target, key, value in [('metadata', 'signatures', []), ('metadata', 'sourceRpm', 'other.src.rpm'),
                                   ('artifact', 'purl', 'pkg:rpm/bluefin/httpd-core@2.4.69-1.fc44')]:
            document = copy.deepcopy(self.document)
            artifact = document['artifacts'][0]
            (artifact['metadata'] if target == 'metadata' else artifact)[key] = value
            package = self.collect(document)['targetRpmPackages'][0]
            self.assertEqual(package['metadataStatus'], 'unknown')
            self.assertFalse(package['rpmSignatureCryptographicallyVerified'])

    def test_non_rpm_and_unselected_package_do_not_supply_expected_file_authority(self):
        document = copy.deepcopy(self.document)
        document['artifacts'][0]['foundBy'] = 'elf-binary-package-cataloger'
        report = self.collect(document)
        self.assertEqual(report['targetRpmPackages'], [])
        self.assertIn('httpd-core', report['targetsNotCataloged'])
        self.assertTrue(report['absenceNotProof'])

    def test_raw_sbom_hash_and_duplicate_json_validation(self):
        path = self.directory / 'sbom.json'
        raw = json.dumps(self.document).encode()
        path.write_bytes(raw)
        parsed, digest = collector.read_sbom(path)
        self.assertEqual(parsed, self.document)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        path.write_text('{"artifacts":[], "artifacts":[]}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            collector.read_sbom(path)

    def test_sbom_symlink_oversize_and_mid_read_changes_reject(self):
        path = self.directory / 'sbom.json'
        path.symlink_to(self.binary)
        with self.assertRaises(OSError):
            collector.read_sbom(path)
        path.unlink()
        path.write_text(json.dumps(self.document))
        with mock.patch.object(collector, 'MAX_SBOM', 1):
            with self.assertRaisesRegex(ValueError, 'bounded'):
                collector.read_sbom(path)
        original_read = os.read
        changed = False
        def changing(fd, size):
            nonlocal changed
            result = original_read(fd, size)
            if result and not changed:
                changed = True
                path.write_bytes(b' ' * len(result))
            return result
        with mock.patch.object(collector.os, 'read', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed'):
                collector.read_sbom(path)

    def test_cli_hosted_guard_runs_before_any_sbom_read(self):
        argv = ['--rootfs', str(self.rootfs), '--sbom', str(self.directory / 'missing.json'),
                '--image', IMAGE, '--output', str(self.directory / 'report.json')]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(collector, 'read_sbom') as read:
            with self.assertRaises(SystemExit) as stopped:
                collector.main(argv)
            self.assertEqual(stopped.exception.code, 2)
            read.assert_not_called()

    def test_hosted_cli_creates_bounded_diagnostic_output_without_overwrite(self):
        sbom = self.directory / 'sbom.json'
        sbom.write_text(json.dumps(self.document))
        output = self.directory / 'report.json'
        argv = ['--rootfs', str(self.rootfs), '--sbom', str(sbom), '--image', IMAGE, '--output', str(output)]
        with mock.patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite'}):
            self.assertEqual(collector.main(argv), 0)
            self.assertFalse(json.loads(output.read_text())['releaseEligible'])
            with self.assertRaises(SystemExit) as stopped:
                collector.main(argv)
            self.assertEqual(stopped.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
