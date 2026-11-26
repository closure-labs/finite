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

MEMORY_MIB = 3072
RESERVE_MIB = 3072
DISK_SERIAL = 'FINITEQUALIFICATION'
MOK_GUID = '605dab50-e046-4300-abb6-3dd810dd8b23'
GUEST_FAILURE = re.compile(rb'(?:Installation stopped:|Kernel panic|FINITE_NATIVE_FRESH_BOOT_FAILED)[^\r\n]*\r?\n')


def available_mib():
    return next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                if line.startswith('MemAvailable:'))


def file_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install_media(iso):
    # The hybrid ISO includes a GPT ESP for disk/USB boot. OVMF's optical
    # path failed to read GRUB from the larger development ISO.
    return ['-drive', f'if=none,id=media,format=raw,readonly=on,file={iso}',
            '-device', 'virtio-blk-pci,drive=media,bootindex=1,serial=FINITEINSTALLMEDIA']


class Guest:
    def __init__(self, arguments, log, timeout):
        if available_mib() < MEMORY_MIB + RESERVE_MIB:
            raise RuntimeError('Host lacks the 3 GiB guest budget plus 3 GiB reserve')
        self.deadline = time.monotonic() + timeout
        self.output = b''
        self.log = log
        self.process = subprocess.Popen(['nice', '-n', '19', 'qemu-system-x86_64', *arguments],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
            self.process.stdin.close()
            self.process.stdout.close()

    def expect(self, expression):
        while time.monotonic() < self.deadline:
            match = re.search(expression, self.output)
            if match:
                self.output = self.output[match.end():]
                return match
            if GUEST_FAILURE.search(self.output):
                raise RuntimeError('Guest reported a failure. See the serial log.')
            if available_mib() < RESERVE_MIB:
                raise RuntimeError('Host fell below the 3 GiB available-memory reserve')
            if self.selector.select(timeout=1):
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError('QEMU exited before completing the expected guest phase')
                self.log.write(data)
                self.log.flush()
                self.output = (self.output + data)[-262144:]
        raise RuntimeError('Timed out waiting for guest output: ' + repr(expression))

    def send(self, value):
        self.process.stdin.write(value.encode() + b'\r')
        self.process.stdin.flush()


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
    subprocess.run(['virt-fw-vars', '--input', firmware / 'OVMF_VARS_4M.ms.fd',
                    '--output', vars_file, '--add-mok', MOK_GUID, args.certificate,
                    '--add-mok', MOK_GUID, args.module_certificate], check=True, timeout=30)
    disk = state / 'target.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', disk, '64G'], check=True, timeout=30)
    common = ['-enable-kvm', '-machine', 'q35,smm=on', '-cpu', 'host', '-smp', '2',
              '-m', str(MEMORY_MIB), '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
              '-no-reboot', '-nic', 'none',
              '-global', 'driver=cfi.pflash01,property=secure,value=on',
              '-drive', f'if=pflash,format=raw,readonly=on,file={firmware / "OVMF_CODE_4M.secboot.fd"}',
              '-drive', f'if=pflash,format=raw,file={vars_file}',
              '-drive', f'if=none,id=target,format=qcow2,file={disk}',
              '-device', f'virtio-blk-pci,drive=target,serial={DISK_SERIAL}']
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
    with (args.evidence / 'first-boot-serial.log').open('xb') as serial:
        with Guest(common, serial, 900) as guest:
            guest.expect(rb'(?i)(?:please )?(?:enter passphrase|password for|unlock disk)[^\r\n]{0,200}:')
            guest.send(password)
            match = guest.expect(rb'FINITE_NATIVE_FRESH_BOOT (\{[^\r\n]+\})')
            facts = json.loads(match[1])
    if (facts['profile'] != profile or facts['bootableRootDigest'] != seal['bootableRootDigest']
            or any(facts.get(key) is not True for key in (
                'secureBoot', 'selinuxEnforcing', 'encryptedRoot', 'efiUpdaterSucceeded'))
            or facts.get('signedModules') != ['zfs', 'v4l2loopback']
            or facts.get('espBytes') != 600 * 1024**2 or facts.get('xbootldrBytes') != 4 * 1024**3):
        raise ValueError('Observed guest acceptance differs from the exact native seal or required boot facts')
    report = {'schema': 1, 'scope': 'fresh encrypted installation and boot', 'validationOnly': True,
              'sourceRevision': seal['sourceRevision'], 'image': metadata['payload'], 'isoSha256': iso_hash,
              'bootCertificateDerSha256': seal['certificateDerSha256'],
              'installerMedium': 'read-only hybrid ISO attached as a VirtIO disk',
              'mokEnrollment': 'pre-enrolled disposable OVMF variables', 'memoryMiB': MEMORY_MIB,
              'hostReserveMiB': RESERVE_MIB, 'vcpu': 2, 'freshAccepted': True, **facts}
    (args.evidence / 'fresh-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('iso', 'seal', 'certificate', 'module-certificate', 'state', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    try:
        qualify(parser.parse_args())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'Native ISO guest qualification failed: {error}')


if __name__ == '__main__':
    main()
