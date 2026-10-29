#!/usr/bin/env python3
"""Fail closed on recipe drift; assemble a local-only experimental build plan."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {'finite': 'bluefin', 'finite-dev': 'bluefin-dx'}
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(root=ROOT):
    manifest = json.loads((root / 'experiments/containerfile/parity.json').read_text())
    if manifest['schema'] != 1:
        raise ValueError('Unknown experimental contract')
    recipes = {}
    for name, expected in manifest['recipeContracts'].items():
        document = yaml.safe_load((root / name).read_text())
        shape = dict(document)
        shape.pop('image-version', None)
        shape.pop('cosign-version', None)
        if shape != expected:
            raise ValueError('Recipe drift requires explicit Containerfile parity review: ' + name)
        recipes[name] = document
    for source in manifest['requiredFeatures'].values():
        if not (root / source).is_file():
            raise ValueError('Missing required implementation: ' + source)
    cosign = json.loads((root / 'sources/cosign-runtime.json').read_text())
    cli = json.loads((root / 'sources/bluebuild-cli.json').read_text())
    for digest in (cosign['indexDigest'], cli['digest']):
        if not DIGEST.fullmatch(digest):
            raise ValueError('Tool image is not digest pinned')
    for profile, foundation in PROFILES.items():
        recipe = recipes['recipes/' + profile + '.yml']
        if (recipe['base-image'] != 'ghcr.io/ublue-os/' + foundation
                or not recipe['image-version'].startswith('stable@')
                or not DIGEST.fullmatch(recipe['image-version'].removeprefix('stable@'))
                or recipe['cosign-version'] != cosign['version'] + '@' + cosign['indexDigest']
                or recipe['blue-build-tag'] != cli['version']):
            raise ValueError('Base/tool identity mismatch: ' + profile)
    return recipes, cosign, cli


def prepare(profile, root=ROOT):
    recipes, cosign, cli = contract(root)
    recipe = recipes['recipes/' + profile + '.yml']
    base = recipes['recipes/shared/base.yml']['modules']
    final = recipes['recipes/shared/final.yml']['modules']
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if not re.fullmatch('[a-f0-9]{40}', revision) or os.environ.get('GITHUB_SHA', revision) != revision:
        raise ValueError('Checkout differs from requested source revision')
    # Read the same payload derivation and production input identity, but NEVER
    # label experimental bytes with that production identity.
    sys.path.insert(0, str(root / 'scripts/ci'))
    from image_identity import identity
    reference = identity(profile, root)
    implementation = {str(p.relative_to(root)): sha(p) for p in sorted(
        (root / 'experiments/containerfile').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    workflow = '.github/workflows/containerfile-experiment.yml'
    implementation[workflow] = sha(root / workflow)
    experiment = 'containerfile-v1:' + hashlib.sha256(json.dumps(
        {'reference': reference, 'files': implementation}, sort_keys=True).encode()).hexdigest()
    plan = {'schema': 1, 'profile': profile, 'foundation': PROFILES[profile],
            'sourceRevision': revision, 'baseImage': recipe['base-image'],
            'baseDigest': recipe['image-version'].removeprefix('stable@'),
            'cosignImage': cosign['repository'] + '@' + cosign['indexDigest'],
            'bluebuildImage': cli['image'] + '@' + cli['digest'],
            'referenceIdentity': reference, 'experimentIdentity': experiment,
            'productionEligible': False, 'bootValidated': False,
            'repos': base[1]['repos']['files'], 'packages': base[1]['install']['packages'],
            'copies': base[3]['files'], 'systemUnits': base[5]['system']['enabled'],
            'userUnits': base[5]['user']['enabled'], 'osRelease': final[0]['properties'],
            'implementation': implementation}
    output = root / '.bluebuild/containerfile'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return plan


def build(plan, root=ROOT):
    if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or not os.environ.get('GITHUB_REF', '').startswith('refs/heads/')
            or os.environ['GITHUB_REF'] == 'refs/heads/main'):
        raise ValueError('Full experiment requires an explicit dispatch on a branch, never main')
    profile = plan['profile']
    tag = 'localhost/finite-containerfile:' + profile
    args = {'BASE_IMAGE': plan['baseImage'] + '@' + plan['baseDigest'],
            'COSIGN_IMAGE': plan['cosignImage'], 'BLUEBUILD_IMAGE': plan['bluebuildImage'],
            'PROFILE': profile, 'FOUNDATION': plan['foundation'], 'SOURCE_REVISION': plan['sourceRevision'],
            'BASE_DIGEST': plan['baseDigest'], 'REFERENCE_IDENTITY': plan['referenceIdentity'],
            'EXPERIMENT_IDENTITY': plan['experimentIdentity']}
    command = ['docker', 'buildx', 'build', '--load', '--platform', 'linux/amd64',
               '--file', 'experiments/containerfile/Containerfile', '--tag', tag,
               '--metadata-file', '.bluebuild/containerfile/build-metadata.json']
    for name, value in args.items():
        command += ['--build-arg', name + '=' + value]
    env = dict(os.environ)
    env.pop('SOURCE_DATE_EPOCH', None)
    subprocess.run(command + ['.'], cwd=root, env=env, check=True)
    result = subprocess.check_output(['docker', 'image', 'inspect', tag], text=True)
    info = json.loads(result)[0]
    labels = info['Config']['Labels']
    expected = {'io.finite.build-inputs': plan['experimentIdentity'],
                'io.finite.reference-build-inputs': plan['referenceIdentity'],
                'org.opencontainers.image.revision': plan['sourceRevision'],
                'org.opencontainers.image.base.digest': plan['baseDigest'],
                'io.finite.profile': profile, 'io.finite.foundation': plan['foundation'],
                'org.opencontainers.image.base.name': plan['baseImage'],
                'io.finite.production-eligible': 'false'}
    if any(labels.get(k) != v for k, v in expected.items()):
        raise ValueError('Experimental image labels do not match prepared inputs')
    (root / '.bluebuild/containerfile/image-inspect.json').write_text(result)
    subprocess.run(['docker', 'run', '--rm', '--network=none', '--entrypoint', 'bash',
                    '-v', str(root / 'scripts/bluebuild/verify-image.sh') + ':/verify.sh:ro',
                    tag, '/verify.sh', profile], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    contract()
    if args.build and not args.profile:
        parser.error('--build requires --profile')
    if args.profile:
        plan = prepare(args.profile)
        if args.build:
            build(plan)


if __name__ == '__main__':
    main()
