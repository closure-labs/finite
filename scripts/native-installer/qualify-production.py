#!/usr/bin/env python3
"""Install the exact production ISO in a capped guest and observe its sealed boot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shutil
import socket
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ISO = runpy.run_path(str(HERE / 'qualify-iso.py'))
RECOVERY_KEY = rb'(?:[cbdefghijklnrtuv]{8}-){7}[cbdefghijklnrtuv]{8}'
UNLOCK_SCREEN = re.compile(r'pass\s*(?:phrase|word)|unlock\s+(?:disk|volume)', re.IGNORECASE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def grub_rescue(guest):
    # Use the exact ISO's own shim, GRUB, signed Fedora kernel and initrd.
    # The one-time live arguments route the rescue console to the guest UART.
    guest.expect(rb'Press enter to boot the selected OS')
    guest.send_bytes(b'c')
    guest.expect(rb'grub>')
    for command in (
            'search --no-floppy --label FINITE-INSTALL --set=root',
            'linux /images/pxeboot/vmlinuz root=live:CDLABEL=FINITE-INSTALL rd.live.image '
            'enforcing=0 finite.native-installer=1 systemd.unit=multi-user.target console=ttyS0,115200n8 '
            'rd.plymouth=0 plymouth.enable=0 systemd.mask=finite-native-installer.service '
            'systemd.mask=serial-getty@ttyS0.service systemd.debug_shell=ttyS0',
            'initrd /images/pxeboot/initrd.img'):
        guest.send(command)
        result = guest.expect(rb'grub>|error:')
        require(result.group() == b'grub>', 'Production ISO GRUB could not load the live environment')
    guest.send('boot')
    guest.expect(rb'(?:bash|sh)-[0-9.]+# ')
    guest.send("stty -echo; printf '%s%s\\n' FINITE_PRODUCTION_ LIVE_READY")
    guest.expect(rb'FINITE_PRODUCTION_LIVE_READY')


def install(guest, password):
    guest.send('/usr/libexec/finite/finite-native-install install')
    guest.expect(rb'Finite native installer[^\r\n]*Secure Boot enabled', filter_kernel_messages=True, timeout=300)
    guest.expect(rb'Type the disk ID "virtio-FINITEQUALIFICATION" to continue:',
                 filter_kernel_messages=True, timeout=60)
    print('The normal installer verified its payload and selected the disposable disk', flush=True)
    guest.send('virtio-FINITEQUALIFICATION')
    guest.expect(rb'LUKS passphrase \(recovery fallback\):', filter_kernel_messages=True, timeout=60)
    guest.send(password)
    guest.expect(rb'Repeat the passphrase:', filter_kernel_messages=True, timeout=60)
    guest.send(password)
    print('The installer accepted interactive disk and passphrase confirmation', flush=True)
    recovery = guest.expect(RECOVERY_KEY, filter_kernel_messages=True).group().decode('ascii')
    guest.expect(rb'Installation complete\.')
    print('Exact ISO completed installation and generated a recovery key', flush=True)
    guest.send('mkdir -p /run/finite-observation && '
               'mount -o ro,noload,nodev,nosuid,noexec /dev/disk/by-id/virtio-FINITEOBSERVATION /run/finite-observation && '
               'cp /run/finite-observation/production-observer-setup.sh /run/finite-production-setup.sh && '
               'umount /run/finite-observation && bash /run/finite-production-setup.sh')
    guest.expect_unlock()
    guest.send(password)
    guest.expect(rb'FINITE_PRODUCTION_OBSERVER_READY')
    guest.send('systemctl --no-block poweroff')
    guest.shutdown()
    return recovery


def qmp_command(channel, command, **arguments):
    channel.write(json.dumps({'execute': command, 'arguments': arguments}).encode() + b'\n')
    channel.flush()
    for response in channel:
        message = json.loads(response)
        if 'return' in message:
            return message['return']
        if 'error' in message:
            raise RuntimeError(f'QEMU monitor rejected {command}')
    raise RuntimeError(f'QEMU monitor closed during {command}')


def unlock(guest, monitor, screenshot, recovery):
    deadline = min(guest.deadline, time.monotonic() + 300)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        while not monitor.is_socket() and time.monotonic() < deadline:
            if not guest.read_console(0.25):
                raise RuntimeError('QEMU stopped before opening its local monitor')
        connection.connect(str(monitor))
        with connection.makefile('rwb') as channel:
            require('QMP' in json.loads(channel.readline()), 'Invalid QEMU monitor greeting')
            qmp_command(channel, 'qmp_capabilities')
            while time.monotonic() < deadline:
                qmp_command(channel, 'screendump', filename=str(screenshot))
                screen = subprocess.check_output(['tesseract', str(screenshot), 'stdout', '--psm', '11'],
                                                 text=True, stderr=subprocess.DEVNULL, timeout=15)
                if UNLOCK_SCREEN.search(screen):
                    for key in [*recovery, 'ret']:
                        qmp_command(channel, 'send-key', **{
                            'hold-time': 30, 'keys': [{'type': 'qcode', 'data': 'minus' if key == '-' else key}],
                        })
                        time.sleep(0.08)
                    return
                guest.check_failure()
                if not guest.read_console(1):
                    raise RuntimeError('QEMU stopped before asking for the recovery key')
    raise RuntimeError('Timed out waiting for the graphical LUKS prompt')


def qualify(args):
    branch = 'qualification/native-production-console' if args.console_probe else 'main'
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REF') == f'refs/heads/{branch}'
            and os.environ.get('GITHUB_WORKFLOW_REF') == (
                f'closure-labs/finite/.github/workflows/native-production-validation.yml@refs/heads/{branch}'),
            'Exact ISO qualification requires its dedicated hosted workflow')
    proof = json.loads(args.production_input.read_bytes())
    iso = args.iso.resolve(strict=True)
    metadata = iso.parent / 'installation.json'
    record = json.loads(metadata.read_bytes())
    certificate = subprocess.check_output(['openssl', 'x509', '-in', args.certificate, '-outform', 'DER'], timeout=30)
    require(proof['sourceRevision'] == record['finiteRevision'] == os.environ['GITHUB_SHA']
            and proof['validationOnly'] is args.console_probe and record['validationOnly'] is args.console_probe
            and record.get('consoleProbe', False) is args.console_probe and not record.get('migrationRehearsal', False)
            and record['payload'] == proof['image']
            and record['payloadTag'] == 'ghcr.io/closure-labs/finite:' + proof['profile']
            and hashlib.sha256(certificate).hexdigest() == proof['bootCertificateDerSha256'],
            'Production ISO metadata does not match the independently checked production input')
    iso_hash = ISO['file_sha256'](iso)
    sums = (iso.parent / 'SHA256SUMS').read_text().splitlines()
    require(f'{iso_hash}  {iso.name}' in sums
            and f'{ISO["file_sha256"](metadata)}  installation.json' in sums, 'Production ISO checksums differ')
    require(os.access('/dev/kvm', os.R_OK | os.W_OK), 'KVM is unavailable on the qualification runner')
    state = args.state.resolve()
    state.mkdir(mode=0o700)
    inputs = state / 'observer'
    inputs.mkdir()
    for name in ('production-observer-setup.sh', 'validation-guest.py', 'validation-guest.service', 'serial_records.py'):
        shutil.copyfile(HERE / name, inputs / name)
    observer = state / 'observer.raw'
    ISO['prepare_readonly_inputs'](observer, inputs, 0)
    firmware = Path(os.environ['FINITE_VM_FIRMWARE_DIR'])
    variables, disk = state / 'vars.fd', state / 'target.qcow2'
    guid = ISO['MOK_GUID']
    subprocess.run(['virt-fw-vars', '--input', firmware / 'OVMF_VARS_4M.ms.fd', '--output', variables,
                    '--add-mok', guid, args.certificate, '--add-mok', guid, args.module_certificate],
                   check=True, timeout=30)
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', disk, '64G'], check=True, timeout=30)
    command = ISO['qemu_arguments'](firmware, variables, disk, ISO['DISK_SERIAL'])
    setup = [*command, *ISO['install_media'](iso), '-smbios', 'type=1,serial=finite-production-install',
             '-drive', f'if=none,id=observation,format=raw,file={observer},readonly=on',
             '-device', 'virtio-blk-pci,drive=observation,serial=FINITEOBSERVATION']
    password = secrets.token_hex(16)
    # The default installer prints its generated key. Keep this transcript in
    # the private VM scratch area, outside both retained Actions artifacts.
    with (state / 'live-serial.log').open('xb') as log:
        with ISO['Guest'](setup, log, 2400) as guest:
            try:
                grub_rescue(guest)
            finally:
                # This copy precedes the installer and its printed key.
                shutil.copyfile(log.name, args.evidence / 'live-preinstall-serial.log')
            print('The ISO shim and GRUB reached the live installer console', flush=True)
            recovery = install(guest, password)
    print('Booting the installed production UKI with its generated recovery key', flush=True)
    monitor = state / 'qmp.sock'
    boot = [*command, '-smbios', 'type=1,serial=finite-production-boot', '-qmp', f'unix:{monitor},server=on,wait=off']
    with (args.evidence / 'production-boot-serial.log').open('xb') as log:
        with ISO['Guest'](boot, log, 900) as guest:
            unlock(guest, monitor, state / 'screen.ppm', recovery)
            facts = guest.record('FINITE_NATIVE_FRESH_BOOT')
            guest.shutdown()
    ISO['validate_boot_facts'](facts, proof)
    require(facts['installedUkiSha256'] in {uki['sha256'] for uki in proof['ukis']},
            'Running UKI bytes differ from the independently verified production UKIs')
    scope = 'disposable console rehearsal' if args.console_probe else 'production candidate and fresh encrypted installation'
    report = {'schema': 1, 'scope': scope, 'validationOnly': args.console_probe,
              'image': proof['image'], 'sourceRevision': proof['sourceRevision'],
              'isoSha256': iso_hash, 'freshAccepted': True, 'recoveryKeyUnlock': True,
              'bootCertificateDerSha256': proof['bootCertificateDerSha256'], 'vcpu': 2,
              'memoryMiB': ISO['MEMORY_MIB'], 'hostReserveMiB': ISO['RESERVE_MIB'], **facts}
    name = 'console-probe-acceptance.json' if args.console_probe else 'production-acceptance.json'
    (args.evidence / name).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('iso', 'production-input', 'certificate', 'module-certificate', 'state', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--console-probe', action='store_true')
    try:
        qualify(parser.parse_args())
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'Exact production qualification stopped: {error}')
