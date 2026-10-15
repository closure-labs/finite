#!/usr/bin/env python3
"""Bounded synthetic ELF tests; no compiler, images or image code execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('applicability', ROOT / 'scripts/ci/applicability-evidence.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)
REVISION = 'a' * 40
IDENTITY = 'v1:' + 'b' * 64


def varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def fixture(version='go1.26.4', settings='build\tGOOS=linux\nbuild\tGOARCH=amd64\n', flags=2):
    module = app.START + ('path\tgithub.com/sigstore/cosign/v3/cmd/cosign\n'
        'mod\tgithub.com/sigstore/cosign/v3\tv3.1.3\th1:fixture\n'
        'dep\tgolang.org/x/mod\tv0.37.0\th1:fixture\n' + settings).encode() + app.END
    info = app.MAGIC + bytes([8, flags]) + b'\0' * 16
    info += varint(len(version)) + version.encode() + varint(len(module)) + module
    names = b'\0.shstrtab\0.go.buildinfo\0'
    data = bytearray(352 + len(info))
    data[:16] = b'\x7fELF\x02\x01\x01' + b'\0' * 9
    struct.pack_into('<HHIQQQIHHHHHH', data, 16, 2, 62, 1, 0, 64, 128, 0, 64, 56, 1, 64, 3, 1)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 6, 0, 0x400000, 0x400000, len(data), len(data), 4096)
    struct.pack_into('<IIQQQQIIQQ', data, 192, 1, 3, 0, 0, 320, len(names), 0, 0, 1, 0)
    struct.pack_into('<IIQQQQIIQQ', data, 256, 11, 1, 3, 0x400000 + 352, 352, len(info), 0, 0, 16, 0)
    data[320:320 + len(names)] = names
    data[352:] = info
    return data


class Applicability(unittest.TestCase):
    def test_current_catalog_selects_development_and_retained_go_files(self):
        root = Path('/extracted/rootfs')
        sbom = {'source': {'type': 'directory', 'metadata': {'path': str(root)}},
                'artifacts': [{'name': 'stdlib', 'type': 'go-module', 'purl': 'pkg:golang/stdlib@1.26.8',
                    'locations': [{'path': '/usr/libexec/docker/docker-buildx'}]},
                    {'name': 'stdlib', 'type': 'go-module', 'purl': 'pkg:golang/stdlib@1.26.6',
                    'locations': [{'path': str(root) + '/sysroot/ostree/repo/objects/aa/example.file'}]},
                    {'name': 'other', 'type': 'rpm', 'locations': [{'path': '/ignored'}]}]}
        ledger = app.catalog_selection(sbom, root, 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64)
        findings, paths = app.selected_findings(ledger)
        self.assertEqual(paths, ['/sysroot/ostree/repo/objects/aa/example.file', '/usr/libexec/docker/docker-buildx'])
        self.assertEqual(ledger['selectionType'], 'current-native-catalog-probes')
        self.assertTrue(all('GO-2026-6604' in finding['aliases'] for finding in findings))
        bad = deepcopy(sbom)
        bad['source']['metadata']['path'] = '/another/rootfs'
        with self.assertRaises(ValueError):
            app.catalog_selection(bad, root, ledger['image'])
        bad = deepcopy(sbom)
        bad['artifacts'][0]['locations'][0]['path'] = '/usr/../outside'
        with self.assertRaises(ValueError):
            app.catalog_selection(bad, root, ledger['image'])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binary = self.root / 'binary'
        self.binary.write_bytes(fixture())
        self.rootfs = self.root / 'rootfs'
        (self.rootfs / 'usr/bin').mkdir(parents=True)
        (self.rootfs / 'usr/bin/cosign').write_bytes(fixture())
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        self.config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'io.finite.profile': 'finite', 'org.opencontainers.image.revision': REVISION,
            'io.finite.build-inputs': IDENTITY, 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}}}
        self.bind()
        self.ledger = {'schema': 1, 'image': 'ghcr.io/closure-labs/finite@sha256:' + 'c' * 64,
            'findings': [{'component': 'pkg:golang/stdlib@1.26.4', 'advisory': 'GO-2026-6604',
                         'aliases': ['GO-2026-6604', 'CVE-2026-56857'], 'locations': ['/usr/bin/cosign']}]}

    def bind(self):
        config = json.dumps(self.config).encode()
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'size': len(config),
                               'digest': 'sha256:' + hashlib.sha256(config).hexdigest()}, 'layers': []}
        raw = json.dumps(manifest).encode()
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(raw).hexdigest()
        (self.evidence / 'image-config.json').write_bytes(config)
        (self.evidence / 'image-manifest.json').write_bytes(raw)

    def collect(self):
        return app.collect(self.rootfs, self.evidence, self.image, 'finite', REVISION, IDENTITY, self.ledger)

    def test_actual_bytes_platform_and_build_metadata_are_positive_evidence(self):
        result = app.inspect(self.binary)
        self.assertEqual(result['status'], 'platform-proven')
        self.assertEqual(result['sha256'], hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.assertEqual((result['os'], result['arch']), ('linux', 'amd64'))
        self.assertEqual(result['goVersion'], 'go1.26.4')
        self.assertIn('dep\tgolang.org/x/mod\tv0.37.0\th1:fixture', result['relevantModuleRecords'])
        self.assertTrue(result['absenceNotProof'])
        self.assertEqual(result['symbolCoverage'], 'not-collected')

    def test_reviewed_fedora_suffix_and_prerelease_metadata_remain_exact(self):
        for version in ('go1.26.8-X:nodwarf5', 'go1.26rc2-X:nodwarf5', 'go1.27.1'):
            self.binary.write_bytes(fixture(version))
            self.assertEqual(app.inspect(self.binary)['goVersion'], version)

    def test_wrong_platform_duplicate_missing_or_quoted_settings_remain_unknown(self):
        for settings in ('build\tGOOS=windows\nbuild\tGOARCH=amd64\n',
                         'build\tGOOS=linux\nbuild\tGOARCH=arm64\n', 'build\tGOARCH=amd64\n',
                         'build\tGOOS=linux\nbuild\tGOOS=linux\nbuild\tGOARCH=amd64\n',
                         'build\tGOOS=linux\nbuild\t"GOOS"=windows\nbuild\tGOARCH=amd64\n'):
            self.binary.write_bytes(fixture(settings=settings))
            self.assertEqual(app.inspect(self.binary)['status'], 'unknown')

    def test_malformed_elf_header_and_tables_fail_closed(self):
        changes = [(0, b'MZ'), (4, b'\x01'), (5, b'\x02'), (7, b'\x09'), (18, struct.pack('<H', 183)),
                   (40, struct.pack('<Q', 2**63)), (58, struct.pack('<H', 1)), (60, struct.pack('<H', 65535)),
                   (62, struct.pack('<H', 3)), (192 + 24, struct.pack('<Q', 2**63)),
                   (256 + 32, struct.pack('<Q', app.MAX_METADATA + 1)),
                   (256 + 24, struct.pack('<Q', 400)), (256 + 16, struct.pack('<Q', 0xdeadbeef)),
                   (64, struct.pack('<I', 0)), (64 + 32, struct.pack('<Q', 2**63))]
        for offset, value in changes:
            with self.subTest(offset=offset):
                data = fixture()
                data[offset:offset + len(value)] = value
                self.binary.write_bytes(data)
                self.assertEqual(app.inspect(self.binary)['status'], 'unknown')

    def test_unsupported_flags_versions_and_corrupt_framing_are_unknown(self):
        for data in (fixture(flags=0), fixture(flags=3), fixture('go1.28.1'), fixture('devel go1.28'),
                     fixture().replace(app.START, b'x' * 16), fixture()[:-1]):
            self.binary.write_bytes(data)
            self.assertEqual(app.inspect(self.binary)['status'], 'unknown')

    def test_varint_length_and_overflow_are_bounded(self):
        for raw in (b'\x80', b'\xff' * 10, varint(app.MAX_METADATA + 1) + b'x', b'\x08x'):
            with self.assertRaises(ValueError):
                app.inline_string(raw, 0)

    def test_symlink_fifo_and_oversize_binary_never_supply_platform_proof(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.binary)
        self.assertEqual(app.inspect(alias)['status'], 'unknown')
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        self.assertEqual(app.inspect(fifo)['status'], 'unknown')
        with self.binary.open('wb') as stream:
            stream.truncate(app.MAX_BINARY + 1)
        self.assertEqual(app.inspect(self.binary)['status'], 'unknown')

    def test_file_change_during_inspection_invalidates_proof(self):
        original = app.build_info
        def changed(stream, size):
            result = original(stream, size)
            with self.binary.open('ab') as target:
                target.write(b'changed')
            return result
        with patch.object(app, 'build_info', side_effect=changed):
            self.assertEqual(app.inspect(self.binary)['status'], 'unknown')

    def test_selectors_remain_explicitly_historical_and_no_clearance_is_granted(self):
        result = self.collect()
        self.assertEqual(result['selectionLedgerImage'], self.ledger['image'])
        self.assertNotEqual(result['image'], self.ledger['image'])
        self.assertEqual(result['selectionFindings'], self.ledger['findings'])
        self.assertNotIn('findings', result)
        self.assertEqual(result['dispositionsGranted'], [])
        self.assertFalse(result['releaseEligible'])
        self.assertEqual(result['vulnerabilityClearance'], 'not-assessed')

    def test_every_selected_path_attempted_missing_and_symlink_paths_remain_unknown(self):
        self.ledger['findings'][0]['locations'].extend(['/missing', '/usr/bin/alias'])
        (self.rootfs / 'usr/bin/alias').symlink_to('cosign')
        result = self.collect()
        self.assertEqual(len(result['binaries']), 3)
        self.assertEqual(result['status'], 'diagnostic-complete-with-unknowns')
        self.assertEqual(sum(b['status'] == 'unknown' for b in result['binaries']), 2)

    def test_traversal_missing_locations_or_excess_paths_are_not_partial_success(self):
        for locations in ([], ['/usr/../secret'], ['relative/path'], ['/'], ['/f' + str(i) for i in range(129)]):
            self.ledger['findings'][0]['locations'] = locations
            with self.assertRaises(ValueError):
                self.collect()

    def test_mutable_digest_hash_mismatch_and_wrong_expected_config_are_rejected(self):
        old_image = self.image
        self.image = 'ghcr.io/closure-labs/finite:latest'
        with self.assertRaises(ValueError): self.collect()
        self.image = old_image
        (self.evidence / 'image-config.json').write_bytes(b'{}')
        with self.assertRaises(ValueError): self.collect()
        for label, value in [('io.finite.profile', 'bluefin-next'), ('org.opencontainers.image.revision', 'c' * 40),
                             ('io.finite.build-inputs', 'v1:' + 'd' * 64)]:
            config = deepcopy(self.config)
            self.config['config']['Labels'][label] = value
            self.bind()
            with self.assertRaises(ValueError): self.collect()
            self.config = config

    def test_metadata_duplicate_json_keys_are_rejected(self):
        path = self.root / 'metadata.json'
        path.write_text('{"image":"first","image":"second"}')
        with self.assertRaises(ValueError): app.read(path)

    def test_main_requires_hosted_runner_and_never_overwrites_evidence(self):
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps(self.ledger))
        output = self.root / 'output.json'
        arguments = ['--rootfs', str(self.rootfs), '--manifest-dir', str(self.evidence), '--image', self.image,
                     '--profile', 'finite', '--revision', REVISION, '--identity', IDENTITY,
                     '--ledger', str(ledger), '--output', str(output)]
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit): app.main(arguments)
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite'}
        with patch.dict(os.environ, environment, clear=True): self.assertEqual(app.main(arguments), 0)
        original = output.read_bytes()
        with patch.dict(os.environ, environment, clear=True), self.assertRaises(SystemExit): app.main(arguments)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(json.loads(original)['selectionLedgerSha256'], hashlib.sha256(ledger.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
