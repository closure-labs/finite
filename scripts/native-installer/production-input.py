#!/usr/bin/env python3
"""Bind a fresh pull to an independently verified same-run production seal."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = 'closure-labs/finite/.github/workflows/native-production-validation.yml@refs/heads/main'
REPO = 'ghcr.io/closure-labs/finite'


def bind(directory, profile, digest):
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_WORKFLOW_REF') != WORKFLOW
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Production candidate binding requires the reviewed hosted workflow')
    if profile not in {'finite-native', 'finite-native-dev'}:
        raise ValueError('Unknown native production profile')
    revision = os.environ['GITHUB_SHA']
    publication = runpy.run_path(str(ROOT / 'scripts/bluebuild/publication.py'))
    record = json.loads((directory / f'{profile}-publication.json').read_bytes())
    receipt = (directory / f'{profile}-native-seal.json').read_bytes()
    seal = json.loads(receipt)
    publication['validate_boot_seal'](record, receipt, digest, revision, ROOT)
    verified = json.loads((directory / 'registry-integrity.json').read_bytes())
    observed = json.loads((directory / 'registry-image.json').read_bytes())
    reference = REPO + '@' + digest
    if ((directory / f'{profile}-image-ref.txt').read_text().strip() != reference
            or record.get('publish') is not True or 'resumeOrigin' in record
            or record.get('revision') != revision or record.get('sourceRevision') != revision
            or record.get('profile') != profile or record.get('candidate') != 'candidate-' + profile
            or observed.get('Digest') != digest or observed.get('Os') != 'linux'
            or observed.get('Architecture') != 'amd64'):
        raise ValueError('Production candidate does not match its fresh same-run image receipt')
    labels = observed.get('Labels') or {}
    if (labels.get('io.finite.profile') != profile
            or labels.get('io.finite.boot-architecture') != 'native-composefs'
            or labels.get('org.opencontainers.image.revision') != revision
            or labels.get('io.finite.build-inputs') != record.get('buildIdentity')):
        raise ValueError('Production candidate differs from the protected source and profile')
    if (verified.get('strictVerity') is not True or verified.get('validationOnly') is not False
            or any(verified.get(key) != seal['integrity'].get(key) for key in (
                'bootableRootDigest', 'certificateDerSha256', 'ukis'))):
        raise ValueError('Independent production import differs from the protected signer receipt')
    return {'schema': 1, 'validationOnly': False, 'profile': profile, 'image': reference, 'sourceRevision': revision,
            'producerRun': os.environ['GITHUB_RUN_ID'], 'producerAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'artifact': f'image-{profile}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}',
            'archiveSha256': verified['archiveSha256'], 'bootableRootDigest': verified['bootableRootDigest'],
            'bootCertificateDerSha256': verified['certificateDerSha256'], 'ukis': verified['ukis']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('profile')
    parser.add_argument('digest')
    args = parser.parse_args()
    try:
        print(json.dumps(bind(args.directory, args.profile, args.digest), indent=2))
    except (KeyError, OSError, ValueError) as error:
        sys.exit(f'Production candidate binding failed: {error}')
