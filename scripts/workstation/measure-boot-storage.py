#!/usr/bin/env python3
"""Measure lossless initramfs recompression; optionally remove backed-up Windows EFI files."""

import argparse
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


SPEC = importlib.util.spec_from_file_location(
    'prepare_trial', Path(__file__).with_name('prepare-boot-trial.py'))
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)
MIB = 1024**2


def recompress(raw, destination):
    """Use Linux-compatible XZ/CRC32 while preserving the uncompressed cpio bytes."""
    with raw.open('rb') as source, lzma.open(
            destination, 'wb', format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=6) as target:
        shutil.copyfileobj(source, target)
    original_hash = PREPARE.digest(raw)
    with lzma.open(destination, 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != original_hash:
            raise ValueError('Recompression changed initramfs contents')
    return original_hash


def decoder(header):
    if header.startswith(b'\x1f\x8b'):
        return ['gzip', '-dc']
    if header.startswith(b'\xfd7zXZ\0'):
        return ['xz', '-dc']
    if header.startswith(b'\x28\xb5\x2f\xfd'):
        return ['zstd', '-dc']
    if header.startswith((b'070701', b'070702', b'070707')):
        return ['cat']
    raise ValueError('Unsupported initramfs compression; refusing to guess')


def measure(initrd, directory):
    directory.mkdir()
    main = directory / 'main.compressed'
    raw = directory / 'main.cpio'
    compact = directory / 'main.xz'
    with main.open('wb') as stream:
        subprocess.run(['/usr/lib/dracut/skipcpio', str(initrd)], stdout=stream, check=True)
    prefix_size = initrd.stat().st_size - main.stat().st_size
    if prefix_size < 0:
        raise ValueError('skipcpio output is larger than the source')
    # skipcpio must have returned an exact suffix of the original file.
    with initrd.open('rb') as original, main.open('rb') as extracted:
        original.seek(prefix_size)
        while True:
            chunk = original.read(MIB)
            if chunk != extracted.read(MIB):
                raise ValueError('skipcpio did not preserve the main archive bytes')
            if not chunk:
                break
    with main.open('rb') as stream:
        command = decoder(stream.read(8))
    with main.open('rb') as source, raw.open('wb') as target:
        subprocess.run(command, stdin=source, stdout=target, check=True)
    with raw.open('rb') as stream:
        if not stream.read(6).startswith((b'070701', b'070702', b'070707')):
            raise ValueError('Decoded initramfs is not a recognized cpio archive')
    raw_hash = recompress(raw, compact)
    result = {
        'original_initrd_bytes': initrd.stat().st_size,
        'early_cpio_bytes_preserved': prefix_size,
        'main_cpio_sha256': raw_hash,
        'recompressed_initrd_bytes': prefix_size + compact.stat().st_size,
        'contents_verified_identical': True,
    }
    # Measurements keep only the small report; never retain extra copies of private initrd data.
    shutil.rmtree(directory)
    return result


def cleanup_windows(state, esp):
    windows = esp / 'EFI/Microsoft'
    if not windows.exists():
        return {'result': 'No EFI/Microsoft directory exists; nothing removed'}
    if windows.is_symlink() or not windows.is_dir():
        raise SystemExit('Unexpected Windows EFI path')
    inventory = json.loads(PREPARE.run('lsblk', '--json', '--output', 'NAME,FSTYPE,PARTTYPE'))

    def check_disks(disks):
        for disk in disks:
            if ((disk.get('fstype') or '').lower() in {'ntfs', 'ntfs3', 'bitlocker'}
                    or (disk.get('parttype') or '').lower() in {
                        'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7',
                        'e3c9e316-0b5c-4db8-817d-f92df00215ae',
                        'de94bba4-06d1-4d40-a16a-bfd50179d6ac'}):
                raise SystemExit('Windows-compatible partition detected; inspect before cleanup')
            check_disks(disk.get('children', []))

    check_disks(inventory['blockdevices'])
    backup = state / 'windows-efi-before.tar'
    if backup.exists():
        raise SystemExit('Windows backup already exists; inspect previous cleanup before retrying')
    before = PREPARE.run('efibootmgr', '-v')
    entries = []
    for line in before.splitlines():
        if '\\efi\\microsoft\\' in line.lower():
            match = re.match(r'^Boot([0-9a-fA-F]{4})\*?\s', line)
            if not match:
                raise SystemExit('Cannot identify Windows firmware entry')
            entries.append(match.group(1))
    (state / 'efibootmgr-before-windows-cleanup.txt').write_text(before + '\n')
    # FAT has no symlinks; still reject any unexpected object before following a tree.
    for path in windows.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise SystemExit('Unexpected object in Windows EFI directory')
    files = {str(p.relative_to(windows)): PREPARE.digest(p)
             for p in windows.rglob('*') if p.is_file()}
    with tarfile.open(backup, 'w') as archive:
        archive.add(windows, arcname='EFI/Microsoft')
    # Verify every file's content in the backup before deletion.
    with tarfile.open(backup, 'r') as archive:
        for name, expected in files.items():
            with archive.extractfile('EFI/Microsoft/' + name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise SystemExit('Windows EFI backup verification failed')
    os.sync()
    for number in entries:
        subprocess.run(['efibootmgr', '--bootnum', number, '--delete-bootnum'], check=True)
    shutil.rmtree(windows)
    os.sync()
    return {'removed_directory': str(windows), 'removed_firmware_entries': entries,
            'backup': str(backup), 'verified_files': len(files),
            'firmware_certificates_modified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove-windows-efi', action='store_true',
                        help='Back up and remove only leftover Windows EFI files/entries')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to read private initramfs files')
    os.umask(0o077)
    state, esp = PREPARE.STATE, PREPARE.ESP
    if state.stat().st_uid != 0 or state.stat().st_mode & 0o077:
        raise SystemExit('Measurement state must be root-owned and private')
    if PREPARE.run('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', str(esp)) != 'vfat':
        raise SystemExit('ESP not mounted as FAT')
    device = PREPARE.run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(esp))
    if PREPARE.run('lsblk', '-n', '-o', 'PARTUUID', device) != PREPARE.EXPECTED_ESP:
        raise SystemExit('ESP identity changed')
    status = json.loads(PREPARE.run('bootc', 'status', '--json'))
    if status['status'].get('staged') or status['status'].get('rollbackQueued'):
        raise SystemExit('A deployment change is queued; resolve before measurement')
    report = {}
    if args.remove_windows_efi:
        report['windows_cleanup'] = cleanup_windows(state, esp)
        (state / 'windows-cleanup.json').write_text(
            json.dumps(report['windows_cleanup'], indent=2) + '\n')
        print(json.dumps(report['windows_cleanup'], indent=2), flush=True)
    report['deployments'] = []
    before = shutil.disk_usage(esp)
    trial = esp / 'EFI/finite-systemd/finite-trial.efi'
    with tempfile.TemporaryDirectory(prefix='storage-measure-', dir=state) as temporary:
        for index, entry in enumerate(sorted(Path('/boot/loader/entries').glob('*.conf'))):
            fields = {}
            for line in entry.read_text().splitlines():
                key, _, value = line.partition(' ')
                fields.setdefault(key, []).append(value.strip())
            if any(len(fields.get(key, [])) != 1 for key in ('linux', 'initrd')):
                raise SystemExit('Expected exactly one kernel/initrd per boot entry')
            kernel = PREPARE.boot_file(fields['linux'][0])
            initrd = PREPARE.boot_file(fields['initrd'][0])
            print(f'Measuring {entry.name}; contents and ESP boot files remain unchanged.', flush=True)
            result = measure(initrd, Path(temporary) / str(index))
            result.update({'entry': entry.name, 'kernel_bytes': kernel.stat().st_size})
            result['estimated_uki_bytes'] = result['recompressed_initrd_bytes'] + kernel.stat().st_size + MIB
            report['deployments'].append(result)
    sizes = [deployment['estimated_uki_bytes'] for deployment in report['deployments']]
    if not sizes:
        raise SystemExit('No boot entries found')
    report['esp_free_bytes_after_cleanup'] = before.free
    report['existing_trial_uki_bytes'] = trial.stat().st_size
    report['usable_bytes_after_retiring_old_trial_with_reserve'] = before.free + trial.stat().st_size - 64 * MIB
    report['estimated_current_rollback_plus_replacement_bytes'] = sum(sizes) + max(sizes)
    report['estimated_to_fit'] = (report['estimated_current_rollback_plus_replacement_bytes']
                                  <= report['usable_bytes_after_retiring_old_trial_with_reserve'])
    report['note'] = ('Estimates only. No initramfs, UKI, boot entry or partition was replaced. '
                      'Windows cleanup, when requested, is reported separately.')
    (state / 'storage-measurement.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
