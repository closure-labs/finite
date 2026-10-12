#!/usr/bin/env python3
"""Upgrade an installed Tailscale RPM from its reviewed, authenticated vendor source."""
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


def run(args):
    # Spool transaction output, then bound diagnostics rather than buffering all
    # package-manager output in memory or exposing unbounded errors in CI.
    with tempfile.TemporaryFile(mode='w+') as output:
        result = subprocess.run(args, text=True, stdout=output, stderr=subprocess.STDOUT,
                                timeout=900, env={**os.environ, 'LC_ALL': 'C'})
        output.seek(0, 2)
        size = output.tell()
        if result.returncode:
            output.seek(max(0, size - 65536))
            print(output.read(), file=sys.stderr)
            result.check_returncode()
        if size > 2 * 1024 * 1024:
            raise ValueError('Command output exceeded the reviewed limit')
        output.seek(0)
        return output.read().strip()


def load_policy(path):
    policy = json.loads(Path(path).read_text())
    fields = {'schema', 'fedora', 'package', 'minimumEVR', 'arch', 'url', 'sha256',
              'keySHA256', 'keyFingerprint', 'keySource'}
    if (not isinstance(policy, dict) or set(policy) != fields
            or type(policy['schema']) is not int or policy['schema'] != 1
            or type(policy['fedora']) is not int or policy['fedora'] != 44
            or policy['package'] != 'tailscale' or policy['arch'] != 'x86_64'
            or not isinstance(policy['minimumEVR'], str)
            or not re.fullmatch(r'0:[0-9]+\.[0-9]+\.[0-9]+-[0-9]+', policy['minimumEVR'])
            or any(not isinstance(policy[k], str) or not re.fullmatch(r'[a-f0-9]{64}', policy[k])
                   for k in ('sha256', 'keySHA256'))
            or not isinstance(policy['keyFingerprint'], str)
            or not re.fullmatch(r'[A-F0-9]{40}', policy['keyFingerprint'])
            or policy['keySource'] != 'https://pkgs.tailscale.com/stable/fedora/repo.gpg'):
        raise ValueError('Invalid Tailscale security policy')
    version = policy['minimumEVR'].split(':')[1].split('-')[0]
    expected = f'https://pkgs.tailscale.com/stable/fedora/x86_64/tailscale_{version}_x86_64.rpm'
    if policy['url'] != expected:
        raise ValueError('Tailscale RPM must use the exact reviewed stable vendor URL')
    return policy


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, destination, runner):
    runner(['curl', '--fail', '--silent', '--show-error', '--location',
            '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15',
            '--max-time', '120', '--retry', '2', '--retry-max-time', '300',
            '--max-filesize', '134217728', '--output', str(destination), url])


def authenticate(package, key, database, fingerprint, runner):
    runner(['rpm', '--dbpath', str(database), '--initdb'])
    runner(['rpmkeys', '--dbpath', str(database), '--import', str(key)])
    output = runner(['rpmkeys', '--dbpath', str(database), '--checksig', '--verbose', str(package)])
    signatures = [line.strip() for line in output.splitlines() if 'signature' in line.lower()]
    if (not signatures or any(not line.endswith(': OK')
                                  or f'key fingerprint: {fingerprint.lower()}: OK' not in line
                                  for line in signatures)
            or re.search(r'\b(?:NOKEY|NOT OK|BAD|FAILED|UNTRUSTED)\b', output, re.IGNORECASE)):
        raise ValueError('Tailscale RPM signature was not authenticated with the reviewed key')


def remediate(policy, key, runner=None, downloader=None, comparator=None):
    runner = runner or run
    downloader = downloader or download
    comparator = comparator or rpm.compare
    if runner(['rpm', '--eval', '%{fedora}']) != str(policy['fedora']):
        raise ValueError('Tailscale remediation requires the reviewed Fedora release')
    before = rpm.inventory(runner)
    installed = before.get(policy['package'], [])
    if not installed:
        print('Tailscale is not installed; no vendor access required')
        return
    if any(arch != policy['arch'] for _, arch in installed):
        raise ValueError('Installed Tailscale architecture is not reviewed')
    if all(comparator(evr, policy['minimumEVR']) >= 0 for evr, _ in installed):
        print('Reviewed Tailscale floor already satisfied; no vendor access required')
        return
    if digest(key) != policy['keySHA256']:
        raise ValueError('Tailscale signing key digest mismatch')
    with tempfile.TemporaryDirectory(prefix='finite-tailscale-') as directory:
        package = Path(directory) / 'tailscale.rpm'
        database = Path(directory) / 'rpmdb'
        database.mkdir()
        downloader(policy['url'], package, runner)
        if digest(package) != policy['sha256']:
            raise ValueError('Tailscale RPM digest mismatch')
        authenticate(package, key, database, policy['keyFingerprint'], runner)
        metadata = runner(['rpm', '-qp', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}', str(package)])
        if metadata != '\t'.join((policy['package'], policy['minimumEVR'], policy['arch'])):
            raise ValueError('Tailscale RPM metadata does not match the reviewed package')
        # The isolated database established trust independently of existing keys.
        # DNF independently checks the local payload signature using this key.
        runner(['rpmkeys', '--import', str(key)])
        runner(['dnf5', '-y', '--refresh', '--disable-repo=*', '--enable-repo=fedora',
                '--enable-repo=updates', '--setopt=gpgcheck=1', '--setopt=*.gpgcheck=1',
                '--setopt=localpkg_gpgcheck=1', '--setopt=*.skip_if_unavailable=False',
                '--setopt=install_weak_deps=False', '--exclude=' + ','.join(rpm.PROTECTED),
                'upgrade', '--no-allow-downgrade', str(package)])
    after = rpm.inventory(runner)
    if {n: v for n, v in before.items() if rpm.protected(n)} != {n: v for n, v in after.items() if rpm.protected(n)}:
        raise ValueError('Tailscale transaction changed the protected boot stack')
    final = after.get(policy['package'], [])
    if not final or any(comparator(evr, policy['minimumEVR']) < 0 for evr, _ in final):
        raise ValueError('Reviewed Tailscale floor not satisfied')
    if {arch for _, arch in installed} != {arch for _, arch in final}:
        raise ValueError('Tailscale transaction changed installed architectures')
    print('Reviewed Tailscale RPM floor satisfied')


if __name__ == '__main__':
    try:
        scripts = Path(os.environ['CONFIG_DIRECTORY']) / 'scripts'
        remediate(load_policy(scripts / 'tailscale-security.json'), scripts / 'tailscale-signing.pub')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f'Tailscale security remediation failed: {error}')
