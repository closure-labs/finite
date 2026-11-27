#!/usr/bin/python3
"""Prove the boot and shared state from inside the migrated rehearsal disk."""
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

from migration_layout import rescue_esp
from serial_records import emit_record


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def arm_rescue(order, current):
    # OVMF can reuse its automatically numbered PCI boot entries. Create a
    # short-form UEFI device path tied to the actual read-only ISO ESP.
    disk = Path('/dev/disk/by-id/virtio-FINITEINSTALLMEDIA').resolve(strict=True)
    require(re.fullmatch(r'/dev/vd[a-z]', str(disk)) and run('blockdev', '--getro', disk) == '1',
            'Expected the read-only rescue VirtIO disk')
    esp, partuuid = rescue_esp(json.loads(run('sfdisk', '--json', disk)))
    part = run('lsblk', '--noheadings', '--nodeps', '--output', 'PARTN', esp)
    require(part.isdecimal() and int(part) > 0 and run('blockdev', '--getro', esp) == '1',
            'Expected the read-only rescue EFI partition')
    label = 'Finite migration rescue'
    loader = r'\EFI\BOOT\BOOTX64.EFI'
    entries = run('efibootmgr', '-v').splitlines()
    require(not any(label in row for row in entries) and order.split(',')[0] == current,
            'Expected the original Fedora default and no previous rescue entry')
    run('efibootmgr', '--create-only', '--disk', disk, '--part', part, '--label', label, '--loader', loader)
    entries = run('efibootmgr', '-v').splitlines()
    boot_id, = (match[1] for row in entries
                if (match := re.match(r'Boot([0-9A-Fa-f]{4})\*?\s+' + label + r'\s+', row))
                and f'HD({part},GPT,{partuuid},'.casefold() in row.casefold()
                and loader.casefold() in row.casefold())
    require(boot_id not in order.split(',') and f'BootOrder: {order}' in entries,
            'Rescue entry creation changed the default BootOrder')
    run('efibootmgr', '--bootnext', boot_id)
    armed = run('efibootmgr').splitlines()
    require(f'BootOrder: {order}' in armed and f'BootNext: {boot_id}' in armed,
            'Could not arm the one-time rescue boot without changing BootOrder')
    return boot_id, partuuid


def main():
    require(run('systemd-detect-virt', '--vm') in {'kvm', 'qemu'}, 'Expected an isolated VM')
    identifier = Path('/sys/class/dmi/id/product_serial').read_text().strip()
    require(identifier in {'finite-migration-old-initialize', 'finite-migration-old', 'finite-migration-new'},
            'Unexpected migration boot phase')
    command_line = Path('/proc/cmdline').read_text().split()
    native = identifier == 'finite-migration-new'
    root_mount_spec = None
    root_subvolume = run('findmnt', '-n', '-o', 'FSROOT', '--mountpoint', '/sysroot')
    if native:
        preflight = runpy.run_path('/etc/finite-migration/preflight.py')['inspect']()
        require(not preflight['blockers'], 'Full native preflight failed: ' + str(preflight['blockers']))
        require(preflight['loader_image'] == r'\EFI\finite\grubx64.efi'
                and preflight['stub'] and preflight['stub'].startswith('systemd-stub '),
                'Unexpected running EFI loader or UKI')
        require(any(level in preflight['kernel_lockdown'] for level in ('[integrity]', '[confidentiality]')),
                'Kernel lockdown is inactive')
        deployment = json.loads(run('bootc', 'status', '--json'))['status']['booted']['composefs']
        require(deployment['bootloader'] == 'systemd' and deployment['bootType'] == 'Uki'
                and deployment['missingVerityAllowed'] is False, 'Unexpected native integrity policy')
        require(not any(arg.startswith(('root=', 'rootflags=', 'rd.luks.')) for arg in command_line),
                'Native boot is using machine-specific root or LUKS arguments')
        require(root_subvolume == '/root-native', 'Native sysroot is not in root-native')
    else:
        roots = [arg.removeprefix('root=') for arg in command_line if arg.startswith('root=')]
        flags = [arg for arg in command_line if arg.startswith('rootflags=')]
        require(len(roots) == 1 and roots[0].startswith('UUID=') and flags == ['rootflags=subvol=/root']
                and root_subvolume == '/root' and any(arg.startswith('ostree=') for arg in command_line)
                and Path('/run/ostree-booted').exists(), 'Original OSTree root did not boot explicitly')
        root_mount_spec = roots[0]
        preflight = None
    require(run('mokutil', '--sb-state').splitlines()[0] == 'SecureBoot enabled', 'Secure Boot disabled')
    require(run('getenforce') == 'Enforcing', 'SELinux not enforcing')
    require(run('findmnt', '-n', '-o', 'FSROOT', '--mountpoint', '/var/home') == '/home',
            'Shared home subvolume is missing')
    require(run('findmnt', '-n', '--mountpoint', '/nix'), 'Persistent Nix mount is missing')
    passwd = run('getent', 'passwd', 'finite-rehearsal').split(':')
    require(passwd[2:4] == ['1234', '2345'], 'Account numeric ownership differs')
    home = Path('/var/home/finite-rehearsal/documents/example.txt')
    require((home.stat().st_uid, home.stat().st_gid) == (1234, 2345), 'Document ownership changed')
    marker = 'disposable workstation layout fixture\n'
    require(home.read_text() == marker, 'Shared document contents changed')
    nix_state = Path('/nix/var/nix/finite-rehearsal.txt')
    if identifier == 'finite-migration-old-initialize':
        with nix_state.open('x') as stream:
            stream.write(marker)
    require(nix_state.read_text() == marker, 'Shared Nix state changed')
    firmware = run('efibootmgr', '-v').splitlines()
    order = next(row.split(': ', 1)[1] for row in firmware if row.startswith('BootOrder: '))
    current = next(row.split(': ', 1)[1] for row in firmware if row.startswith('BootCurrent: '))
    path = r'\efi\finite\shimx64.efi' if native else r'\efi\fedora\shimx64.efi'
    require(any(re.match('Boot' + re.escape(current) + r'\*?\s+', row) and path in row.lower()
                for row in firmware), 'The expected shim firmware entry did not boot')
    require(not any(row.startswith('BootNext: ') for row in firmware), 'One-time boot entry not consumed')
    boot_type = run('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', '/boot')
    require(boot_type == ('vfat' if native else 'ext4'), 'Boot filesystem differs')
    next_rescue = rescue_partuuid = None
    if identifier == 'finite-migration-old-initialize':
        next_rescue, rescue_partuuid = arm_rescue(order, current)
    emit_record('FINITE_MIGRATION_BOOT', {
        'native': native, 'bootOrder': order, 'bootCurrent': current,
        'nextRescue': next_rescue, 'rescueEspPartuuid': rescue_partuuid,
        'rootMountSpec': root_mount_spec, 'rootSubvolume': root_subvolume,
        'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'preflight': preflight, 'secureBoot': True, 'selinuxEnforcing': True,
        'uid': 1234, 'gid': 2345, 'sharedHome': True, 'sharedNix': True,
    })
    run('sync')
    run('systemctl', '--no-block', 'poweroff')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'FINITE_MIGRATION_FAILED {error}')
