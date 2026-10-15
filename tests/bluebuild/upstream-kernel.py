#!/usr/bin/env python3
"""Small filesystem/RPM fixtures for inherited Bluefin ABI preservation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('upstream_kernel', ROOT / 'files/scripts/upstream-kernel.py')
kernel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kernel)
RELEASE = '7.2.5-200.fc44.x86_64'


class Preservation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.modules = self.root / 'modules'
        self.tree = self.modules / RELEASE
        self.tree.mkdir(parents=True)
        self.receipt = self.root / 'upstream.json'
        for relative in ('vmlinuz', 'initramfs.img', 'modules.dep',
                         'extra/zfs/zfs.ko.xz', 'extra/zfs/spl.ko.xz',
                         'extra/v4l2loopback/v4l2loopback.ko', 'kernel/native.ko.zst'):
            self.write(relative)
        self.rpms = {name: [('0:7.2.5-200.fc44', 'x86_64')] for name in
                     ('kernel', 'kernel-core', 'kernel-modules-core', 'kernel-modules-extra', 'kernel-devel')}
        self.rpms.update({name: [('0:2.4.4-1.fc44', 'x86_64')] for name in
                          ('kmod-zfs', 'zfs', 'python3-pyzfs', 'libzfs7', 'libzpool7', 'kmod-v4l2loopback')})
        self.rpms['nix'] = [('0:2.31.0-1.fc44', 'x86_64')]

    def write(self, relative, content=None):
        path = self.tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relative if content is None else content).encode())
        return path

    def rpm(self, command):
        self.assertEqual(command[:2], ['rpm', '-qa'])
        return ''.join('\t'.join((name, *record)) + '\n'
                       for name, records in self.rpms.items() for record in records)

    def snapshot(self):
        return kernel.snapshot(self.receipt, self.modules, self.rpm)

    def verify(self):
        return kernel.verify(self.receipt, self.modules, self.rpm)

    def test_preserves_zfs_camera_kernel_and_development_packages(self):
        value = self.snapshot()
        self.assertEqual(self.verify(), value)
        self.assertEqual(value['kernelRelease'], RELEASE)
        for name in ('kernel-devel', 'zfs', 'kmod-zfs', 'python3-pyzfs', 'kmod-v4l2loopback', 'libzfs7'):
            self.assertIn(name, value['packages'])
        self.assertIn(RELEASE + '/extra/zfs/zfs.ko.xz', value['modules'])
        self.assertIn(RELEASE + '/extra/v4l2loopback/v4l2loopback.ko', value['modules'])

    def test_finite_additions_and_derived_initramfs_do_not_change_upstream_abi(self):
        original = self.snapshot()
        self.rpms['nix'] = [('0:2.32.0-1.fc44', 'x86_64')]
        self.rpms['fido2-tools'] = [('0:1.0-1.fc44', 'x86_64')]
        self.write('initramfs.img', 'regenerated encrypted-root/FIDO2 archive')
        self.assertEqual(self.verify(), original)

    def test_any_protected_package_removal_upgrade_or_addition_fails(self):
        self.snapshot()
        original = copy.deepcopy(self.rpms)
        for name in ('kernel-core', 'kernel-devel', 'kmod-zfs', 'zfs', 'libzfs7', 'kmod-v4l2loopback'):
            for change in ('remove', 'upgrade'):
                self.rpms = copy.deepcopy(original)
                if change == 'remove': del self.rpms[name]
                else: self.rpms[name] = [('0:99.0-1.fc44', 'x86_64')]
                with self.subTest(name=name, change=change), self.assertRaises(ValueError): self.verify()
        self.rpms = copy.deepcopy(original)
        self.rpms['kmod-unreviewed'] = [('0:1.0-1.fc44', 'x86_64')]
        with self.assertRaises(ValueError): self.verify()

    def test_changed_removed_added_or_repermissioned_module_payload_fails(self):
        self.snapshot()
        path = self.tree / 'extra/zfs/zfs.ko.xz'
        before = path.read_bytes()
        path.write_bytes(b'changed module')
        with self.assertRaises(ValueError): self.verify()
        path.unlink()
        with self.assertRaises(ValueError): self.verify()
        path.write_bytes(before)
        path.chmod(0o666)
        with self.assertRaises(ValueError): self.verify()
        path.chmod(0o644)
        self.write('extra/unknown.ko')
        with self.assertRaises(ValueError): self.verify()

    def test_link_metadata_is_bound_without_following_external_header_trees(self):
        (self.tree / 'build').symlink_to('/usr/src/kernels/' + RELEASE)
        self.snapshot()
        self.verify()
        (self.tree / 'build').unlink()
        (self.tree / 'build').symlink_to('/usr/src/changed')
        with self.assertRaises(ValueError): self.verify()

    def test_module_link_must_resolve_to_preserved_bytes(self):
        outside = self.root / 'untracked.ko'
        outside.write_bytes(b'untracked')
        (self.tree / 'escaped.ko').symlink_to(outside)
        with self.assertRaises(ValueError): self.snapshot()

    def test_snapshot_and_receipt_are_bounded_new_regular_files(self):
        with patch.object(kernel, 'MAX_FILE', 1), self.assertRaises(ValueError): self.snapshot()
        self.snapshot()
        with self.assertRaises(FileExistsError): self.snapshot()
        self.receipt.unlink()
        self.receipt.symlink_to(self.tree / 'vmlinuz')
        with self.assertRaises(ValueError): self.verify()

    def test_missing_multiple_or_symlinked_authoritative_kernel_is_rejected(self):
        original = copy.deepcopy(self.rpms)
        for name in ('kernel-core', 'kernel-modules-core'):
            self.rpms = copy.deepcopy(original); del self.rpms[name]
            with self.subTest(name=name), self.assertRaises(ValueError): self.snapshot()
        self.rpms = copy.deepcopy(original)
        self.rpms['kernel-core'].append(('0:7.2.4-100.fc44', 'x86_64'))
        with self.assertRaises(ValueError): self.snapshot()
        self.rpms = original
        (self.tree / 'vmlinuz').unlink()
        (self.tree / 'vmlinuz').symlink_to(self.root / 'elsewhere')
        with self.assertRaises(ValueError): self.snapshot()


if __name__ == '__main__':
    unittest.main()
