#!/usr/bin/env python3
"""Metadata-only OCI adapters preserve the original authenticated image bytes."""
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('extraction_scan', ROOT / 'scripts/bluebuild/security-scan.py')
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)
LOCAL_SPEC = importlib.util.spec_from_file_location('extraction_local', ROOT / 'scripts/ci/local-candidate-evidence.py')
local = importlib.util.module_from_spec(LOCAL_SPEC)
LOCAL_SPEC.loader.exec_module(local)
REVISION = 'a' * 40
IDENTITY = 'v1:' + 'b' * 64


class ExtractionLayout(unittest.TestCase):
    def test_scanner_extracts_rootfs_without_repack_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(scan, 'run') as run:
                scan.unpack_rootfs(root / 'image', root / 'bundle/rootfs')
            run.assert_called_once_with(['umoci', 'raw', 'unpack', '--rootless', '--image',
                                         str(root / 'image') + ':audit', str(root / 'bundle/rootfs')])
            self.assertTrue((root / 'bundle').is_dir())

    def test_raw_extraction_rejects_existing_or_linked_rootfs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'existing'
            directory.mkdir()
            link = root / 'dangling'
            link.symlink_to(root / 'missing')
            for destination in (directory, link):
                with patch.object(scan, 'run') as run, self.assertRaisesRegex(ValueError, 'must be new'):
                    scan.unpack_rootfs(root / 'image', destination)
                run.assert_not_called()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.layout = self.root / 'image'
        self.blobs = self.layout / 'blobs/sha256'
        self.blobs.mkdir(parents=True)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            content = b'actual tiny hosted unpack probe\n'
            member = tarfile.TarInfo('probe-file')
            member.size = len(content)
            member.mode = 0o644
            tar.addfile(member, io.BytesIO(content))
        self.layer = self.blob(gzip.compress(archive.getvalue(), mtime=0), 'application/vnd.docker.image.rootfs.diff.tar.gzip')
        self.config_raw = json.dumps({'os': 'linux', 'architecture': 'amd64',
            'created': '2026-10-13T00:00:00Z', 'container_config': {'Cmd': ['/bin/never-execute']},
            'config': {'Labels': {'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                'org.opencontainers.image.revision': REVISION, 'io.finite.profile': 'finite',
                'io.finite.build-inputs': IDENTITY}}, 'rootfs': {'type': 'layers',
                'diff_ids': ['sha256:' + hashlib.sha256(archive.getvalue()).hexdigest()]}}).encode()
        self.config = self.blob(self.config_raw, scan.DOCKER_CONFIG)
        self.manifest = {'schemaVersion': 2, 'mediaType': scan.DOCKER_MANIFEST,
                         'config': self.config, 'layers': [self.layer], 'annotations': {'org.example.probe': 'unchanged'}}
        (self.layout / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
        self.bind()

    def blob(self, raw, media_type):
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        (self.blobs / digest[7:]).write_bytes(raw)
        return {'mediaType': media_type, 'digest': digest, 'size': len(raw)}

    def bind(self, indexed=False):
        raw = json.dumps(self.manifest).encode()
        self.descriptor = self.blob(raw, self.manifest['mediaType'])
        self.platform_raw = raw
        if indexed:
            parent = {'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.list.v2+json',
                      'manifests': [{**self.descriptor, 'platform': {'os': 'linux', 'architecture': 'amd64'}}]}
            self.parent_raw = json.dumps(parent).encode()
            self.parent_descriptor = self.blob(self.parent_raw, parent['mediaType'])
        else:
            self.parent_raw = raw
            self.parent_descriptor = self.descriptor
        self.image = 'ghcr.io/closure-labs/finite@' + self.parent_descriptor['digest']
        self.index = {'schemaVersion': 2, 'manifests': [{**self.parent_descriptor,
                      'annotations': {'org.opencontainers.image.ref.name': 'audit'}}]}
        (self.layout / 'index.json').write_text(json.dumps(self.index))

    def prepare(self):
        return scan.prepare_layout(self.layout, self.image, self.evidence)

    def test_docker_projection_preserves_config_id_layers_and_original_source_digest(self):
        before = {path.name: path.read_bytes() for path in self.blobs.iterdir()}
        original = self.prepare()
        self.assertEqual(original, {'parent': self.parent_raw.decode(), 'child': None, 'config': self.config_raw.decode()})
        for name, raw in before.items():
            self.assertEqual((self.blobs / name).read_bytes(), raw)
        descriptor = json.loads((self.layout / 'index.json').read_text())['manifests'][0]
        self.assertEqual(descriptor['mediaType'], scan.OCI_MANIFEST)
        projected_raw = (self.blobs / descriptor['digest'][7:]).read_bytes()
        self.assertEqual(descriptor['digest'], 'sha256:' + hashlib.sha256(projected_raw).hexdigest())
        self.assertEqual(descriptor['size'], len(projected_raw))
        projected = json.loads(projected_raw)
        self.assertEqual(projected['mediaType'], scan.OCI_MANIFEST)
        self.assertEqual(projected['config'], {**self.config, 'mediaType': scan.OCI_CONFIG})
        self.assertEqual(projected['layers'], [{**self.layer, 'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip'}])
        self.assertEqual(projected['annotations'], self.manifest['annotations'])
        self.assertEqual((self.evidence / 'image-manifest.json').read_bytes(), self.parent_raw)
        self.assertEqual((self.evidence / 'image-config.json').read_bytes(), self.config_raw)
        trace = json.loads((self.evidence / 'extraction-layout.json').read_text())
        self.assertEqual(trace['originalImageDigest'], self.image.split('@')[1])
        self.assertEqual(trace['configurationDigest'], 'sha256:' + hashlib.sha256(self.config_raw).hexdigest())
        self.assertFalse(trace['extractionManifestIsAuthenticatedSource'])
        self.assertFalse(trace['configurationBytesChanged'])
        self.assertFalse(trace['layerBytesChanged'])
        self.assertEqual(scan.policy_module.manifest_binding(self.image, original), self.descriptor['digest'])

    def test_indexed_docker_preserves_parent_platform_and_original_binding(self):
        self.bind(indexed=True)
        original = self.prepare()
        self.assertEqual(original['parent'], self.parent_raw.decode())
        self.assertEqual(original['child'], self.platform_raw.decode())
        trace = json.loads((self.evidence / 'extraction-layout.json').read_text())
        self.assertEqual(trace['originalImageDigest'], self.parent_descriptor['digest'])
        self.assertEqual(trace['originalPlatformManifestDigest'], self.descriptor['digest'])
        self.assertEqual((self.evidence / 'platform-manifest.json').read_bytes(), self.platform_raw)

    def test_existing_oci_graph_only_flattens_pointer_without_conversion(self):
        self.manifest['mediaType'] = scan.OCI_MANIFEST
        self.manifest['config']['mediaType'] = scan.OCI_CONFIG
        self.manifest['layers'][0]['mediaType'] = 'application/vnd.oci.image.layer.v1.tar+gzip'
        self.bind(indexed=True)
        before = {path.name: path.read_bytes() for path in self.blobs.iterdir()}
        self.prepare()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.blobs.iterdir()})
        self.assertFalse((self.evidence / 'extraction-layout.json').exists())
        self.assertEqual(json.loads((self.layout / 'index.json').read_text())['manifests'][0]['digest'], self.descriptor['digest'])

    def test_unknown_foreign_layer_bad_size_or_mixed_graph_fails_before_index_mutation(self):
        for change in (lambda: self.manifest['layers'][0].update(mediaType='unsupported'),
                       lambda: self.manifest['layers'][0].update(mediaType='application/vnd.docker.image.rootfs.foreign.diff.tar.gzip'),
                       lambda: self.manifest['layers'][0].update(size=True),
                       lambda: self.manifest['layers'][0].update(size=-1),
                       lambda: self.manifest['layers'][0].update(digest='sha256:../../escape'),
                       lambda: self.manifest['layers'][0].update(urls=['https://unapproved.invalid/layer']),
                       lambda: self.manifest.update(manifests=[])):
            with self.subTest(change=change):
                self.setUp()
                change()
                self.bind()
                before = (self.layout / 'index.json').read_bytes()
                with self.assertRaises(ValueError): self.prepare()
                self.assertEqual((self.layout / 'index.json').read_bytes(), before)

    def test_parent_config_tampering_and_descriptor_size_mismatch_are_rejected(self):
        for which in ('parent', 'config', 'config-size'):
            self.setUp()
            if which == 'parent': (self.blobs / self.parent_descriptor['digest'][7:]).write_bytes(self.parent_raw + b' ')
            if which == 'config': (self.blobs / self.config['digest'][7:]).write_bytes(self.config_raw.replace(b'linux', b'other'))
            if which == 'config-size':
                self.manifest['config']['size'] += 1
                self.bind()
            before = (self.layout / 'index.json').read_bytes()
            with self.assertRaises(ValueError): self.prepare()
            self.assertEqual((self.layout / 'index.json').read_bytes(), before)

    def test_same_size_layer_tamper_is_rejected_by_existing_single_hash_gate(self):
        raw = (self.blobs / self.layer['digest'][7:]).read_bytes()
        (self.blobs / self.layer['digest'][7:]).write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaisesRegex(ValueError, 'layer blob digest mismatch'):
            local.validate_candidate(self.layout, 'finite', IDENTITY, REVISION)
        self.assertFalse((self.evidence / 'extraction-layout.json').exists())

    def test_private_hardlinked_pointer_never_modifies_original_builder_graph(self):
        candidate = local.validate_candidate(self.layout, 'finite', IDENTITY, REVISION)
        before = {path.relative_to(self.layout).as_posix(): path.read_bytes() for path in self.layout.rglob('*') if path.is_file()}
        pointer = self.root / 'private/image'
        blobs = pointer / 'blobs/sha256'
        blobs.mkdir(parents=True)
        (pointer / 'index.json').write_text(json.dumps(self.index))
        (pointer / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
        for path in candidate['paths']:
            os.link(path, blobs / path.name)
        scan.prepare_layout(pointer, self.image, self.evidence)
        after = {path.relative_to(self.layout).as_posix(): path.read_bytes() for path in self.layout.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertNotEqual((pointer / 'index.json').read_bytes(), (self.layout / 'index.json').read_bytes())

    def test_duplicate_config_keys_and_symlinked_metadata_reject(self):
        raw = b'{"os":"linux","os":"windows"}'
        self.manifest['config'] = self.blob(raw, scan.DOCKER_CONFIG)
        self.bind()
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.prepare()
        self.setUp()
        config = self.blobs / self.config['digest'][7:]
        saved = self.root / 'saved-config'
        config.rename(saved)
        config.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, 'symlinked'): self.prepare()


if __name__ == '__main__':
    unittest.main()
