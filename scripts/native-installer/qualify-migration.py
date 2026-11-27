#!/usr/bin/env python3
"""Rehearse workstation migration and recovery on capped file-backed guests."""
import argparse
import json
import os
from pathlib import Path
import runpy
import secrets
import shutil
import subprocess
import sys

import migration_layout as layout

iso_harness = runpy.run_path(str(Path(__file__).with_name('qualify-iso.py')))
Guest = iso_harness['Guest']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def qualify(args):
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'closure-labs/finite'
            and os.environ.get('GITHUB_REF') == 'refs/heads/qualification/native-migration',
            'Migration rehearsal requires the dedicated hosted branch')
    require(os.access('/dev/kvm', os.R_OK | os.W_OK), 'KVM is unavailable')
    iso = args.iso.resolve(strict=True)
    record = json.loads((iso.parent / 'installation.json').read_text())
    seal = json.loads(args.seal.read_text())
    iso_hash = iso_harness['file_sha256'](iso)
    checksum = (iso.parent / 'SHA256SUMS').read_text().splitlines()
    require(record['validationOnly'] is True and record['migrationRehearsal'] is True
            and seal['profile'] == 'finite-native' and seal['validationOnly'] is True
            and record['finiteRevision'] == seal['sourceRevision']
            and f'{iso_hash}  {iso.name}' in checksum
            and f'{iso_harness["file_sha256"](iso.parent / "installation.json")}  installation.json' in checksum,
            'Rescue ISO identity differs')
    inputs = args.legacy_archive.resolve(strict=True).parent
    require(args.legacy_archive.name == 'legacy.oci.tar'
            and {path.name for path in inputs.iterdir()} == {'legacy.oci.tar', 'legacy.sha256'},
            'Legacy inputs must occupy a dedicated directory')
    legacy_hash = (inputs / 'legacy.sha256').read_text().strip()
    require(legacy_hash == iso_harness['file_sha256'](args.legacy_archive), 'Legacy OCI archive hash differs')
    state = args.state.resolve()
    state.mkdir(mode=0o700)
    args.evidence.mkdir(parents=True, exist_ok=True)
    firmware = Path(os.environ['FINITE_VM_FIRMWARE_DIR'])
    variables = state / 'original-vars.fd'
    original = state / 'original.qcow2'
    media = state / 'legacy-input.raw'
    guid = iso_harness['MOK_GUID']
    subprocess.run(['virt-fw-vars', '--input', firmware / 'OVMF_VARS_4M.ms.fd',
                    '--output', variables, '--add-mok', guid, args.certificate,
                    '--add-mok', guid, args.module_certificate], check=True, timeout=30)
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', original, str(layout.DISK_SECTORS * layout.SECTOR_BYTES)],
                   check=True, timeout=30)
    iso_harness['prepare_readonly_inputs'](media, inputs, args.legacy_archive.stat().st_size)
    password = secrets.token_hex(16)
    alternate = secrets.token_hex(16)

    def guest_command(disk, vars_file, phase):
        command = iso_harness['qemu_arguments'](firmware, vars_file, disk, 'FINITEMIGRATION')
        command.extend(['-smbios', f'type=1,serial=finite-migration-{phase}'])
        return command + iso_harness['install_media'](iso, prioritize=phase == 'legacy')

    def rescue(disk, vars_file, phase, events, *, baseline=None):
        command = guest_command(disk, vars_file, phase)
        if phase == 'legacy':
            command.extend(['-drive', f'if=none,id=inputs,format=raw,file={media},readonly=on',
                            '-device', 'virtio-blk-pci,drive=inputs,serial=FINITEMIGRATIONDATA'])
        observations = {}
        print('Rehearsal rescue phase ' + phase, flush=True)
        with (args.evidence / f'{phase}-serial.log').open('xb') as log:
            with Guest(command, log, 2400) as guest:
                firmware_boot = guest.record('FINITE_MIGRATION')
                require(firmware_boot['phase'] == 'rescue-boot', 'Missing rescue boot identity')
                observations['rescue-boot'] = firmware_boot
                if baseline is not None:
                    require(firmware_boot['bootCurrent'] == baseline['nextRescue']
                            and firmware_boot['bootOrder'] == baseline['bootOrder'],
                            'Unexpected firmware selection of the rescue ISO')
                guest.expect(rb'LUKS passphrase:')
                guest.send(password)
                if phase == 'legacy':
                    guest.expect(rb'LUKS alternate passphrase:')
                    guest.send(alternate)
                for event in [*events, 'shutdown']:
                    outcome = guest.record('FINITE_MIGRATION')
                    require(outcome['phase'] == event, 'Out-of-order rescue checkpoint for ' + phase)
                    observations[event] = outcome
                guest.shutdown()
        return observations

    def boot(disk, vars_file, phase, name):
        print('Rehearsal disk boot ' + name, flush=True)
        with (args.evidence / f'{name}-serial.log').open('xb') as log:
            with Guest(guest_command(disk, vars_file, phase), log, 900) as guest:
                guest.expect(rb'(?i)(?:please )?(?:enter passphrase|password for|unlock disk)[^\r\n]{0,200}:')
                guest.send(alternate if phase == 'new' else password)
                result = guest.record('FINITE_MIGRATION_BOOT')
                guest.shutdown()
        result['unlockKeyslot'] = 'alternate' if phase == 'new' else 'primary'
        return result

    def fork(name):
        disk = state / f'{name}.qcow2'
        vars_file = state / f'{name}-vars.fd'
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', original, disk],
                       check=True, timeout=30)
        shutil.copyfile(variables, vars_file)
        return disk, vars_file

    created = rescue(original, variables, 'legacy', ['legacy-created'])
    media.unlink()
    before = boot(original, variables, 'old-initialize', 'legacy-before')
    require(before['nextRescue'] == created['rescue-boot']['bootCurrent'],
            'Legacy boot selected an unexpected rescue entry for subsequent forks')
    root_spec = created['legacy-created']['rootMountSpec']
    require(before['rootMountSpec'] == root_spec and before['rootSubvolume'] == '/root',
            'Original firmware path did not boot the exact legacy Btrfs root')
    boots = {'legacyBefore': before}
    recovery = {}
    for phase, events in (
            ('shrink-fault', ['before-gpt-change']),
            ('efi-fault', ['before-gpt-change', 'partitioned', 'efi-recovered']),
            ('selector-fault', ['before-gpt-change', 'partitioned', 'native-armed'])):
        disk, vars_file = fork(phase)
        recovery[phase] = rescue(disk, vars_file, phase, events, baseline=before)
        boots[phase] = boot(disk, vars_file, 'old', phase + '-old-boot')
        if phase == 'selector-fault':
            require(boots[phase]['bootCurrent'] != recovery[phase]['native-armed']['bootNext'],
                    'Failed native selection did not return to the existing boot entry')
        disk.unlink()
        vars_file.unlink()
    disk, vars_file = fork('native')
    staged = rescue(disk, vars_file, 'native', ['before-gpt-change', 'partitioned', 'native-armed'],
                    baseline=before)
    boots['nativeBootNext'] = boot(disk, vars_file, 'new', 'native-bootnext')
    boots['legacyAfter'] = boot(disk, vars_file, 'old', 'legacy-after')
    for name, phase in boots.items():
        require(phase['bootOrder'] == before['bootOrder']
                and phase['native'] == (name == 'nativeBootNext'), 'Unexpected BootOrder or boot path for ' + name)
        if name != 'nativeBootNext':
            require(phase['bootCurrent'] == before['bootCurrent'], 'Original Fedora entry changed for ' + name)
            require(phase['rootMountSpec'] == root_spec and phase['rootSubvolume'] == '/root',
                    'Original Btrfs root changed for ' + name)
    native = boots['nativeBootNext']
    require(native['bootCurrent'] == staged['native-armed']['bootNext']
            and 'composefs.digest=v1-sha512-12:' + seal['bootableRootDigest'] in native['preflight']['cmdline'].split(),
            'BootNext did not select the exact sealed native root')
    report = {'schema': 1, 'sourceRevision': seal['sourceRevision'], 'rescueIsoSha256': iso_hash,
              'legacyArchiveSha256': legacy_hash, 'nativeRootDigest': seal['bootableRootDigest'],
              'guestMemoryMiB': iso_harness['MEMORY_MIB'], 'hostReserveMiB': iso_harness['RESERVE_MIB'], 'vcpu': 2,
              'legacyFixture': created, 'recovery': recovery, 'staged': staged, 'boots': boots}
    output = json.dumps(report, indent=2) + '\n'
    (args.evidence / 'migration-acceptance.json').write_text(output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('iso', 'seal', 'legacy-archive', 'certificate', 'module-certificate', 'state', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    try:
        qualify(parser.parse_args())
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'Stopped workstation-layout rehearsal: {error}')
