#!/usr/bin/env python3
"""Verify deterministic OCI edits and rejection of corrupt source metadata."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/bluebuild'))
import native_oci as oci


def fixture(path, corrupt=False, pax_headers=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        member = tarfile.TarInfo('original')
        member.pax_headers = pax_headers or {}
        member.size = 4
        archive.addfile(member, io.BytesIO(b'root'))
    layer = data.getvalue()
    layer_desc = oci.descriptor(layer, oci.LAYER)
    config = oci.encoded({'architecture': 'amd64', 'os': 'linux', 'created': '2026-11-17T00:00:00Z',
                          'config': {'Labels': {'io.finite.profile': 'finite', 'revision': 'exact'}},
                          'rootfs': {'type': 'layers', 'diff_ids': [layer_desc['digest']]}})
    config_desc = oci.descriptor(config, oci.CONFIG)
    manifest = oci.encoded({'schemaVersion': 2, 'mediaType': oci.MANIFEST,
                            'config': config_desc, 'layers': [layer_desc]})
    manifest_desc = oci.descriptor(manifest, oci.MANIFEST)
    files = {'oci-layout': oci.encoded({'imageLayoutVersion': '1.0.0'}),
             'index.json': oci.encoded({'schemaVersion': 2, 'manifests': [{**manifest_desc,
                                       'annotations': {'org.opencontainers.image.ref.name': 'candidate'}}]}),
             oci.blob_name(manifest_desc): manifest, oci.blob_name(config_desc): config,
             oci.blob_name(layer_desc): b'corrupt' if corrupt else layer}
    with tarfile.open(path, 'w') as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


class NativeLayer(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.tar'
        fixture(self.source)

    def test_repeated_edit_is_byte_identical_and_preserves_labels(self):
        outputs = [self.root / 'one.tar', self.root / 'two.tar']
        for output in outputs:
            oci.append(self.source, output, [oci.File('boot/EFI/Linux/kernel.efi', b'signed fixture')])
        self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
        image = oci.Image(outputs[0])
        self.addCleanup(image.close)
        self.assertEqual(image.config['config']['Labels'], {'io.finite.profile': 'finite', 'revision': 'exact'})
        self.assertEqual(len(image.manifest['layers']), 2)
        layer = image.archive.extractfile(image.members[oci.blob_name(image.manifest['layers'][-1])]).read()
        self.assertEqual('sha256:' + hashlib.sha256(layer).hexdigest(), image.config['rootfs']['diff_ids'][-1])
        with tarfile.open(fileobj=io.BytesIO(layer)) as archive:
            entry = archive.getmember('boot/EFI/Linux/kernel.efi')
            self.assertEqual((entry.uid, entry.gid, entry.mtime, entry.mode), (0, 0, 0, 0o644))
            self.assertEqual(archive.extractfile(entry).read(), b'signed fixture')

    def test_sealing_layers_preserve_file_capability_metadata(self):
        # Linux VFS capability revision 2 with CAP_NET_RAW in the permitted set.
        capability = bytes.fromhex('0100000200200000000000000000000000000000').decode('ascii')
        key = 'SCHILY.xattr.security.capability'
        fixture(self.source, pax_headers={key: capability})
        source = oci.Image(self.source)
        self.addCleanup(source.close)
        original = source.manifest['layers'][0]
        name = oci.blob_name(original)
        expected = source.archive.extractfile(source.members[name]).read()

        loader, sealed = self.root / 'loader.tar', self.root / 'sealed.tar'
        oci.append(self.source, loader, [oci.File('usr/lib/finite/efi/grubx64.efi', b'loader')])
        oci.append(loader, sealed, [oci.File('boot/EFI/Linux/kernel.efi', b'uki')])
        completed = oci.Image(sealed)
        self.addCleanup(completed.close)
        self.assertEqual(completed.manifest['layers'][0], original)
        preserved = completed.archive.extractfile(completed.members[name]).read()
        self.assertEqual(preserved, expected)
        with tarfile.open(fileobj=io.BytesIO(preserved)) as archive:
            self.assertEqual(archive.getmember('original').pax_headers[key], capability)

    def test_corrupt_blob_cannot_create_a_completed_output(self):
        fixture(self.source, corrupt=True)
        output = self.root / 'bad.tar'
        with self.assertRaisesRegex(ValueError, 'blob content'):
            oci.append(self.source, output, [oci.File('boot/new', b'value')])
        self.assertFalse(output.exists())

    def test_traversal_duplicate_and_conflicting_layer_paths_are_rejected(self):
        for files in [[oci.File('../outside', b'x')], [oci.File('/absolute', b'x')],
                      [oci.File('file', b'a'), oci.File('file', b'b')],
                      [oci.File('directory', b'a'), oci.File('directory/child', b'b')]]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                oci.append(self.source, self.root / 'bad.tar', files)

    def test_completed_output_cannot_be_replaced(self):
        output = self.root / 'keep.tar'
        output.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            oci.append(self.source, output, [oci.File('new', b'value')])
        self.assertEqual(output.read_bytes(), b'keep')

    def test_transport_unpack_retains_blobs_and_normalizes_only_reference_name(self):
        sealed = self.root / 'sealed.tar'
        digest = oci.append(self.source, sealed, [oci.File('boot/EFI/Linux/kernel.efi', b'signed fixture')])
        target = self.root / 'oci'
        script = ROOT / 'scripts/bluebuild/native_oci.py'
        transport = subprocess.check_output([sys.executable, script, sealed, target], text=True).strip()
        self.assertEqual(transport, f'oci:{target}:candidate')
        index = json.loads((target / 'index.json').read_text())
        self.assertEqual(index['manifests'][0]['annotations']['org.opencontainers.image.ref.name'], 'candidate')
        self.assertEqual(index['manifests'][0]['digest'], digest)
        for blob in (target / 'blobs/sha256').iterdir():
            self.assertEqual(blob.stat().st_uid, os.geteuid())
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), blob.name)


if __name__ == '__main__':
    unittest.main()
