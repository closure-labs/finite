#!/usr/bin/python3
"""Prove the boot and shared state from inside the migrated rehearsal disk."""
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

from serial_records import emit_record


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    require(run('systemd-detect-virt', '--vm') in {'kvm', 'qemu'}, 'Expected an isolated VM')
    identifier = Path('/sys/class/dmi/id/product_serial').read_text().strip()
    require(identifier in {'finite-migration-old-initialize', 'finite-migration-old', 'finite-migration-new'},
            'Unexpected migration boot phase')
    command_line = Path('/proc/cmdline').read_text().split()
    native = identifier == 'finite-migration-new'
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
        require(run('findmnt', '-n', '-o', 'FSROOT', '--mountpoint', '/sysroot') == '/root-native',
                'Native sysroot is not in root-native')
    else:
        require(any(arg.startswith('ostree=') for arg in command_line) and 'rootflags=subvol=/root' in command_line
                and Path('/run/ostree-booted').exists(), 'Original OSTree root did not boot')
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
    emit_record('FINITE_MIGRATION_BOOT', {
        'native': native, 'bootOrder': order, 'bootCurrent': current,
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
