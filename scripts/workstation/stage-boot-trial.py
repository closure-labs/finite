#!/usr/bin/env python3
"""Stage the inspected trial alongside existing loaders, without selecting it."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


SPEC = importlib.util.spec_from_file_location(
    'inspect_trial', Path(__file__).with_name('inspect-boot-trial.py'))
INSPECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECT)
PREPARE = INSPECT.PREPARE
LABEL = 'Finite systemd-boot trial'
LOADER_PATH = r'\EFI\finite-systemd\shimx64.efi'
LOADER_CONFIG = ('default finite-trial.conf\ntimeout 10\neditor no\n'
                 'auto-entries no\nauto-firmware yes\nsecure-boot-enroll off\n')
ENTRY = ('title Finite signed workstation trial\n'
         'efi /EFI/finite-systemd/finite-trial.efi\n')


def firmware_field(listing, name):
    match = re.search(rf'^{re.escape(name)}: (.*)$', listing, re.MULTILINE)
    return match.group(1).strip() if match else None


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to stage the inspected trial')
    os.umask(0o077)
    state = PREPARE.STATE
    if (state / 'staging.json').exists():
        raise SystemExit('Staging was already attempted; inspect staging.json before retrying')
    INSPECT.main()  # Includes the gshadow classification; aborts before ESP writes on a failure.
    manifest = json.loads((state / 'manifest.json').read_text())
    esp = PREPARE.ESP
    if PREPARE.run('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', str(esp)) != 'vfat':
        raise SystemExit('Expected a mounted FAT ESP')
    device = PREPARE.run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(esp))
    if PREPARE.run('lsblk', '-n', '-o', 'PARTUUID', device) != manifest['esp_partuuid']:
        raise SystemExit('ESP identity changed')
    if device != '/dev/nvme0n1p1':
        raise SystemExit('Unexpected workstation ESP device')
    before = PREPARE.run('efibootmgr', '-v')
    order = firmware_field(before, 'BootOrder')
    if not order or not re.fullmatch(r'[0-9A-Fa-f]{4}(,[0-9A-Fa-f]{4})*', order):
        raise SystemExit('Cannot preserve current BootOrder')
    if LABEL in before or LOADER_PATH.lower() in before.lower():
        raise SystemExit('A trial firmware entry already exists; inspect it before proceeding')
    output = state / 'output'
    # DER and PEM must identify the same certificate; only the public DER is staged.
    der = subprocess.check_output(['openssl', 'x509', '-in', str(output / 'MOK.pem'),
                                   '-outform', 'DER'])
    if der != (output / 'MOK.der').read_bytes():
        raise SystemExit('Enrollment certificate does not match signing certificate')
    directory = esp / 'EFI/finite-systemd'
    entry = esp / 'loader/entries/finite-trial.conf'
    config = esp / 'loader/loader.conf'
    for path in (directory, entry, config):
        if path.exists() or path.is_symlink():
            raise SystemExit(f'Refusing to replace existing path: {path}')
    names = ['shimx64.efi', 'mmx64.efi', 'grubx64.efi', 'finite-trial.efi', 'MOK.der']
    required = sum((output / name).stat().st_size for name in names) + 64 * 1024**2
    if shutil.disk_usage(esp).free < required:
        raise SystemExit('Insufficient ESP space including 64 MiB reserve')
    journal = {
        'phase': 'planned', 'boot_order_before': order,
        'boot_next_before': firmware_field(before, 'BootNext'),
        'new_paths': [str(directory), str(entry), str(config)],
        'firmware_entry': None,
    }

    def checkpoint(phase):
        journal['phase'] = phase
        (state / 'staging.json').write_text(json.dumps(journal, indent=2) + '\n')

    checkpoint('planned')
    (state / 'efibootmgr-pre-stage.txt').write_text(before + '\n')
    directory.mkdir()
    for name in names:
        shutil.copyfile(output / name, directory / name)
        if PREPARE.digest(output / name) != PREPARE.digest(directory / name):
            raise SystemExit(f'Staged copy verification failed: {name}')
    entry.parent.mkdir(parents=True, exist_ok=True)
    with entry.open('x') as stream:
        stream.write(ENTRY)
    with config.open('x') as stream:
        stream.write(LOADER_CONFIG)
    os.sync()
    checkpoint('files-copied')
    subprocess.run(['efibootmgr', '--create-only', '--disk', '/dev/nvme0n1',
                    '--part', '1', '--label', LABEL, '--loader', LOADER_PATH], check=True)
    after = PREPARE.run('efibootmgr', '-v')
    (state / 'efibootmgr-post-stage.txt').write_text(after + '\n')
    matches = re.findall(r'^Boot([0-9A-Fa-f]{4})\*?\s+' + re.escape(LABEL) + r'\s',
                         after, re.MULTILINE)
    if len(matches) != 1:
        checkpoint('firmware-entry-needs-review')
        raise SystemExit('Cannot identify the new firmware entry; review saved firmware listing')
    journal['firmware_entry'] = matches[0]
    checkpoint('firmware-entry-created')
    if firmware_field(after, 'BootOrder') != order:
        # Some firmware may insert it despite create-only; restore the exact original order.
        subprocess.run(['efibootmgr', '--bootorder', order], check=True)
        after = PREPARE.run('efibootmgr', '-v')
        if firmware_field(after, 'BootOrder') != order:
            raise SystemExit('Firmware did not retain original BootOrder; review before reboot')
    if firmware_field(after, 'BootNext') != journal['boot_next_before']:
        raise SystemExit('BootNext changed unexpectedly; review before reboot')
    checkpoint('staged-not-selected')
    print(json.dumps({
        'result': 'Staged successfully; original BootOrder preserved',
        'firmware_entry': matches[0], 'label': LABEL,
        'loader': LOADER_PATH, 'boot_order': order,
        'certificate': str(directory / 'MOK.der'),
        'next_step': 'Enroll the public certificate via mokutil/MokManager, '
                     'then verify enrollment before selecting the trial.',
        'reboot_requested': False,
    }, indent=2))


if __name__ == '__main__':
    main()
