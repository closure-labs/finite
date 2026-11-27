#!/usr/bin/python3
"""Create and migrate the dedicated file-backed workstation rehearsal disk."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys
import tempfile

import migration_layout as layout
from serial_records import emit_record

WORK = Path('/run/finite-migration')
TOP = WORK / 'top'
TARGET = WORK / 'target'
DEPLOYMENT = WORK / 'deployment'
MEDIA = WORK / 'media'
MAPPER = 'finite-migration'
DEVICE = Path('/dev/mapper') / MAPPER
UID, GID = 1234, 2345
ACCOUNT = 'finite-rehearsal'
HOME_MARKER = f'{ACCOUNT}/documents/example.txt'
MARKER = 'disposable workstation layout fixture\n'
OBSERVATION = Path('/usr/libexec/finite/observe-migration.py')


def run(*args, stdin=None, timeout=120):
    return subprocess.run(args, input=stdin, check=True, stdout=subprocess.PIPE,
                          timeout=timeout).stdout.decode().strip()


def process(*args, stdin=None, timeout=120):
    subprocess.run(args, input=stdin, check=True, timeout=timeout)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def mark(phase, **facts):
    emit_record('FINITE_MIGRATION', {'phase': phase, **facts})


def mount(device, target, options=None):
    command = ['mount', '--mkdir']
    if options:
        command.extend(['-o', options])
    process(*command, device, target)


def table(disk):
    return json.loads(run('sfdisk', '--json', disk))


def disk_for(phase):
    require(os.geteuid() == 0 and run('systemd-detect-virt', '--vm') in {'kvm', 'qemu'},
            'The rehearsal requires an isolated KVM guest')
    identifier = Path('/sys/class/dmi/id/product_serial').read_text().strip()
    require(identifier == 'finite-migration-' + phase and
            'finite.native-installer=1' in Path('/proc/cmdline').read_text().split(),
            'The rehearsal requires the dedicated native rescue guest')
    disk = str(layout.REHEARSAL_DISK.resolve(strict=True))
    require(re.fullmatch(r'/dev/vd[a-z]', disk) is not None and stat.S_ISBLK(Path(disk).stat().st_mode)
            and int(run('blockdev', '--getsz', disk)) == layout.DISK_SECTORS
            and int(run('blockdev', '--getss', disk)) == layout.SECTOR_BYTES
            and run('blockdev', '--getro', disk) == '0', 'Unexpected target disk identity or size')
    devices = json.loads(run('lsblk', '--json', '--output', 'NAME,MOUNTPOINTS', disk))['blockdevices']
    require(len(devices) == 1 and not any(devices[0]['mountpoints']), 'Mounted rehearsal target')
    for child in devices[0].get('children', []):
        require(not any(child['mountpoints']) and not child.get('children', []),
                'Rehearsal disk has active child mappings or mounts')
    return disk


def open_root(partition, secret):
    process('cryptsetup', 'open', '--type', 'luks2', '--key-file=-', partition, MAPPER, stdin=secret)


def boot_firmware():
    values = run('efibootmgr', '-v').splitlines()
    order = next(line.split(': ', 1)[1] for line in values if line.startswith('BootOrder: '))
    require(not any(line.startswith('BootNext: ') for line in values), 'A BootNext selection already exists')
    return values, order


def add_observation(root):
    unit = '[Unit]\nAfter=local-fs.target finite-efi-update.service nix.mount\nRequiresMountsFor=/var/home /nix\n\n' \
           '[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /etc/finite-migration/observe.py\n' \
           'StandardOutput=journal+console\nStandardError=journal+console\n'
    etc = root / 'etc'
    (etc / 'finite-migration').mkdir(mode=0o700)
    (etc / 'finite-migration/observe.py').write_bytes(OBSERVATION.read_bytes())
    (etc / 'finite-migration/preflight.py').write_bytes(
        Path('/usr/libexec/finite/systemd-boot-preflight.py').read_bytes())
    (etc / 'finite-migration/serial_records.py').write_bytes(
        OBSERVATION.with_name('serial_records.py').read_bytes())
    unit_path = etc / 'systemd/system/finite-migration-observe.service'
    unit_path.write_text(unit)
    wants = unit_path.parent / 'multi-user.target.wants'
    wants.mkdir(parents=True, exist_ok=True)
    (wants / unit_path.name).symlink_to('../' + unit_path.name)


def account_and_home(root, fsuuid, *, rescue_entry=None):
    process('groupadd', '--root', root, '--gid', str(GID), ACCOUNT)
    process('useradd', '--root', root, '--no-create-home', '--uid', str(UID),
            '--gid', str(GID), '--home-dir', '/var/home/' + ACCOUNT, ACCOUNT)
    fstab = root / 'etc/fstab'
    with fstab.open('a') as stream:
        stream.write(f'\nUUID={fsuuid} /var/home btrfs subvol=/home 0 0\n')
    add_observation(root)
    if rescue_entry is not None:
        (root / 'etc/finite-migration/rescue-boot-entry').write_text(rescue_entry + '\n')
    process('chroot', root, 'restorecon', '-RF', '/etc/finite-migration', '/etc/systemd/system',
            '/etc/fstab', '/etc/passwd', '/etc/group', '/etc/shadow', '/etc/gshadow')


def legacy(disk, secret, alternate, rescue_entry):
    require(not run('lsblk', '-nr', '-o', 'PARTTYPE', disk), 'Legacy creation requires a blank fixture')
    process('sfdisk', disk, stdin=layout.original_table(disk).encode())
    process('udevadm', 'settle')
    layout.verify_table(disk, table(disk), layout.LEGACY)
    esp, boot, root = (layout.partition(disk, idx) for idx in (1, 7, 8))
    process('mkfs.fat', '-F', '32', '-n', 'FINITEESP', esp)
    process('mkfs.ext4', '-L', 'LEGACYBOOT', boot)
    process('cryptsetup', 'luksFormat', '--type', 'luks2', '--batch-mode', '--key-file=-', root, stdin=secret)
    # Both synthetic keys stay on the host or in the guest's private /run.
    # The raw file is ephemeral and never attached to a qualification receipt.
    with tempfile.NamedTemporaryFile(prefix='luks-key-', dir=WORK) as key:
        key.write(alternate)
        key.flush()
        process('cryptsetup', 'luksAddKey', '--batch-mode', '--key-file=-', root, key.name, stdin=secret)
    keyslots = json.loads(run('cryptsetup', 'luksDump', '--dump-json-metadata', root))['keyslots']
    require(len(keyslots) == 2, 'Fixture requires a distinct alternate LUKS keyslot')
    open_root(root, secret)
    process('mkfs.btrfs', '-L', 'REHEARSAL', DEVICE)
    mount(DEVICE, TOP, 'subvolid=5')
    for name in ('root', 'home'):
        process('btrfs', 'subvolume', 'create', TOP / name)
    path = TOP / 'home' / HOME_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MARKER)
    os.chown(TOP / 'home' / ACCOUNT, UID, GID)
    os.chown(TOP / 'home' / HOME_MARKER, UID, GID)
    mount(DEVICE, TARGET, 'subvol=/root')
    mount(boot, TARGET / 'boot')
    mount(esp, TARGET / 'boot/efi')
    media = Path('/dev/disk/by-id/virtio-FINITEMIGRATIONDATA')
    require(run('blockdev', '--getro', media) == '1', 'Legacy input is writable')
    mount(media, MEDIA, 'ro,noload,nodev,nosuid,noexec')
    archive = MEDIA / 'legacy.oci.tar'
    require(sha256(archive) == (MEDIA / 'legacy.sha256').read_text().strip(), 'Legacy archive hash differs')
    luks = run('cryptsetup', 'luksUUID', root)
    fsuuid = run('blkid', '-s', 'UUID', '-o', 'value', DEVICE)
    root_spec = 'UUID=' + fsuuid
    subvolume = 'rootflags=subvol=/root'
    scratch = TOP / 'scratch'
    scratch.mkdir()
    process('mount', '--bind', scratch, '/var/tmp')
    process('bootc', 'install', 'to-filesystem', '--bootloader', 'grub', '--skip-fetch-check',
            '--skip-finalize', '--bound-images', 'skip', '--source-imgref', 'oci-archive:' + str(archive),
            '--target-imgref', 'ghcr.io/closure-labs/finite:finite',
            '--root-mount-spec', root_spec, '--karg', subvolume,
            '--karg', 'rd.luks.uuid=' + luks, '--karg', 'console=ttyS0,115200n8',
            '--karg', 'rd.plymouth=0', '--karg', 'plymouth.enable=0', TARGET, timeout=1800)
    process('umount', '/var/tmp')
    DEPLOYMENT.mkdir()
    process('bootc', 'install', 'mount', '--sysroot', TARGET, '--latest', DEPLOYMENT)
    account_and_home(DEPLOYMENT, fsuuid, rescue_entry=rescue_entry)
    process('umount', '--recursive', DEPLOYMENT)
    boot_dir = TARGET / 'boot'
    loader = boot_dir / 'loader'
    # Retain the offline view for triage. The running GRUB entry and actual
    # mounted old subvolume are the gate before opening any migration fork.
    bls_entries = {}
    for entry in sorted(boot_dir.glob('loader*/entries/*.conf')):
        options = [words[1:] for line in entry.read_text().splitlines()
                   if (words := line.split()) and words[0] == 'options']
        bls_entries[str(entry.relative_to(boot_dir))] = [
            arg for row in options for arg in row if arg.startswith(('root=', 'rootflags=', 'ostree='))]
    boot_inventory = {'loaderLink': os.readlink(loader) if loader.is_symlink() else None,
                      'topLevel': sorted(entry.name for entry in boot_dir.iterdir()), 'blsEntries': bls_entries}
    process('umount', '--recursive', TARGET)
    process('umount', TOP, MEDIA)
    process('cryptsetup', 'close', MAPPER)
    _, order = boot_firmware()
    mark('legacy-created', bootOrder=order, gpt=table(disk), luksKeyslots=len(keyslots),
         rootMountSpec=root_spec, rootFlags=subvolume, bootInventory=boot_inventory)


def resize(disk, secret, *, interrupt=False):
    original = table(disk)
    new_table = layout.native_table(disk, original)
    root = layout.partition(disk, 8)
    open_root(root, secret)
    luks = json.loads(run('cryptsetup', 'luksDump', '--dump-json-metadata', root))
    segments = luks['segments']
    require(set(segments) == {'0'} and segments['0']['type'] == 'crypt',
            'Fixture requires one standard dm-crypt segment')
    offset = int(segments['0']['offset'])
    sectors, size = layout.shrink_sizes(offset, int(run('blockdev', '--getsize64', DEVICE)))
    mount(DEVICE, TOP, 'subvolid=5')
    process('btrfs', 'filesystem', 'resize', str(size), TOP)
    devices = re.findall(r'\bdevid\s+(\d+)\s+size\s+(\d+)', run('btrfs', 'filesystem', 'show', '--raw', TOP))
    require(devices == [('1', str(size))], 'Unexpected Btrfs size after shrinking')
    process('umount', TOP)
    process('cryptsetup', 'resize', '--key-file=-', '--size', str(sectors), MAPPER, stdin=secret)
    require(int(run('blockdev', '--getsz', DEVICE)) == sectors, 'Encrypted mapping did not shrink')
    process('cryptsetup', 'close', MAPPER)
    mark('before-gpt-change', btrfsBytes=size, mappedSectors=sectors, luksPayloadOffset=offset)
    if interrupt:
        return False
    process('sfdisk', '--wipe', 'never', '--wipe-partitions', 'never', disk, stdin=new_table.encode())
    process('udevadm', 'settle')
    actual_id, actual = layout.verify_table(disk, table(disk), layout.NATIVE)
    old_id, old = layout.verify_table(disk, original, layout.LEGACY)
    require(actual_id == old_id and all(actual[number] == uuid for number, uuid in old.items()),
            'Original GPT identity changed')
    open_root(root, secret)
    require(int(run('blockdev', '--getsz', DEVICE)) == sectors, 'Reopened dm-crypt geometry differs')
    process('btrfs', 'check', '--readonly', DEVICE, timeout=600)
    process('mkfs.fat', '-F', '32', '-n', 'XBOOTLDR', layout.partition(disk, 9))
    mark('partitioned', btrfsBytes=size, mappedSectors=sectors, gpt=table(disk))
    return True


def efi_inventory(esp, names):
    return {str(path.relative_to(esp)): sha256(path) for name in names
            for path in (esp / name).rglob('*') if path.is_file()}


def native(disk, phase):
    installer = runpy.run_path('/usr/libexec/finite/finite-native-install')
    pins = installer['load_pins']()
    installer['check_environment'](pins)
    installer['verify_payload'](pins)
    esp_device, xbootldr = (layout.partition(disk, idx) for idx in (1, 9))
    _, order = boot_firmware()
    mount(DEVICE, TOP, 'subvolid=5')
    process('btrfs', 'subvolume', 'create', TOP / 'root-native')
    mount(DEVICE, TARGET, 'subvol=/root-native')
    mount(esp_device, TARGET / 'efi')
    mount(xbootldr, TARGET / 'boot')
    esp = TARGET / 'efi'
    old_efi = ['EFI/fedora', 'EFI/BOOT']
    original = efi_inventory(esp, old_efi)
    require('EFI/fedora/shimx64.efi' in original, 'Old Fedora shim entry not found on ESP')
    fallback = {name: (esp / name).read_bytes() for name in original if name.startswith('EFI/BOOT/')}
    scratch = TOP / 'native-scratch'
    scratch.mkdir()
    process('mount', '--bind', scratch, '/var/tmp')
    try:
        process('bootc', 'install', 'to-filesystem', '--composefs-backend', '--bootloader', 'systemd',
                '--generic-image', '--skip-fetch-check', '--skip-finalize',
                '--source-imgref', pins['sourceImgref'], '--target-imgref', pins['targetImgref'],
                TARGET, timeout=1800)
    finally:
        process('umount', '/var/tmp')
        # bootctl may install its own fallback. Keep the original fallback
        # bytes and remove only this installer-created fallback file.
        for name, data in fallback.items():
            path = esp / name
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
        for name in set(efi_inventory(esp, ['EFI/BOOT'])) - set(fallback):
            require(name.upper() == 'EFI/BOOT/BOOTX64.EFI', 'Unexpected replacement fallback path')
            (esp / name).unlink()
    require(efi_inventory(esp, old_efi) == original, 'Original shim, GRUB or fallback files changed')
    installer['verify_placement'](TARGET)
    DEPLOYMENT.mkdir()
    process('bootc', 'install', 'mount', '--sysroot', TARGET, '--latest', DEPLOYMENT)
    installer['configure_target'](DEPLOYMENT, TARGET)
    config = DEPLOYMENT / 'etc/finite/bootloader.json'
    config.write_text('{"schema":1,"manageFallback":false}\n')
    account_and_home(DEPLOYMENT, run('blkid', '-s', 'UUID', '-o', 'value', DEVICE))
    state = DEPLOYMENT / 'var/lib/finite/efi-updates'
    updater = '/usr/libexec/finite/update-efi'
    if phase == 'efi-fault':
        update = runpy.run_path(updater)
        functions = update['apply'].__globals__
        atomic_bytes = functions['atomic_bytes']

        def stop_after_write(path, data):
            atomic_bytes(path, data)
            if path.is_relative_to(esp / 'EFI/finite'):
                raise InterruptedError('Fixture interruption after the first EFI write')

        functions['atomic_bytes'] = stop_after_write
        payload = update['load_payload'](DEPLOYMENT / 'usr/lib/finite/efi',
                                         DEPLOYMENT / 'usr/share/finite/secure-boot/finite-boot.pem')
        state.mkdir(mode=0o700, parents=True)
        uuid = run('blkid', '-s', 'UUID', '-o', 'value', esp_device).upper()
        try:
            update['apply'](esp, state, update['mapping'](payload, False), esp_uuid=uuid)
        except InterruptedError:
            journal, = state.glob('*/journal.json')
            require(json.loads(journal.read_text())['phase'] == 'prepared', 'Prepared journal missing')
        else:
            raise ValueError('Fixture did not reach an EFI write')
        process('python3', updater, '--esp', esp, '--state', state, '--recover', journal.parent.name)
        require(json.loads(journal.read_text())['phase'] == 'recovered', 'Recovery journal was not resolved')
        require(not efi_inventory(esp, ['EFI/finite']), 'Recovery left a partial native shim path')
        mark('efi-recovered', generation=journal.parent.name, bootOrder=order)
    else:
        process('python3', updater, '--esp', esp, '--state', state, '--install-root', DEPLOYMENT)
        process('chroot', DEPLOYMENT, 'restorecon', '-RF', '/etc/finite', '/var/lib/finite/efi-updates')
        process('btrfs', 'subvolume', 'set-default', TOP / 'root-native')
        _, after = boot_firmware()
        require(after == order, 'Native installation changed the existing BootOrder')
        firmware_label = 'Finite native rehearsal'
        loader_name = 'not-installed.efi' if phase == 'selector-fault' else 'shimx64.efi'
        require((esp / 'EFI/finite' / loader_name).exists() == (phase != 'selector-fault'),
                'Unexpected native selection target')
        process('efibootmgr', '--create-only', '--disk', disk, '--part', '1', '--label', firmware_label,
                '--loader', r'\EFI\finite' + '\\' + loader_name)
        values, after = boot_firmware()
        numbers = [match[1] for line in values
                   if (match := re.match(r'Boot([0-9A-Fa-f]{4})\*?\s+' + firmware_label, line))]
        require(len(numbers) == 1 and after == order, 'Could not create a separate native boot entry')
        process('efibootmgr', '--bootnext', numbers[0])
        mark('native-armed', bootOrder=order, bootNext=numbers[0], selectedLoader=loader_name, oldEfi=original)
    require(efi_inventory(esp, old_efi) == original, 'Original EFI files differ after staging')
    process('umount', '--recursive', DEPLOYMENT)
    process('umount', '--recursive', TARGET)
    process('umount', TOP)
    process('cryptsetup', 'close', MAPPER)


def main():
    phase = Path('/sys/class/dmi/id/product_serial').read_text().strip().removeprefix('finite-migration-')
    require(phase in {'legacy', 'shrink-fault', 'efi-fault', 'selector-fault', 'native'},
            'Unexpected rescue rehearsal phase')
    disk = disk_for(phase)
    firmware, order = boot_firmware()
    current = next(line.split(': ', 1)[1] for line in firmware if line.startswith('BootCurrent: '))
    require(re.fullmatch(r'[0-9A-Fa-f]{4}', current), 'Invalid rescue boot entry number')
    mark('rescue-boot', bootCurrent=current, bootOrder=order)
    # A real tty with echo disabled keeps even the disposable password out of
    # retained serial transcripts. cryptsetup reads it through stdin pipes.
    secret = getpass.getpass('LUKS passphrase: ').encode()
    require(bool(secret), 'Empty disposable LUKS passphrase')
    if phase == 'legacy':
        WORK.mkdir()
        alternate = getpass.getpass('LUKS alternate passphrase: ').encode()
        require(alternate and alternate != secret, 'Expected a distinct alternate LUKS passphrase')
        legacy(disk, secret, alternate, current)
    elif resize(disk, secret, interrupt=phase == 'shrink-fault'):
        native(disk, phase)
    process('sync')
    mark('shutdown', action=phase)
    process('systemctl', '--no-block', 'poweroff')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'FINITE_MIGRATION_FAILED {error}')
