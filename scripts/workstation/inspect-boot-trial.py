#!/usr/bin/env python3
"""Check the private trial bundle and print public evidence; no boot changes."""

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess


SPEC = importlib.util.spec_from_file_location(
    'prepare_trial', Path(__file__).with_name('prepare-boot-trial.py'))
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def sensitive_paths(listing):
    """Flag names for review; never print file contents or guess they are safe."""
    candidates = []
    for line in listing.splitlines():
        if not re.match(r'^[-dlcbps][rwxStTs-]{9}\s', line):
            continue
        fields = line.split(None, 8)
        if len(fields) < 9:
            raise ValueError('Cannot parse initramfs inventory')
        path = fields[8].split(' -> ', 1)[0]
        lower = path.lower()
        if (lower.endswith(('.key', '.priv', '.p12', '.pfx', '.keyfile'))
                or 'cryptsetup-keys.d/' in lower
                or 'initramfs-root-binding' in lower
                or re.search(r'(^|/)(id_rsa|id_ed25519|shadow|gshadow)$', lower)):
            candidates.append(path)
    return sorted(set(candidates))


def gshadow_summary(content):
    """Classify password fields without returning names, hashes, or memberships."""
    rows = [line.split(':') for line in content.splitlines() if line.strip()]
    if not rows or any(len(row) != 4 for row in rows):
        raise ValueError('Unexpected gshadow format; private review required')
    return {
        'entries': len(rows),
        'password_material_present': any(set(row[1]) - {'!', '*'} for row in rows),
    }


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to read the private trial bundle')
    state = PREPARE.STATE
    info = state.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        raise SystemExit('Trial state must be root-owned and inaccessible to other users')
    manifest = json.loads((state / 'manifest.json').read_text())
    output = state / 'output'
    inputs = state / 'inputs'
    required_files = {'finite-trial.efi', 'grubx64.efi', 'shimx64.efi', 'mmx64.efi'}
    if set(manifest['files']) != required_files:
        raise SystemExit('Unexpected manifest artifact set')
    for name, expected in manifest['files'].items():
        if PREPARE.digest(output / name) != expected:
            raise SystemExit(f'Artifact changed: {name}')
    image = manifest['tools_image']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise SystemExit('Invalid tools image identity')
    status = json.loads(PREPARE.run('bootc', 'status', '--json'))['status']
    if status.get('staged') or status.get('rollbackQueued'):
        raise SystemExit('Deployment change queued; trial needs review')
    cmdline = Path('/proc/cmdline').read_text().strip()
    if cmdline != manifest['cmdline_before']:
        raise SystemExit('Running arguments changed since preparation')
    entry, fields = PREPARE.select_entry(cmdline, Path('/boot/loader/entries').glob('*.conf'))
    if PREPARE.digest(entry) != manifest['bls_sha256']:
        raise SystemExit('Boot entry changed since preparation')
    target = (Path('/sysroot') / manifest['ostree_target'].lstrip('/')).resolve(strict=True)
    if str(target) != manifest['resolved_deployment']:
        raise SystemExit('OSTree boot target changed since preparation')
    current = status['booted']['ostree']
    if target.name != f"{current['checksum']}.{current['deploySerial']}":
        raise SystemExit('Current deployment differs from trial')
    for name, field in [('linux', 'linux'), ('initrd', 'initrd')]:
        if PREPARE.digest(inputs / name) != PREPARE.digest(PREPARE.boot_file(fields[field][0])):
            raise SystemExit(f'Current {name} differs from trial input')
    for name in ('shimx64.efi', 'mmx64.efi'):
        if PREPARE.digest(output / name) != PREPARE.digest(PREPARE.ESP / 'EFI/fedora' / name):
            raise SystemExit(f'Installed {name} changed since preparation')
    backup = state / 'esp-before.tar'
    if not backup.is_file() or backup.stat().st_size == 0:
        raise SystemExit('Missing ESP backup')
    # The inventory exposes filenames only. Never unpack keys into public storage.
    listing = PREPARE.run('lsinitrd', str(inputs / 'initrd'))
    if not any(re.match(r'^[-dlcbps][rwxStTs-]{9}\s', line) for line in listing.splitlines()):
        raise SystemExit('No file inventory parsed from lsinitrd')
    candidates = sensitive_paths(listing)
    if 'etc/gshadow' in candidates:
        # Read into memory only; never send the contents to the terminal or log.
        group_passwords = gshadow_summary(PREPARE.run(
            'lsinitrd', '--file', 'etc/gshadow', str(inputs / 'initrd')))
        if not group_passwords['password_material_present']:
            candidates.remove('etc/gshadow')
    # Check signatures AND exact embedded input bytes, without exposing the key.
    subprocess.run([
        'podman', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--security-opt=label=disable',
        '--tmpfs=/tmp:rw,nosuid,nodev', '-v', f'{inputs}:/inputs:ro',
        '-v', f'{output}:/output:ro', '--entrypoint=/bin/bash', image, '-euc',
        '''
sbverify --cert /output/MOK.pem /output/finite-trial.efi
sbverify --cert /output/MOK.pem /output/grubx64.efi
for pair in linux:linux initrd:initrd cmdline:cmdline osrel:os-release uname:uname; do
  section=${pair%%:*}
  input=${pair#*:}
  objcopy --dump-section .$section=/tmp/$section /output/finite-trial.efi /tmp/image.efi
  python3 -c 'import pathlib,sys; a=pathlib.Path(sys.argv[1]).read_bytes(); b=pathlib.Path(sys.argv[2]).read_bytes(); assert a.rstrip(b"\\0\\n")==b.rstrip(b"\\0\\n"), "UKI section mismatch"' /tmp/$section /inputs/$input
done
''',
    ], check=True)
    report = {
        'deployment': target.name,
        'uki_bytes': (output / 'finite-trial.efi').stat().st_size,
        'certificate': (output / 'certificate.txt').read_text().strip(),
        'tools': (output / 'tool-versions.txt').read_text().splitlines(),
        'signatures_and_embedded_inputs_verified': True,
        'esp_backup_bytes': backup.stat().st_size,
        'initramfs_paths_requiring_review': candidates,
        'initramfs_modules': PREPARE.run('lsinitrd', '-m', str(inputs / 'initrd')),
        'note': 'Filename screening does not prove absence of secrets. '
                'No EFI files, firmware entries or trust settings changed.',
    }
    print(json.dumps(report, indent=2))
    if candidates:
        raise SystemExit('Review flagged initramfs paths before staging on the ESP')


if __name__ == '__main__':
    main()
