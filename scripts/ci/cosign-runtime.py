#!/usr/bin/env python3
"""Authenticate the immutable Cosign executable source without fetching image layers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ('bluefin-generic', 'bluefin-next', 'bluefin-dx-generic', 'bluefin-dx-next')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
LIMIT = 2 * 1024 * 1024


def policy(root=ROOT):
    value = json.loads((Path(root) / 'sources/cosign-runtime.json').read_text())
    fields = {'schema', 'version', 'repository', 'indexDigest', 'platformDigest', 'platform',
              'certificateIdentity', 'certificateOidcIssuer', 'annotations'}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['version'], str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value['version'])
            or value['repository'] != 'ghcr.io/sigstore/cosign/cosign'
            or any(not isinstance(value[key], str) or not DIGEST.fullmatch(value[key])
                   for key in ('indexDigest', 'platformDigest'))
            or value['platform'] != {'os': 'linux', 'architecture': 'amd64'}
            or value['certificateIdentity'] != 'keyless@projectsigstore.iam.gserviceaccount.com'
            or value['certificateOidcIssuer'] != 'https://accounts.google.com'
            or not isinstance(value['annotations'], dict)
            or set(value['annotations']) != {'GIT_VERSION', 'GIT_HASH'}
            or value['annotations']['GIT_VERSION'] != 'v' + value['version']
            or not isinstance(value['annotations']['GIT_HASH'], str)
            or not re.fullmatch(r'[a-f0-9]{40}', value['annotations']['GIT_HASH'])):
        raise ValueError('Invalid Cosign runtime publisher policy')
    return value


def recipe_pins(value, root=ROOT):
    expected = value['version'] + '@' + value['indexDigest']
    for profile in PROFILES:
        text = (Path(root) / 'recipes' / (profile + '.yml')).read_text()
        recipe = yaml.safe_load(text)
        if (not isinstance(recipe, dict) or recipe.get('cosign-version') != expected
                or len(re.findall(r'^cosign-version:', text, re.M)) != 1):
            raise ValueError(f'{profile}: Cosign runtime must use the exact reviewed immutable pin')
    return expected


def run(args, timeout):
    # Spool tool output so remote metadata cannot exhaust the caller's memory.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(args, stdout=output, stderr=errors, timeout=timeout)
        if result.returncode:
            errors.seek(0, 2)
            errors.seek(max(0, errors.tell() - 8192))
            message = errors.read().decode(errors='replace').strip()
            raise RuntimeError(f'{args[0]} verification failed: {message}')
        output.seek(0, 2)
        if output.tell() > LIMIT:
            raise ValueError(f'{args[0]} metadata exceeded the reviewed size limit')
        output.seek(0)
        return output.read()


def authenticate(value, runner=run):
    reference = value['repository'] + '@' + value['indexDigest']
    raw = runner(['skopeo', '--command-timeout', '30s', 'inspect', '--raw',
                  'docker://' + reference], timeout=35)
    if len(raw) > LIMIT or 'sha256:' + hashlib.sha256(raw).hexdigest() != value['indexDigest']:
        raise ValueError('Cosign runtime index digest mismatch')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or type(manifest.get('schemaVersion')) is not int
            or manifest['schemaVersion'] != 2
            or manifest.get('mediaType') != 'application/vnd.oci.image.index.v1+json'
            or not isinstance(manifest.get('manifests'), list)
            or any(not isinstance(entry, dict) or not isinstance(entry.get('platform'), dict)
                   for entry in manifest['manifests'])):
        raise ValueError('Cosign runtime source is not the reviewed OCI index')
    matching = [entry for entry in manifest['manifests']
                if entry.get('platform', {}).get('os') == 'linux'
                and entry.get('platform', {}).get('architecture') == 'amd64']
    if (len(matching) != 1 or matching[0].get('platform') != value['platform']
            or matching[0].get('digest') != value['platformDigest']
            or matching[0].get('mediaType') != 'application/vnd.oci.image.manifest.v1+json'):
        raise ValueError('Cosign runtime linux/amd64 descriptor does not match the reviewed child')
    # Standard Sigstore bundles preserve certificate, claims and transparency-log
    # validation. The publisher's OCI release does not use Bluefin's legacy format.
    command = ['cosign', 'verify', '--new-bundle-format=true',
               '--certificate-identity', value['certificateIdentity'],
               '--certificate-oidc-issuer', value['certificateOidcIssuer']]
    for name, annotation in sorted(value['annotations'].items()):
        command.extend(['-a', name + '=' + annotation])
    command.append(reference)
    verified = runner(command, timeout=150)
    if len(verified) > LIMIT:
        raise ValueError('Cosign runtime signature metadata exceeded the reviewed size limit')
    signatures = json.loads(verified)
    if not isinstance(signatures, list) or not signatures:
        raise ValueError('Cosign runtime has no verified publisher signatures')
    for signature in signatures:
        if (not isinstance(signature, dict)
                or signature.get('critical', {}).get('image', {}).get('docker-manifest-digest') != value['indexDigest']
                or any(signature.get('optional', {}).get(name) != annotation
                       for name, annotation in value['annotations'].items())):
            raise ValueError('Cosign runtime verified claims do not match the reviewed source')
    return {'schema': 1, 'status': 'publisher-authenticated', 'image': reference,
            'platform': value['platform'], 'platformDigest': value['platformDigest'],
            'certificateIdentity': value['certificateIdentity'],
            'certificateOidcIssuer': value['certificateOidcIssuer'],
            'annotations': value['annotations'],
            'verificationSha256': hashlib.sha256(verified).hexdigest(),
            'note': 'OCI publisher metadata only; executable modules and image vulnerability clearance require separate evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate source policy and recipe pins without registry access')
    parser.add_argument('--output', type=Path, help='Retain the small publisher verification report')
    args = parser.parse_args()
    value = policy()
    recipe_pins(value)
    report = {'schema': 1, 'status': 'source-policy-valid'} if args.check else authenticate(value)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'Cosign runtime verification failed: {error}')
