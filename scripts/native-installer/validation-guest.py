#!/usr/bin/python3
"""Report fresh-install facts in the disposable native ISO guest."""
import hashlib
import json
from pathlib import Path
import subprocess


def capture(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def partition(path, guid, size):
    device = capture('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', path)
    require(capture('findmnt', '-n', '-o', 'FSTYPE', '--mountpoint', path) == 'vfat', path + ' must be VFAT')
    require(capture('lsblk', '-dnro', 'PARTTYPE', device).lower() == guid, path + ' partition type differs')
    require(int(capture('blockdev', '--getsize64', device)) == size, path + ' partition size differs')
    return device


def main():
    require(capture('systemd-detect-virt', '--vm') in {'kvm', 'qemu'}, 'Expected a disposable VM')
    require(capture('mokutil', '--sb-state').splitlines()[0] == 'SecureBoot enabled', 'Secure Boot disabled')
    require(capture('getenforce') == 'Enforcing', 'SELinux is not enforcing')
    lockdown = Path('/sys/kernel/security/lockdown').read_text()
    require('[integrity]' in lockdown or '[confidentiality]' in lockdown, 'Kernel lockdown inactive')
    line = Path('/proc/cmdline').read_text().split()
    digest = [arg.removeprefix('composefs.digest=v1-sha512-12:') for arg in line
              if arg.startswith('composefs.digest=v1-sha512-12:')]
    require(len(digest) == 1 and len(digest[0]) == 128, 'Strict sealed root digest missing')
    status = json.loads(capture('bootc', 'status', '--json'))['status']['booted']['composefs']
    require(status['bootloader'] == 'systemd' and status['bootType'] == 'Uki'
            and status['missingVerityAllowed'] is False, 'Unexpected bootc loader or integrity settings')
    root = capture('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', '/sysroot')
    require(capture('lsblk', '-dnro', 'TYPE', root) == 'crypt', 'Sysroot is not backed by a crypt mapping')
    partition('/efi', 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b', 600 * 1024**2)
    partition('/boot', 'bc13c2ff-59e6-4262-a352-b275fd6f7172', 4 * 1024**3)
    require(any(Path('/boot/EFI/Linux').rglob('*.efi')), 'XBOOTLDR has no UKI')
    require(not any(Path('/efi/EFI/Linux').rglob('*.efi')), 'ESP contains a UKI')
    require(Path('/efi/EFI/finite/shimx64.efi').is_file(), 'Finite shim is missing')
    require(Path('/efi/EFI/BOOT/BOOTX64.EFI').is_file(), 'Maintained fallback shim is missing')
    state = Path('/var/lib/finite/efi-updates')
    require(any(state.glob('*/journal.json')), 'Persistent EFI recovery journal missing')
    runtime = json.loads(Path('/usr/share/finite/bootc-runtime.json').read_text())
    for name, expected in runtime['files'].items():
        with open(name, 'rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Runtime bytes differ: ' + name)
    capture('mokutil', '--test-key', '/etc/pki/akmods/certs/akmods-ublue.der')
    # Module insertion under lockdown is the actual acceptance condition.
    for module in ('zfs', 'v4l2loopback'):
        capture('modprobe', module)
        require(Path('/sys/module', module).is_dir() and capture('modinfo', '-F', 'signer', module),
                'Signed module did not load: ' + module)
    print('FINITE_NATIVE_FRESH_BOOT ' + json.dumps({
        'profile': Path('/usr/share/finite/build-profile').read_text().strip(),
        'bootableRootDigest': digest[0], 'secureBoot': True, 'selinuxEnforcing': True,
        'encryptedRoot': True, 'signedModules': ['zfs', 'v4l2loopback'],
        'espBytes': 600 * 1024**2, 'xbootldrBytes': 4 * 1024**3,
    }), flush=True)


if __name__ == '__main__':
    main()
