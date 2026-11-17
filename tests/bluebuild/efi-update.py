#!/usr/bin/env python3
"""Inject interruption at every EFI write and restore the previous boot files."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('efi', str(ROOT / 'files/system/usr/libexec/finite/update-efi'))
spec = importlib.util.spec_from_loader(loader.name, loader)
efi = importlib.util.module_from_spec(spec)
loader.exec_module(efi)


def setup(root):
    esp, state = root / 'esp', root / 'state'
    esp.mkdir()
    state.mkdir(mode=0o700)
    for name, value in {'EFI/finite/grubx64.efi': b'old loader', 'EFI/BOOT/BOOTX64.EFI': b'old fallback',
                        'EFI/fedora/grubx64.efi': b'GRUB recovery', 'EFI/refind/refind_x64.efi': b'old refind'}.items():
        path = esp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    payload = {name: ('new ' + name).encode() for name in efi.PAYLOAD_NAMES}
    return esp, state, payload


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob('*') if path.is_file()}


class EFIUpdate(unittest.TestCase):
    def test_rescue_mount_path_can_change_but_filesystem_identity_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp, state, payload = setup(root)
            before = snapshot(esp)
            generation = efi.apply(esp, state, efi.mapping(payload, False), esp_uuid='1234-ABCD')
            rescue = root / 'rescue-esp'
            esp.rename(rescue)
            current = snapshot(rescue)
            for identity in [None, '5678-ABCD']:
                with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'this ESP'):
                    efi.recover(rescue, state, generation.name, esp_uuid=identity)
                self.assertEqual(snapshot(rescue), current)
            efi.recover(rescue, state, generation.name, esp_uuid='1234-ABCD')
            self.assertEqual(snapshot(rescue), before)

    def test_each_interrupted_write_can_restore_the_complete_previous_generation(self):
        for interrupted_write in range(1, 8):
            with self.subTest(write=interrupted_write), tempfile.TemporaryDirectory() as directory:
                esp, state, payload = setup(Path(directory))
                before = snapshot(esp)
                atomic = efi.atomic_bytes
                writes = 0

                def interrupt(path, data):
                    nonlocal writes
                    if path.is_relative_to(esp):
                        writes += 1
                        if writes == interrupted_write:
                            raise InterruptedError('injected power-loss boundary')
                    atomic(path, data)

                with patch.object(efi, 'atomic_bytes', side_effect=interrupt):
                    with self.assertRaises(InterruptedError):
                        efi.apply(esp, state, efi.mapping(payload, True))
                generation = next(state.glob('*/journal.json')).parent
                with self.assertRaisesRegex(ValueError, 'Interrupted EFI update'):
                    efi.apply(esp, state, efi.mapping(payload, True))
                efi.recover(esp, state, generation.name)
                self.assertEqual(snapshot(esp), before)
                self.assertEqual(json.loads((generation / 'journal.json').read_text())['phase'], 'recovered')

    def test_coexistence_preserves_grub_refind_and_fallback_and_updates_all_managed_loaders(self):
        with tempfile.TemporaryDirectory() as directory:
            esp, state, payload = setup(Path(directory))
            before = snapshot(esp)
            generation = efi.apply(esp, state, efi.mapping(payload, False))
            self.assertIsNotNone(generation)
            for name in ['EFI/fedora/grubx64.efi', 'EFI/refind/refind_x64.efi', 'EFI/BOOT/BOOTX64.EFI']:
                self.assertEqual((esp / name).read_bytes(), before[name])
            for name in ['EFI/finite/grubx64.efi', 'EFI/systemd/systemd-bootx64.efi']:
                self.assertEqual((esp / name).read_bytes(), payload['grubx64.efi'])
            self.assertIsNone(efi.apply(esp, state, efi.mapping(payload, False)))
            efi.recover(esp, state, generation.name)
            self.assertEqual(snapshot(esp), before)

    def test_unknown_external_change_is_not_overwritten_by_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            esp, state, payload = setup(Path(directory))
            generation = efi.apply(esp, state, efi.mapping(payload, False))
            (esp / 'EFI/finite/grubx64.efi').write_bytes(b'admin intervention')
            before = snapshot(esp)
            with self.assertRaisesRegex(ValueError, 'outside this transaction'):
                efi.recover(esp, state, generation.name)
            self.assertEqual(snapshot(esp), before)

    def test_insufficient_space_and_symlink_targets_do_not_modify_efi_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp, state, payload = setup(root)
            before = snapshot(esp)
            from collections import namedtuple
            usage = namedtuple('usage', 'total used free')
            with patch.object(efi.shutil, 'disk_usage', return_value=usage(1, 1, 0)):
                with self.assertRaisesRegex(ValueError, 'Insufficient ESP space'):
                    efi.apply(esp, state, efi.mapping(payload, False))
            self.assertEqual(snapshot(esp), before)
            outside = root / 'outside'
            outside.write_bytes(b'untouched')
            (esp / 'EFI/finite/grubx64.efi').unlink()
            (esp / 'EFI/finite/grubx64.efi').symlink_to(outside)
            with self.assertRaises(ValueError):
                efi.apply(esp, state, efi.mapping(payload, False))
            self.assertEqual(outside.read_bytes(), b'untouched')


if __name__ == '__main__':
    unittest.main()
