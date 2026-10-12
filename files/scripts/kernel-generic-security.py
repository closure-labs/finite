#!/usr/bin/env python3
"""Install the authenticated generic Fedora kernel and retire optional virtual cameras."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('security_remediate', Path(__file__).with_name('security-remediate.py'))
rpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpm)

RUNTIME = ('kernel', 'kernel-core', 'kernel-modules-core', 'kernel-modules', 'kernel-modules-extra')
DEVELOPMENT = ('kernel-devel', 'kernel-devel-matched')
CAMERA = ('kmod-v4l2loopback', 'v4l2loopback')
PROFILES = ('bluefin-generic', 'bluefin-dx-generic')
RELEASE = '7.2.9-201.fc44.x86_64'
prune_spec = importlib.util.spec_from_file_location('kernel_module_prune', Path(__file__).with_name('kernel-module-prune.py'))
module_prune = importlib.util.module_from_spec(prune_spec)
prune_spec.loader.exec_module(module_prune)
# Preserve the public helper name for callers and the focused guard fixtures.
prune_modules = module_prune.prune_modules
ZFS = module_prune.ZFS_PACKAGES

def run(args):
    with tempfile.TemporaryFile(mode='w+') as output:
        result = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, text=True,
                                timeout=900, env={**os.environ, 'LC_ALL': 'C'})
        output.seek(0, 2)
        size = output.tell()
        if result.returncode:
            output.seek(max(0, size - 65536))
            diagnostic = output.read()
            expected_unowned = (args[:2] == ['rpm', '-qf'] and result.returncode == 1
                                and diagnostic.strip() == f'file {args[-1]} is not owned by any package')
            if not expected_unowned:
                print(diagnostic, file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode, args, output=diagnostic)
        if size > 2 * 1024 * 1024:
            raise ValueError('Kernel command output exceeded the reviewed limit')
        output.seek(0)
        return output.read().strip()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_policy(path):
    policy = json.loads(Path(path).read_text())
    fields = {'schema', 'fedora', 'release', 'keySHA256', 'keyFingerprint', 'source', 'packages'}
    if (not isinstance(policy, dict) or set(policy) != fields
            or type(policy['schema']) is not int or policy['schema'] != 1
            or type(policy['fedora']) is not int or policy['fedora'] != 44
            or policy['release'] != RELEASE
            or policy['source'] != 'https://bodhi.fedoraproject.org/updates/FEDORA-2026-c2d6603acd'
            or policy['keySHA256'] != '93642aec521a1e5e96dd715f7ae0ec0850ebc9de09a94ce03cae5263f26cc18a'
            or policy['keyFingerprint'] != '36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6'
            or not isinstance(policy['packages'], list)
            or len(policy['packages']) != len(RUNTIME + DEVELOPMENT)):
        raise ValueError('Invalid generic kernel source policy')
    for entry, name in zip(policy['packages'], RUNTIME + DEVELOPMENT):
        file = f'{name}-{RELEASE}.rpm'
        url = f'https://kojipkgs.fedoraproject.org/packages/kernel/7.2.9/201.fc44/data/signed/6d9f90a6/x86_64/{file}'
        if (not isinstance(entry, dict) or set(entry) != {'name', 'file', 'url', 'sha256'}
                or entry['name'] != name or entry['file'] != file or entry['url'] != url
                or not isinstance(entry['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])):
            raise ValueError(f'Missing or invalid authenticated generic payload: {name}')
    return policy


def download(url, destination, runner):
    runner(['curl', '--fail', '--silent', '--show-error', '--proto', '=https',
            '--connect-timeout', '15', '--max-time', '300', '--retry', '2',
            '--retry-max-time', '600', '--max-filesize', '268435456',
            '--output', str(destination), url])


def authenticate(package, database, fingerprint, runner):
    output = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(package)])
    signatures = [line.strip() for line in output.splitlines() if 'signature' in line.lower()]
    if (not signatures or any(not line.endswith(': OK')
                              or f'key fingerprint: {fingerprint.lower()}: OK' not in line
                              for line in signatures)
            or re.search(r'\b(?:NOKEY|NOT OK|BAD|FAILED|UNTRUSTED)\b', output, re.IGNORECASE)):
        raise ValueError('Generic kernel RPM signature does not match the reviewed Fedora key')


def check_changes(before, after, allowed):
    # Fail the image build before it can be published if the solver affects any
    # unrelated package, including bootc, ostree, developer tools, or firmware.
    for name in before.keys() | after.keys():
        if name in ZFS and name in allowed:
            if after.get(name) is not None and before.get(name) != after.get(name):
                raise ValueError('Authorized ZFS transition must remove the package: ' + name)
            continue
        if name not in allowed and before.get(name) != after.get(name):
            raise ValueError(f'Generic kernel transaction changed unrelated package: {name}')


def validate_kernel(inventory, development):
    expected = [('0:' + RELEASE.rsplit('.', 1)[0], 'x86_64')]
    for name in RUNTIME + (DEVELOPMENT if development else ()):
        if inventory.get(name) != expected:
            raise ValueError(f'Generic kernel package does not match the reviewed release: {name}')
    if not development and any(name in inventory for name in DEVELOPMENT):
        raise ValueError('Generic kernel transaction introduced development packages')
    if any(name in inventory for name in CAMERA):
        raise ValueError('Optional virtual camera packages remain installed')
    if any(name in inventory for name in ZFS):
        raise ValueError('Host ZFS packages remain installed')


def remediate(policy, key, profile, runner=None, downloader=None, modules_root='/usr/lib/modules'):
    runner = runner or run
    downloader = downloader or download
    if profile not in PROFILES:
        raise ValueError('Generic kernel remediation requires an explicit generic profile')
    if runner(['rpm', '--eval', '%{fedora}']) != '44':
        raise ValueError('Generic kernel remediation requires Fedora 44')
    before = rpm.inventory(runner)
    if any(name not in before for name in RUNTIME):
        raise ValueError('Generic base is missing a required runtime kernel package')
    for name in RUNTIME + DEVELOPMENT:
        if any(arch != 'x86_64' or not evr.startswith('0:') or not evr.endswith('.fc44')
               for evr, arch in before.get(name, [])):
            raise ValueError('Installed generic kernel package is outside the reviewed architecture/release')
    development = any(name in before for name in DEVELOPMENT)
    old_releases = {evr.split(':', 1)[1] + '.' + arch for evr, arch in before['kernel-core']}
    try:
        validate_kernel(before, development)
    except ValueError:
        pass
    else:
        prune_modules(modules_root, RELEASE, old_releases, runner)
        print('Reviewed generic kernel already installed; no network access required')
        return
    target_evr = '0:' + RELEASE.rsplit('.', 1)[0]
    for name in RUNTIME + DEVELOPMENT:
        for evr, _ in before.get(name, []):
            compared = runner(['rpm', '--eval', '%{lua:print(rpm.vercmp("' + evr + '", "' + target_evr + '"))}'])
            if compared not in ('-1', '0', '1') or compared == '1':
                raise ValueError('Generic kernel would downgrade an installed package: ' + name)
    for evr, arch in before['kernel-core']:
        old_release = evr.split(':', 1)[1] + '.' + arch
        path = Path(modules_root) / old_release / 'vmlinuz'
        owner = runner(['rpm', '-qf', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}', str(path)])
        if owner != '\t'.join(('kernel-core', evr, arch)):
            raise ValueError('Original generic module directory ownership is not established: ' + old_release)
    if digest(key) != policy['keySHA256']:
        raise ValueError('Generic kernel signing key digest mismatch')
    allowed = set(RUNTIME + CAMERA + ZFS + (DEVELOPMENT if development else ()))
    with tempfile.TemporaryDirectory(prefix='finite-generic-kernel-') as temporary:
        directory = Path(temporary)
        database = directory / 'rpmdb'
        database.mkdir()
        runner(['rpm', '--dbpath', str(database), '--initdb'])
        runner(['rpmkeys', '--dbpath', str(database), '--import', str(key)])
        packages = []
        for entry in policy['packages']:
            if entry['name'] in DEVELOPMENT and not development:
                continue
            package = directory / entry['file']
            downloader(entry['url'], package, runner)
            if digest(package) != entry['sha256']:
                raise ValueError('Generic kernel RPM digest mismatch: ' + entry['name'])
            authenticate(package, database, policy['keyFingerprint'], runner)
            metadata = runner(['rpm', '-qp', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}', str(package)])
            expected = '\t'.join((entry['name'], '0:' + RELEASE.rsplit('.', 1)[0], 'x86_64'))
            if metadata != expected:
                raise ValueError('Generic kernel RPM metadata mismatch: ' + entry['name'])
            packages.append(str(package))
        # Authenticate every required payload before the first image mutation.
        cleanup = [name for name in CAMERA + ZFS if name in before]
        dnf = ['dnf5', '-y', '--disable-repo=*', '--setopt=install_weak_deps=False']
        if cleanup:
            runner([*dnf, 'remove', '--no-autoremove', *cleanup])
            cleaned = rpm.inventory(runner)
            check_changes(before, cleaned, set(CAMERA + ZFS))
            if any(name in cleaned for name in CAMERA + ZFS):
                raise ValueError('Authorized virtual camera or ZFS cleanup was incomplete')
        # Import only the already hash-verified key; DNF checks local RPM trust
        # again. All repository access is disabled and no erasure is permitted.
        runner(['rpmkeys', '--import', str(key)])
        authenticated = rpm.inventory(runner)
        check_changes(before, authenticated, allowed | {'gpg-pubkey'})
        runner([*dnf, '--setopt=gpgcheck=1', '--setopt=*.gpgcheck=1',
                '--setopt=localpkg_gpgcheck=1', 'install', *packages])
        installed = rpm.inventory(runner)
        check_changes(authenticated, installed, allowed)
        target = ('0:' + RELEASE.rsplit('.', 1)[0], 'x86_64')
        if any(target not in installed.get(name, []) for name in RUNTIME + (DEVELOPMENT if development else ())):
            raise ValueError('New generic kernel package set was not installed completely')
        stale = [f'{name}-{evr}.{arch}' for name in RUNTIME + (DEVELOPMENT if development else ())
                 for evr, arch in installed.get(name, [])
                 if (evr, arch) != target]
        if stale:
            runner([*dnf, 'remove', '--no-autoremove', *stale])
        after = rpm.inventory(runner)
        check_changes(authenticated, after, allowed)
        validate_kernel(after, development)
    prune_modules(modules_root, RELEASE, old_releases, runner)
    print('Authenticated generic kernel installed; optional virtual cameras and host ZFS removed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, choices=PROFILES)
    args = parser.parse_args()
    try:
        security = Path(os.environ['CONFIG_DIRECTORY']) / 'security'
        remediate(load_policy(security / 'kernel-generic.json'), security / 'fedora-44.pub', args.profile)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f'Generic kernel security remediation failed: {error}')
