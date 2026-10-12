#!/usr/bin/env python3
"""Exercise authenticated, bounded kernel replacement with no package mutations."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('kernel_generic', ROOT / 'files/scripts/kernel-generic-security.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
POLICY = json.loads((ROOT / 'files/security/kernel-generic.json').read_text())
OLD = ('0:7.2.5-200.fc44', 'x86_64')
NEW = ('0:7.2.9-201.fc44', 'x86_64')


class Transaction:
    def __init__(self, directory, development=True, camera=True, installed=False, zfs=False):
        self.directory = Path(directory)
        self.calls = []
        self.downloads = []
        self.policy = copy.deepcopy(POLICY)
        self.key = self.directory / 'fedora-44.pub'
        self.key.write_bytes(b'fixture signing key')
        self.policy['keySHA256'] = mod.digest(self.key)
        for entry in self.policy['packages']:
            entry['sha256'] = hashlib.sha256(entry['name'].encode()).hexdigest()
        self.inventory = {name: [NEW if installed else OLD] for name in mod.RUNTIME}
        self.inventory.update({'bootc': [('0:1.13.0-1.fc44', 'x86_64')],
                               'podman': [('0:6.4.1-1.fc44', 'x86_64')]})
        if development:
            self.inventory['kernel-devel-matched'] = [NEW if installed else OLD]
            if installed:
                self.inventory['kernel-devel'] = [NEW]
        if camera:
            for name in mod.CAMERA:
                self.inventory[name] = [('0:0.15.4-1.fc44', 'x86_64')]
        self.modules = self.directory / 'modules'
        current = self.modules / mod.RELEASE
        current.mkdir(parents=True)
        (current / 'vmlinuz').write_bytes(b'fixture kernel')
        if not installed:
            stale = self.modules / '7.2.5-200.fc44.x86_64'
            stale.mkdir()
            (stale / 'initramfs.img').write_bytes(b'generated old initramfs')
        if zfs:
            for name in mod.ZFS:
                self.inventory[name] = [('0:2.4.4-1.fc44', 'noarch' if name == 'python3-pyzfs' else 'x86_64')]
            for name in ('libnvpair3', 'libuutil3', 'libzfs7', 'libzpool7'):
                self.inventory[name] = [('0:2.4.4-1.fc44', 'x86_64')]
            tree = self.modules / (mod.RELEASE if installed else '7.2.5-200.fc44.x86_64') / 'extra/zfs'
            tree.mkdir(parents=True)
            for name in ('spl.ko', 'zfs.ko'):
                (tree / name).write_bytes(b'owned ZFS module')
        self.signature = 'Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: ' + self.policy['keyFingerprint'].lower() + ': OK'
        self.metadata_override = None
        self.after_install = None
        self.after_remove = None
        self.failure = False
        self.fedora = '44'
        self.compare = '-1'
        self.owner_override = None
        self.stale_owners = {}
        self.stale_probe_failure = None

    def download(self, url, path, runner):
        self.downloads.append(url)
        entry = next(e for e in self.policy['packages'] if e['url'] == url)
        path.write_bytes(entry['name'].encode())

    def run(self, args):
        self.calls.append(args)
        if args == ['rpm', '--eval', '%{fedora}']:
            return self.fedora
        if args[:2] == ['rpm', '--eval']:
            return self.compare
        if args[0] == 'rpmkeys' and '--checksig' in args:
            return self.signature
        if args[:2] == ['rpm', '-qp']:
            entry = next(e for e in self.policy['packages'] if Path(args[-1]).name == e['file'])
            return self.metadata_override or '\t'.join((entry['name'], NEW[0], NEW[1]))
        if args[:2] == ['rpm', '-qf']:
            if args[3] == '%{NAME}\n':
                path = args[-1]
                if self.stale_probe_failure:
                    raise self.stale_probe_failure
                if path in self.stale_owners:
                    return self.stale_owners[path]
                raise subprocess.CalledProcessError(1, args, output=f'file {path} is not owned by any package')
            release = Path(args[-1]).parent.name
            version, arch = release.rsplit('.', 1)
            return self.owner_override or '\t'.join(('kernel-core', '0:' + version, arch))
        if args[0] == 'depmod':
            (self.modules / mod.RELEASE / 'modules.dep').write_text('')
        if args[0] == 'dnf5':
            if self.failure:
                raise subprocess.CalledProcessError(1, args)
            if 'remove' in args:
                for item in args[args.index('--no-autoremove') + 1:]:
                    if item in mod.CAMERA + mod.ZFS:
                        self.inventory.pop(item, None)
                        if item == 'kmod-zfs':
                            for file in self.modules.glob('*/extra/zfs/*.ko'):
                                file.unlink()
                    else:
                        for name in mod.RUNTIME + mod.DEVELOPMENT:
                            if item.startswith(name + '-'):
                                self.inventory[name] = [v for v in self.inventory.get(name, [])
                                                        if item != f'{name}-{v[0]}.{v[1]}']
                if self.after_remove:
                    self.after_remove(self.inventory)
            if 'install' in args:
                for file in args[args.index('install') + 1:]:
                    name = next(e['name'] for e in self.policy['packages'] if e['file'] == Path(file).name)
                    # Kernel packages are install-only; matched-devel upgrades.
                    self.inventory[name] = ([*self.inventory.get(name, []), *([] if NEW in self.inventory.get(name, []) else [NEW])]
                                            if name != 'kernel-devel-matched' else [NEW])
                if self.after_install:
                    self.after_install(self.inventory)
        return ''

    def execute(self, profile='bluefin-dx-generic'):
        with patch.object(mod.rpm, 'inventory', side_effect=lambda runner: copy.deepcopy(self.inventory)):
            mod.remediate(self.policy, self.key, profile, self.run, self.download, self.modules)


class GenericKernel(unittest.TestCase):
    def test_source_lock_is_exact_and_requires_every_authenticated_payload(self):
        policy = copy.deepcopy(POLICY)
        for entry in policy['packages']:
            entry['sha256'] = 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            path.write_text(json.dumps(policy))
            self.assertEqual(mod.load_policy(path)['release'], mod.RELEASE)
            for field, value in [('schema', True), ('fedora', 45), ('release', '7.2.9-200.fc44.x86_64')]:
                changed = copy.deepcopy(policy)
                changed[field] = value
                path.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    mod.load_policy(path)
            for field, value in [('sha256', None), ('url', 'https://example.com/kernel.rpm'),
                                 ('name', 'kernel-debug'), ('file', '../kernel.rpm')]:
                changed = copy.deepcopy(policy)
                changed['packages'][0][field] = value
                path.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    mod.load_policy(path)

    def test_complete_transaction_preserves_development_and_container_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.execute()
            self.assertEqual(len(transaction.downloads), 7)
            self.assertEqual(transaction.inventory['kernel-devel-matched'], [NEW])
            self.assertEqual(transaction.inventory['podman'], [('0:6.4.1-1.fc44', 'x86_64')])
            self.assertFalse(any(n in transaction.inventory for n in mod.CAMERA))
            self.assertEqual([p.name for p in transaction.modules.iterdir()], [mod.RELEASE])
            for command in transaction.calls:
                self.assertNotIn('--allowerasing', command)
                self.assertNotIn('--nodeps', command)
                self.assertFalse(any('enable-repo' in arg for arg in command))
                if command[0] == 'dnf5':
                    self.assertIn('--disable-repo=*', command)
                    if 'remove' in command:
                        self.assertIn('--no-autoremove', command)
                    if 'install' in command:
                        self.assertIn('--setopt=localpkg_gpgcheck=1', command)

    def test_development_absent_remains_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, development=False)
            transaction.execute(profile='bluefin-generic')
            self.assertEqual(len(transaction.downloads), 5)
            self.assertFalse(any(n in transaction.inventory for n in mod.DEVELOPMENT))

    def test_authorized_zfs_cleanup_preserves_shared_libraries_and_development(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, zfs=True)
            transaction.execute()
            self.assertFalse(any(name in transaction.inventory for name in mod.ZFS))
            self.assertFalse(list(transaction.modules.glob('*/extra/zfs/*.ko')))
            for name in ('libnvpair3', 'libuutil3', 'libzfs7', 'libzpool7'):
                self.assertEqual(transaction.inventory[name], [('0:2.4.4-1.fc44', 'x86_64')])
            self.assertEqual(transaction.inventory['kernel-devel-matched'], [NEW])
            first = next(i for i, command in enumerate(transaction.calls) if command[0] == 'dnf5')
            self.assertEqual(sum('--checksig' in command for command in transaction.calls[:first]), 7)
            cleanup = transaction.calls[first]
            self.assertTrue(set(mod.ZFS).issubset(cleanup))
            self.assertIn('--disable-repo=*', cleanup)
            self.assertIn('--no-autoremove', cleanup)
            count = len(transaction.downloads)
            operations = sum(command[0] == 'dnf5' for command in transaction.calls)
            transaction.execute()
            self.assertEqual(len(transaction.downloads), count)
            self.assertEqual(sum(command[0] == 'dnf5' for command in transaction.calls), operations)

    def test_current_kernel_with_zfs_is_not_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, installed=True, camera=False, zfs=True)
            transaction.execute()
            self.assertEqual(len(transaction.downloads), 7)
            self.assertFalse(any(name in transaction.inventory for name in mod.ZFS))

    def test_authentication_failure_preserves_installed_zfs(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, zfs=True)
            transaction.signature = 'Header signature: BAD'
            with self.assertRaisesRegex(ValueError, 'signature'):
                transaction.execute()
            self.assertTrue(all(name in transaction.inventory for name in mod.ZFS))
            self.assertTrue(list(transaction.modules.glob('*/extra/zfs/*.ko')))
            self.assertFalse(any(command[0] == 'dnf5' for command in transaction.calls))

    def test_zfs_cleanup_cannot_remove_a_shared_library_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, zfs=True)
            transaction.after_remove = lambda inventory: inventory.pop('libzfs7')
            with self.assertRaisesRegex(ValueError, 'unrelated package: libzfs7'):
                transaction.execute()

    def test_zfs_reintroduction_or_replacement_is_forbidden(self):
        for stage in ('after_remove', 'after_install'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory, zfs=True)
                setattr(transaction, stage, lambda inventory: inventory.update({'kmod-zfs': [NEW]}))
                with self.assertRaisesRegex(ValueError, 'ZFS transition must remove'):
                    transaction.execute()

    def test_exact_current_kernel_without_camera_needs_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, camera=False, installed=True)
            transaction.key.unlink()
            transaction.execute()
            self.assertFalse(transaction.downloads)
            self.assertFalse(any(c[0] == 'dnf5' for c in transaction.calls))

    def test_next_profile_and_wrong_fedora_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            with self.assertRaisesRegex(ValueError, 'explicit generic profile'):
                transaction.execute(profile='bluefin-next')
            transaction.fedora = '45'
            with self.assertRaisesRegex(ValueError, 'Fedora 44'):
                transaction.execute()
            self.assertFalse(transaction.downloads)

    def test_installed_wrong_architecture_or_missing_kernel_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.inventory['kernel-core'] = [(OLD[0], 'aarch64')]
            with self.assertRaisesRegex(ValueError, 'architecture/release'):
                transaction.execute()
            transaction.inventory.pop('kernel-core')
            with self.assertRaisesRegex(ValueError, 'missing a required'):
                transaction.execute()

    def test_newer_installed_kernel_cannot_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.compare = '1'
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                transaction.execute()
            self.assertFalse(transaction.downloads)

    def test_signing_key_digest_checked_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.key.write_bytes(b'wrong key')
            with self.assertRaisesRegex(ValueError, 'key digest mismatch'):
                transaction.execute()
            self.assertFalse(transaction.downloads)

    def test_old_module_directory_requires_installed_kernel_core_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.owner_override = 'unrelated-package\t' + OLD[0] + '\tx86_64'
            with self.assertRaisesRegex(ValueError, 'ownership is not established'):
                transaction.execute()
            self.assertFalse(transaction.downloads)

    def test_package_hash_failure_never_mutates_image(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.policy['packages'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'RPM digest mismatch'):
                transaction.execute()
            self.assertFalse(any(c[0] == 'dnf5' for c in transaction.calls))

    def test_unsigned_wrong_key_and_bad_signature_never_mutate_image(self):
        for signature in ('Header SHA256 digest: OK', 'Header signature, key fingerprint: ' + '0' * 40 + ': OK',
                          'Header signature: NOT OK', 'Header signature: NOKEY'):
            with self.subTest(signature=signature), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory)
                transaction.signature = signature
                with self.assertRaisesRegex(ValueError, 'signature'):
                    transaction.execute()
                self.assertFalse(any(c[0] == 'dnf5' for c in transaction.calls))

    def test_metadata_rejects_wrong_name_arch_epoch_and_release(self):
        for metadata in ('kernel-debug\t' + NEW[0] + '\tx86_64', 'kernel\t' + NEW[0] + '\taarch64',
                         'kernel\t1:7.2.9-201.fc44\tx86_64', 'kernel\t0:7.2.9-200.fc44\tx86_64'):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory)
                transaction.metadata_override = metadata
                with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
                    transaction.execute()
                self.assertFalse(any(c[0] == 'dnf5' for c in transaction.calls))

    def test_all_payloads_authenticated_before_camera_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.policy['packages'][-1]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'RPM digest mismatch'):
                transaction.execute()
            self.assertFalse(any(c[0] == 'dnf5' for c in transaction.calls))
            self.assertTrue(all(n in transaction.inventory for n in mod.CAMERA))

    def test_unrelated_removal_or_boot_stack_change_fails_build(self):
        for name in ('podman', 'bootc'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory)
                transaction.after_remove = lambda inventory: inventory.pop(name)
                with self.assertRaisesRegex(ValueError, 'unrelated package'):
                    transaction.execute()

    def test_unrelated_dependency_addition_fails_build(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.after_install = lambda inventory: inventory.update({'unreviewed': [OLD]})
            with self.assertRaisesRegex(ValueError, 'unrelated package'):
                transaction.execute()

    def test_incomplete_install_does_not_remove_old_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.after_install = lambda inventory: inventory.pop('kernel-modules-extra')
            with self.assertRaisesRegex(ValueError, 'not installed completely'):
                transaction.execute()
            self.assertTrue(any(v == OLD for v in transaction.inventory['kernel-core']))
            self.assertTrue((transaction.modules / '7.2.5-200.fc44.x86_64').exists())

    def test_failed_transaction_retains_old_module_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.failure = True
            with self.assertRaises(subprocess.CalledProcessError):
                transaction.execute()
            self.assertTrue((transaction.modules / '7.2.5-200.fc44.x86_64').exists())

    def test_unknown_or_symlinked_stale_module_directory_rejected(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory)
                unknown = transaction.modules / 'unreviewed'
                unknown.symlink_to(transaction.directory) if symlink else unknown.mkdir()
                with self.assertRaisesRegex(ValueError, 'Unrecognized stale'):
                    transaction.execute()
                self.assertTrue(unknown.exists())

    def test_old_development_kernel_removed_after_new_install(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.inventory['kernel-devel'] = [OLD]
            transaction.execute()
            self.assertEqual(transaction.inventory['kernel-devel'], [NEW])

    def test_preserved_foreign_package_file_prevents_any_tree_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            foreign = transaction.modules / '7.2.5-200.fc44.x86_64' / 'modules.dep'
            foreign.write_text('owned by an unrelated installed package')
            transaction.stale_owners[str(foreign)] = 'podman'
            earlier = transaction.modules / '7.2.4-200.fc44.x86_64'
            earlier.mkdir()
            (earlier / 'modules.dep').write_text('generated artifact')
            for name in mod.RUNTIME:
                transaction.inventory[name].append(('0:7.2.4-200.fc44', 'x86_64'))
            with self.assertRaisesRegex(ValueError, 'Still installed package owns'):
                transaction.execute()
            self.assertEqual(transaction.inventory['podman'], [('0:6.4.1-1.fc44', 'x86_64')])
            self.assertTrue(foreign.exists())
            self.assertTrue(earlier.exists())

    def test_unowned_manual_module_is_not_a_generated_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            manual = transaction.modules / '7.2.5-200.fc44.x86_64' / 'manual.ko'
            manual.write_bytes(b'manual module')
            with self.assertRaisesRegex(ValueError, 'Unreviewed unowned file'):
                transaction.execute()
            self.assertTrue(manual.exists())

    def test_ownership_database_error_is_not_treated_as_unowned(self):
        for code, output in ((2, 'RPM database error'), (1, 'permission denied')):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                transaction = Transaction(directory)
                transaction.stale_probe_failure = subprocess.CalledProcessError(code, ['rpm'], output=output)
                with self.assertRaisesRegex(ValueError, 'Cannot establish'):
                    transaction.execute()
                self.assertTrue((transaction.modules / '7.2.5-200.fc44.x86_64').exists())

    def test_stale_descendant_symlink_cannot_escape_deletion_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            outside = transaction.directory / 'outside'
            outside.mkdir()
            (outside / 'keep').write_text('preserve')
            link = transaction.modules / '7.2.5-200.fc44.x86_64' / 'escape'
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'Symlink in stale'):
                transaction.execute()
            self.assertTrue((outside / 'keep').exists())
            self.assertTrue(link.is_symlink())

    def test_current_module_directory_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory, camera=False, installed=True)
            current = transaction.modules / mod.RELEASE
            destination = transaction.directory / 'actual-current'
            current.rename(destination)
            current.symlink_to(destination)
            with self.assertRaisesRegex(ValueError, 'no authoritative module directory'):
                transaction.execute()
            self.assertTrue((destination / 'vmlinuz').exists())

    def test_final_stale_removal_cannot_add_a_foreign_package(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction = Transaction(directory)
            transaction.after_remove = lambda inventory: inventory.update({'foreign': [OLD]}) if NEW in inventory['kernel-core'] else None
            with self.assertRaisesRegex(ValueError, 'unrelated package: foreign'):
                transaction.execute()
            self.assertTrue((transaction.modules / '7.2.5-200.fc44.x86_64').exists())


if __name__ == '__main__':
    unittest.main()
