"""Reject ambiguous or stale boot inputs before any privileged preparation."""

import importlib.util
import contextlib
import io
import json
import lzma
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/workstation/prepare-boot-trial.py'
SPEC = importlib.util.spec_from_file_location('boot_trial', SOURCE)
TRIAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIAL)
INSPECT_SPEC = importlib.util.spec_from_file_location(
    'inspect_trial', SOURCE.with_name('inspect-boot-trial.py'))
INSPECT = importlib.util.module_from_spec(INSPECT_SPEC)
INSPECT_SPEC.loader.exec_module(INSPECT)
STAGE_SPEC = importlib.util.spec_from_file_location(
    'stage_trial', SOURCE.with_name('stage-boot-trial.py'))
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)
ARM_SPEC = importlib.util.spec_from_file_location(
    'arm_trial', SOURCE.with_name('arm-boot-trial.py'))
ARM = importlib.util.module_from_spec(ARM_SPEC)
ARM_SPEC.loader.exec_module(ARM)
PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    'preflight_trial', SOURCE.with_name('systemd-boot-preflight.py'))
PREFLIGHT = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(PREFLIGHT)
STORAGE_SPEC = importlib.util.spec_from_file_location(
    'storage_trial', SOURCE.with_name('measure-boot-storage.py'))
STORAGE = importlib.util.module_from_spec(STORAGE_SPEC)
STORAGE_SPEC.loader.exec_module(STORAGE)


class StorageTests(unittest.TestCase):
    @unittest.skipUnless(Path('/usr/lib/dracut/skipcpio').exists(), 'dracut skipcpio required')
    def test_measurement_preserves_early_archive_and_main_contents(self):
        import subprocess
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            early_dir, main_dir = root / 'early', root / 'main'
            early_dir.mkdir()
            main_dir.mkdir()
            (early_dir / 'early_cpio').write_text('1\n')
            (main_dir / 'init').write_bytes(b'example-init\n' * 100)
            def archive(directory, name):
                return subprocess.run(['cpio', '-o', '-H', 'newc'], input=name.encode() + b'\n',
                                      cwd=directory, capture_output=True, check=True).stdout
            early = archive(early_dir, 'early_cpio')
            raw = archive(main_dir, 'init')
            image = root / 'initrd'
            image.write_bytes(early + lzma.compress(raw))
            result = STORAGE.measure(image, root / 'work')
            self.assertEqual(result['early_cpio_bytes_preserved'], len(early))
            self.assertEqual(result['main_cpio_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertTrue(result['contents_verified_identical'])
            self.assertEqual(image.read_bytes(), early + lzma.compress(raw))
            self.assertFalse((root / 'work').exists())

    def test_recompression_preserves_cpio_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            raw, compact = Path(temp) / 'raw', Path(temp) / 'compact'
            data = b'070701' + b'cpio-test-bytes' * 1000
            raw.write_bytes(data)
            STORAGE.recompress(raw, compact)
            self.assertEqual(lzma.decompress(compact.read_bytes()), data)
            self.assertLess(compact.stat().st_size, len(data))

    def test_unknown_compression_is_rejected(self):
        with self.assertRaises(ValueError):
            STORAGE.decoder(b'unknown')

    def test_windows_cleanup_preserves_other_efi_files_and_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            state, esp = Path(temp) / 'state', Path(temp) / 'esp'
            state.mkdir()
            windows = esp / 'EFI/Microsoft/Boot'
            windows.mkdir(parents=True)
            (windows / 'bootmgfw.efi').write_bytes(b'windows-file')
            fedora = esp / 'EFI/fedora'
            fedora.mkdir()
            (fedora / 'shimx64.efi').write_bytes(b'keep-shim')

            def read(*args):
                if args[0] == 'lsblk':
                    return json.dumps({'blockdevices': [{'name': 'linux', 'fstype': 'btrfs'}]})
                return ('BootOrder: 0007,0006,0009\n'
                        'Boot0009* Windows Boot Manager HD(...)\\EFI\\Microsoft\\Boot\\bootmgfw.efi\n')

            with (patch.object(STORAGE.PREPARE, 'run', side_effect=read),
                  patch.object(STORAGE.subprocess, 'run') as mutation,
                  patch.object(STORAGE.os, 'sync')):
                result = STORAGE.cleanup_windows(state, esp)
            self.assertFalse((esp / 'EFI/Microsoft').exists())
            self.assertEqual((fedora / 'shimx64.efi').read_bytes(), b'keep-shim')
            self.assertTrue((state / 'windows-efi-before.tar').exists())
            self.assertEqual(result['verified_files'], 1)
            mutation.assert_called_once_with(
                ['efibootmgr', '--bootnum', '0009', '--delete-bootnum'], check=True)

    def test_windows_partition_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            state, esp = Path(temp) / 'state', Path(temp) / 'esp'
            state.mkdir()
            windows = esp / 'EFI/Microsoft'
            windows.mkdir(parents=True)
            with patch.object(STORAGE.PREPARE, 'run', return_value=json.dumps({
                    'blockdevices': [{'name': 'windows', 'fstype': 'ntfs'}]})):
                with self.assertRaises(SystemExit):
                    STORAGE.cleanup_windows(state, esp)
            self.assertTrue(windows.exists())
            self.assertFalse((state / 'windows-efi-before.tar').exists())


class TrialRuntimeTests(unittest.TestCase):
    def evidence(self, **overrides):
        evidence = {
            'loader': 'systemd-boot 259.10', 'secure': '01', 'setup': '00', 'audit': '00',
            'loader_image': r'\EFI\finite-systemd\grubx64.efi',
            'stub': 'systemd-stub 259.10',
            'stub_image': r'\EFI\finite-systemd\finite-trial.efi',
            'entry': 'finite-trial.conf', 'cmdline': ['finite.boot-trial=1'],
            'lockdown': 'none [integrity] confidentiality',
        }
        evidence.update(overrides)
        return PREFLIGHT.trial_blockers(**evidence)

    def test_verifies_matching_enforced_trial(self):
        self.assertEqual(self.evidence(), [])

    def test_audit_mode_is_not_accepted_as_enforcement(self):
        self.assertTrue(self.evidence(audit='01'))

    def test_grub_recovery_boot_is_not_a_trial_success(self):
        self.assertTrue(self.evidence(loader='GRUB 2.12', cmdline=[]))

    def test_other_signed_uki_is_not_trial_success(self):
        self.assertTrue(self.evidence(stub_image=r'\EFI\Linux\other.efi'))

    def test_no_lockdown_is_not_success(self):
        self.assertTrue(self.evidence(lockdown='[none] integrity confidentiality'))


class ArmingTests(unittest.TestCase):
    def enrollment_check(self, enrolled, export_fails=False):
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / 'expected.der'
            certificate.write_bytes(b'exact-certificate')

            def export(*args, **kwargs):
                if export_fails:
                    raise ARM.subprocess.CalledProcessError(1, args[0])
                (Path(kwargs['cwd']) / 'MOK-0001.der').write_bytes(
                    b'exact-certificate' if enrolled else b'other-certificate')

            with (patch.object(ARM.subprocess, 'run', side_effect=export),
                  contextlib.redirect_stdout(io.StringIO())):
                if export_fails:
                    with self.assertRaises(ARM.subprocess.CalledProcessError):
                        ARM.verify_enrollment(certificate)
                elif not enrolled:
                    with self.assertRaises(SystemExit):
                        ARM.verify_enrollment(certificate)
                else:
                    ARM.verify_enrollment(certificate)

    def test_enrollment_matches_exact_der_bytes(self):
        self.enrollment_check(enrolled=True)

    def test_another_certificate_does_not_satisfy_enrollment(self):
        self.enrollment_check(enrolled=False)

    def test_export_failure_does_not_satisfy_enrollment(self):
        self.enrollment_check(enrolled=True, export_fails=True)

    def exercise(self, pending=False, changed_order=False):
        with tempfile.TemporaryDirectory() as temp:
            original = '0007,0006'
            order = '0006,0007' if changed_order else original
            listing = (f'BootOrder: {order}\n'
                       'Boot0002* Finite systemd-boot trial\tHD(1,GPT,expected)'
                       '\\EFI\\finite-systemd\\shimx64.efi\n')
            if pending:
                listing += 'BootNext: 0006\n'
            listings = iter([listing, listing + 'BootNext: 0002\n'])
            journal = {'boot_order_before': original, 'firmware_entry': '0002'}
            with (patch.object(ARM.PREPARE, 'STATE', Path(temp)),
                  patch.object(ARM.STAGE.INSPECT, 'main'),
                  patch.object(ARM, 'check_staged', return_value=(
                      {'esp_partuuid': 'expected'}, journal)),
                  patch.object(ARM.PREPARE, 'run', side_effect=lambda *args: next(listings)),
                  patch.object(ARM.os, 'geteuid', return_value=0),
                  patch.object(ARM.os, 'umask'),
                  patch.object(ARM.subprocess, 'run') as mutation,
                  contextlib.redirect_stdout(io.StringIO())):
                if pending or changed_order:
                    with self.assertRaises(SystemExit):
                        ARM.main()
                    mutation.assert_not_called()
                    self.assertFalse((Path(temp) / 'armed.json').exists())
                else:
                    ARM.main()
                    mutation.assert_called_once_with(['efibootmgr', '--bootnext', '0002'],
                                                     check=True)
                    self.assertTrue((Path(temp) / 'armed.json').exists())

    def test_selects_only_bootnext_after_validation(self):
        self.exercise()

    def test_preserves_existing_pending_boot(self):
        self.exercise(pending=True)

    def test_refuses_unreviewed_boot_order(self):
        self.exercise(changed_order=True)


class StagingTests(unittest.TestCase):
    def exercise(self, conflict=False, firmware_reorders=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, esp = root / 'state', root / 'esp'
            output = state / 'output'
            output.mkdir(parents=True)
            (esp / 'EFI').mkdir(parents=True)
            (state / 'manifest.json').write_text(json.dumps({'esp_partuuid': 'expected'}))
            for name in ('shimx64.efi', 'mmx64.efi', 'grubx64.efi', 'finite-trial.efi', 'MOK.der'):
                (output / name).write_bytes(b'public-test-data')
            if conflict:
                (esp / 'EFI/finite-systemd').mkdir()
            before = 'BootOrder: 0007,0006\nBoot0007* rEFInd\n'
            after_order = '0008,0007,0006' if firmware_reorders else '0007,0006'
            after = (f'BootOrder: {after_order}\nBoot0007* rEFInd\n'
                     'Boot0008* Finite systemd-boot trial\tHD(...)\n')
            listings = iter([before, after, before] if firmware_reorders else [before, after])

            def read(*args):
                if args[0] == 'efibootmgr':
                    return next(listings)
                if args[0] == 'lsblk':
                    return 'expected'
                if args[0] == 'findmnt':
                    return 'vfat' if 'FSTYPE' in args else '/dev/nvme0n1p1'
                raise AssertionError(args)

            with (patch.object(STAGE.PREPARE, 'STATE', state),
                  patch.object(STAGE.PREPARE, 'ESP', esp),
                  patch.object(STAGE.PREPARE, 'run', side_effect=read),
                  patch.object(STAGE.INSPECT, 'main'),
                  patch.object(STAGE.os, 'geteuid', return_value=0),
                  patch.object(STAGE.os, 'umask'), patch.object(STAGE.os, 'sync'),
                  patch.object(STAGE.subprocess, 'check_output', return_value=b'public-test-data'),
                  patch.object(STAGE.subprocess, 'run') as mutation,
                  patch.object(STAGE.shutil, 'disk_usage', return_value=type('Space', (), {'free': 10**9})()),
                  contextlib.redirect_stdout(io.StringIO())):
                if conflict:
                    with self.assertRaises(SystemExit):
                        STAGE.main()
                    mutation.assert_not_called()
                    self.assertFalse((state / 'staging.json').exists())
                    return
                STAGE.main()
                calls = [call.args[0] for call in mutation.call_args_list]
                self.assertIn('--create-only', calls[0])
                self.assertFalse(any('--bootnext' in call for call in calls))
                self.assertEqual(len(calls), 2 if firmware_reorders else 1)
                if firmware_reorders:
                    self.assertEqual(calls[1], ['efibootmgr', '--bootorder', '0007,0006'])
                self.assertEqual((esp / 'EFI/finite-systemd/finite-trial.efi').read_bytes(),
                                 b'public-test-data')
                self.assertFalse((esp / 'EFI/finite-systemd/MOK.key').exists())
                journal = json.loads((state / 'staging.json').read_text())
                self.assertEqual(journal['phase'], 'staged-not-selected')
                self.assertEqual(journal['firmware_entry'], '0008')

    def test_stages_public_files_and_creates_entry_without_selecting_it(self):
        self.exercise()

    def test_restores_order_if_firmware_inserts_create_only_entry(self):
        self.exercise(firmware_reorders=True)

    def test_refuses_existing_trial_directory_before_mutations(self):
        self.exercise(conflict=True)


class InventoryTests(unittest.TestCase):
    def test_gshadow_empty_and_lock_markers_are_not_hashes(self):
        report = INSPECT.gshadow_summary('root:::root\ndaemon:!!::\nbin:*::\n')
        self.assertEqual(report, {'entries': 3, 'password_material_present': False})

    def test_gshadow_locked_hash_still_needs_review(self):
        self.assertTrue(INSPECT.gshadow_summary('group:!$6$example::\n')
                        ['password_material_present'])

    def test_gshadow_malformed_data_fails(self):
        with self.assertRaises(ValueError):
            INSPECT.gshadow_summary('cannot parse this')

    def test_flags_key_material_without_reading_contents(self):
        listing = '\n'.join([
            '-rw------- 1 root root 32 Nov 16 2026 etc/cryptsetup-keys.d/root.key',
            '-rw------- 1 root root 32 Nov 16 2026 etc/ostree/initramfs-root-binding.key',
            '-rw-r--r-- 1 root root 32 Nov 16 2026 etc/pki/tls/certs/public.pem',
            '-rwxr-xr-x 1 root root 32 Nov 16 2026 usr/bin/keyctl',
        ])
        self.assertEqual(INSPECT.sensitive_paths(listing), [
            'etc/cryptsetup-keys.d/root.key', 'etc/ostree/initramfs-root-binding.key'])

    def test_does_not_ignore_bad_inventory_format(self):
        with self.assertRaises(ValueError):
            INSPECT.sensitive_paths('-rw------- malformed')


class EntrySelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.cmdline = 'BOOT_IMAGE=(hd0,gpt7)/linux ostree=/ostree/boot.0/x/0 root=UUID=x rw'

    def entry(self, name='one.conf', options='ostree=/ostree/boot.0/x/0 root=UUID=x rw', extra=''):
        path = self.directory / name
        path.write_text(f'linux /ostree/x/linux\ninitrd /ostree/x/initrd\noptions {options}\n{extra}')
        return path

    def test_matches_running_not_first_entry(self):
        old = self.entry('old.conf', options='ostree=/ostree/boot.0/y/0 root=UUID=x rw')
        current = self.entry()
        selected, _ = TRIAL.select_entry(self.cmdline, [old, current])
        self.assertEqual(selected, current)

    def test_rejects_changed_arguments(self):
        path = self.entry(options='ostree=/ostree/boot.0/x/0 root=UUID=x ro')
        with self.assertRaises(ValueError):
            TRIAL.select_entry(self.cmdline, [path])

    def test_rejects_ambiguous_entries(self):
        with self.assertRaises(ValueError):
            TRIAL.select_entry(self.cmdline, [self.entry(), self.entry('two.conf')])

    def test_rejects_multiple_initrds_instead_of_silently_dropping_one(self):
        with self.assertRaises(ValueError):
            TRIAL.select_entry(self.cmdline, [self.entry(extra='initrd /microcode\n')])

    def test_rejects_no_matching_deployment(self):
        with self.assertRaises(ValueError):
            TRIAL.select_entry(self.cmdline, [])

    def test_rejects_multiple_ostree_targets(self):
        with self.assertRaises(ValueError):
            TRIAL.select_entry(self.cmdline + ' ostree=/other', [self.entry()])


if __name__ == '__main__':
    unittest.main()
