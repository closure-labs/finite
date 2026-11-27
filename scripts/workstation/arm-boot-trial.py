#!/usr/bin/env python3
"""Verify the enrolled, staged trial and select it for one boot only."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


SPEC = importlib.util.spec_from_file_location(
    'stage_trial', Path(__file__).with_name('stage-boot-trial.py'))
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)
PREPARE = STAGE.PREPARE


def verify_enrollment(certificate):
    """Compare exact DER bytes with enrolled MOKs, independent of test-key status."""
    expected = certificate.read_bytes()
    with tempfile.TemporaryDirectory(prefix='finite-mok-check-') as directory:
        subprocess.run(['mokutil', '--export'], cwd=directory, check=True,
                       capture_output=True, text=True)
        certificates = Path(directory).glob('*.der')
        if not any(path.read_bytes() == expected for path in certificates):
            raise SystemExit('The exact trial signing certificate is not in the enrolled MOK list')
    print('Exact trial signing certificate verified in enrolled MOK list.')


def check_staged():
    state = PREPARE.STATE
    manifest = json.loads((state / 'manifest.json').read_text())
    journal = json.loads((state / 'staging.json').read_text())
    if journal['phase'] != 'staged-not-selected':
        raise SystemExit('Staging did not complete; inspect the staging journal')
    esp = PREPARE.ESP
    if PREPARE.run('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', str(esp)) != 'vfat':
        raise SystemExit('ESP is not mounted as FAT')
    device = PREPARE.run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(esp))
    if PREPARE.run('lsblk', '-n', '-o', 'PARTUUID', device) != manifest['esp_partuuid']:
        raise SystemExit('ESP identity changed')
    for name, expected in manifest['files'].items():
        if PREPARE.digest(esp / 'EFI/finite-systemd' / name) != expected:
            raise SystemExit(f'Staged artifact changed: {name}')
    certificate = state / 'output/MOK.der'
    if PREPARE.digest(certificate) != PREPARE.digest(esp / 'EFI/finite-systemd/MOK.der'):
        raise SystemExit('Staged enrollment certificate changed')
    if (esp / 'loader/loader.conf').read_text() != STAGE.LOADER_CONFIG:
        raise SystemExit('Trial loader configuration changed')
    if (esp / 'loader/entries/finite-trial.conf').read_text() != STAGE.ENTRY:
        raise SystemExit('Trial boot entry changed')
    verify_enrollment(certificate)
    # Shim's validation must not have been disabled via MokManager.
    bypass = Path('/sys/firmware/efi/efivars/MokSBStateRT-605dab50-e046-4300-abb6-3dd810dd8b23')
    if bypass.exists() and bypass.read_bytes()[4:] != b'\x00':
        raise SystemExit('Shim validation is disabled or its state is unrecognized')
    return manifest, journal


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to verify and select the one-time trial')
    os.umask(0o077)
    STAGE.INSPECT.main()
    manifest, journal = check_staged()
    number = journal['firmware_entry']
    if not re.fullmatch(r'[0-9A-Fa-f]{4}', number or ''):
        raise SystemExit('Invalid trial firmware entry number')
    before = PREPARE.run('efibootmgr', '-v')
    order = STAGE.firmware_field(before, 'BootOrder')
    if order != journal['boot_order_before']:
        raise SystemExit('BootOrder changed since staging; inspect before selecting trial')
    if STAGE.firmware_field(before, 'BootNext') is not None:
        raise SystemExit('Another one-time boot is queued; inspect before replacing it')
    lines = [line for line in before.splitlines()
             if re.match(rf'^Boot{number}\*\s', line, re.IGNORECASE)]
    if (len(lines) != 1 or STAGE.LABEL not in lines[0]
            or STAGE.LOADER_PATH.lower() not in lines[0].lower()
            or manifest['esp_partuuid'].lower() not in lines[0].lower()):
        raise SystemExit('Firmware entry does not match the staged shim on this ESP')
    evidence = {
        'boot_id_before_trial': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'firmware_entry': number, 'boot_order': order,
        'certificate_enrollment_verified': True,
        'staged_artifact_hashes_verified': True,
    }
    (PREPARE.STATE / 'armed.json').write_text(json.dumps(evidence, indent=2) + '\n')
    subprocess.run(['efibootmgr', '--bootnext', number], check=True)
    after = PREPARE.run('efibootmgr', '-v')
    if (STAGE.firmware_field(after, 'BootNext') or '').upper() != number.upper():
        raise SystemExit('Firmware did not confirm BootNext')
    if STAGE.firmware_field(after, 'BootOrder') != order:
        raise SystemExit('Unexpected BootOrder change; inspect before reboot')
    print(f'One-time trial selected: Boot{number} ({STAGE.LABEL}).')
    print('Original BootOrder preserved. Keep Secure Boot enabled for the trial.')
    print('If firmware setup consumes BootNext, select Finite systemd-boot trial in the F12 menu.')
    print('No reboot requested. Do not queue an OS update before the trial.')


if __name__ == '__main__':
    main()
