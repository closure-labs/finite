#!/usr/bin/env python3
"""The native installer's disk choice, layout and command contract, without touching disks."""
from importlib.machinery import SourceFileLoader
import importlib.util
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
import dataclasses
from pathlib import Path
import runpy
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/native-installer/finite-native-install'
loader = SourceFileLoader('finite_native_install', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(ROOT / 'files/system/usr/libexec/finite'), *sys.path]):
    loader.exec_module(installer)

GIB = 1024**3
PINS = {'schema': 3, 'bootcSha256': 'b' * 64, 'bootcVersion': '1.17.5', 'payloadDigest': 'sha256:' + 'a' * 64,
        'sourceImgref': 'oci:/usr/lib/finite/installer/payload',
        'targetImgref': 'ghcr.io/closure-labs/finite:finite-native'}


def disk(path='/dev/nvme0n1', by_id='nvme-KIOXIA_512GB_X', size=512 * GIB, **changes):
    values = dict(path=path, by_id=by_id, size=size, model='KIOXIA', removable=False,
                  read_only=False, mounted=False, holds_boot_medium=False)
    values.update(changes)
    return installer.Disk(**values)


class DiskChoice(unittest.TestCase):
    def test_last_moment_disk_and_stable_id_changes_prevent_the_wipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            ids = Path(temporary)
            device = ids / 'device'
            device.touch()
            selected = disk(path=str(device))
            link = ids / selected.by_id
            link.symlink_to(device)
            installer.revalidate_disk(selected, [selected], ids)
            for current in ([], [dataclasses.replace(selected, mounted=True)],
                            [dataclasses.replace(selected, active_holders=True)],
                            [dataclasses.replace(selected, size=selected.size + GIB)]):
                with self.subTest(current=current), self.assertRaises(installer.InstallError):
                    installer.revalidate_disk(selected, current, ids)
            other = ids / 'other'
            other.touch()
            link.unlink()
            link.symlink_to(other)
            with self.assertRaisesRegex(installer.InstallError, 'stable disk ID changed'):
                installer.revalidate_disk(selected, [selected], ids)

    def test_unsafe_disks_are_never_offered(self):
        cases = {'holds the installer boot medium': dict(holds_boot_medium=True),
                 'has mounted filesystems or active swap': dict(mounted=True),
                 'is read-only': dict(read_only=True),
                 'is smaller than 64 GiB': dict(size=63 * GIB),
                 'has no stable /dev/disk/by-id name': dict(by_id=''),
                 'has active device-mapper, RAID or other block-device holders': dict(active_holders=True)}
        for reason, change in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(disk(**change).refusal(), reason)
        self.assertIsNone(disk().refusal())

    def test_typed_disk_id_is_required(self):
        out = []
        with self.assertRaisesRegex(installer.InstallError, 'nothing was changed'):
            installer.choose([disk()], ask=lambda _: 'yes', say=out.append)
        self.assertEqual(installer.choose([disk()], ask=lambda _: 'nvme-KIOXIA_512GB_X', say=out.append), disk())
        self.assertTrue(any('permanently erased' in line for line in out))

    def test_multiple_disks_require_an_explicit_eligible_path(self):
        usb = disk('/dev/sda', 'usb-Live', 32 * GIB, holds_boot_medium=True)
        second = disk('/dev/sdb', 'ata-Second', 1000 * GIB)
        answers = iter(['/dev/sdb', 'ata-Second'])
        self.assertEqual(installer.choose([disk(), usb, second], ask=lambda _: next(answers), say=lambda _: None),
                         second)
        with self.assertRaisesRegex(installer.InstallError, 'No eligible disk'):
            installer.choose([disk(), usb, second], ask=lambda _: '/dev/sda', say=lambda _: None)
        with self.assertRaisesRegex(installer.InstallError, 'No disk is eligible'):
            installer.choose([usb], ask=lambda _: '', say=lambda _: None)


class Layout(unittest.TestCase):
    def test_partition_names_follow_kernel_rules(self):
        self.assertEqual(installer.partition('/dev/nvme0n1', 3), '/dev/nvme0n1p3')
        self.assertEqual(installer.partition('/dev/mmcblk0', 1), '/dev/mmcblk0p1')
        self.assertEqual(installer.partition('/dev/sda', 2), '/dev/sda2')
        self.assertEqual(installer.partition('/dev/vdb', 1), '/dev/vdb1')

    def test_gpt_layout_matches_the_vm_qualified_xbootldr_install(self):
        layout = installer.layout()
        self.assertIn('size=600MiB,type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B', layout)
        self.assertIn('size=4096MiB,type=BC13C2FF-59E6-4262-A352-B275FD6F7172', layout)
        # The root is the discoverable x86-64 type and takes the rest of the disk.
        self.assertTrue(layout.rstrip().endswith('type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709,name=finite-root'))
        vm = (ROOT / 'scripts/vm-composefs/install-xbootldr.sh').read_text()
        for guid in (installer.ESP_TYPE, installer.XBOOTLDR_TYPE, installer.ROOT_TYPE):
            self.assertIn(guid, vm)


class Plan(unittest.TestCase):
    def argv(self, steps, first):
        matches = [step for step in steps if step.argv[0] == first]
        self.assertEqual(len(matches), 1, first)
        return matches[0]

    def test_bootc_installs_composefs_systemd_boot_without_kernel_arguments(self):
        steps = installer.plan(disk(), PINS)
        bootc = next(step.argv for step in steps if step.argv[:3] == ('bootc', 'install', 'to-filesystem'))
        for flag in ('--composefs-backend', '--generic-image', '--skip-fetch-check'):
            self.assertIn(flag, bootc)
        self.assertEqual(bootc[bootc.index('--bootloader') + 1], 'systemd')
        self.assertEqual(bootc[bootc.index('--source-imgref') + 1], PINS['sourceImgref'])
        self.assertEqual(bootc[bootc.index('--target-imgref') + 1], PINS['targetImgref'])
        self.assertNotIn('--karg', bootc)
        self.assertNotIn('--skip-finalize', bootc)
        self.assertEqual(bootc[-1], str(installer.TARGET))

    def test_destructive_order_and_target_devices(self):
        steps = installer.plan(disk(), PINS)
        order = [step.argv[0] for step in steps]
        self.assertEqual(order[0], 'sfdisk')
        self.assertLess(order.index('cryptsetup'), order.index('mkfs.ext4'))
        self.assertLess(order.index('bootc'), order.index('efibootmgr'))
        self.assertEqual(order[-3:], ['umount', 'cryptsetup', 'sync'])
        luks = next(step.argv for step in steps if step.argv[:2] == ('cryptsetup', 'luksFormat'))
        self.assertEqual(luks[-1], '/dev/nvme0n1p3')
        fats = [step.argv[-1] for step in steps if step.argv[0] == 'mkfs.fat']
        self.assertEqual(fats, ['/dev/nvme0n1p1', '/dev/nvme0n1p2'])
        self.assertEqual(self.argv(steps, 'mkfs.ext4').argv,
                         ('mkfs.ext4', '-O', 'verity', '-L', 'finiteroot', '/dev/mapper/root'))
        efi = self.argv(steps, 'efibootmgr').argv
        self.assertEqual(efi[efi.index('--loader') + 1], r'\EFI\finite\shimx64.efi')
        self.assertEqual(efi[efi.index('--disk') + 1], '/dev/nvme0n1')

    def test_scratch_space_moves_onto_the_target_before_bootc(self):
        steps = installer.plan(disk(), PINS)
        binds = [i for i, s in enumerate(steps) if s.argv[:2] == ('mount', '--bind')]
        bootc = next(i for i, s in enumerate(steps) if s.argv[0] == 'bootc')
        self.assertEqual(len(binds), 2)
        self.assertLess(binds[1], bootc)
        scratch = steps[binds[0]].argv[2]
        self.assertTrue(scratch.startswith(str(installer.TARGET) + '/'))
        self.assertEqual(steps[binds[0]].argv[3], scratch)
        self.assertEqual(steps[binds[1]].argv[2:], (scratch, '/var/tmp'))
        release = next(i for i, step in enumerate(steps) if step.argv == ('umount', scratch))
        reopen = next(i for i, step in enumerate(steps)
                      if step.argv == ('mount', '-o', 'remount,rw', str(installer.TARGET)))
        remove = next(i for i, step in enumerate(steps) if step.argv[0] == 'rm')
        self.assertLess(bootc, release)
        self.assertLess(release, reopen)
        self.assertLess(reopen, remove)

    def test_optional_key_enrollment(self):
        plain = installer.plan(disk(), PINS, recovery_key=False)
        self.assertFalse(any(step.argv[0] == 'systemd-cryptenroll' for step in plain))
        both = installer.plan(disk(), PINS, fido2=True)
        enrolls = [step for step in both if step.argv[0] == 'systemd-cryptenroll']
        self.assertEqual([step.argv[1] for step in enrolls], ['--recovery-key', '--fido2-device=auto'])
        self.assertTrue(all(step.secret == 'env' and step.interactive for step in enrolls))

    def test_rendered_plan_never_contains_the_passphrase(self):
        rendered = json.dumps([step.render() for step in installer.plan(disk(), PINS, fido2=True)])
        self.assertIn('<passphrase>', rendered)
        self.assertNotIn('correct horse', rendered)

    def test_installed_state_and_signed_payload_supply_the_efi_transaction(self):
        steps = installer.plan(disk(), PINS)
        deployment = str(installer.DEPLOYMENT)
        mount = ('bootc', 'install', 'mount', '--sysroot', str(installer.TARGET), '--latest', deployment)
        updater = self.argv(steps, '/usr/bin/python3').argv
        self.assertEqual(updater[:2], ('/usr/bin/python3', '/usr/libexec/finite/update-efi'))
        unit = ROOT / 'files/system/usr/lib/systemd/system/finite-efi-update.service'
        self.assertIn('ExecStart=' + ' '.join(updater[:2]), unit.read_text().splitlines())
        self.assertEqual(updater[updater.index('--install-root') + 1], deployment)
        self.assertEqual(updater[updater.index('--state') + 1], deployment + '/var/lib/finite/efi-updates')
        commands = [step.argv for step in steps]
        self.assertLess(commands.index(('mount', '-o', 'remount,rw', str(installer.TARGET))),
                        commands.index(mount))
        self.assertLess(commands.index(mount), commands.index(updater))
        finish = ('mount', '-o', 'remount,ro', str(installer.TARGET))
        release = ('umount', '--recursive', deployment)
        self.assertLess(commands.index(updater), commands.index(release))
        self.assertLess(commands.index(release), commands.index(finish))
        self.assertLess(commands.index(finish),
                        next(i for i, command in enumerate(commands) if command[0] == 'efibootmgr'))


class Execute(unittest.TestCase):
    def test_passphrase_routing_and_stop_on_failure(self):
        calls = []

        class Result:
            def __init__(self, code):
                self.returncode = code

        def run(argv, input=None, text=None, env=None):
            calls.append((argv, input, (env or {}).get('PASSWORD')))
            return Result(1 if argv[0] == 'mkfs.fat' else 0)

        steps = installer.plan(disk(), PINS, fido2=True)
        with self.assertRaisesRegex(installer.InstallError, 'Format the ESP'):
            installer.execute(steps, 'correct horse battery', run=run, say=lambda _: None)
        by_tool = {}
        for argv, stdin, password in calls:
            by_tool.setdefault(argv[0], []).append((stdin, password))
        self.assertEqual(by_tool['cryptsetup'], [('correct horse battery', None)] * 2)
        self.assertEqual(by_tool['systemd-cryptenroll'], [(None, 'correct horse battery')] * 2)
        self.assertEqual(by_tool['sfdisk'][0][0], installer.layout())
        self.assertNotIn('bootc', by_tool)


class Environment(unittest.TestCase):
    def test_embedded_layout_cannot_substitute_another_manifest_or_profile(self):
        good = {'Digest': PINS['payloadDigest'], 'Architecture': 'amd64', 'Os': 'linux',
                'Labels': {'io.finite.profile': 'finite-native',
                           'io.finite.boot-architecture': 'native-composefs'}}
        installer.verify_payload(PINS, good)
        for change in ({'Digest': 'sha256:' + 'f' * 64}, {'Architecture': 'arm64'},
                       {'Os': 'other'}, {'Labels': {'io.finite.profile': 'finite'}},
                       {'Labels': {'io.finite.profile': 'finite-native-dev',
                                   'io.finite.boot-architecture': 'native-composefs'}}):
            with self.subTest(change=change), self.assertRaisesRegex(installer.InstallError, 'Embedded payload'):
                installer.verify_payload(PINS, {**good, **change})

    def test_wrong_repository_default_tag_and_source_transport_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = dict(efi_dir=Path(temporary), cmdline='finite.native-installer=1',
                        bootc_version='bootc 1.17.5', bootc_sha256=PINS['bootcSha256'])
            for change in ({'targetImgref': 'ghcr.io/closure-labs/finite:latest'},
                           {'targetImgref': 'ghcr.io/closure-labs/finite-native:latest'},
                           {'sourceImgref': 'docker://ghcr.io/closure-labs/finite:finite-native'},
                           {'sourceImgref': 'oci:/var/tmp/other-payload'},
                           {'sourceImgref': 'containers-storage:ghcr.io/closure-labs/finite:finite-native'},
                           {'bootcSha256': ''}, {'schema': True}):
                with self.subTest(change=change), self.assertRaises(installer.InstallError):
                    installer.check_environment({**PINS, **change}, **args)

    def test_payload_failure_stops_before_disk_selection_and_execution(self):
        with patch.object(installer, 'load_pins', return_value=PINS), \
                patch.object(installer, 'check_environment'), \
                patch.object(installer, 'verify_payload', side_effect=installer.InstallError('bad payload')), \
                patch.object(installer, 'discover') as discover, patch.object(installer, 'execute') as execute:
            self.assertEqual(installer.main(['install']), 1)
            discover.assert_not_called()
            execute.assert_not_called()

    def test_requires_uefi_installer_media_and_pinned_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            efi = Path(temporary)
            good = dict(efi_dir=efi, cmdline='quiet finite.native-installer=1', bootc_version='bootc 1.17.5', bootc_sha256=PINS['bootcSha256'])
            installer.check_environment(PINS, **good)
            for change, message in [(dict(efi_dir=efi / 'missing'), 'UEFI'),
                                    (dict(cmdline='quiet'), 'installer media'),
                                    (dict(bootc_version='bootc 1.17.4'), 'differs from the pinned'),
                                    (dict(bootc_sha256='c' * 64), 'runtime bytes differ')]:
                with self.subTest(change=change), self.assertRaisesRegex(installer.InstallError, message):
                    installer.check_environment(PINS, **{**good, **change})
            for pins, message in [({**PINS, 'payloadDigest': 'latest'}, 'immutable'),
                                  ({**PINS, 'schema': 1}, 'Invalid'),
                                  ({k: v for k, v in PINS.items() if k != 'targetImgref'}, 'targetImgref')]:
                with self.subTest(pins=pins), self.assertRaisesRegex(installer.InstallError, message):
                    installer.check_environment(pins, **good)

    def test_passphrase_rules(self):
        answers = iter(['short'])
        with self.assertRaisesRegex(installer.InstallError, 'at least 12'):
            installer.passphrase(read=lambda _: next(answers))
        answers = iter(['correct horse battery', 'different words here'])
        with self.assertRaisesRegex(installer.InstallError, 'differ'):
            installer.passphrase(read=lambda _: next(answers))


class Placement(unittest.TestCase):
    def test_ukis_and_entries_must_be_on_xbootldr_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            with self.assertRaisesRegex(installer.InstallError, 'No UKI'):
                installer.verify_placement(target)
            (target / 'boot/EFI/Linux/bootc').mkdir(parents=True)
            (target / 'boot/EFI/Linux/bootc/finite.efi').write_bytes(b'uki')
            with self.assertRaisesRegex(installer.InstallError, 'No boot entry'):
                installer.verify_placement(target)
            (target / 'boot/loader/entries').mkdir(parents=True)
            (target / 'boot/loader/entries/finite.conf').write_text('uki /EFI/Linux/finite.efi\n')
            installer.verify_placement(target)
            (target / 'efi/EFI/Linux/bootc').mkdir(parents=True)
            (target / 'efi/EFI/Linux/bootc/stray.efi').write_bytes(b'uki')
            with self.assertRaisesRegex(installer.InstallError, 'ESP instead'):
                installer.verify_placement(target)


class TargetConfiguration(unittest.TestCase):
    def test_boot_mounts_replace_stale_entries_and_keep_other_fstab_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            deployment = Path(temporary)
            setup = deployment / 'usr/lib/composefs/setup-root-conf.toml'
            setup.parent.mkdir(parents=True)
            setup.touch()
            fstab = deployment / 'etc/fstab'
            fstab.parent.mkdir()
            original = '# Existing entries\nUUID=other /var/log ext4 defaults 0 0\n'
            fstab.write_text(original + 'UUID=old /boot vfat defaults 0 0\nUUID=old /efi vfat defaults 0 0\n')
            esp = '11111111-1111-1111-1111-111111111111'
            xbootldr = '22222222-2222-2222-2222-222222222222'
            with patch.object(Path, 'is_mount', return_value=True), patch(
                'subprocess.check_output', side_effect=[f'{esp} vfat\n', f'{xbootldr} vfat\n'] * 2
            ) as read_mount:
                installer.configure_target(deployment)
                installer.configure_target(deployment)
            self.assertEqual([c.args[0][-1] for c in read_mount.call_args_list],
                             [str(installer.TARGET / name) for name in ('efi', 'boot')] * 2)
            self.assertEqual(fstab.read_text(), original + f'PARTUUID={esp} /efi vfat umask=0077 0 0\n'
                             f'PARTUUID={xbootldr} /boot vfat ro,umask=0077 0 0\n')
            self.assertTrue(json.loads((deployment / 'etc/finite/bootloader.json').read_text())['manageFallback'])
            with patch.object(Path, 'is_mount', return_value=True), patch(
                'subprocess.check_output', side_effect=[f'{esp} vfat\n'] * 2
            ), self.assertRaisesRegex(installer.InstallError, 'distinct partitions'):
                installer.configure_target(deployment)


class Enrollment(unittest.TestCase):
    def test_pre_enrolled_keys_skip_prompt_and_missing_key_is_queued(self):
        with tempfile.TemporaryDirectory() as temporary:
            boot = Path(temporary) / 'boot.der'
            module = Path(temporary) / 'module.der'
            boot.write_bytes(b'boot cert')
            module.write_bytes(b'module cert')
            with patch.object(installer, 'MOK_BOOT_CERT', boot), patch.object(installer, 'MODULE_CERT', module):
                for exports, missing in (([boot, module], []), ([module], [boot])):
                    commands = []

                    def run(argv, **kwargs):
                        commands.append(argv)
                        if argv[1] == '--export':
                            destination = Path(kwargs['cwd'])
                            for index, cert in enumerate(exports):
                                (destination / f'MOK-{index}.der').write_bytes(cert.read_bytes())
                        return CompletedProcess(argv, 0)

                    with patch.object(installer, 'print', create=True):
                        installer.enroll_mok(run)
                    expected = [['mokutil', '--export']]
                    if missing:
                        expected.append(['mokutil', '--import', *map(str, missing)])
                    self.assertEqual(commands, expected)

    def test_failed_mok_export_does_not_queue_enrollment(self):
        with patch('subprocess.run', side_effect=CalledProcessError(1, ['mokutil', '--export'])) as run:
            with self.assertRaises(CalledProcessError):
                installer.enroll_mok(run)
            run.assert_called_once()


class Media(unittest.TestCase):
    directory = ROOT / 'scripts/native-installer'

    def test_live_kernel_argument_matches_installer_and_service(self):
        lock = json.loads((ROOT / 'sources/native-installer.json').read_text())
        iso = (self.directory / 'iso.yaml').read_text()
        argument = lock['liveKernelArgument']
        self.assertIn('  - ' + argument, iso)
        self.assertIn('label: ' + lock['isoLabel'], iso)
        self.assertLessEqual(len(lock['isoLabel']), 32)
        service = (self.directory / 'finite-native-installer.service').read_text()
        self.assertIn('ConditionKernelCommandLine=' + argument, service)
        self.assertIn('ExecStart=/usr/libexec/finite/finite-native-install install', service)
        self.assertIn(argument, SCRIPT.read_text())

    def test_containerfile_builds_live_media_from_the_exact_payload(self):
        content = (self.directory / 'Containerfile').read_text()
        self.assertIn('FROM ${PAYLOAD}', content)
        self.assertIn('--add dmsquash-live', content)
        self.assertIn('find /kernel', content)
        self.assertIn('install -m644 "/kernel/$kver/vmlinuz"', content)
        self.assertIn('--omit \'bootc ostree\'', content)
        self.assertIn('/usr/share/finite/bootc-runtime.json', content)
        self.assertIn('grub2-efi-x64-cdboot', content)
        self.assertIn('cp -ra /usr/lib/efi/*/*/EFI /boot/efi', content)
        self.assertIn('COPY iso.yaml /usr/lib/image-builder/bootc/iso.yaml', content)
        self.assertIn('/usr/libexec/finite/finite-native-install', content)
        self.assertIn('systemctl enable finite-native-installer.service', content)
        self.assertIn('source="oci:$directory/payload"', content)
        self.assertIn('skopeo inspect --raw "$source" | sha256sum', content)
        # The plan calls the installed copy for placement checks.
        steps = installer.plan(disk(), PINS)
        self.assertTrue(any(step.argv[0] == '/usr/libexec/finite/finite-native-install' for step in steps))
        self.assertEqual(str(installer.PINS), '/usr/lib/finite/installer/pins.json')

    def test_builder_is_pinned_by_digest_and_uses_generic_iso(self):
        lock = json.loads((ROOT / 'sources/native-installer.json').read_text())['imageBuilder']
        self.assertEqual(lock['image'], 'ghcr.io/osbuild/image-builder-cli')
        self.assertRegex(lock['digest'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(lock['imageType'], 'generic-iso')
        script = (self.directory / 'build-iso.sh').read_text()
        self.assertIn('.imageBuilder.digest', script)
        self.assertIn('cosign verify', script)
        self.assertIn('--volume "$payload_archive:/run/finite-payload.oci.tar:ro"', script)
        self.assertNotIn('--bootc-installer-payload-ref', script)
        self.assertNotIn('anaconda-iso', script)

    def test_capped_guest_keeps_the_complete_failure_line_in_its_serial_log(self):
        spec = importlib.util.spec_from_file_location('qualify_iso', self.directory / 'qualify-iso.py')
        qual = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qual)
        for message in (b'Installation stopped: Embedded payload manifest digest differs',
                        b'FINITE_NATIVE_FRESH_BOOT_FAILED The installed EFI updater failed'):
            with self.subTest(message=message):
                guest = qual.Guest.__new__(qual.Guest)
                guest.deadline = time.monotonic() + 10
                guest.output = b''
                guest.log = BytesIO()
                guest.selector = SimpleNamespace(select=lambda timeout: True)
                guest.process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 0))
                chunks = [b'Guest output\r\n' + message[:-5], message[-5:] + b'\r\n']
                with patch.object(qual, 'available_mib', return_value=qual.RESERVE_MIB), \
                        patch.object(qual.os, 'read', side_effect=chunks), \
                        self.assertRaisesRegex(RuntimeError, 'Guest reported a failure'):
                    guest.expect(rb'Installation complete\.')
                self.assertEqual(guest.log.getvalue(), b''.join(chunks))

    def test_hybrid_iso_uses_a_distinct_read_only_boot_device(self):
        spec = importlib.util.spec_from_file_location('qualify_iso', self.directory / 'qualify-iso.py')
        qual = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qual)
        args = qual.install_media(Path('/tmp/finite-native-dev.iso'))
        self.assertEqual(args, [
            '-drive', 'if=none,id=media,format=raw,readonly=on,file=/tmp/finite-native-dev.iso',
            '-device', 'virtio-blk-pci,drive=media,bootindex=1,serial=FINITEINSTALLMEDIA',
        ])
        self.assertNotEqual('FINITEINSTALLMEDIA', qual.DISK_SERIAL)

    def test_serial_records_handle_fragmented_reads_and_missing_console_newlines(self):
        qual = runpy.run_path(str(self.directory / 'qualify-iso.py'))
        emit = runpy.run_path(str(self.directory / 'serial_records.py'))['emit_record']
        guest = qual['Guest'].__new__(qual['Guest'])
        guest.deadline = time.monotonic() + 10
        guest.output = b''
        guest.log = BytesIO()
        guest.selector = SimpleNamespace(select=lambda timeout: True)
        guest.process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 0))
        first = {'nested': {'root': 'old'}, 'ready': True}
        payload = {'phase': 'stage', 'status': {'deployed': 'a' * 1024, 'staged': 'b' * 1024}}
        stream = StringIO()
        with redirect_stdout(stream):
            emit('BOOT', first)
            emit('TRANSITION', payload)
        lines = stream.getvalue().splitlines()
        self.assertGreater(len(lines), 2)
        self.assertTrue(all(len(line) < 300 for line in lines))
        wire = ''.join('journal prefix ' + line + '[26.778346] EXT4-fs: mounted filesystem\r\n'
                       for line in lines).encode()
        split = wire.index(b'|END|')
        fragmented = [wire[:split]] + [wire[offset:offset + 41] for offset in range(split, len(wire), 41)]
        with patch.dict(qual['Guest'].expect.__globals__, available_mib=lambda: qual['RESERVE_MIB']), \
                patch.object(qual['os'], 'read', side_effect=fragmented):
            self.assertEqual(guest.record(b'BOOT'), first)
            self.assertEqual(guest.record(b'TRANSITION'), payload)
        self.assertIn(b'|END|', guest.log.getvalue())
        self.assertTrue(wire.startswith(guest.log.getvalue()))

    def test_boot_receipt_requires_signed_modules_from_the_upstream_image(self):
        qual = runpy.run_path(str(self.directory / 'qualify-iso.py'))
        seal = {'profile': 'finite-native', 'bootableRootDigest': 'a' * 128}
        common = dict(seal, secureBoot=True, selinuxEnforcing=True, encryptedRoot=True,
                      efiUpdaterSucceeded=True, espBytes=600 * 1024**2, xbootldrBytes=4 * GIB)
        for provided, modules in ((True, ['zfs', 'v4l2loopback']), (False, ['v4l2loopback'])):
            with self.subTest(zfs=provided):
                facts = dict(common, zfsProvided=provided, signedModules=modules)
                guest = SimpleNamespace(expect=lambda _: None, send=lambda _: None, record=lambda _: facts)
                self.assertEqual(qual['boot_facts'](guest, 'disposable-password', seal), facts)
                facts['signedModules'] = []
                with self.assertRaisesRegex(ValueError, 'required boot facts'):
                    qual['boot_facts'](guest, 'disposable-password', seal)

    def test_workflow_is_manual_main_only_and_uploads_unqualified_media(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/native-iso.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        self.assertEqual(triggers['workflow_dispatch']['inputs']['channel']['options'],
                         ['finite-native', 'finite-native-dev'])
        job = workflow['jobs']['iso']
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertEqual(job['permissions'], {'contents': 'read', 'packages': 'read'})
        self.assertNotIn('environment', job)
        text = (ROOT / '.github/workflows/native-iso.yml').read_text()
        self.assertNotIn('secrets.', text)
        self.assertIn('bash scripts/native-installer/build-iso.sh', text)


if __name__ == '__main__':
    unittest.main()
