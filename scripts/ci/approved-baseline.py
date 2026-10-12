#!/usr/bin/env python3
"""Bind authenticated Bluefin publisher evidence to an exact Finite inventory."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
REVISION = re.compile(r'[0-9a-f]{40}')
IDENTITY = re.compile(r'v1:[0-9a-f]{64}')
PROFILES = {'bluefin-generic': 'bluefin', 'bluefin-next': 'bluefin',
            'bluefin-dx-generic': 'bluefin-dx', 'bluefin-dx-next': 'bluefin-dx'}


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Publisher evidence must be a bounded regular file')
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Publisher evidence exceeds the read bound')
    def unique(pairs):
        document = {}
        for key, value in pairs:
            if key in document:
                raise ValueError('Duplicate publisher evidence key')
            document[key] = value
        return document
    return json.loads(raw, object_pairs_hook=unique), hashlib.sha256(raw).hexdigest()


def image_identity(inspected):
    if isinstance(inspected, list):
        if len(inspected) != 1:
            raise ValueError('Expected one inspected image')
        inspected = inspected[0]
    if not isinstance(inspected, dict):
        raise ValueError('Invalid image metadata')
    if 'config' in inspected:
        labels, platform = inspected['config'].get('Labels'), (inspected.get('os'), inspected.get('architecture'))
    elif 'Config' in inspected:
        labels, platform = inspected['Config'].get('Labels'), (inspected.get('Os'), inspected.get('Architecture'))
    else:
        labels, platform = inspected.get('Labels'), (inspected.get('Os'), inspected.get('Architecture'))
    if not isinstance(labels, dict) or platform != ('linux', 'amd64'):
        raise ValueError('Approved baseline requires exact linux/amd64 image metadata')
    profile = labels.get('io.finite.profile')
    revision, identity = labels.get('org.opencontainers.image.revision', ''), labels.get('io.finite.build-inputs', '')
    if (profile not in PROFILES or not REVISION.fullmatch(revision) or not IDENTITY.fullmatch(identity)
            or labels.get('org.opencontainers.image.source') != 'https://github.com/closure-labs/finite'):
        raise ValueError('Missing exact Finite source/profile/build identity')
    base = 'ghcr.io/ublue-os/' + PROFILES[profile]
    digest = labels.get('org.opencontainers.image.base.digest', '')
    if not DIGEST.fullmatch(digest) or labels.get('org.opencontainers.image.base.name') != base + ':stable@' + digest:
        raise ValueError('Image does not declare the approved profile-specific Bluefin source')
    return {'profile': profile, 'sourceRevision': revision, 'buildIdentity': identity, 'baseImage': base + '@' + digest}


def context(inspected, image, receipt, root=ROOT):
    if not re.fullmatch(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}', image):
        raise ValueError('Approved baseline requires an immutable Finite manifest')
    identity = image_identity(inspected)
    policy, policy_hash = read(root / 'sources/bluefin-trust.json')
    key = root / 'sources/bluefin.pub'
    if (type(policy.get('schema')) is not int or policy['schema'] != 1
            or policy.get('key') != key.name or policy.get('signatureFormat') != 'legacy'
            or sorted(policy.get('repositories', [])) != ['ghcr.io/ublue-os/bluefin', 'ghcr.io/ublue-os/bluefin-dx']
            or hashlib.sha256(key.read_bytes()).hexdigest() != policy.get('keySha256')):
        raise ValueError('Unreviewed Bluefin publisher trust policy/key')
    if (not isinstance(receipt, dict) or type(receipt.get('schema')) is not int or receipt['schema'] != 1
            or receipt.get('repository') != 'closure-labs/finite'
            or not REVISION.fullmatch(receipt.get('sourceRevision', ''))
            or receipt.get('trustPolicySha256') != policy_hash
            or not isinstance(receipt.get('verified'), list)):
        raise ValueError('Missing authenticated publisher verification receipt')
    verified = receipt['verified']
    if (not verified or any(not isinstance(entry, dict) or set(entry) != {'image', 'keySha256', 'signatureFormat'}
            or not isinstance(entry['image'], str)
            or not re.fullmatch(r'ghcr\.io/ublue-os/(?:bluefin|bluefin-dx)@sha256:[0-9a-f]{64}', entry['image'])
            or entry['keySha256'] != policy['keySha256'] or entry['signatureFormat'] != 'legacy'
            for entry in verified)
            or len({entry['image'] for entry in verified}) != len(verified)
            or not any(entry['image'] == identity['baseImage'] for entry in verified)):
        raise ValueError('Publisher receipt does not authenticate the declared exact base')
    # The receipt is emitted by actual signature verification in a trusted build
    # job, or by the direct verification fallback below. A status string alone
    # never supplies that authority. Production consumes its own build artifact.
    return {'schema': 1, 'status': 'verified', **identity, 'trustPolicySha256': policy_hash, 'image': image}


def authenticate(inspected, root=ROOT):
    identity = image_identity(inspected)
    spec = importlib.util.spec_from_file_location('approved_bluefin_publisher', root / 'scripts/ci/bluefin-upstream.py')
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    base, digest = identity['baseImage'].split('@')
    verified = publisher.authenticate(base, digest, root)
    _, policy_hash = read(root / 'sources/bluefin-trust.json')
    return {'schema': 1, 'repository': 'closure-labs/finite', 'sourceRevision': identity['sourceRevision'],
            'trustPolicySha256': policy_hash, 'verified': [verified]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--image-config', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inspected, _ = read(args.image_config)
    receipt = read(args.receipt)[0] if args.receipt else authenticate(inspected)
    document = context(inspected, args.image, receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + '\n')


if __name__ == '__main__':
    main()
