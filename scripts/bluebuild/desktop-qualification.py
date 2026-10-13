#!/usr/bin/env python3
"""Bind bounded candidate VM observations to existing boot qualification."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

LIMIT = 4 * 1024 * 1024
SPEC = importlib.util.spec_from_file_location('vm_desktop', Path(__file__).with_name('check-vm-desktop.py'))
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)


def read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('Missing, linked or oversized VM evidence')
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Oversized VM evidence')
    return data


def validate_observations(value, profile):
    processes = '\n'.join(f"{r['context']} {r['pid']} {r['command']}" for r in value['processes'])
    listeners = '\n'.join(f"{r['protocol']} {r['state']} 0 0 {r['local']} {r['peer']} {r['owners']}" for r in value['listeners'])
    expected = guest.observations(value['selinux']['mode'], str(value['selinux']['kernelEnforce']),
                                  '\n'.join(value['selinux']['permissiveDomains']), processes, listeners, profile)
    if value != expected:
        raise ValueError('VM observations are incomplete or inconsistent')


def validate(value, acceptance):
    keys = ('candidate', 'profile', 'buildIdentity', 'sourceRevision')
    if value.get('schema') != 1 or any(value.get(k) != acceptance.get(k) for k in keys):
        raise ValueError('VM security receipt identifies another candidate')
    if not re.fullmatch(r'ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}', value['candidate']):
        raise ValueError('VM receipt candidate must be immutable')
    expected = ['fresh', 'upgrade'] if acceptance.get('previousDigest') else ['fresh']
    if list(value.get('phases', {})) != expected:
        raise ValueError('VM receipt lacks required fresh/upgrade observations')
    for phase in value['phases'].values():
        manifest = phase['manifest'].encode()
        if 'sha256:' + hashlib.sha256(manifest).hexdigest() != value['candidate'].split('@')[1]:
            raise ValueError('VM manifest differs from authenticated candidate')
        manifest = json.loads(manifest)
        digests = [value['candidate'].split('@')[1]] + [m['digest'] for m in manifest.get('manifests', [])]
        if phase['bootedDigest'] not in digests:
            raise ValueError('VM booted another image')
        validate_observations(phase['observations'], value['profile'])


def verify(directory, acceptance):
    reference = acceptance.get('vmSecurityEvidence', {})
    name = acceptance['profile'] + '-desktop-acceptance.json'
    if reference.get('path') != name or not re.fullmatch(r'[0-9a-f]{64}', reference.get('sha256', '')):
        raise ValueError('Missing hash-bound VM security receipt')
    path = Path(directory) / name
    data = read(path)
    if hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise ValueError('VM security receipt hash mismatch')
    validate(json.loads(data), acceptance)
    return path


def assemble(directory, acceptance):
    result = {key: acceptance[key] for key in ('candidate', 'profile', 'buildIdentity', 'sourceRevision')}
    result.update(schema=1, phases={})
    for phase, boot, manifest in [('fresh', 'first-boot', 'source'), *([('upgrade', 'updated', 'target')] if acceptance['previousDigest'] else [])]:
        base = directory / ('vm-' + phase)
        result['phases'][phase] = {
            'manifest': read(base / (manifest + '-manifest.json')).decode(),
            'bootedDigest': json.loads(read(base / (boot + '.json')))['status']['booted']['image']['imageDigest'],
            'observations': json.loads(read(base / (boot + '-desktop.json')))}
    validate(result, acceptance)
    data = (json.dumps(result, indent=2) + '\n').encode()
    if len(data) > LIMIT:
        raise ValueError('Combined VM receipt exceeds bound')
    name = acceptance['profile'] + '-desktop-acceptance.json'
    (directory / name).write_bytes(data)
    acceptance['vmSecurityEvidence'] = {'path': name, 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acceptance', type=Path)
    args = parser.parse_args()
    acceptance = json.loads(read(args.acceptance))
    assemble(args.acceptance.parent, acceptance)
    args.acceptance.write_text(json.dumps(acceptance, indent=2) + '\n')


if __name__ == '__main__':
    main()
