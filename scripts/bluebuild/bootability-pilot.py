#!/usr/bin/env python3
"""Diagnostic bootability contract. Never a production qualification receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

DIGEST = r'sha256:[0-9a-f]{64}'
IMAGE = r'ghcr.io/closure-labs/finite@' + DIGEST

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def preflight(env=os.environ):
    ref = env.get('GITHUB_REF', '')
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == 'closure-labs/finite'
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and ref.startswith('refs/heads/') and ref != 'refs/heads/main'
            and env.get('GITHUB_WORKFLOW_REF') in {
                'closure-labs/finite/.github/workflows/' + workflow + '@' + ref
                for workflow in ('bootability-pilot.yml', 'benchmark-image-tools.yml')}
            and env.get('GITHUB_RUN_ATTEMPT') == '1', 'Pilot requires a first-attempt manual branch run')
    require(bool(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', ''))), 'Missing exact checkout head')

def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate receipt key')
            result[key] = value
        return result
    require(path.stat().st_size <= 1024 * 1024, 'Oversized evidence')
    return json.loads(path.read_text(), object_pairs_hook=unique)

def manifest_digests(manifest, image):
    expected = image.split('@')[1]
    digests = {expected}
    for entry in manifest.get('manifests', []):
        if entry.get('platform') == {'architecture': 'amd64', 'os': 'linux'}:
            require(bool(re.fullmatch(DIGEST, entry.get('digest', ''))), 'Malformed platform digest')
            digests.add(entry['digest'])
    return digests

def validate(value):
    require(set(value) == {'schema', 'kind', 'authorizesPublication', 'validationOnly', 'head', 'runId',
        'runAttempt', 'source', 'candidate', 'expected', 'first', 'updated', 'staged', 'booted',
        'secureBoot', 'mokCertificateSha256', 'firmwareSha256', 'status'}, 'Incomplete/unknown receipt fields')
    require(value['schema'] == 1 and value['kind'] == 'finite-bootability-pilot' and value['status'] == 'pass'
            and value['authorizesPublication'] is False and value['validationOnly'] is True, 'Wrong receipt boundary')
    require(bool(re.fullmatch('[0-9a-f]{40}', value['head'])) and str(value['runId']).isdigit()
            and value['runAttempt'] == 1, 'Missing native run identity')
    require(all(re.fullmatch(IMAGE, value[k]) for k in ('source', 'candidate'))
            and value['source'] != value['candidate'], 'Must perform an actual predecessor update')
    expected = value['expected']
    require(set(expected) == {'profile', 'kernel', 'digests', 'identity', 'revision'}, 'Missing immutable image expectation')
    require(expected['profile'] in ('finite', 'finite-dev') and bool(expected['kernel'])
            and re.fullmatch('v1:[0-9a-f]{64}', expected['identity'])
            and re.fullmatch('[0-9a-f]{40}', expected['revision']), 'Malformed image expectation')
    require(value['candidate'].split('@')[1] in expected['digests']
            and all(re.fullmatch(DIGEST, d) for d in expected['digests']), 'Missing signed digest binding')
    first, updated = value['first'], value['updated']
    guest_fields = {'profile', 'kernel', 'bootId', 'ostree', 'ostreeArgument', 'rootUuid', 'localFs', 'multiUser',
                    'emergency', 'encryptedRoot', 'encryptedVar', 'rootBinding', 'initramfsFailure'}
    for guest in (first, updated):
        require(set(guest) == guest_fields, 'Incomplete guest boot observation')
        require(all(guest[k] is True for k in ('localFs', 'multiUser', 'encryptedRoot', 'encryptedVar', 'rootBinding'))
                and all(guest[k] is False for k in ('emergency', 'initramfsFailure')), 'Guest is not ready or root is unsafe')
        require(bool(re.fullmatch('[0-9a-f]{64}', guest['ostree']))
                and bool(re.fullmatch('[0-9a-f-]{36}', guest['bootId']))
                and guest['ostreeArgument'].startswith('/ostree/boot.') and bool(guest['rootUuid']), 'Missing boot/root identity')
    require(first['bootId'] != updated['bootId'] and first['ostree'] != updated['ostree']
            and first['rootUuid'] == updated['rootUuid'], 'No new deployment boot, fallback or wrong root')
    require(updated['profile'] == expected['profile'] and updated['kernel'] == expected['kernel'], 'Wrong booted profile/kernel')
    for deployment in (value['staged'], value['booted']):
        require(set(deployment) == {'image', 'digest', 'ostree'}, 'Incomplete deployment')
        require(deployment['image'] == value['candidate'] and deployment['digest'] in expected['digests']
                and deployment['ostree'] == updated['ostree'], 'Staged-only candidate, fallback or wrong digest')
    require(value['secureBoot'] is True and re.fullmatch('[0-9a-f]{64}', value['mokCertificateSha256'])
            and set(value['firmwareSha256']) == {'code', 'template', 'prepared'}
            and all(re.fullmatch('[0-9a-f]{64}', h) for h in value['firmwareSha256'].values()), 'Firmware trust not bound')
    return value

def receipt(args):
    preflight()
    state = args.state
    def deployment(status):
        return {'image': status['image']['image']['image'], 'digest': status['image']['imageDigest'], 'ostree': status['ostree']['checksum']}
    metadata = load(Path('.bluebuild/pilot-candidate.json'))
    raw = (state / 'target-manifest.json').read_bytes()
    require('sha256:' + hashlib.sha256(raw).hexdigest() == args.target.split('@')[1], 'Manifest bytes do not match signed index')
    expected = {**metadata, 'digests': sorted(manifest_digests(json.loads(raw), args.target))}
    firmware = Path(os.environ.get('FINITE_VM_FIRMWARE_DIR', '/usr/share/OVMF'))
    value = {'schema': 1, 'kind': 'finite-bootability-pilot', 'authorizesPublication': False, 'validationOnly': True,
        'head': os.environ['GITHUB_SHA'], 'runId': os.environ['GITHUB_RUN_ID'], 'runAttempt': 1,
        'source': args.source, 'candidate': args.target, 'expected': expected,
        'first': load(state / 'first-boot-pilot.json'), 'updated': load(state / 'updated-pilot.json'),
        'staged': deployment(load(state / 'staged.json')['status']['staged']),
        'booted': deployment(load(state / 'updated.json')['status']['booted']),
        'secureBoot': True, 'mokCertificateSha256': hashlib.sha256((state / 'sb_pubkey.der').read_bytes()).hexdigest(),
        'firmwareSha256': {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in
            [('code', firmware / 'OVMF_CODE_4M.secboot.fd'), ('template', firmware / 'OVMF_VARS_4M.ms.fd'), ('prepared', state / 'OVMF_VARS.fd')]},
        'status': 'pass'}
    validate(value)
    (state / 'pilot-receipt.json').write_text(json.dumps(value, indent=2) + '\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('preflight')
    collect = sub.add_parser('receipt')
    collect.add_argument('--state', type=Path, required=True)
    collect.add_argument('--source', required=True)
    collect.add_argument('--target', required=True)
    check = sub.add_parser('validate')
    check.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.command == 'preflight': preflight()
    elif args.command == 'receipt': receipt(args)
    else: validate(load(args.path))
