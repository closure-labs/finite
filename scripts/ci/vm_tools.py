#!/usr/bin/env python3
"""Provision VM tools and bind evidence to the actual Nix executables."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ('qemu-system-x86_64', 'qemu-img', 'xorriso', 'mcopy', 'openssl',
         'ssh', 'ssh-keygen', 'skopeo', 'virt-fw-vars', 'python3')
PACKAGES = ('qemu-system-x86', 'qemu-utils', 'ovmf', 'xorriso', 'skopeo',
            'mtools', 'openssl', 'python3-virt-firmware')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def provision(provider):
    env = dict(os.environ)
    if provider == 'nix':
        result = subprocess.check_output(['nix', 'build', '--file', 'lib/ci-tools.nix', 'vm-tools',
                                          '--no-link', '--print-out-paths'], cwd=ROOT, text=True, timeout=1800).strip()
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-finite-ci-vm-tools', result):
            raise ValueError('Expected one pinned VM tools output')
        directory = Path(result)
        if (directory / 'bin/nix').exists() or (directory / 'bin/bluebuild').exists():
            raise ValueError('VM tools must preserve host Nix and BlueBuild')
        env.update(PATH=str(directory / 'bin') + os.pathsep + env['PATH'],
                   FINITE_VM_FIRMWARE_DIR=str(directory / 'share/finite-vm/firmware'),
                   FINITE_VM_TOOLS_MANIFEST=str(directory / 'share/finite-vm/toolchain.json'))
    elif provider in ('apt', 'apt-minimal'):
        subprocess.run(['sudo', 'apt-get', 'update'], check=True, timeout=1800)
        command = ['sudo', 'apt-get', 'install', '-y']
        if provider == 'apt-minimal':
            command.append('--no-install-recommends')
        subprocess.run(command + list(PACKAGES), check=True, timeout=1800)
        env.pop('FINITE_VM_TOOLS_MANIFEST', None)
        env['FINITE_VM_FIRMWARE_DIR'] = '/usr/share/OVMF'
    else:
        raise ValueError('Unknown VM tools provider')
    return env


def identity(env=os.environ):
    path = Path(env['FINITE_VM_TOOLS_MANIFEST'])
    if path.stat().st_size > 65536:
        raise ValueError('Oversized VM tools manifest')
    value = json.loads(path.read_text())
    if (value.get('schema') != 1 or value.get('provider') != 'nix'
            or set(value.get('executables', {})) != set(TOOLS)
            or value.get('firmware', {}).get('secureBoot') is not True):
        raise ValueError('Incomplete Nix VM tools identity')
    for name, record in value['executables'].items():
        actual = shutil.which(name, path=env['PATH'])
        expected = record.get('path', '')
        if (not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/\s]+/bin/' + re.escape(name), expected)
                or not actual or Path(actual).resolve() != Path(expected).resolve()
                or not isinstance(record.get('version'), str) or not record['version']):
            raise ValueError('VM executable differs from pinned manifest: ' + name)
        record['sha256'] = digest(actual)
    firmware = Path(env['FINITE_VM_FIRMWARE_DIR'])
    for name, key in [('OVMF_CODE_4M.secboot.fd', 'code'), ('OVMF_VARS_4M.ms.fd', 'variables')]:
        if (firmware / name).resolve() != Path(value['firmware'][key]).resolve():
            raise ValueError('VM firmware differs from pinned manifest')
    return value


def smoke(env):
    for name in TOOLS:
        if not shutil.which(name, path=env['PATH']):
            raise ValueError('Missing VM tool: ' + name)
    for command in (['qemu-system-x86_64', '--version'], ['qemu-img', '--version'],
                    ['xorriso', '-version'], ['openssl', 'version'], ['skopeo', '--version']):
        subprocess.run(command, env=env, check=True, timeout=30)
    directory = Path(env['FINITE_VM_FIRMWARE_DIR'])
    for name in ('OVMF_CODE_4M.secboot.fd', 'OVMF_VARS_4M.ms.fd'):
        if not (directory / name).is_file():
            raise ValueError('Missing Secure Boot firmware: ' + name)
    return identity(env) if env.get('FINITE_VM_TOOLS_MANIFEST') else {
        'provider': 'apt', 'packages': subprocess.check_output(
            ['dpkg-query', '-W', '-f=${Package}=${Version}\n', *PACKAGES], text=True, timeout=30),
        'executables': {name: str(Path(shutil.which(name, path=env['PATH'])).resolve()) for name in TOOLS},
        'firmware': {name: digest(directory / name) for name in ('OVMF_CODE_4M.secboot.fd', 'OVMF_VARS_4M.ms.fd')}}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    env = provision('nix')
    smoke(env)
    # Values originate only from a strictly checked local store path.
    with open(os.environ['GITHUB_PATH'], 'a') as output:
        output.write(env['PATH'].split(os.pathsep)[0] + '\n')
    with open(os.environ['GITHUB_ENV'], 'a') as output:
        for name in ('FINITE_VM_FIRMWARE_DIR', 'FINITE_VM_TOOLS_MANIFEST'):
            output.write(name + '=' + env[name] + '\n')


if __name__ == '__main__':
    main()
