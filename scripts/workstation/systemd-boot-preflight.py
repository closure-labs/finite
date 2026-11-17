#!/usr/bin/env python3
"""Read-only migration checks. Never installs or removes a bootloader."""

import argparse
import json
from pathlib import Path
import sys


EFI = Path('/sys/firmware/efi/efivars')
LOADER_GUID = '4a67b082-0a4c-41cf-b6c7-440b29bb8c4f'
GLOBAL_GUID = '8be4df61-93ca-11d2-aa0d-00e098032b8c'


def variable(name, guid, text=False):
    try:
        data = (EFI / f'{name}-{guid}').read_bytes()[4:]
    except OSError:
        return None
    if text:
        return data.decode('utf-16-le', errors='replace').rstrip('\0')
    return data.hex()


def trial_blockers(loader, secure, setup, audit, loader_image, stub, stub_image,
                   entry, cmdline, lockdown):
    failures = []
    if not loader or not loader.startswith('systemd-boot '):
        failures.append('This boot was not identified as systemd-boot.')
    if secure != '01' or setup != '00' or audit != '00':
        failures.append('Secure Boot enforcement outside setup/audit mode is not confirmed.')
    if loader_image != r'\EFI\finite-systemd\grubx64.efi':
        failures.append('Current loader is not the staged systemd-boot binary.')
    if not stub or not stub.startswith('systemd-stub '):
        failures.append('Current UKI stub is not identified.')
    if stub_image != r'\EFI\finite-systemd\finite-trial.efi' or entry != 'finite-trial.conf':
        failures.append('Current UKI or selected entry differs from the staged trial.')
    if 'finite.boot-trial=1' not in cmdline:
        failures.append('Signed trial command-line marker is missing.')
    if '[integrity]' not in lockdown and '[confidentiality]' not in lockdown:
        failures.append('Kernel lockdown enforcement is not confirmed.')
    return failures


def inspect(trial=False):
    cmdline = Path('/proc/cmdline').read_text().split()
    loader = variable('LoaderInfo', LOADER_GUID, text=True)
    secure = variable('SecureBoot', GLOBAL_GUID)
    setup = variable('SetupMode', GLOBAL_GUID)
    audit = variable('AuditMode', GLOBAL_GUID)
    loader_image = variable('LoaderImageIdentifier', LOADER_GUID, text=True)
    stub = variable('StubInfo', LOADER_GUID, text=True)
    stub_image = variable('StubImageIdentifier', LOADER_GUID, text=True)
    entry = variable('LoaderEntrySelected', LOADER_GUID, text=True)
    try:
        lockdown = Path('/sys/kernel/security/lockdown').read_text().strip()
    except OSError:
        lockdown = ''
    trial_failures = trial_blockers(loader, secure, setup, audit, loader_image,
                                   stub, stub_image, entry, cmdline, lockdown)
    blockers = []
    if not loader or not loader.startswith('systemd-boot '):
        blockers.append('This boot was not identified as systemd-boot.')
    if secure != '01' or setup != '00':
        blockers.append('Secure Boot enabled in user mode is not confirmed.')
    if any(arg.startswith('ostree=') for arg in cmdline):
        backend = 'ostree'
        blockers.append('bootc does not support systemd-boot on its OSTree backend; '
                        'an update/rollback migration is required.')
    elif any(arg.startswith(('composefs=', 'composefs.digest=')) for arg in cmdline):
        backend = 'composefs'
    else:
        backend = 'unknown'
        blockers.append('Cannot identify the running bootc backend.')
    return {
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'loader': loader,
        'secure_boot': secure,
        'setup_mode': setup,
        'audit_mode': audit,
        'loader_image': loader_image,
        'stub': stub,
        'stub_image': stub_image,
        'selected_entry': entry,
        'kernel_lockdown': lockdown,
        'cmdline': ' '.join(cmdline),
        'backend': backend,
        'blockers': trial_failures if trial else blockers,
        'trial_boot_verified': not trial_failures,
        'migration_blockers': blockers,
        'grub_removal_ready': False,
        'note': 'The trial checks the boot chain. Staged-image identity, functional '
                'login/unlock, and verified update/rollback integration are also '
                'required before retiring GRUB. This tool never removes boot files.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', action='store_true',
                        help='Verify the staged trial boot; retain migration blockers separately')
    args = parser.parse_args()
    report = inspect(trial=args.trial)
    print(json.dumps(report, indent=2))
    sys.exit(1 if report['blockers'] else 0)
