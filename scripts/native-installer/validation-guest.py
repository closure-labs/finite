#!/usr/bin/python3
"""Observe boot and drive lifecycle transitions in the disposable native ISO guest."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from finite_mok import enrolled_mok_certificates
from serial_records import emit_record

SENTINELS = (Path('/etc/finite-validation-persistence'), Path('/var/lib/finite-validation-persistence'))
SENTINEL = 'finite native lifecycle\n'


def efi_string(name):
    value = Path('/sys/firmware/efi/efivars', name + '-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f')
    return value.read_bytes()[4:].decode('utf-16-le').rstrip('\0')


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


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lifecycle(phase):
    if phase == 'stage':
        media = Path('/dev/disk/by-id/virtio-FINITEUPDATE')
        require(capture('blockdev', '--getro', media) == '1', 'Update disk is writable')
        mount = Path('/var/mnt/finite-validation')
        mount.mkdir(parents=True, exist_ok=True)
        capture('mount', '-t', 'ext4', '-o', 'ro,noload,nodev,nosuid,noexec', media, mount)
        try:
            archive = mount / 'update.oci.tar'
            receipt = json.loads((mount / 'update.json').read_text())
            require(sha256(archive) == receipt['archiveSha256'], 'Update archive hash differs')
            for path in SENTINELS:
                with path.open('x') as stream:
                    stream.write(SENTINEL)
            subprocess.run(['bootc', 'switch', '--transport', 'oci-archive', archive], check=True, timeout=1800)
        finally:
            capture('umount', mount)
    elif phase == 'rollback':
        subprocess.run(['bootc', 'rollback'], check=True, timeout=180)
    else:
        require(phase in {'updated', 'restored', 'verified'}, 'Unexpected lifecycle phase')
    if phase in {'stage', 'rollback'}:
        status = json.loads(capture('bootc', 'status', '--json'))['status']
        emit_record('FINITE_NATIVE_TRANSITION', {'phase': phase, 'status': status})
    capture('sync')
    emit_record('FINITE_NATIVE_SHUTDOWN', {'phase': phase})
    capture('systemctl', '--no-block', 'poweroff')


def main():
    require(capture('systemd-detect-virt', '--vm') in {'kvm', 'qemu'}, 'Expected a disposable VM')
    serial = Path('/sys/class/dmi/id/product_serial')
    identifier = serial.read_text().strip() if serial.is_file() else ''
    if identifier.startswith('finite-migration-'):
        # The migration-specific observer verifies both boot chains and the
        # Btrfs mounts without imposing the fresh install's fallback policy.
        return
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
    updater = 'finite-efi-update.service'
    service = dict(line.split('=', 1) for line in capture(
        'systemctl', 'show', '--property=Result', '--property=ExecMainStartTimestampMonotonic', updater
    ).splitlines())
    if service.get('Result') != 'success' or int(service.get('ExecMainStartTimestampMonotonic', '0')) <= 0:
        subprocess.run(['journalctl', '--boot', '--unit', updater, '--no-pager', '--lines=12'], timeout=30)
        raise ValueError('The installed EFI updater did not complete successfully')
    runtime = json.loads(Path('/usr/share/finite/bootc-runtime.json').read_text())
    for name, expected in runtime['files'].items():
        with open(name, 'rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Runtime bytes differ: ' + name)
    require(Path('/etc/pki/akmods/certs/akmods-ublue.der').read_bytes() in enrolled_mok_certificates(),
            'Module-signing certificate is absent from the enrolled MOKs')
    # v4l2loopback is required. Follow the upstream image for ZFS, and
    # still require signed loading under lockdown whenever it is provided.
    zfs = subprocess.run(['modinfo', '-n', 'zfs'], text=True, capture_output=True, timeout=120)
    zfs_provided = zfs.returncode == 0
    require(zfs_provided or zfs.stderr.strip() == 'modinfo: ERROR: Module zfs not found.',
            'Could not determine upstream ZFS availability: ' + zfs.stderr.strip())
    modules = ['zfs', 'v4l2loopback'] if zfs_provided else ['v4l2loopback']
    for module in modules:
        capture('modprobe', module)
        require(Path('/sys/module', module).is_dir() and capture('modinfo', '-F', 'signer', module),
                'Signed module did not load: ' + module)
    facts = {
        'profile': Path('/usr/share/finite/build-profile').read_text().strip(),
        'bootableRootDigest': digest[0], 'secureBoot': True, 'selinuxEnforcing': True,
        'encryptedRoot': True, 'efiUpdaterSucceeded': True, 'zfsProvided': zfs_provided, 'signedModules': modules,
        'espBytes': 600 * 1024**2, 'xbootldrBytes': 4 * 1024**3,
    }
    phase = identifier.removeprefix('finite-lifecycle-')
    if phase != identifier:
        facts.update({
            'kernelRelease': capture('uname', '-r'),
            'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'loaderInfo': efi_string('LoaderInfo'),
            'espLoaderSha256': sha256(Path('/efi/EFI/finite/grubx64.efi')),
            'fallbackLoaderSha256': sha256(Path('/efi/EFI/BOOT/grubx64.efi')),
            'persistence': {str(path): path.is_file() and path.read_text() == SENTINEL for path in SENTINELS},
        })
    if identifier == 'finite-production-boot':
        loader = efi_string('LoaderInfo')
        loader_path = efi_string('LoaderImageIdentifier')
        stub = efi_string('StubInfo')
        require(loader.startswith('systemd-boot ') and loader_path == r'\EFI\finite\grubx64.efi'
                and stub.startswith('systemd-stub '), 'Production boot did not select the signed shim chain')
        uki_path = efi_string('StubImageIdentifier')
        uki = Path('/boot', uki_path.lstrip('\\').replace('\\', '/')).resolve(strict=True)
        require(uki.is_relative_to('/boot/EFI/Linux') and uki.is_file(), 'Booted UKI is not on XBOOTLDR')
        facts.update({'loaderInfo': loader, 'loaderPath': loader_path, 'stubInfo': stub, 'ukiPath': uki_path,
                      'installedUkiSha256': sha256(uki), 'kernelRelease': capture('uname', '-r'),
                      'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
    emit_record('FINITE_NATIVE_FRESH_BOOT', facts)
    if identifier == 'finite-production-boot':
        capture('sync')
        capture('systemctl', '--no-block', 'poweroff')
    if phase != identifier:
        lifecycle(phase)


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'FINITE_NATIVE_FRESH_BOOT_FAILED {error}', file=sys.stderr, flush=True)
        sys.exit(1)
