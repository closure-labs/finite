#!/usr/bin/env python3
"""Prepare a signed, root-private trial bundle; do not install or select it."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile


ESP = Path('/boot/efi')
STATE = Path('/var/lib/finite-boot-trial')
EXPECTED_ESP = '5bc0db94-2336-4824-b55c-1c6d8395221b'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def select_entry(cmdline, entries):
    """Match the running boot, rejecting ambiguity and expanded GRUB variables."""
    current = cmdline.split()
    ostree = [arg for arg in current if arg.startswith('ostree=')]
    if len(ostree) != 1:
        raise ValueError('Expected exactly one OSTree target')
    matches = []
    for path in entries:
        fields = {}
        for line in path.read_text().splitlines():
            key, _, value = line.partition(' ')
            fields.setdefault(key, []).append(value.strip())
        options = fields.get('options', [''])[0].split()
        if ostree[0] in options:
            if options != [arg for arg in current if not arg.startswith('BOOT_IMAGE=')]:
                raise ValueError('Running arguments differ from BLS; inspect before continuing')
            if any(len(fields.get(key, [])) != 1 for key in ('linux', 'initrd', 'options')):
                raise ValueError('Expected one kernel, initrd and options line')
            matches.append((path, fields))
    if len(matches) != 1:
        raise ValueError('Running deployment must match exactly one BLS entry')
    return matches[0]


def boot_file(value):
    path = (Path('/boot') / value.lstrip('/')).resolve(strict=True)
    if not path.is_relative_to('/boot/ostree') or not path.is_file():
        raise ValueError('Boot input must be a regular file under /boot/ostree')
    return path


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit('Usage: sudo python3 prepare-boot-trial.py TOOL_ARCHIVE')
    os.umask(0o077)
    archive = Path(sys.argv[1]).resolve(strict=True)
    expected = Path(str(archive) + '.sha256').read_text().split()[0]
    if digest(archive) != expected:
        raise SystemExit('Tool archive checksum mismatch')
    image_id = Path(str(archive) + '.image-id').read_text().strip()
    if re.fullmatch(r'[0-9a-f]{64}', image_id):
        image_id = 'sha256:' + image_id
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise SystemExit('Invalid tools image ID')
    if STATE.exists():
        raise SystemExit(f'{STATE} already exists; inspect it instead of overwriting keys/evidence')
    if run('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', str(ESP)) != 'vfat':
        raise SystemExit('Expected mounted FAT ESP')
    device = run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(ESP))
    if run('lsblk', '-n', '-o', 'PARTUUID', device) != EXPECTED_ESP:
        raise SystemExit('ESP is not the inspected workstation partition')
    status = json.loads(run('bootc', 'status', '--json'))
    if status['status'].get('staged') or status['status'].get('rollbackQueued'):
        raise SystemExit('A deployment change is queued; resolve it before creating the trial')
    booted = status['status']['booted']
    if booted.get('store') != 'ostreeContainer':
        raise SystemExit('This preparation is only for the inspected OSTree host')
    cmdline = Path('/proc/cmdline').read_text().strip()
    entry, fields = select_entry(cmdline, Path('/boot/loader/entries').glob('*.conf'))
    kernel = boot_file(fields['linux'][0])
    initrd = boot_file(fields['initrd'][0])
    release = run('uname', '-r')
    if kernel.name != f'vmlinuz-{release}':
        raise SystemExit('BLS kernel does not match the running kernel')
    target = next(arg[7:] for arg in cmdline.split() if arg.startswith('ostree='))
    resolved = (Path('/sysroot') / target.lstrip('/')).resolve(strict=True)
    deployment = booted['ostree']
    if resolved.name != f"{deployment['checksum']}.{deployment['deploySerial']}":
        raise SystemExit('OSTree boot link differs from bootc running deployment')
    required = kernel.stat().st_size + initrd.stat().st_size + 64 * 1024**2
    if shutil.disk_usage(ESP).free < required:
        raise SystemExit('Insufficient ESP space for one trial UKI plus 64 MiB reserve')
    STATE.mkdir(mode=0o700)
    inputs = STATE / 'inputs'
    output = STATE / 'output'
    inputs.mkdir()
    output.mkdir()
    (STATE / 'bootc-before.json').write_text(json.dumps(status, indent=2))
    (STATE / 'efibootmgr-before.txt').write_text(run('efibootmgr', '-v') + '\n')
    (STATE / 'mok-before.txt').write_text(run('mokutil', '--list-enrolled') + '\n')
    # Root-only backups may contain machine-specific configuration.
    with tarfile.open(STATE / 'esp-before.tar', 'w') as backup:
        backup.add(ESP, arcname='esp')
    shutil.copyfile(kernel, inputs / 'linux')
    shutil.copyfile(initrd, inputs / 'initrd')
    shutil.copyfile('/etc/os-release', inputs / 'os-release')
    (inputs / 'uname').write_text(release + '\n')
    trial_args = [arg for arg in cmdline.split() if not arg.startswith('BOOT_IMAGE=')]
    trial_args.append('finite.boot-trial=1')
    (inputs / 'cmdline').write_text(' '.join(trial_args) + '\n')
    # Import only our previously built tools. No host system packages are changed.
    subprocess.run(['podman', 'load', '-i', str(archive)], check=True)
    subprocess.run([
        'podman', 'run', '--rm', '--pull=never', '--network=none',
        '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
        '--security-opt=label=disable', '--tmpfs=/tmp:rw,nosuid,nodev',
        '-v', f'{inputs}:/inputs:ro', '-v', f'{output}:/output:rw', image_id,
    ], check=True)
    # Copy only public, existing boot components. Never change the Fedora copies.
    for name in ('shimx64.efi', 'mmx64.efi'):
        shutil.copyfile(ESP / 'EFI/fedora' / name, output / name)
    manifest = {
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'cmdline_before': cmdline,
        'ostree_target': target,
        'resolved_deployment': str(resolved),
        'bls_entry': str(entry),
        'bls_sha256': digest(entry),
        'tools_image': image_id,
        'tools_archive_sha256': expected,
        'esp_partuuid': EXPECTED_ESP,
        'files': {p.name: digest(p) for p in output.iterdir() if p.suffix == '.efi'},
        'installed': False,
    }
    (STATE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    report = '\n'.join([
        'Signed trial bundle prepared; nothing installed on ESP or in firmware.',
        f'Deployment: {resolved.name}',
        f'UKI bytes: {(output / "finite-trial.efi").stat().st_size}',
        (output / 'certificate.txt').read_text().strip(),
        f'Root-private state and backup: {STATE}',
        'Next: inspect artifacts, then stage an isolated entry; do not reboot into it yet.',
        'This bundle is invalidated by deployment changes; it is not an update mechanism.',
    ])
    print(report)


if __name__ == '__main__':
    main()
