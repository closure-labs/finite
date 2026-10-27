#!/usr/bin/env python3
"""Bind qualification to reviewed inputs and the actual runner firmware/tools."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
import vm_tools
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
                    root / 'scripts/ci/nix-resources.py', root / 'scripts/ci/bluefin-upstream.py',
                    root / 'scripts/ci/ci-options.py', root / 'cosign.pub',
                    root / 'scripts/ci/foundation_timings.py',
                    root / 'scripts/ci/vm_tools.py', root / 'scripts/ci/vm-host.py', root / 'lib/vm-tools.nix',
                    root / '.github/actions/setup-vm-tools/action.yml',
                    root / '.github/workflows/iso.yml',
                    root / '.github/workflows/qualification.yml',
                    root / '.github/workflows/vm-acceptance.yml'})
    # Include scripts copied into guests and their security contract inputs.
    paths += sorted(root.joinpath('files/system/usr/libexec/finite').glob('*'))
    # Preserve content and executable-mode changes now that host-only installer
    # inputs have their own identity rather than forcing another image build.
    inputs = {str(path.relative_to(root)): {
        'sha256': sha(path), 'executable': bool(path.stat().st_mode & 0o111),
        'symlink': str(path.readlink()) if path.is_symlink() else None
    } for path in paths if path.is_file() and path.suffix != '.pyc'}
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
    directory = Path(os.environ.get('FINITE_VM_FIRMWARE_DIR', '/usr/share/OVMF'))
    firmware = {name: sha(directory / name) for name in (
        'OVMF_CODE_4M.secboot.fd', 'OVMF_VARS_4M.ms.fd')}
    if os.environ.get('FINITE_VM_TOOLS_MANIFEST'):
        versions = json.dumps(vm_tools.identity(), sort_keys=True)
    else:
        versions = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}=${Version}\n',
            'qemu-system-x86', 'qemu-utils', 'ovmf', 'xorriso', 'mtools', 'openssl', 'skopeo', 'python3-virt-firmware'], text=True, timeout=30)
    value = {'schema': 2, 'platform': 'linux/amd64', 'runner': 'ubuntu-24.04',
            'inputs': inputs, 'firmware': firmware, 'packages': versions.strip(),
            'bluebuildVersion': json.loads((root / 'sources/bluebuild-cli.json').read_text())}
    compression = os.environ.get('FINITE_INSTALLER_COMPRESSION', 'default')
    if compression == 'zstd':
        value['installerCompression'] = {'schema': 1, 'algorithm': 'zstd', 'level': 15, 'bcj': False,
            'presetSha256': sha(root / 'files/installer/lorax-zstd.conf')}
    elif compression != 'default':
        raise ValueError('Unknown installer compression experiment')
    return value


def iso_binding(directory):
    subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=directory, check=True, timeout=300)
    paths = list(directory.glob('*.iso'))
    if len(paths) != 1 or paths[0].is_symlink():
        raise ValueError('Qualification requires one pristine candidate ISO')
    value = {'name': paths[0].name, 'sha256': sha(paths[0]),
            'installationSha256': sha(directory / 'installation.json'),
            'installer': json.loads((directory / 'installation.json').read_text())['installer']}
    if os.environ.get('FINITE_VALIDATION_ONLY') == 'true':
        value['sizeBytes'] = paths[0].stat().st_size
    return value


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
        historical = {'finite': 'bluefin-generic', 'finite-dev': 'bluefin-dx-generic'}
        if phase == 'upgrade' and value.get('sourceProfile', profile) not in (profile, historical.get(profile)):
            raise ValueError('Upgrade source profile belongs to a different foundation')
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
        origins_path = directory / 'qualification-phase-origins.json'
        if origins_path.exists():
            origins = json.loads(desktop.read(origins_path))
            if (origins.get('schema') != 1 or origins.get('repository') != 'closure-labs/finite'
                    or origins.get('run') != int(os.environ['GITHUB_RUN_ID'])
                    or origins.get('attempt') != int(os.environ['GITHUB_RUN_ATTEMPT'])
                    or origins.get('revision') != revision or origins.get('profile') != profile
                    or origins.get('validationOnly') is not False
                    or not isinstance(origins.get('phases'), dict) or set(origins['phases']) != set(phases)):
                raise ValueError('Collected phase origins differ from aggregation identity')
            for origin in origins['phases'].values():
                if (not isinstance(origin, dict) or origin.get('run') != origins['run']
                        or origin.get('revision') != revision or type(origin.get('attempt')) is not int
                        or not 1 <= origin['attempt'] <= origins['attempt']
                        or any(type(origin.get(key)) is not int or origin[key] <= 0 for key in ('job', 'artifactId'))
                        or not isinstance(origin.get('completedAt'), str)
                        or not isinstance(origin.get('artifactDigest'), str)
                        or not re.fullmatch(r'sha256:[0-9a-f]{64}', origin['artifactDigest'])):
                    raise ValueError('Invalid collected phase origin')
            completions = [datetime.fromisoformat(origin['completedAt'].replace('Z', '+00:00'))
                           for origin in origins['phases'].values()]
            now = datetime.now(timezone.utc)
            if any(value.tzinfo is None or value > now or now - value > timedelta(hours=24) for value in completions):
                raise ValueError('Collected qualification phase is expired or from the future')
            acceptance['qualifiedAt'] = min(completions).isoformat()
            acceptance['qualificationPhaseOrigins'] = origins['phases']
            acceptance['qualifiedIsoOrigin'] = {key: origins['phases']['fresh'][key]
                                                 for key in ('run', 'attempt', 'revision')}

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
