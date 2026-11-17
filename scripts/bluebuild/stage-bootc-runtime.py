#!/usr/bin/env python3
"""Build one source-locked native Fedora bootc RPM for installer and OS images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def validate(pin):
    if (type(pin.get('schema')) is not int or pin['schema'] != 1 or pin.get('kind') not in ('upstream-snapshot', 'release')
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', pin.get('version', ''))
            or not re.fullmatch('[0-9a-f]{40}', pin.get('revision', ''))
            or not re.fullmatch('[0-9a-f]{64}', pin.get('archiveSha256', ''))
            or not re.fullmatch('[0-9a-f]{40}', pin.get('requiredFix', ''))
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', pin.get('minimumOfficialVersion', ''))
            or not re.fullmatch('[0-9A-Za-z.]+', pin.get('rpmRelease', ''))
            or not re.fullmatch(r'registry.fedoraproject.org/fedora@sha256:[0-9a-f]{64}', pin.get('buildBase', ''))):
        raise ValueError('Invalid locked bootc runtime source')
    expected = pin['revision'] if pin['kind'] == 'upstream-snapshot' else 'v' + pin['version']
    if pin.get('ref') != expected:
        raise ValueError('Runtime source must use the exact snapshot or official release tag')
    return pin


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage(engine, output, archive=None, memory_mib=2048):
    pin_path = ROOT / 'sources/bootc-runtime.json'
    pin = validate(json.loads(pin_path.read_text()))
    lock_hash = sha(pin_path)
    # Reuse only exact source AND packaging inputs, and rehash the RPM bytes.
    inputs = hashlib.sha256(b''.join((ROOT / 'scripts/bluebuild' / name).read_bytes()
                            for name in ('bootc-runtime.Containerfile', 'build-bootc-runtime.sh'))).hexdigest()
    receipt_path = output / 'receipt.json'
    if receipt_path.is_file():
        prior = json.loads(receipt_path.read_text())
        if (prior.get('sourceLockSha256') == lock_hash and prior.get('buildInputsSha256') == inputs
                and sha(output / 'source-lock.json') == lock_hash
                and sha(output / 'bootc-runtime.rpm') == prior.get('rpmSha256')):
            print('Reusing checked native bootc RPM')
            return prior
        raise ValueError('Existing runtime output differs; use a fresh output directory')
    if output.exists():
        raise ValueError('Runtime output directory must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bootc-runtime-', dir=output.parent) as temporary:
        work = Path(temporary)
        source = work / 'source.tar.gz'
        if archive:
            shutil.copyfile(archive, source)
        else:
            request = urllib.request.Request('https://codeload.github.com/bootc-dev/bootc/tar.gz/' + pin['ref'],
                                             headers={'User-Agent': 'finite-bootc-runtime'})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read(32 * 1024**2 + 1)
            if not 0 < len(data) <= 32 * 1024**2:
                raise ValueError('Runtime source archive exceeds its bound')
            source.write_bytes(data)
        if sha(source) != pin['archiveSha256']:
            raise ValueError('Upstream runtime archive differs from the reviewed source hash')
        shutil.copyfile(pin_path, work / 'source-lock.json')
        shutil.copyfile(ROOT / 'scripts/bluebuild/build-bootc-runtime.sh', work / 'build-runtime.sh')
        shutil.copyfile(ROOT / 'scripts/bluebuild/bootc-runtime.Containerfile', work / 'Containerfile')
        tag = 'localhost/finite-bootc-runtime:' + lock_hash[:16] + '-' + inputs[:12]
        command = [engine]
        # Workstation isolation can be selected without changing global Podman
        # storage. Credentials and host devices are never mounted by this helper.
        if engine == 'podman' and os.environ.get('FINITE_PODMAN_ROOT'):
            command += ['--root', os.environ['FINITE_PODMAN_ROOT'], '--runroot', os.environ['FINITE_PODMAN_RUNROOT'],
                        '--storage-driver', 'overlay']
        subprocess.run([*command, 'build', '--memory', str(memory_mib) + 'm', '--memory-swap', str(memory_mib) + 'm',
                        '--build-arg', 'BUILD_BASE=' + pin['buildBase'], '--tag', tag, str(work)], check=True)
        container = subprocess.check_output([*command, 'create', tag, '/unused'], text=True).strip()
        try:
            staged = work / 'packages'
            staged.mkdir(mode=0o700)
            for name in ('bootc-runtime.rpm', 'source-lock.json'):
                subprocess.run([*command, 'cp', container + ':/' + name, staged / name], check=True)
        finally:
            subprocess.run([*command, 'rm', container], check=True)
        receipt = {'schema': 1, 'sourceLockSha256': lock_hash, 'buildInputsSha256': inputs,
                   'rpmSha256': sha(staged / 'bootc-runtime.rpm'), 'version': pin['version'],
                   'revision': pin['revision'], 'kind': pin['kind']}
        (staged / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if output.exists():
            raise ValueError('Runtime output appeared while building; refusing replacement')
        staged.rename(output)
        print('Staged native bootc RPM from ' + pin['ref'])
        return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['docker', 'podman'], default='docker')
    parser.add_argument('--output', type=Path, default=ROOT / 'files/bootc-runtime')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--memory-mib', type=int, choices=[1536, 2048, 3072], default=2048)
    args = parser.parse_args()
    stage(args.engine, args.output.resolve(), args.archive, args.memory_mib)
