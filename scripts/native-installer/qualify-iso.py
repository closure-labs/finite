#!/usr/bin/env python3
"""Install and boot an exact disposable native ISO with one capped KVM guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import subprocess
import sys
import time

from serial_records import EVIDENCE_NAME, MAX_RECORD_BYTES

MEMORY_MIB = 3072
RESERVE_MIB = 3072
DISK_SERIAL = 'FINITEQUALIFICATION'
MOK_GUID = '605dab50-e046-4300-abb6-3dd810dd8b23'
GUEST_FAILURE = re.compile(rb'(?:Installation stopped:|Kernel panic|FINITE_NATIVE_FRESH_BOOT_FAILED|'
                           rb'FINITE_MIGRATION_FAILED)[^\r\n]*\r?\n')


def available_mib():
    return next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                if line.startswith('MemAvailable:'))


def file_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install_media(iso, *, prioritize=True):
    # The hybrid ISO includes a GPT ESP for disk/USB boot. OVMF's optical
    # path failed to read GRUB from the larger development ISO.
    device = 'virtio-blk-pci,drive=media,serial=FINITEINSTALLMEDIA'
    if prioritize:
        device += ',bootindex=1'
    return ['-drive', f'if=none,id=media,format=raw,readonly=on,file={iso}',
            '-device', device]


def qemu_arguments(firmware, vars_file, disk, disk_serial):
    return ['-enable-kvm', '-machine', 'q35,smm=on', '-cpu', 'host', '-smp', '2',
            '-m', str(MEMORY_MIB), '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
            '-no-reboot', '-nic', 'none',
            '-global', 'driver=cfi.pflash01,property=secure,value=on',
            '-drive', f'if=pflash,format=raw,readonly=on,file={firmware / "OVMF_CODE_4M.secboot.fd"}',
            '-drive', f'if=pflash,format=raw,file={vars_file}',
            '-drive', f'if=none,id=target,format=qcow2,file={disk}',
            '-device', f'virtio-blk-pci,drive=target,serial={disk_serial}']


def prepare_readonly_inputs(media, directory, capacity):
    with media.open('xb') as stream:
        stream.truncate(capacity + 512 * 1024**2)
    subprocess.run(['mkfs.ext4', '-q', '-F', '-m', '0', '-d', directory, media], check=True, timeout=900)


class Guest:
    def __init__(self, arguments, log, timeout):
        if available_mib() < MEMORY_MIB + RESERVE_MIB:
            raise RuntimeError('Host lacks the 3 GiB guest budget plus 3 GiB reserve')
        self.deadline = time.monotonic() + timeout
        self.output = b''
        self.log = log
        record_path = Path(log.name).with_suffix('.records.jsonl')
        with record_path.open('xb'):
            pass
        channel = ['-chardev', f'file,id=finite-evidence,path={record_path}',
                   '-device', 'virtio-serial-pci,id=finite-evidence-bus',
                   '-device', f'virtserialport,bus=finite-evidence-bus.0,chardev=finite-evidence,name={EVIDENCE_NAME}']
        self.process = subprocess.Popen(['nice', '-n', '19', 'qemu-system-x86_64', *arguments, *channel],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.records = record_path.open('rb')
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=15)
        finally:
            self.selector.close()
            self.records.close()
            self.process.stdin.close()
            self.process.stdout.close()

    def read_console(self, timeout):
        if available_mib() < RESERVE_MIB:
            raise RuntimeError('Host fell below the 3 GiB available-memory reserve')
        if self.selector.select(timeout=timeout):
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                return False
            self.log.write(data)
            self.log.flush()
            self.output = (self.output + data)[-262144:]
        return True

    def check_failure(self):
        if GUEST_FAILURE.search(self.output):
            raise RuntimeError('Guest reported a failure. See the serial log.')

    def expect(self, expression):
        while time.monotonic() < self.deadline:
            match = re.search(expression, self.output)
            if match:
                self.output = self.output[match.end():]
                return match
            self.check_failure()
            if not self.read_console(timeout=1):
                raise RuntimeError('QEMU exited while waiting for guest output: ' + repr(expression))
        raise RuntimeError('Timed out waiting for guest output: ' + repr(expression))

    def send(self, value):
        self.process.stdin.write(value.encode() + b'\r')
        self.process.stdin.flush()

    def record(self, marker, *, timeout=None):
        payload = bytearray()
        console_open = True
        deadline = self.deadline if timeout is None else min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            chunk = self.records.readline(MAX_RECORD_BYTES + 1 - len(payload))
            payload.extend(chunk)
            if len(payload) > MAX_RECORD_BYTES:
                raise ValueError('VM evidence record exceeds 64 KiB')
            if chunk.endswith(b'\n'):
                receipt = json.loads(payload)
                if receipt['marker'] != marker or not isinstance(receipt['value'], dict):
                    raise ValueError('Unexpected VM evidence record while waiting for ' + marker)
                return receipt['value']
            self.check_failure()
            if not console_open:
                raise RuntimeError('QEMU exited while waiting for VM evidence: ' + marker)
            console_open = self.read_console(timeout=0.25)
        raise RuntimeError('Timed out waiting for VM evidence: ' + marker)

    def shutdown(self):
        while time.monotonic() < self.deadline:
            if not self.read_console(timeout=1):
                if self.process.wait(timeout=10) != 0:
                    raise RuntimeError('QEMU exited unsuccessfully after shutdown')
                return
        raise RuntimeError('Timed out waiting for clean guest shutdown')


def boot_facts(guest, password, seal):
    guest.expect(rb'(?i)(?:please )?(?:enter passphrase|password for|unlock disk)[^\r\n]{0,200}:')
    guest.send(password)
    facts = guest.record('FINITE_NATIVE_FRESH_BOOT')
    zfs_provided = facts.get('zfsProvided')
    expected_modules = ['zfs', 'v4l2loopback'] if zfs_provided else ['v4l2loopback']
    if (facts['profile'] != seal['profile'] or facts['bootableRootDigest'] != seal['bootableRootDigest']
            or any(facts.get(key) is not True for key in (
                'secureBoot', 'selinuxEnforcing', 'encryptedRoot', 'efiUpdaterSucceeded'))
            or type(zfs_provided) is not bool or facts.get('signedModules') != expected_modules
            or facts.get('espBytes') != 600 * 1024**2 or facts.get('xbootldrBytes') != 4 * 1024**3):
        raise ValueError('Observed guest acceptance differs from the exact native seal or required boot facts')
    return facts


def verify_update(base, update, archive):
    if (update['profile'] != base['profile'] or update['sourceRevision'] != base['sourceRevision']
            or update['certificateDerSha256'] != base['certificateDerSha256']
            or update['validationOnly'] is not True or update['integrity']['strictVerity'] is not True
            or update['integrity']['archiveSha256'] != update['archiveSha256']
            or update['integrity']['bootableRootDigest'] != update['bootableRootDigest']
            or update['archiveSha256'] != file_sha256(archive)):
        raise ValueError('Update is not the exact verified archive for this validation profile')
    for field in ('kernelRelease', 'bootableRootDigest'):
        if update[field] == base[field]:
            raise ValueError('Upgrade fixture did not change ' + field)
    for field in ('unsignedSha256', 'signedSha256'):
        if update['validationLoader'][field] == base['validationLoader'][field]:
            raise ValueError('Upgrade fixture did not change the EFI payload bytes')


def qualify_lifecycle(args, state, common, password, base, update):
    inputs = args.update_archive.resolve(strict=True).parent
    media = state / 'update.raw'
    prepare_readonly_inputs(media, inputs, args.update_archive.stat().st_size)
    extra = ['-drive', f'if=none,id=update,format=raw,readonly=on,file={media}',
             '-device', 'virtio-blk-pci,drive=update,serial=FINITEUPDATE']
    phases = [('stage', base), ('updated', update), ('rollback', update), ('restored', base), ('verified', base)]
    observed = {}
    boot_ids = set()
    for phase, expected in phases:
        print(f'{base["profile"]}: booting lifecycle phase {phase}', flush=True)
        with (args.evidence / f'{phase}-serial.log').open('xb') as serial:
            with Guest(common + ['-smbios', f'type=1,serial=finite-lifecycle-{phase}']
                       + (extra if phase == 'stage' else []), serial, 2400 if phase == 'stage' else 900) as guest:
                facts = boot_facts(guest, password, expected)
                if expected is update and facts['zfsProvided'] != (args.update_provides_zfs == 'true'):
                    raise ValueError('Booted update ZFS availability differs from the authenticated upstream image')
                loader = expected['validationLoader']['signedSha256']
                if (facts['kernelRelease'] != expected['kernelRelease'] or facts['espLoaderSha256'] != loader
                        or facts['fallbackLoaderSha256'] != loader or not facts['loaderInfo'].startswith('systemd-boot ')
                        or facts['bootId'] in boot_ids):
                    raise ValueError(f'{phase}: unexpected kernel, EFI files, loader identity, or repeated boot')
                boot_ids.add(facts['bootId'])
                if phase != 'stage' and (len(facts['persistence']) != 2 or not all(facts['persistence'].values())):
                    raise ValueError(f'{phase}: /etc or /var persistence differs')
                if phase in {'stage', 'rollback'}:
                    transition = guest.record('FINITE_NATIVE_TRANSITION')
                    status = transition['status']
                    if transition['phase'] != phase:
                        raise ValueError(f'{phase}: unexpected bootc transition state')
                    if phase == 'stage':
                        staged = status.get('staged') or {}
                        composefs = staged.get('composefs') or {}
                        if composefs.get('verity') != update['bootableRootDigest']:
                            raise ValueError('Staged deployment root differs from the verified update')
                    (args.evidence / f'{phase}-status.json').write_text(json.dumps(transition, indent=2) + '\n')
                if guest.record('FINITE_NATIVE_SHUTDOWN')['phase'] != phase:
                    raise ValueError(f'{phase}: unexpected shutdown receipt')
                guest.shutdown()
                observed[phase] = facts
        if phase == 'stage':
            media.unlink()
    if (observed['stage']['loaderInfo'] != args.baseline_loader
            or observed['rollback']['loaderInfo'] != args.updated_loader
            or observed['verified']['loaderInfo'] != args.baseline_loader):
        raise ValueError('Running EFI loader versions did not follow the baseline, upgrade and rollback')
    return {
        'updateArchiveSha256': update['archiveSha256'],
        'loaderBinaryChanged': True,
        'phases': observed,
        'upgradeAccepted': True,
        'rollbackAccepted': True,
    }


def qualify(args):
    iso = args.iso.resolve(strict=True)
    metadata = json.loads((iso.parent / 'installation.json').read_text())
    seal = json.loads(args.seal.read_text())
    profile = seal['profile']
    if (profile not in {'finite-native', 'finite-native-dev'} or seal['validationOnly'] is not True
            or metadata['validationOnly'] is not True or metadata['finiteRevision'] != seal['sourceRevision']
            or metadata['payloadTag'] != 'ghcr.io/closure-labs/finite:' + profile):
        raise ValueError('ISO record and validation seal must identify the same disposable native profile')
    iso_hash = file_sha256(iso)
    checksum = (iso.parent / 'SHA256SUMS').read_text().splitlines()
    if f'{iso_hash}  {iso.name}' not in checksum or (
            f'{file_sha256(iso.parent / "installation.json")}  installation.json' not in checksum):
        raise ValueError('ISO or installation metadata checksum differs')
    update = None
    mok_certificates = [args.certificate, args.module_certificate]
    if args.update_archive:
        archive = args.update_archive.resolve(strict=True)
        if (archive.name != 'update.oci.tar' or {path.name for path in archive.parent.iterdir()} != {
                'update.oci.tar', 'update.json'} or not args.update_module_certificate
                or args.update_provides_zfs is None or not args.baseline_loader or not args.updated_loader
                or args.baseline_loader == args.updated_loader):
            raise ValueError('Use a dedicated directory with a sealed update and specify both expected loader versions')
        update = json.loads(archive.with_name('update.json').read_text())
        verify_update(seal, update, archive)
        if args.update_module_certificate.read_bytes() != args.module_certificate.read_bytes():
            mok_certificates.append(args.update_module_certificate)
    if not os.access('/dev/kvm', os.R_OK | os.W_OK):
        raise RuntimeError('KVM must be available before qualification')
    state = args.state.resolve()
    state.mkdir(mode=0o700)
    args.evidence.mkdir(parents=True, exist_ok=True)
    with (args.evidence / 'media-layout.log').open('xb') as layout:
        subprocess.run(['xorriso', '-indev', iso, '-report_system_area', 'plain', '-report_el_torito', 'plain'],
                       stdout=layout, stderr=subprocess.STDOUT, check=True, timeout=30)
    firmware = Path(os.environ['FINITE_VM_FIRMWARE_DIR'])
    vars_file = state / 'OVMF_VARS.fd'
    command = ['virt-fw-vars', '--input', firmware / 'OVMF_VARS_4M.ms.fd', '--output', vars_file]
    for certificate in mok_certificates:
        command.extend(['--add-mok', MOK_GUID, certificate])
    subprocess.run(command, check=True, timeout=30)
    disk = state / 'target.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', disk, '64G'], check=True, timeout=30)
    common = qemu_arguments(firmware, vars_file, disk, DISK_SERIAL)
    # The only writable guest disk is a fresh qcow2 we created. The
    # disposable password stays in memory and is never passed on a command line.
    password = secrets.token_hex(16)
    with (args.evidence / 'install-serial.log').open('xb') as serial:
        with Guest(common + install_media(iso), serial, 2400) as guest:
            guest.expect(rb'Finite native installer[^\r\n]*Secure Boot enabled')
            guest.expect(rb'Type the disk ID "virtio-FINITEQUALIFICATION" to continue:')
            guest.send('virtio-' + DISK_SERIAL)
            guest.expect(rb'LUKS passphrase \(recovery fallback\):')
            guest.send(password)
            guest.expect(rb'Repeat the passphrase:')
            guest.send(password)
            guest.expect(rb'Installation complete\.')
    print(f'{profile} installation completed; starting first encrypted boot', flush=True)
    lifecycle = None
    if update:
        lifecycle = qualify_lifecycle(args, state, common, password, seal, update)
        facts = lifecycle['phases']['stage']
    else:
        with (args.evidence / 'first-boot-serial.log').open('xb') as serial:
            with Guest(common, serial, 900) as guest:
                facts = boot_facts(guest, password, seal)
    report = {'schema': 1, 'scope': 'fresh encrypted installation and boot', 'validationOnly': True,
              'sourceRevision': seal['sourceRevision'], 'image': metadata['payload'], 'isoSha256': iso_hash,
              'bootCertificateDerSha256': seal['certificateDerSha256'],
              'installerMedium': 'read-only hybrid ISO attached as a VirtIO disk',
              'mokEnrollment': 'pre-enrolled disposable OVMF variables', 'memoryMiB': MEMORY_MIB,
              'hostReserveMiB': RESERVE_MIB, 'vcpu': 2, 'freshAccepted': True, **facts}
    (args.evidence / 'fresh-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if lifecycle:
        lifecycle = {**report, 'scope': 'fresh install, offline bootc switch, and rollback', **lifecycle}
        (args.evidence / 'lifecycle-acceptance.json').write_text(json.dumps(lifecycle, indent=2) + '\n')
        print(f'{profile}: accepted offline upgrade and rollback', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('iso', 'seal', 'certificate', 'module-certificate', 'state', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--update-archive', type=Path)
    parser.add_argument('--update-module-certificate', type=Path)
    parser.add_argument('--update-provides-zfs', choices=('true', 'false'))
    parser.add_argument('--baseline-loader')
    parser.add_argument('--updated-loader')
    try:
        qualify(parser.parse_args())
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'Native ISO guest qualification failed: {error}')


if __name__ == '__main__':
    main()
