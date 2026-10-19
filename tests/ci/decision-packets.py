#!/usr/bin/env python3
"""Reject OCI path, integrity and size failures without using a registry."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import decision_packets as mod


def sha(value):
    return hashlib.sha256(value).hexdigest()


class Registry:
    def __init__(self):
        self.data = b'original native evidence'
        self.packet = {'schema': 1, 'producer': {'runId': 7},
                       'files': {'finite/security-result.json': {'size': len(self.data), 'sha256': sha(self.data)}}}
        self.packet_bytes = json.dumps(self.packet).encode()
        self.layers = [self.layer('decision-packet.json', self.packet_bytes),
                       self.layer('finite/security-result.json', self.data)]
        self.blobs = {sha(self.packet_bytes): self.packet_bytes, sha(self.data): self.data}
        self.manifest = {'schemaVersion': 2, 'artifactType': mod.TYPE, 'layers': self.layers}
        self.raw_override = None
        self.blob_override = None
        self.refresh()

    def layer(self, name, value):
        return {'annotations': {'org.opencontainers.image.title': name},
                'digest': 'sha256:' + sha(value), 'size': len(value)}

    def refresh(self):
        self.raw = self.raw_override if self.raw_override is not None else json.dumps(self.manifest).encode()
        self.reference = mod.REGISTRY + '@sha256:' + sha(self.raw)

    def command(self, args, **kwargs):
        if args[1:3] == ['manifest', 'fetch']:
            return self.raw
        if args[1:3] == ['blob', 'fetch']:
            digest = args[3].split(':')[-1]
            Path(args[args.index('--output') + 1]).write_bytes(self.blob_override if self.blob_override is not None else self.blobs[digest])
            return b''
        raise AssertionError(args)


class Packets(unittest.TestCase):
    def fetch(self, registry, expected=True):
        registry.refresh()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mod, 'command', side_effect=registry.command):
            return mod.fetch(registry.reference, Path(directory) / 'packet',
                             mod.canonical_hash(registry.packet) if expected else None)

    def test_roundtrip_immutable_manifest_and_files(self):
        registry = Registry()
        self.assertEqual(self.fetch(registry), registry.packet)

    def test_wrong_reference_or_manifest_hash_rejected(self):
        registry = Registry()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mod, 'command', side_effect=registry.command):
            with self.assertRaises(ValueError):
                mod.fetch(mod.REGISTRY + ':latest', Path(directory) / 'packet')
            with self.assertRaises(ValueError):
                mod.fetch(mod.REGISTRY + '@sha256:' + '0' * 64, Path(directory) / 'packet')

    def test_traversal_absolute_duplicate_and_parent_paths_rejected(self):
        for name in ('../escape', '/tmp/escape', 'a/../escape', 'a//b', 'a/./b', 'a\\b', '-flag'):
            registry = Registry()
            registry.layers[1]['annotations']['org.opencontainers.image.title'] = name
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.fetch(registry)
        registry = Registry()
        registry.layers.append(copy.deepcopy(registry.layers[1]))
        with self.assertRaises(ValueError):
            self.fetch(registry)

    def test_layer_hash_size_and_packet_bindings_rejected(self):
        for alter in ('data', 'size', 'manifest'):
            registry = Registry()
            if alter == 'data':
                registry.blob_override = b'forged'
            elif alter == 'size':
                registry.layers[1]['size'] += 1
            else:
                registry.layers[1]['digest'] = 'sha256:' + sha(b'forged')
            with self.subTest(alter=alter):
                with self.assertRaises(ValueError):
                    self.fetch(registry)

    def test_packet_expected_hash_rejected(self):
        registry = Registry()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mod, 'command', side_effect=registry.command):
            with self.assertRaises(ValueError):
                mod.fetch(registry.reference, Path(directory) / 'packet', '0' * 64)

    def test_oversized_and_invalid_descriptors_rejected_before_blob_fetch(self):
        for change in ({'size': mod.MAX_BYTES + 1}, {'size': True}, {'size': 0}, {'digest': 'bad'}):
            registry = Registry()
            registry.layers[1].update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.fetch(registry)
        registry = Registry()
        registry.layers[1] = []
        with self.assertRaises(ValueError):
            self.fetch(registry)

    def test_duplicate_json_keys_rejected(self):
        registry = Registry()
        registry.raw_override = b'{"schemaVersion":2,"schemaVersion":2}'
        with self.assertRaises(ValueError):
            self.fetch(registry)

    def test_inventory_rejects_links_reserved_empty_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'native.json').write_text('{}')
            (path / 'link').symlink_to('native.json')
            with self.assertRaises(ValueError):
                mod.inventory(path)
            (path / 'link').unlink()
            (path / 'decision-packet.json').write_text('{}')
            with self.assertRaises(ValueError):
                mod.inventory(path)
            (path / 'decision-packet.json').unlink()
            (path / 'native.json').write_bytes(b'')
            with self.assertRaises(ValueError):
                mod.inventory(path)
            (path / 'native.json').write_text('{}')
            with mock.patch.object(mod, 'MAX_BYTES', 1), self.assertRaises(ValueError):
                mod.inventory(path)

    def test_existing_output_never_reused(self):
        registry = Registry()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mod, 'command', side_effect=registry.command):
            with self.assertRaises(FileExistsError):
                mod.fetch(registry.reference, Path(directory))


if __name__ == '__main__':
    unittest.main()
