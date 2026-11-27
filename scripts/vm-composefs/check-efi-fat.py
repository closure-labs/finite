#!/usr/bin/env python3
"""Exercise EFI file transactions on a loop-mounted scratch FAT inside a VM."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(*command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def check(helper):
    virtual = subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip()
    if os.geteuid() != 0 or virtual not in ('qemu', 'kvm') or not Path('/usr/share/finite-vm/revision').is_file():
        raise ValueError('This test requires root in the disposable Finite fixture VM')
    loader = importlib.machinery.SourceFileLoader('efi_fat_test', str(helper))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    efi = importlib.util.module_from_spec(spec)
    loader.exec_module(efi)
    result = {'schema': 1, 'filesystem': 'vfat', 'interruptedWritesRecovered': [],
              'scope': 'scratch FAT file transactions only; no shim/SBAT or firmware qualification'}
    # Names and writes are realistic, but these inert payloads deliberately test
    # file operations rather than claim a firmware/signature acceptance result.
    payload = {name: ('test payload ' + name).encode() for name in efi.PAYLOAD_NAMES}
    with tempfile.TemporaryDirectory(prefix='finite-vm-efi-', dir='/var/tmp') as temporary:
        root = Path(temporary)
        disk, esp = root / 'fat.img', root / 'esp'
        disk.touch(mode=0o600)
        disk.open('r+b').truncate(64 * 1024**2)
        run('mkfs.fat', '-i', '1234ABCD', str(disk))
        esp.mkdir()
        run('mount', '-o', 'loop,nodev,nosuid,noexec', str(disk), str(esp))
        try:
            for name in ('EFI/finite/grubx64.efi', 'EFI/BOOT/BOOTX64.EFI',
                         'EFI/fedora/grubx64.efi', 'EFI/refind/refind_x64.efi'):
                path = esp / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('preserved ' + name).encode())
            before = snapshot(esp)
            for boundary in range(1, 8):
                state = root / ('state-' + str(boundary))
                state.mkdir(mode=0o700)
                original = efi.atomic_bytes
                writes = 0

                def interrupted(path, content):
                    nonlocal writes
                    if path.is_relative_to(esp):
                        writes += 1
                        if writes == boundary:
                            raise InterruptedError('injected EFI write interruption')
                    original(path, content)

                efi.atomic_bytes = interrupted
                try:
                    try:
                        efi.apply(esp, state, efi.mapping(payload, True), esp_uuid='1234-ABCD')
                    except InterruptedError:
                        pass
                    else:
                        raise ValueError('Failure injection did not interrupt the transaction')
                finally:
                    efi.atomic_bytes = original
                generation = next(state.glob('*/journal.json')).parent.name
                efi.recover(esp, state, generation, esp_uuid='1234-ABCD')
                if snapshot(esp) != before:
                    raise ValueError('FAT recovery did not restore every previous file')
                result['interruptedWritesRecovered'].append(boundary)
            state = root / 'committed'
            state.mkdir(mode=0o700)
            generation = efi.apply(esp, state, efi.mapping(payload, False), esp_uuid='1234-ABCD')
            if efi.apply(esp, state, efi.mapping(payload, False), esp_uuid='1234-ABCD') is not None:
                raise ValueError('FAT transaction is not idempotent')
            run('umount', str(esp))
            run('mount', '-o', 'loop,nodev,nosuid,noexec', str(disk), str(esp))
            efi.recover(esp, state, generation.name, esp_uuid='1234-ABCD')
            if snapshot(esp) != before:
                raise ValueError('Committed FAT generation could not be recovered after remount')
            result.update(idempotent=True, committedGenerationRestoredAfterRemount=True,
                          previousRecoveryPathsPreserved=True)
        finally:
            run('umount', str(esp))
        run('fsck.fat', '-n', str(disk))
        result['fsckClean'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('helper', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.helper), indent=2))
