"""Hermetic approval, path, privilege, publication and rollback checks."""
import contextlib
import grp
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'files/system/usr/libexec/finite/password-manager-setup'
LOADER = importlib.machinery.SourceFileLoader('password_manager_setup', str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
setup = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = self.base / 'store'
        self.store.mkdir()
        self.state = self.base / 'state/1password'
        self.package = self.store / ('a' * 32 + '-1password-wrapped')
        self.helper_root = self.store / ('b' * 32 + '-1password')
        self.wrapper_root = self.store / ('c' * 32 + '-browser-security-wrapper')
        self.generation = self.store / ('d' * 32 + '-home-manager-generation')
        self.helper = self.helper_root / 'share/1password/1Password-BrowserSupport'
        self.wrapper = self.wrapper_root / 'bin/1Password-BrowserSupport'
        self.helper.parent.mkdir(parents=True)
        self.helper.write_bytes(b'\x7fELF reviewed vendor helper\n')
        self.helper.chmod(0o555)
        self.package.mkdir()
        (self.package / 'share').symlink_to(self.helper_root / 'share')
        self.wrapper.parent.mkdir(parents=True)
        self.selected_target = str(self.package / 'share/1password/1Password-BrowserSupport')
        self.wrapper.write_bytes(b'\x7fELF static security wrapper\0' + self.selected_target.encode() + b'\0')
        self.wrapper.chmod(0o555)
        self.generation.mkdir()
        self.requirement_path = self.generation / 'foundation-password-managers.json'
        self.value = {
            'schema': 1, 'manager': '1password', 'package': str(self.package),
            'helper': str(self.helper), 'helperSha256': self.digest(self.helper),
            'wrapper': str(self.wrapper), 'wrapperSha256': self.digest(self.wrapper),
            'hostPath': str(self.state / self.wrapper_root.name / '1Password-BrowserSupport'),
        }
        self.write_requirement(self.value)
        self.calls = []
        self.fail = None
        self.extra_roots = ''
        self.referrers = ''
        self.group_exists = True
        self.group_gid = os.getgid() or 1000
        # File ownership tests use the caller's real group without privileges.
        # Production-boundary tests below explicitly restore the real threshold.
        threshold = patch.object(setup, 'MIN_GID', min(1000, self.group_gid - 1))
        threshold.start()
        self.addCleanup(threshold.stop)
        self.installer = setup.Installer(store_root=self.store, state_root=self.state,
            state_anchor=self.base, trusted_uid=os.getuid(), effective_uid=lambda: 0,
            run=self.run_command, group_lookup=self.group_lookup)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_requirement(self, value):
        self.requirement_path.write_text(json.dumps(value))

    def read_requirement(self):
        return self.installer.requirement(str(self.requirement_path))

    def group_lookup(self, name):
        self.assertEqual(name, 'onepassword')
        if not self.group_exists:
            raise KeyError(name)
        return types.SimpleNamespace(gr_gid=self.group_gid)

    def run_command(self, command, **kwargs):
        self.calls.append(command)
        self.assertEqual(kwargs['env'], {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': '/root', 'LANG': 'C', 'LC_ALL': 'C'})
        self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['timeout'], 60)
        self.assertIn(command[0], (setup.NIX_STORE, setup.RESTORECON, setup.GROUPADD))
        if self.fail and self.fail(command):
            raise subprocess.CalledProcessError(9, command)
        output = ''
        if command[0] == setup.GROUPADD:
            self.assertEqual(command, [setup.GROUPADD, 'onepassword'])
            self.group_exists = True
        elif '--add-root' in command:
            self.assertEqual(command[3:5], ['--indirect', '--realise'])
            Path(command[2]).symlink_to(command[-1])
            output = command[-1] + '\n'
        elif '--referrers-closure' in command:
            output = self.referrers
        elif '--roots' in command:
            roots = self.state / '.roots' / self.wrapper_root.name
            output = ''.join(str(roots / key) + ' -> ' + str(source) + '\n'
                for key, source in self.installer.root_sources(self.value).items()
                if str(source) == command[-1]) + self.extra_roots
        return subprocess.CompletedProcess(command, 0, output)

    def install(self, value=None, **changes):
        value = value or self.read_requirement()
        approvals = {'approve_package': value['package'],
                     'approve_helper_sha256': value['helperSha256'],
                     'approve_wrapper_sha256': value['wrapperSha256']}
        approvals.update(changes)
        return self.installer.install(value, **approvals)

    def test_install_is_explicit_idempotent_and_never_executes_artifacts(self):
        requirement = self.read_requirement()
        self.assertTrue(self.install(requirement)['installed'])
        destination = Path(requirement['hostPath'])
        self.assertEqual(destination.read_bytes(), self.wrapper.read_bytes())
        info = destination.stat()
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o2755)
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(info.st_gid, self.group_gid)
        self.assertFalse(info.st_mode & stat.S_ISUID)
        self.assertTrue(self.installer.status(requirement)['installed'])
        before = list(self.calls)
        self.assertTrue(self.install(requirement)['installed'])
        self.assertEqual(self.calls, before)
        self.assertEqual(sum('--add-root' in command for command in self.calls), 3)
        self.assertEqual(self.calls[-1], [setup.RESTORECON, '-RF', str(destination.parent)])

    def test_read_only_inspect_and_missing_status_do_not_create_state(self):
        requirement = self.read_requirement()
        with self.installer.sources(requirement):
            pass
        self.assertFalse(self.installer.status(requirement)['installed'])
        self.assertFalse(self.state.exists())
        self.assertEqual(self.calls, [])

    def test_top_level_store_json_output_is_a_valid_requirement(self):
        path = self.store / ('f' * 32 + '-foundation-password-managers.json')
        path.write_text(json.dumps(self.value))
        path.chmod(0o444)
        requirement = self.installer.requirement(str(path))
        self.assertEqual(requirement, self.value)
        with self.installer.sources(requirement):
            pass
        self.assertFalse(self.state.exists())
        self.assertEqual(self.calls, [])

    def test_cli_requires_all_literal_approvals(self):
        for omitted in ('--approve-package', '--approve-helper-sha256', '--approve-wrapper-sha256'):
            args = ['install', '--requirement', str(self.requirement_path)]
            for flag, value in [('--approve-package', str(self.package)),
                                ('--approve-helper-sha256', self.value['helperSha256']),
                                ('--approve-wrapper-sha256', self.value['wrapperSha256'])]:
                if flag != omitted:
                    args.extend((flag, value))
            with self.subTest(omitted=omitted), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                setup.main(args)
            self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.state.exists())

    def test_nonroot_or_mismatched_approvals_cannot_install(self):
        for changes in ({'approve_package': str(self.helper_root)},
                        {'approve_helper_sha256': '0' * 64},
                        {'approve_wrapper_sha256': '0' * 64}):
            with self.subTest(changes=changes), self.assertRaises(setup.SetupError):
                self.install(**changes)
            self.assertFalse(self.state.exists())
        self.installer.effective_uid = lambda: 1000
        with self.assertRaisesRegex(setup.SetupError, 'Administrator'):
            self.install()
        self.assertEqual(self.calls, [])

    def test_requirement_rejects_hostile_json_and_noncanonical_paths(self):
        cases = [{'schema': True}, {'schema': 2}, {'manager': 'arbitrary'}, {'extra': 'field'},
                 {'helperSha256': 'bad'}, {'wrapperSha256': 42},
                 {'helper': str(self.base / 'external')},
                 {'package': str(self.store) + '/a/../' + self.package.name},
                 {'hostPath': str(self.base / 'escape')},
                 {'wrapper': str(self.wrapper.parent / 'different-command')}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.write_requirement({**self.value, **changes})
                with self.assertRaises((setup.SetupError, OSError)):
                    self.read_requirement()
        self.requirement_path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(setup.SetupError, 'Duplicate'):
            self.read_requirement()
        self.requirement_path.write_text('x' * (setup.MAX_JSON + 1))
        with self.assertRaisesRegex(setup.SetupError, 'size limit'):
            self.read_requirement()
        self.assertFalse(self.state.exists())

    def test_requires_immutable_requirement_and_no_writable_artifact_parent(self):
        self.requirement_path.chmod(0o666)
        with self.assertRaisesRegex(setup.SetupError, 'writable'):
            self.read_requirement()
        self.requirement_path.chmod(0o644)
        self.helper.parent.chmod(0o775)
        with self.assertRaisesRegex(setup.SetupError, 'writable'):
            self.read_requirement()
        self.helper.parent.chmod(0o755)
        self.wrapper.chmod(0o777)
        with self.assertRaisesRegex(setup.SetupError, 'writable'):
            self.read_requirement()

    def test_wrong_owner_or_symlinked_requirement_is_rejected(self):
        with patch.object(self.installer, 'uid', os.getuid() + 1):
            with self.assertRaisesRegex(setup.SetupError, 'ownership'):
                self.read_requirement()
        alternate = self.requirement_path.with_name('actual.json')
        self.requirement_path.rename(alternate)
        self.requirement_path.symlink_to(alternate)
        with self.assertRaisesRegex(setup.SetupError, 'file type'):
            self.read_requirement()

    def test_selected_package_symlink_must_resolve_to_approved_store_helper(self):
        self.assertEqual(self.read_requirement()['helper'], str(self.helper))
        (self.package / 'share').unlink()
        (self.package / 'share').symlink_to(self.base / 'mutable')
        with self.assertRaisesRegex(setup.SetupError, 'escapes'):
            self.read_requirement()

    def test_missing_helper_and_artifact_leaf_symlinks_are_rejected(self):
        saved = self.helper.read_bytes()
        self.helper.unlink()
        with self.assertRaises(FileNotFoundError):
            self.read_requirement()
        self.helper.write_bytes(saved)
        self.helper.chmod(0o555)
        self.wrapper.unlink()
        self.wrapper.symlink_to(self.helper)
        with self.assertRaisesRegex(setup.SetupError, 'file type'):
            self.read_requirement()

    def test_helper_hash_wrapper_hash_and_fixed_target_are_required(self):
        for key in ('helperSha256', 'wrapperSha256'):
            with self.subTest(key=key):
                value = {**self.value, key: '0' * 64}
                self.write_requirement(value)
                with self.assertRaisesRegex(setup.SetupError, 'hash differs'):
                    self.install()
                self.assertFalse(self.state.exists())
        self.wrapper.chmod(0o755)
        self.wrapper.write_bytes(b'\x7fELF points to /arbitrary/command\0')
        self.value['wrapperSha256'] = self.digest(self.wrapper)
        self.write_requirement(self.value)
        with self.assertRaisesRegex(setup.SetupError, 'fixed helper target'):
            self.install()

    def test_raw_helper_target_is_also_valid_and_shell_wrappers_are_not(self):
        self.wrapper.chmod(0o755)
        self.wrapper.write_bytes(b'\x7fELF native wrapper\0' + str(self.helper).encode() + b'\0')
        self.value['wrapperSha256'] = self.digest(self.wrapper)
        self.write_requirement(self.value)
        with self.installer.sources(self.read_requirement()):
            pass
        self.wrapper.write_text('#!/bin/sh\nexec /arbitrary/command\n')
        self.value['wrapperSha256'] = self.digest(self.wrapper)
        self.write_requirement(self.value)
        with self.assertRaisesRegex(setup.SetupError, 'native ELF'):
            self.install()

    def test_failed_root_creation_or_labeling_never_leaves_a_published_install(self):
        for failure in ('roots', 'label'):
            with self.subTest(failure=failure):
                self.fail = lambda command: (failure == 'label' and command[0] == setup.RESTORECON) or (
                    failure == 'roots' and '--add-root' in command and command[2].endswith('/helper'))
                with self.assertRaises(subprocess.CalledProcessError):
                    self.install()
                self.assertFalse(Path(self.value['hostPath']).parent.exists())
                self.assertFalse((self.state / '.roots' / self.wrapper_root.name).exists())
                self.assertEqual(list(self.state.glob('.install-*')), [])

    def test_existing_unreceipted_root_is_preserved(self):
        roots = self.state / '.roots' / self.wrapper_root.name
        self.installer.directory(roots)
        root = roots / 'package'
        root.write_text('unrecognized administrator file')
        with self.assertRaisesRegex(setup.SetupError, 'Unreceipted'):
            self.install()
        self.assertEqual(root.read_text(), 'unrecognized administrator file')

    def test_mutable_or_symlinked_state_parents_are_rejected(self):
        parent = self.state.parent
        parent.mkdir()
        parent.chmod(0o777)
        with self.assertRaisesRegex(setup.SetupError, 'writable'):
            self.install()
        parent.chmod(0o755)
        parent.rmdir()
        other = self.base / 'other'
        other.mkdir()
        parent.symlink_to(other)
        with self.assertRaisesRegex(setup.SetupError, 'file type'):
            self.install()

    def test_artifact_change_during_root_creation_aborts_publication(self):
        normal = self.run_command
        def change(command, **kwargs):
            result = normal(command, **kwargs)
            if '--add-root' in command and command[2].endswith('/wrapper'):
                self.helper.chmod(0o755)
                self.helper.write_bytes(b'\x7fELF changed after approval')
            return result
        self.installer.run = change
        with self.assertRaisesRegex(setup.SetupError, 'content changed'):
            self.install()
        self.assertFalse(Path(self.value['hostPath']).parent.exists())

    def test_status_checks_receipt_hash_permissions_and_roots(self):
        self.install()
        destination = Path(self.value['hostPath'])
        destination.chmod(0o755)
        with self.assertRaisesRegex(setup.SetupError, 'permissions'):
            self.installer.status(self.value)
        destination.chmod(0o2755)
        receipt = destination.parent / 'receipt.json'
        receipt.write_text('{}')
        with self.assertRaisesRegex(setup.SetupError, 'receipt'):
            self.installer.status(self.value)
        receipt.write_text(json.dumps(self.value))
        root = self.state / '.roots' / self.wrapper_root.name / 'helper'
        root.unlink()
        with self.assertRaisesRegex(setup.SetupError, 'closure root'):
            self.installer.status(self.value)

    def test_existing_identity_group_is_used_and_missing_group_created_without_members(self):
        self.group_exists = False
        self.install()
        self.assertEqual(self.calls.count([setup.GROUPADD, 'onepassword']), 1)
        self.assertFalse(any('usermod' in command or 'gpasswd' in command for command in self.calls))

    def test_identity_group_requires_gid_larger_than_1000(self):
        with patch.object(setup, 'MIN_GID', 1000):
            for gid in (0, 946, 1000):
                with self.subTest(gid=gid):
                    self.group_gid = gid
                    with self.assertRaisesRegex(setup.SetupError, 'larger than 1000'):
                        self.installer.group()
            self.group_gid = 1001
            self.assertEqual(self.installer.group(), 1001)
        self.assertEqual(self.calls, [])

    def test_new_identity_group_is_validated_after_creation(self):
        self.group_exists = False
        self.group_gid = 946
        with patch.object(setup, 'MIN_GID', 1000):
            with self.assertRaisesRegex(setup.SetupError, 'larger than 1000'):
                self.installer.group()
        self.assertEqual(self.calls, [[setup.GROUPADD, 'onepassword']])
        self.assertFalse(self.state.exists())

    def test_status_and_idempotent_install_reject_invalid_existing_group(self):
        self.install()
        before = list(self.calls)
        with patch.object(setup, 'MIN_GID', 1000):
            for gid in (946, 1000):
                with self.subTest(gid=gid):
                    self.group_gid = gid
                    with self.assertRaisesRegex(setup.SetupError, 'larger than 1000'):
                        self.installer.status(self.value)
                    with self.assertRaisesRegex(setup.SetupError, 'larger than 1000'):
                        self.install()
        self.assertEqual(self.calls, before)

    def test_removal_preserves_external_roots_and_generation_rollback(self):
        self.install()
        destination = Path(self.value['hostPath'])
        self.referrers = str(self.generation) + '\n'
        with self.assertRaisesRegex(setup.SetupError, 'Home Manager generation'):
            self.installer.remove(self.value, approve_wrapper_sha256=self.value['wrapperSha256'])
        self.referrers = ''
        self.extra_roots = '/unrelated/administrator/gc-root -> /nix/store/object\n'
        with self.assertRaisesRegex(setup.SetupError, 'external GC root'):
            self.installer.remove(self.value, approve_wrapper_sha256=self.value['wrapperSha256'])
        self.assertTrue(destination.exists())
        self.extra_roots = ''
        with self.assertRaisesRegex(setup.SetupError, 'literal approval'):
            self.installer.remove(self.value, approve_wrapper_sha256='0' * 64)
        self.assertFalse(self.installer.remove(self.value,
            approve_wrapper_sha256=self.value['wrapperSha256'])['installed'])
        self.assertFalse(destination.exists())
        self.assertFalse(self.installer.status(self.value)['installed'])


if __name__ == '__main__':
    unittest.main()
