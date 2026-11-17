#!/usr/bin/env python3
"""Run isolated native-composefs boot/upgrade/rollback tests on file-backed QEMU disks."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tarfile
import time


REPO = Path(__file__).resolve().parents[2]
STATE = REPO / 'artifacts/systemd-boot/vm'
PORT = '22342'
ENGINE = 'docker'
ROOTFS_IMAGE = 'localhost/finite-composefs-rootfs:base'
CANDIDATE_IMAGE = 'localhost/finite-composefs:base'
TARGET_SIZE = '32G'
MEMORY_MIB = 3072
HOST_RESERVE_MIB = 3072


def run(args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def capture(args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def ssh(command, check=True):
    return subprocess.run([
        'ssh', '-i', str(STATE / 'ssh-key'), '-p', PORT, '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ConnectTimeout=3', 'root@127.0.0.1', command,
    ], capture_output=True, text=True, check=check, timeout=600)


def prepare():
    # Export a conventional live installer root separately from the sealed candidate.
    container = capture([ENGINE, 'create', ROOTFS_IMAGE, '/bin/true'])
    try:
        run([ENGINE, 'export', '-o', STATE / 'installer.tar', container])
        run([ENGINE, 'cp', f'{container}:/usr/lib/modules', STATE / 'installer-modules'])
    finally:
        run([ENGINE, 'rm', container])
    # Docker exports runtime container markers which make a directly booted
    # installer misdetect itself as a container and ignore its real kernel args.
    with tarfile.open(STATE / 'installer.tar') as archive:
        markers = [entry.name for entry in archive
                   if entry.name.removeprefix('./').lstrip('/') in
                   {'.dockerenv', 'run/.containerenv', 'run/systemd/container'}]
    if markers:
        run(['tar', '--delete', '--file', STATE / 'installer.tar', *markers])
    if ENGINE == 'docker':
        run(['skopeo', 'copy', f'docker-daemon:{CANDIDATE_IMAGE}',
             f'oci-archive:{STATE / "base.oci.tar"}'])
    else:
        run(['podman', 'save', '--format', 'oci-archive', '-o', STATE / 'base.oci.tar',
             CANDIDATE_IMAGE])
    payload = STATE / 'payload'
    payload.mkdir(exist_ok=True)
    shutil.move(STATE / 'base.oci.tar', payload / 'base.oci.tar')
    environment = dict(os.environ, LIBGUESTFS_BACKEND='direct')
    # Full desktop OCI archives are unpacked into the bootstrap's /var/tmp.
    # Reserve space for more than one archive handle, not just the small fixture.
    run(['virt-make-fs', '--type=ext4', '--size=+18G', STATE / 'installer.tar',
         STATE / 'installer.raw'], env=environment)
    run(['virt-make-fs', '--type=ext4', '--label=FINITEINPUTS', '--size=+1G',
         payload, STATE / 'inputs.raw'], env=environment)
    run(['qemu-img', 'create', '-f', 'raw', STATE / 'target.raw', TARGET_SIZE])
    # Modify only this disposable firmware variables file, with a VM-only db certificate.
    run([ENGINE, 'run', '--rm', '--network=none', '--security-opt=label=disable',
         '--user', f'{os.getuid()}:{os.getgid()}',
         '-v', f'{STATE}:/state:rw', '-v', '/usr/share/edk2/ovmf:/firmware:ro',
         '--entrypoint=virt-fw-vars', ROOTFS_IMAGE,
         '--input', '/firmware/OVMF_VARS.secboot.fd', '--output', '/state/OVMF_VARS.fd',
         '--add-db', '49bc8d48-6a60-4e4d-83e7-2b3b25f6e96a', '/state/db.pem',
         '--sb', '--output-json', '/state/firmware.json'])


def available_memory():
    return next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                if line.startswith('MemAvailable:'))


def qemu(phase, installer=False):
    if available_memory() < MEMORY_MIB + HOST_RESERVE_MIB:
        raise RuntimeError(f'Insufficient memory for {MEMORY_MIB} MiB VM plus {HOST_RESERVE_MIB} MiB host reserve')
    args = ['qemu-system-x86_64', '-enable-kvm', '-machine', 'q35,smm=on',
            '-cpu', 'host', '-m', str(MEMORY_MIB), '-smp', '2', '-display', 'none',
            '-serial', f'file:{STATE / (phase + "-serial.log")}', '-no-reboot',
            '-netdev', f'user,id=net0,hostfwd=tcp:127.0.0.1:{PORT}-:22',
            '-device', 'virtio-net-pci,netdev=net0', '-device', 'virtio-rng-pci']
    if installer:
        kernels = list((STATE / 'installer-modules').glob('*/vmlinuz'))
        if len(kernels) != 1:
            raise RuntimeError('Installer must have exactly one kernel')
        args += ['-smbios', 'type=1,product=Finite Composefs Installer',
                 '-kernel', str(kernels[0]), '-initrd', str(kernels[0].with_name('initramfs.img')),
                 # The exported bootstrap root has not been relabeled by bootc.
                 # Permissive applies only to this installer, never the candidate UKI.
                 '-append', 'root=/dev/vda rw console=ttyS0,115200n8 enforcing=0 audit=0 '
                            'systemd.mask=selinux-autorelabel.service '
                            'systemd.unit=multi-user.target finite.vm.install=1',
                 '-drive', f'file={STATE / "installer.raw"},format=raw,if=virtio']
    else:
        args += ['-global', 'driver=cfi.pflash01,property=secure,value=on',
                 '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd',
                 '-drive', f'if=pflash,format=raw,file={STATE / "OVMF_VARS.fd"}']
    args += ['-drive', f'file={STATE / "target.raw"},format=raw,if=virtio',
             '-drive', f'file={STATE / "inputs.raw"},format=raw,if=virtio,readonly=on']
    log = (STATE / f'{phase}-qemu.log').open('w')
    process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    return process, log


def wait_ssh(process, phase):
    # Desktop images initialize policy, users, library caches and Nix on first boot.
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if available_memory() < 1024:
            raise RuntimeError('Host memory is too low; stopping this disposable VM')
        if process.poll() is not None:
            raise RuntimeError(f'{phase}: QEMU exited with {process.returncode}')
        result = ssh('true', check=False)
        if result.returncode == 0:
            return
        time.sleep(3)
    raise RuntimeError(f'{phase}: SSH readiness timed out; see serial log')


def guest_check(phase):
    process, log = qemu(phase)
    try:
        wait_ssh(process, phase)
        work = ssh('mktemp -d /var/tmp/finite-efi-check.XXXXXXXX').stdout.strip()
        if not re.fullmatch(r'/var/tmp/finite-efi-check\.[A-Za-z0-9]{8}', work):
            raise RuntimeError('Invalid guest scratch directory')
        sources = ([('files/system/usr/libexec/finite/update-efi', 'update-efi'),
                    ('scripts/vm-composefs/check-efi-fat.py', 'check.py')] if phase == 'efi-fat' else
                   [('scripts/vm-composefs/probe-xbootldr.sh', 'check.sh')])
        for source, name in sources:
            run(['scp', '-i', STATE / 'ssh-key', '-P', PORT, '-o', 'BatchMode=yes',
                 '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                 REPO / source, 'root@127.0.0.1:' + work + '/' + name])
        command = ('python3 ' + work + '/check.py ' + work + '/update-efi' if phase == 'efi-fat' else
                   'bash ' + work + '/check.sh')
        result = ssh(command, check=False)
        (STATE / (phase + '-result.json')).write_text(result.stdout)
        (STATE / (phase + '-stderr.log')).write_text(result.stderr)
        if result.returncode:
            raise RuntimeError('Guest check failed; see retained evidence')
        print(result.stdout, flush=True)
        ssh('rm -rf -- ' + work)
        ssh('systemctl poweroff', check=False)
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        log.close()


def evidence(phase, revision):
    command = '''
set -eu
bootctl status
cat /proc/cmdline
cat /sys/kernel/security/lockdown
getenforce
bootc status --json
cat /usr/share/finite-vm/revision
systemctl --failed --no-pager
df -h / /etc /var /sysroot
'''
    result = ssh(command)
    (STATE / f'{phase}-evidence.txt').write_text(result.stdout + result.stderr)
    status = json.loads(ssh('bootc status --json').stdout)
    (STATE / f'{phase}-bootc.json').write_text(json.dumps(status, indent=2) + '\n')
    facts = ssh('cat /usr/share/finite-vm/revision; getenforce; cat /proc/cmdline; '
                'cat /sys/kernel/security/lockdown; bootctl status').stdout
    assert facts.splitlines()[0] == revision, facts
    assert 'Enforcing' in facts, facts
    assert 'systemd-boot ' in facts and 'Secure Boot: enabled' in facts, facts
    assert 'composefs=' in facts or 'composefs.digest=' in facts, facts
    assert 'composefs=?' not in facts and 'composefs.digest=?' not in facts, facts
    assert '[integrity]' in facts or '[confidentiality]' in facts, facts
    assert status['status']['booted'].get('composefs') is not None, status
    composefs = status['status']['booted']['composefs']
    assert composefs['bootloader'] == 'systemd' and composefs['bootType'] == 'Uki', status
    assert composefs['missingVerityAllowed'] is False, status
    if ssh('systemctl --failed --no-legend').stdout.strip():
        failures = ssh('systemctl --failed --no-pager --full; '
                       'journalctl -b -p warning --no-pager -n 300', check=False)
        (STATE / f'{phase}-service-failures.txt').write_text(failures.stdout + failures.stderr)
        raise RuntimeError('Guest has failed units; see retained service-failures log')
    if (STATE / 'native-configuration.json').exists():
        expected = json.loads((STATE / 'native-configuration.json').read_text())
        trust = ssh('''set -eu
test -d /sys/module/zfs
test -d /sys/module/v4l2loopback
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
mokutil --export
sha256sum MOK-*.der
modinfo -F signer zfs
modinfo -F signer v4l2loopback
systemctl show finite-firstboot-rpm-ostree.service rpm-ostreed.service -p ConditionResult
''')
        (STATE / f'{phase}-module-trust.txt').write_text(trust.stdout + trust.stderr)
        assert expected['module_certificate_sha256'] in trust.stdout, 'Expected module MOK absent'
        assert trust.stdout.count('ConditionResult=no') == 2, 'OSTree-only jobs were not guarded'
    print(f'{phase}: native composefs, Secure Boot, lockdown and SELinux verified', flush=True)


def xbootldr_evidence():
    # Read exact runtime bytes, partition identities and placement in the
    # booted guest. This result grants fresh-install/boot evidence only.
    script = '''
import hashlib,json,subprocess
from pathlib import Path
def capture(*args): return subprocess.check_output(args,text=True).strip()
def mount(path): return json.loads(capture('findmnt','--json','--types','vfat','--mountpoint',path,'-o','SOURCE,FSTYPE'))['filesystems'][0]
receipt=json.loads(Path('/usr/share/finite/bootc-runtime.json').read_text())
for name,digest in receipt['files'].items():
 with open(name,'rb') as stream: assert hashlib.file_digest(stream,'sha256').hexdigest()==digest
assert Path('/efi/EFI/BOOT/BOOTX64.EFI').is_file()
boot,esp=mount('/boot'),mount('/efi')
assert boot['fstype']=='vfat' and esp['fstype']=='vfat'
assert boot['source']!=esp['source']
assert capture('lsblk','-dnro','PARTTYPE',boot['source']).lower()=='bc13c2ff-59e6-4262-a352-b275fd6f7172'
assert capture('lsblk','-dnro','PARTTYPE',esp['source']).lower()=='c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
assert int(capture('blockdev','--getsize64',boot['source']))==4*1024**3
assert int(capture('blockdev','--getsize64',esp['source']))==600*1024**2
ukis=sorted(str(p) for p in Path('/boot/EFI/Linux').rglob('*.efi'))
entries=sorted(str(p) for p in Path('/boot/loader/entries').glob('*.conf'))
assert ukis and entries and not list(Path('/efi/EFI/Linux').rglob('*.efi'))
assert Path('/efi/EFI/BOOT/BOOTX64.EFI').is_file()
assert capture('bootc','--version')=='bootc '+receipt['source']['version']
print(json.dumps({'schema':1,'scope':'fresh disposable installation and boot only',
 'runtime':receipt,'xbootldr':boot,'esp':esp,'ukis':ukis,'entries':entries,
 'ukisOnXbootldr':True,'ukisOnEsp':False},indent=2))
'''
    result = ssh('python3 -c ' + shlex.quote(script), check=False)
    (STATE / 'xbootldr-check.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('XBOOTLDR placement check failed; see xbootldr-check.log')
    (STATE / 'xbootldr-boot.json').write_text(result.stdout)
    print('Booted runtime and ESP/XBOOTLDR identities verified', flush=True)


def tamper_test():
    """Require explicit firmware/loader rejection on a clone of a verified VM."""
    global STATE
    original = STATE
    status = json.loads((STATE / 'rolled-back-bootc.json').read_text())
    digest = status['status']['booted']['composefs']['verity']
    if len(digest) != 128 or any(c not in '0123456789abcdef' for c in digest):
        raise RuntimeError('Unexpected verified deployment digest')
    clone = STATE / 'tamper'
    clone.mkdir(mode=0o700)
    run(['cp', '--reflink=auto', '--sparse=always', STATE / 'target.raw', clone / 'target.raw'])
    for name in ['OVMF_VARS.fd', 'db.pem', 'ssh-key']:
        shutil.copyfile(STATE / name, clone / name)
        (clone / name).chmod(0o600)
    (clone / 'inputs.raw').symlink_to(STATE / 'inputs.raw')
    table = json.loads(capture(['sfdisk', '--json', clone / 'target.raw']))['partitiontable']
    esp = [p for p in table['partitions']
           if p['type'].lower() == 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b']
    if len(esp) != 1:
        raise RuntimeError('Expected exactly one test ESP')
    disk = str(clone / 'target.raw') + '@@' + str(esp[0]['start'] * table['sectorsize'])
    uki = f'::/EFI/Linux/bootc/bootc_composefs-{digest}.efi'
    run(['mcopy', '-i', disk, uki, clone / 'original.efi'])
    data = bytearray((clone / 'original.efi').read_bytes())
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise RuntimeError('Expected PE image')
    count = struct.unpack_from('<H', data, pe + 6)[0]
    sections = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    for offset in range(sections, sections + count * 40, 40):
        if data[offset:offset + 8].rstrip(b'\0') == b'.cmdline':
            size, start = struct.unpack_from('<II', data, offset + 16)
            marker = b'composefs.digest=v1-sha512-12:'
            position = data.find(marker, start, start + size)
            if position < 0:
                raise RuntimeError('Missing authenticated digest')
            position += len(marker)
            data[position] = ord('a') if data[position] != ord('a') else ord('b')
            break
    else:
        raise RuntimeError('Missing signed command-line section')
    (clone / 'tampered.efi').write_bytes(data)
    verifier = [ENGINE, 'run', '--rm', '--network=none', '--security-opt=label=disable',
                '--user', f'{os.getuid()}:{os.getgid()}', '-v', f'{clone}:/test:ro',
                '--entrypoint=sbverify', ROOTFS_IMAGE, '--cert', '/test/db.pem']
    good = run([*verifier, '/test/original.efi'], capture_output=True, text=True)
    bad = subprocess.run([*verifier, '/test/tampered.efi'], capture_output=True, text=True)
    (clone / 'signature-check.txt').write_text(good.stdout + good.stderr + bad.stdout + bad.stderr)
    assert bad.returncode != 0 and 'Signature verification failed' in bad.stdout + bad.stderr
    run(['mcopy', '-o', '-i', disk, clone / 'tampered.efi', uki])
    STATE = clone
    process, log = qemu('tampered')
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            serial_path = clone / 'tampered-serial.log'
            serial = serial_path.read_text(errors='replace') if serial_path.exists() else ''
            rejected = ('security violation' in serial.lower()
                        or 'security policy violation' in serial.lower()
                        or any('Error loading EFI binary ' in line and ': Access denied' in line
                               for line in serial.splitlines()))
            if rejected:
                assert 'Linux version ' not in serial
                (clone / 'result.json').write_text(json.dumps({
                    'original_signature_verified': True, 'modified_signature_rejected': True,
                    'secure_boot_rejection_observed': True, 'kernel_started': False,
                    'scope': 'cloned disposable disk and firmware only',
                }, indent=2) + '\n')
                print('tamper: explicit Secure Boot rejection verified', flush=True)
                return
            if process.poll() is not None:
                break
            time.sleep(2)
        raise RuntimeError('No explicit Secure Boot rejection observed; inspect retained console log')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        log.close()
        STATE = original


def main():
    global STATE, ENGINE, ROOTFS_IMAGE, CANDIDATE_IMAGE, TARGET_SIZE, MEMORY_MIB, HOST_RESERVE_MIB
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'install', 'first-boot', 'upgrade', 'rollback', 'tamper', 'efi-fat', 'xbootldr-probe'])
    parser.add_argument('--engine', choices=['docker', 'podman'], default='docker')
    parser.add_argument('--state', type=Path, default=STATE)
    parser.add_argument('--rootfs-image', default=ROOTFS_IMAGE)
    parser.add_argument('--candidate-image', default=CANDIDATE_IMAGE)
    parser.add_argument('--target-size', choices=['32G', '64G'], default=TARGET_SIZE)
    parser.add_argument('--memory-mib', type=int, choices=[1024, 1536, 2048, 3072, 4096], default=MEMORY_MIB)
    parser.add_argument('--host-reserve-mib', type=int, choices=[2048, 2560, 3072, 4096], default=HOST_RESERVE_MIB)
    parser.add_argument('--expect-xbootldr', action='store_true')
    args = parser.parse_args()
    STATE = args.state.resolve()
    if not STATE.is_relative_to(REPO / 'artifacts'):
        raise SystemExit('VM state must stay under this checkout\'s artifacts directory')
    ENGINE = args.engine
    ROOTFS_IMAGE, CANDIDATE_IMAGE = args.rootfs_image, args.candidate_image
    TARGET_SIZE = args.target_size
    MEMORY_MIB = args.memory_mib
    HOST_RESERVE_MIB = args.host_reserve_mib
    if args.phase in ('efi-fat', 'xbootldr-probe'):
        guest_check(args.phase)
        return
    if args.phase == 'tamper':
        tamper_test()
        return
    if args.phase == 'prepare':
        if any((STATE / name).exists() for name in ['target.raw', 'installer.raw', 'inputs.raw']):
            raise SystemExit('Refusing to overwrite existing VM disks; use a fresh state directory')
        prepare()
        return
    process, log = qemu(args.phase, installer=args.phase == 'install')
    try:
        if args.phase == 'install':
            process.wait(timeout=1800)
            serial = (STATE / 'install-serial.log').read_text(errors='replace')
            assert process.returncode == 0 and 'FINITE_VM_INSTALL_COMPLETE' in serial
            print('Disposable disk installation completed', flush=True)
        else:
            wait_ssh(process, args.phase)
            before_revision = 'update' if args.phase == 'rollback' else 'base'
            evidence(args.phase + '-before' if args.phase != 'first-boot' else args.phase,
                     before_revision)
            if args.expect_xbootldr:
                xbootldr_evidence()
            if args.phase in {'upgrade', 'rollback'}:
                if args.phase == 'upgrade':
                    ssh("mkdir -p /var/lib/finite-vm; printf 'preserve-me\\n' > /var/lib/finite-vm/persistence; "
                        "printf 'preserve-me\\n' > /etc/finite-vm-persistence; "
                        'mkdir -p /var/mnt/finite-vm-inputs; '
                        'mount -o ro /dev/disk/by-label/FINITEINPUTS /var/mnt/finite-vm-inputs')
                    result = ssh('bootc switch --transport oci-archive '
                                 '/var/mnt/finite-vm-inputs/update.oci.tar', check=False)
                else:
                    result = ssh('bootc rollback', check=False)
                (STATE / f'{args.phase}-staging.txt').write_text(result.stdout + result.stderr)
                staged = ssh('bootc status --json').stdout
                (STATE / f'{args.phase}-staged.json').write_text(staged)
                if result.returncode:
                    raise RuntimeError(f'{args.phase}: bootc returned {result.returncode}; '
                                       'see retained staging output and status')
                ssh('systemctl reboot', check=False)
                process.wait(timeout=90)
                log.close()
                phase = 'updated' if args.phase == 'upgrade' else 'rolled-back'
                process, log = qemu(phase)
                wait_ssh(process, phase)
                evidence(phase, 'update' if args.phase == 'upgrade' else 'base')
                persisted = ssh('cat /var/lib/finite-vm/persistence /etc/finite-vm-persistence').stdout
                assert persisted == 'preserve-me\npreserve-me\n', persisted
                (STATE / f'{phase}-persistence.txt').write_text(persisted)
            ssh('systemctl poweroff', check=False)
            process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        log.close()


if __name__ == '__main__':
    main()
