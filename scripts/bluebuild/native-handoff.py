#!/usr/bin/env python3
"""Bind protected boot sealing to the exact raw build and final registry image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import native_oci as oci

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'ghcr.io/closure-labs/finite'


def read(path):
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= 4 * 1024**2:
        raise ValueError('Missing or oversized native build evidence')
    return json.loads(path.read_text())


def validate_context(profile, digest, revision, identity):
    if (profile not in ('finite-native', 'finite-native-dev') or not re.fullmatch('sha256:[0-9a-f]{64}', digest)
            or not re.fullmatch('[0-9a-f]{40}', revision) or not re.fullmatch('v1:[0-9a-f]{64}', identity)):
        raise ValueError('Native handoff requires exact profile, digest, source and build identity')


def validate_image(info, profile, digest, revision, identity, base):
    expected = {'io.finite.profile': profile, 'io.finite.build-inputs': identity,
                'io.finite.boot-architecture': 'native-composefs',
                'org.opencontainers.image.revision': revision,
                'org.opencontainers.image.base.digest': base,
                'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}
    if (info.get('Digest') != digest or info.get('Architecture') != 'amd64' or info.get('Os') != 'linux'
            or any(info.get('Labels', {}).get(name) != value for name, value in expected.items())):
        raise ValueError('Native image differs from its trusted build identity')


def prepare(args):
    validate_context(args.profile, args.digest, args.revision, args.identity)
    record = read(args.directory / (args.profile + '-publication.json'))
    if (record.get('publish') is not True or record.get('profile') != args.profile
            or record.get('revision') != args.revision or record.get('sourceRevision') != args.revision
            or record.get('buildIdentity') != args.identity or record.get('candidate') != 'candidate-' + args.profile
            or record.get('qualificationMode') != 'enforce' or 'resumeOrigin' in record or 'bootSeal' in record):
        raise ValueError('Boot signing requires a fresh same-revision raw build')
    reference = (args.directory / (args.profile + '-image-ref.txt')).read_text().strip()
    if reference != REPOSITORY + '@' + args.digest:
        raise ValueError('Raw build artifact refers to a different image')
    validate_image(read(args.info), args.profile, args.digest, args.revision, args.identity, record['digest'])
    # The raw archive was exported from the checked immutable reference. Bind
    # its bytes before the scoped signing child receives any private key.
    value = {'schema': 1, 'profile': args.profile, 'sourceDigest': args.digest,
             'sourceRevision': args.revision, 'buildIdentity': args.identity,
             'sourceArchiveSha256': oci.sha256(args.archive)}
    path = args.directory / (args.profile + '-native-source.json')
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def finalize(args):
    validate_context(args.profile, args.digest, args.revision, args.identity)
    source = read(args.directory / (args.profile + '-native-source.json'))
    receipt = read(args.receipt)
    signer = read(ROOT / 'sources/boot-signing.json')
    importer = read(ROOT / 'sources/native-composefs-verifier.json')
    accepted = {importer['bootcSha256'], *importer.get('additionalBootcSha256', [])}
    integrity = receipt.get('integrity', {})
    if (source.get('profile') != args.profile or source.get('sourceRevision') != args.revision
            or source.get('buildIdentity') != args.identity or receipt.get('schema') != 1
            or receipt.get('validationOnly') is not False or receipt.get('profile') != args.profile
            or receipt.get('sourceRevision') != args.revision
            or receipt.get('sourceArchiveSha256') != source['sourceArchiveSha256']
            or receipt.get('certificateDerSha256') != signer['certificateDerSha256']
            or receipt.get('importerSha256') not in accepted
            or integrity.get('importerBinarySha256') != receipt['importerSha256']
            or integrity.get('validationOnly') is True
            or integrity.get('strictVerity') is not True or not integrity.get('ukis')
            or integrity.get('certificateDerSha256') != signer['certificateDerSha256']
            or integrity.get('bootableRootDigest') != receipt.get('bootableRootDigest')
            or integrity.get('archiveSha256') != receipt.get('archiveSha256')
            or receipt.get('archiveSha256') != oci.sha256(args.archive)):
        raise ValueError('Native sealing evidence does not authenticate the completed production image')
    image = oci.Image(args.archive)
    try:
        if image.index['manifests'][0]['digest'] != args.digest:
            raise ValueError('Registry upload changed the sealed OCI manifest digest')
    finally:
        image.close()
    record_path = args.directory / (args.profile + '-publication.json')
    record = read(record_path)
    validate_image(read(args.info), args.profile, args.digest, args.revision, args.identity, record['digest'])
    record['bootSeal'] = {**source, 'imageDigest': args.digest,
                          'certificateDerSha256': signer['certificateDerSha256'],
                          'archiveSha256': receipt['archiveSha256'],
                          'bootableRootDigest': receipt['bootableRootDigest'],
                          'receiptSha256': hashlib.sha256(args.receipt.read_bytes()).hexdigest(),
                          'validationOnly': False}
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    (args.directory / (args.profile + '-image-ref.txt')).write_text(REPOSITORY + '@' + args.digest + '\n')
    (args.directory / (args.profile + '-native-seal.json')).write_bytes(args.receipt.read_bytes())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            print('digest=' + args.digest, file=stream)
            print('evidence=image-' + args.profile + '-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'], file=stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'finalize'])
    for name in ('directory', 'info', 'archive'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('profile', 'digest', 'revision', 'identity'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.operation == 'finalize' and not args.receipt:
        parser.error('Finalization requires a sealing receipt')
    try:
        globals()[args.operation](args)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
