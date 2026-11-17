#!/usr/bin/env python3
"""Configure the disposable Finite VM's native service guard and shim/MOK chain."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--refresh-service-guards', action='store_true')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('vmrun', directory / 'run.py')
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)
    state = args.state.resolve()
    if not state.is_relative_to(vm.REPO / 'artifacts'):
        raise SystemExit('State must stay under checkout artifacts')
    if (not (state / 'target.raw').is_file()
            or (state / 'target.raw').stat().st_size not in {34359738368, 68719476736}):
        raise SystemExit('Expected the disposable 32 or 64 GiB target file')
    guard = (directory / 'native-firstboot.conf').read_text()
    guard_commands = ''
    for unit in ['finite-firstboot-rpm-ostree.service', 'rpm-ostreed.service']:
        path = '/etc/systemd/system/' + unit + '.d'
        guard_commands += (f'mkdir -p {path}\ncat > {path}/90-native.conf <<\'GUARD\'\n'
                           + guard + 'GUARD\n' + f'restorecon -RF {path}\n')
    if args.refresh_service_guards:
        if not (state / 'native-configuration.json').exists():
            raise SystemExit('Initial native configuration must be complete')
        vm.STATE = state
        process, log = vm.qemu('refresh-native-guards')
        try:
            vm.wait_ssh(process, 'refresh-native-guards')
            result = vm.ssh("bash -se <<'FINITE_GUARDS'\nset -eu\ntest ! -e /run/ostree-booted\n"
                            + guard_commands + '\nFINITE_GUARDS')
            (state / 'native-guard-refresh.txt').write_text(result.stdout + result.stderr)
            vm.ssh('systemctl poweroff', check=False)
            process.wait(timeout=60)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
            log.close()
        return
    if (state / 'native-configuration.json').exists():
        raise SystemExit('Configuration already completed; inspect its evidence')
    vm.STATE = state
    image = 'localhost/finite-native-rootfs:base'
    container = vm.capture(['docker', 'create', image, '/bin/true'])
    try:
        vm.run(['docker', 'cp', container + ':/etc/pki/akmods/certs/akmods-ublue.der',
                state / 'module-signing.der'])
    finally:
        vm.run(['docker', 'rm', container])
    vm.run(['openssl', 'x509', '-inform', 'DER', '-in', state / 'module-signing.der',
            '-out', state / 'module-signing.pem'])
    process, log = vm.qemu('configure-native')
    try:
        vm.wait_ssh(process, 'configure-native')
        status = json.loads(vm.ssh('bootc status --json').stdout)
        assert status['status']['booted']['composefs']['bootloader'] == 'systemd'
        # This is writable per-machine configuration; the signed image is unchanged.
        script = '''set -eu
case $(blockdev --getsize64 /dev/vda) in 34359738368|68719476736) ;; *) exit 1 ;; esac
test "$(cat /usr/share/finite-vm/revision)" = base
test ! -e /run/ostree-booted
test ! -e /boot/EFI/finite-shim
test ! -e /etc/systemd/system/finite-firstboot-rpm-ostree.service.d/90-native.conf
test ! -e /etc/systemd/system/rpm-ostreed.service.d/90-native.conf
''' + guard_commands + '''
mount -o remount,rw /boot
mkdir /boot/EFI/finite-shim
cp /usr/lib/efi/shim/16.1-7/EFI/fedora/shimx64.efi /boot/EFI/finite-shim/shimx64.efi
cp /usr/lib/efi/shim/16.1-7/EFI/fedora/mmx64.efi /boot/EFI/finite-shim/mmx64.efi
cp /boot/EFI/systemd/systemd-bootx64.efi /boot/EFI/finite-shim/grubx64.efi
sync
mount -o remount,ro /boot
efibootmgr --create --disk /dev/vda --part 2 --label 'Finite VM shim' --loader '\\EFI\\finite-shim\\shimx64.efi'
efibootmgr -v
'''
        result = vm.ssh('bash -se <<\'FINITE_CONFIGURATION\'\n' + script + '\nFINITE_CONFIGURATION')
        (state / 'native-guest-configuration.txt').write_text(result.stdout + result.stderr)
        vm.ssh('systemctl poweroff', check=False)
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        log.close()
    shutil.copyfile(state / 'OVMF_VARS.fd', state / 'OVMF_VARS-before-mok.fd')
    vm.run(['docker', 'run', '--rm', '--network=none', '--user', f'{os.getuid()}:{os.getgid()}',
            '--security-opt=label=disable', '-v', f'{state}:/state:rw',
            '--entrypoint=virt-fw-vars', image,
            '--input', '/state/OVMF_VARS.fd', '--output', '/state/OVMF_VARS-with-mok.fd',
            '--add-mok', '605dab50-e046-4300-abb6-3dd810dd8b23', '/state/module-signing.pem',
            '--add-mok', '49bc8d48-6a60-4e4d-83e7-2b3b25f6e96a', '/state/db.pem',
            '--sb', '--output-json', '/state/firmware-with-mok.json'])
    (state / 'OVMF_VARS-with-mok.fd').replace(state / 'OVMF_VARS.fd')
    report = {'module_certificate_sha256': hashlib.sha256((state / 'module-signing.der').read_bytes()).hexdigest(),
              'native_firstboot_guard': True, 'shim_chain_staged': True,
              'scope': 'disposable VM only; runtime trust not yet qualified'}
    (state / 'native-configuration.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
