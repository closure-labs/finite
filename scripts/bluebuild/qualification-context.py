#!/usr/bin/env python3
"""Bind qualification to reviewed inputs and the actual runner firmware/tools."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qualification_desktop', ROOT / 'scripts/bluebuild/desktop-qualification.py')
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_inputs(root=ROOT):
    # Conservative dependency coverage: a change to any VM helper or installer
    # invalidates reuse, including desktop observations and personalization.
    paths = sorted({*root.joinpath('scripts/bluebuild').glob('*'),
                    *root.joinpath('files/installer').glob('*'),
                    root / 'sources/bluebuild-installer.json', root / 'sources/bluebuild-cli.json', root / 'sources/installer-security.json',
                    root / 'scripts/ci/nix-resources.py', root / 'scripts/ci/bluefin-upstream.py', root / 'cosign.pub',
                    root / '.github/workflows/qualification.yml',
                    root / '.github/workflows/vm-acceptance.yml'})
    # Include scripts copied into guests and their security contract inputs.
    paths += sorted(root.joinpath('files/system/usr/libexec/finite').glob('*'))
    inputs = {str(path.relative_to(root)): sha(path) for path in paths if path.is_file() and path.suffix != '.pyc'}
    if 'sources/installer-security.json' not in inputs:
        raise ValueError('Pinned installer certificate context is missing')
    return inputs


def validate_certificate(root=ROOT):
    lock = json.loads((root / 'sources/installer-security.json').read_text())
    if lock.get('certificate') != 'files/installer/secure-boot.pem':
        raise ValueError('Qualification requires the reviewed installer certificate path')
    subprocess.run(['openssl', 'x509', '-in', str(root / lock['certificate']), '-checkend', '0', '-noout'],
                   check=True, stdout=subprocess.DEVNULL, timeout=30)


def context(root=ROOT):
    validate_certificate(root)
    inputs = source_inputs(root)
    firmware = {name: sha('/usr/share/OVMF/' + name) for name in (
        'OVMF_CODE_4M.secboot.fd', 'OVMF_VARS_4M.ms.fd')}
    versions = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}=${Version}\n',
        'qemu-system-x86', 'qemu-utils', 'ovmf', 'xorriso', 'mtools', 'openssl', 'skopeo', 'python3-virt-firmware'], text=True, timeout=30)
    return {'schema': 1, 'platform': 'linux/amd64', 'runner': 'ubuntu-24.04',
            'inputs': inputs, 'firmware': firmware, 'packages': versions.strip(),
            'bluebuildVersion': json.loads((root / 'sources/bluebuild-cli.json').read_text())}


def iso_binding(directory):
    subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=directory, check=True, timeout=300)
    paths = list(directory.glob('*.iso'))
    if len(paths) != 1 or paths[0].is_symlink():
        raise ValueError('Qualification requires one pristine candidate ISO')
    return {'name': paths[0].name, 'sha256': sha(paths[0]),
            'installationSha256': sha(directory / 'installation.json'),
            'installer': json.loads((directory / 'installation.json').read_text())['installer']}


def bind_phase(directory, phase):
    acceptance = directory / ('vm-' + phase) / 'acceptance.json'
    value = json.loads(acceptance.read_text())
    current = json.loads((directory / (phase + '-qualification-context.json')).read_text())
    if os.environ.get('FINITE_VALIDATION_ONLY') == 'true':
        value['validationOnly'] = True
    value['qualificationContext'] = current
    value['qualificationContextSha256'] = identity(current)
    value['iso'] = iso_binding(directory / ('iso-candidate' if phase == 'fresh' else 'iso-predecessor'))
    acceptance.write_text(json.dumps(value, indent=2) + '\n')


def aggregate(directory, profile, candidate, previous, source, build_identity, revision):
    phases = ['fresh', 'upgrade'] if previous else ['fresh']
    contexts = []
    for phase in phases:
        value = json.loads(desktop.read(directory / ('vm-' + phase) / 'acceptance.json'))
        image = candidate if phase == 'fresh' else 'ghcr.io/closure-labs/finite@' + previous
        if (value.get('accepted') is not True or value.get('secureBoot') is not True
                or value.get('encryptedRoot') is not True or value.get('source') != image
                or value.get('profile') != profile
                or (phase == 'upgrade' and value.get('target') != candidate)):
            raise ValueError('Required VM phase did not accept the exact candidate/predecessor')
        current = value.get('qualificationContext')
        if not current or identity(current) != value.get('qualificationContextSha256'):
            raise ValueError('VM phase has no complete qualification context')
        if (value.get('validationOnly') is True) != (os.environ.get('FINITE_VALIDATION_ONLY') == 'true'):
            raise ValueError('VM phase diagnostic mode differs from aggregation mode')
        contexts.append(current)
    if any(current != contexts[0] for current in contexts):
        raise ValueError('Qualification runners used different firmware, tools or tests')
    fresh = json.loads(desktop.read(directory / 'vm-fresh/acceptance.json'))
    installation_path = directory / 'iso-candidate/installation.json'
    installation = json.loads(desktop.read(installation_path))
    if (sha(installation_path) != fresh['iso']['installationSha256']
            or installation['image'] != candidate or installation['profile'] != profile
            or installation['installer'] != fresh['iso']['installer']):
        raise ValueError('Pristine candidate ISO metadata differs from the tested bytes')
    acceptance = {'schema': 2, 'candidate': candidate, 'previousDigest': previous,
        'profile': profile, 'revision': revision, 'sourceRevision': source, 'buildIdentity': build_identity,
        'secureBoot': True, 'encryptedRoot': True, 'accepted': True, 'bootstrap': not previous,
        'qualifiedAt': datetime.now(timezone.utc).isoformat(),
        'qualificationContext': contexts[0], 'qualificationContextSha256': identity(contexts[0]),
        'qualifiedIso': fresh['iso']}
    if os.environ.get('FINITE_VALIDATION_ONLY') == 'true':
        acceptance['validationOnly'] = True
    if os.environ.get('FINITE_VALIDATION_ONLY') != 'true' and os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_RUN_ATTEMPT'):
        acceptance['qualifiedIsoOrigin'] = {'run': int(os.environ['GITHUB_RUN_ID']),
            'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'revision': revision}
    desktop.assemble(directory, acceptance)
    (directory / (profile + '-acceptance.json')).write_text(json.dumps(acceptance, indent=2) + '\n')
    return acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['context', 'bind-phase', 'aggregate'])
    parser.add_argument('--directory', type=Path, default=Path('.bluebuild'))
    parser.add_argument('--phase', choices=['fresh', 'upgrade'])
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.operation == 'context':
        filename = (args.phase + '-' if args.phase else '') + 'qualification-context.json'
        (args.directory / filename).write_text(json.dumps(context(), indent=2) + '\n')
    elif args.operation == 'bind-phase':
        bind_phase(args.directory, args.phase)
    else:
        aggregate(args.directory, os.environ['PROFILE'], 'ghcr.io/closure-labs/finite@' + os.environ['CANDIDATE_DIGEST'],
                  os.environ.get('PREVIOUS_DIGEST', ''), os.environ['SOURCE_REVISION'],
                  os.environ['BUILD_IDENTITY'], os.environ['GITHUB_SHA'])


if __name__ == '__main__':
    main()
