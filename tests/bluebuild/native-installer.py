#!/usr/bin/env python3
"""The native installer's disk choice, layout and command contract, without touching disks."""
from importlib.machinery import SourceFileLoader
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/native-installer/finite-native-install'
loader = SourceFileLoader('finite_native_install', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)

GIB = 1024**3
PINS = {'schema': 1, 'bootcVersion': '1.17.5', 'payloadDigest': 'sha256:' + 'a' * 64,
        'sourceImgref': 'oci-archive:/run/install/payload.oci.tar',
        'targetImgref': 'ghcr.io/closure-labs/finite-native:latest'}


def disk(path='/dev/nvme0n1', by_id='nvme-KIOXIA_512GB_X', size=512 * GIB, **changes):
    values = dict(path=path, by_id=by_id, size=size, model='KIOXIA', removable=False,
                  read_only=False, mounted=False, holds_boot_medium=False)
    values.update(changes)
    return installer.Disk(**values)


class DiskChoice(unittest.TestCase):
    def test_unsafe_disks_are_never_offered(self):
        cases = {'holds the installer boot medium': dict(holds_boot_medium=True),
                 'has mounted filesystems or active swap': dict(mounted=True),
                 'is read-only': dict(read_only=True),
                 'is smaller than 64 GiB': dict(size=63 * GIB),
                 'has no stable /dev/disk/by-id name': dict(by_id='')}
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
        bootc = self.argv(steps, 'bootc').argv
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
        self.assertEqual(len(binds), 1)
        self.assertLess(binds[0], bootc)
        self.assertTrue(steps[binds[0]].argv[2].startswith(str(installer.TARGET) + '/'))
        self.assertEqual(steps[binds[0]].argv[3], '/var/tmp')

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
    def test_requires_uefi_installer_media_and_pinned_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            efi = Path(temporary)
            good = dict(efi_dir=efi, cmdline='quiet finite.native-installer=1', bootc_version='bootc 1.17.5')
            installer.check_environment(PINS, **good)
            for change, message in [(dict(efi_dir=efi / 'missing'), 'UEFI'),
                                    (dict(cmdline='quiet'), 'installer media'),
                                    (dict(bootc_version='bootc 1.17.4'), 'differs from the pinned')]:
                with self.subTest(change=change), self.assertRaisesRegex(installer.InstallError, message):
                    installer.check_environment(PINS, **{**good, **change})
            for pins, message in [({**PINS, 'payloadDigest': 'latest'}, 'immutable'),
                                  ({**PINS, 'schema': 2}, 'Invalid'),
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
            (target / 'boot/EFI/Linux').mkdir(parents=True)
            (target / 'boot/EFI/Linux/finite.efi').write_bytes(b'uki')
            with self.assertRaisesRegex(installer.InstallError, 'No boot entry'):
                installer.verify_placement(target)
            (target / 'boot/loader/entries').mkdir(parents=True)
            (target / 'boot/loader/entries/finite.conf').write_text('uki /EFI/Linux/finite.efi\n')
            installer.verify_placement(target)
            (target / 'efi/EFI/Linux').mkdir(parents=True)
            (target / 'efi/EFI/Linux/stray.efi').write_bytes(b'uki')
            with self.assertRaisesRegex(installer.InstallError, 'ESP instead'):
                installer.verify_placement(target)


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
        self.assertIn('grub2-efi-x64-cdboot', content)
        self.assertIn('cp -ra /usr/lib/efi/*/*/EFI /boot/efi', content)
        self.assertIn('COPY iso.yaml /usr/lib/image-builder/bootc/iso.yaml', content)
        self.assertIn('/usr/libexec/finite/finite-native-install', content)
        self.assertIn('systemctl enable finite-native-installer.service', content)
        self.assertIn('"sourceImgref": "containers-storage:%s"', content)
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
        self.assertIn('--bootc-installer-payload-ref', script)
        self.assertNotIn('anaconda-iso', script)

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
