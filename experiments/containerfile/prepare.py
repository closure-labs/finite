#!/usr/bin/env python3
"""Fail closed on recipe drift; assemble a local-only experimental build plan."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

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


def authorized_revision():
    """Temporary exact internal experiment opt-ins, never production authority."""
    if os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        raise ValueError('Full experiment requires the authorized repository')
    event = os.environ.get('GITHUB_EVENT_NAME')
    if event == 'workflow_dispatch':
        ref = os.environ.get('GITHUB_REF', '')
        if not ref.startswith('refs/heads/') or ref == 'refs/heads/main':
            raise ValueError('Full experiment requires an explicit dispatch on a branch, never main')
        revision = os.environ.get('GITHUB_SHA', '')
    elif event == 'pull_request':
        payload = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        pull = payload.get('pull_request', {})
        head = pull.get('head', {})
        repository = head.get('repo', {})
        number = payload.get('number')
        branches = {321: 'codex/explore-containerfile', 341: 'codex/matched-builder-benchmark'}
        if (type(number) is not int or number not in branches or pull.get('number') != number
                or payload.get('action') not in ('opened', 'synchronize', 'reopened')
                or payload.get('repository', {}).get('full_name') != 'closure-labs/finite'
                or repository.get('full_name') != 'closure-labs/finite'
                or repository.get('fork') is not False
                or head.get('ref') != branches[number]
                or pull.get('base', {}).get('ref') != 'main'
                or pull.get('base', {}).get('repo', {}).get('full_name') != 'closure-labs/finite'
                or os.environ.get('GITHUB_REF') != f'refs/pull/{number}/merge'):
            raise ValueError('PR is outside the temporary experiment opt-in')
        revision = head.get('sha', '')
    else:
        raise ValueError('Full experiment requires an explicit dispatch or authorized PR 321')
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Experiment requires an exact source revision')
    return revision


def foundation_source(root=ROOT):
    lock = json.loads((root / 'flake.lock').read_text())
    node = lock['nodes'][lock['nodes'][lock['root']]['inputs']['foundation']]['locked']
    source = json.loads((root / 'sources/foundation.json').read_text())
    if (node.get('type'), node.get('owner'), node.get('repo')) != ('github', 'closure-labs', 'foundation'):
        raise ValueError('Unexpected Foundation lock source')
    if (not re.fullmatch('[a-f0-9]{40}', node.get('rev', ''))
            or any(source.get(key) != node.get(key) for key in ('rev', 'narHash'))):
        raise ValueError('Foundation release metadata differs from the lock')
    return {key: source[key] for key in ('schema', 'compatibility', 'version', 'rev', 'narHash')} | {
        'lastModified': node['lastModified']}


def prepare(profile, root=ROOT):
    recipes, cosign, cli = contract(root)
    recipe = recipes['recipes/' + profile + '.yml']
    base = recipes['recipes/shared/base.yml']['modules']
    final = recipes['recipes/shared/final.yml']['modules']
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    expected = authorized_revision() if os.environ.get('GITHUB_ACTIONS') == 'true' else revision
    if not re.fullmatch('[a-f0-9]{40}', revision) or expected != revision:
        raise ValueError('Checkout differs from requested source revision')
    # Read the same payload derivation and production input identity, but NEVER
    # label experimental bytes with that production identity.
    sys.path.insert(0, str(root / 'scripts/ci'))
    from image_identity import identity
    reference = identity(profile, root)
    implementation = {str(p.relative_to(root)): sha(p) for p in sorted(
        (root / 'experiments/containerfile').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    workflow = '.github/workflows/containerfile-experiment.yml'
    if (os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_EVENT_NAME') == 'pull_request'
            and json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()).get('number') == 341):
        workflow = '.github/workflows/builder-benchmark.yml'
    implementation[workflow] = sha(root / workflow)
    experiment = 'containerfile-v1:' + hashlib.sha256(json.dumps(
        {'reference': reference, 'files': implementation}, sort_keys=True).encode()).hexdigest()
    plan = {'schema': 1, 'profile': profile, 'foundation': PROFILES[profile],
            'sourceRevision': revision, 'created': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'version': 'containerfile-' + revision[:12],
            'description': recipe['description'] + ' (unpublished Containerfile experiment)',
            'url': recipe['labels']['org.opencontainers.image.url'],
            'baseImage': recipe['base-image'],
            'baseDigest': recipe['image-version'].removeprefix('stable@'),
            'cosignImage': cosign['repository'] + '@' + cosign['indexDigest'],
            'bluebuildImage': cli['image'] + '@' + cli['digest'],
            'referenceIdentity': reference, 'experimentIdentity': experiment,
            'productionEligible': False, 'bootValidated': False,
            'foundationSource': foundation_source(root),
            'repos': base[1]['repos']['files'], 'packages': base[1]['install']['packages'],
            'copies': base[3]['files'], 'systemUnits': base[5]['system']['enabled'],
            'userUnits': base[5]['user']['enabled'], 'osRelease': final[0]['properties'],
            'implementation': implementation}
    output = root / '.bluebuild/containerfile'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return plan


def rpm_inventory(output):
    fields = ('name', 'epoch', 'version', 'release', 'arch')
    rows = sorted(set(tuple(line.split('\t')) for line in output.splitlines()))
    if not rows or any(len(row) != 5 or not all(row) or not row[1].isdigit() for row in rows):
        raise ValueError('Malformed RPM inventory')
    packages = [dict(zip(fields, row)) for row in rows]
    canonical = json.dumps(packages, sort_keys=True, separators=(',', ':')).encode()
    return packages, hashlib.sha256(canonical).hexdigest()


# Read installed metadata and RPM ownership only: do not start services, invoke
# Foundation preparation, execute fzf, or install optional Homebrew bundles.
PROVENANCE_QUERY = r"""
import hashlib, json, os, subprocess
from pathlib import Path
source = Path('/usr/share/finite/foundation-source.json').read_bytes()
fzf = Path('/usr/bin/fzf')
if not fzf.is_file() or not os.access(fzf, os.X_OK):
    raise ValueError('Stock fzf is missing or not executable')
owner = subprocess.check_output(['rpm', '-qf', '--qf',
    '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n', str(fzf)], text=True)
print(json.dumps({'foundationSource': json.loads(source),
    'foundationSourceSha256': hashlib.sha256(source).hexdigest(),
    'fzf': {'path': str(fzf), 'resolvedPath': str(fzf.resolve()),
            'sha256': hashlib.sha256(fzf.read_bytes()).hexdigest(), 'owner': owner}}))
"""


def validate_provenance(observed, expected, packages):
    if observed.get('foundationSource') != expected:
        raise ValueError('Installed Foundation metadata differs from the exact lock source')
    fzf = observed.get('fzf', {})
    if (fzf.get('path') != '/usr/bin/fzf'
            or not fzf.get('resolvedPath', '').startswith('/usr/')
            or not re.fullmatch('[a-f0-9]{64}', fzf.get('sha256', ''))
            or not re.fullmatch('[a-f0-9]{64}', observed.get('foundationSourceSha256', ''))):
        raise ValueError('Invalid installed provenance paths or hashes')
    owners, _ = rpm_inventory(fzf.get('owner', ''))
    if len(owners) != 1 or owners[0]['name'] != 'fzf' or owners[0] not in packages:
        raise ValueError('Stock fzf is not owned by the inventoried fzf RPM')
    return dict(observed, fzf=dict(fzf, owner=owners[0]))


def build(plan, root=ROOT):
    if authorized_revision() != plan['sourceRevision']:
        raise ValueError('Prepared plan differs from authorized source revision')
    profile = plan['profile']
    tag = 'localhost/finite-containerfile:' + profile
    args = {'BASE_IMAGE': plan['baseImage'] + '@' + plan['baseDigest'],
            'COSIGN_IMAGE': plan['cosignImage'], 'BLUEBUILD_IMAGE': plan['bluebuildImage'],
            'PROFILE': profile, 'FOUNDATION': plan['foundation'], 'SOURCE_REVISION': plan['sourceRevision'],
            'BASE_DIGEST': plan['baseDigest'], 'REFERENCE_IDENTITY': plan['referenceIdentity'],
            'EXPERIMENT_IDENTITY': plan['experimentIdentity'], 'CREATED': plan['created'],
            'VERSION': plan['version'], 'DESCRIPTION': plan['description'], 'URL': plan['url']}
    command = ['docker', 'buildx', 'build', '--load', '--platform', 'linux/amd64',
               '--file', 'experiments/containerfile/Containerfile', '--tag', tag,
               '--metadata-file', '.bluebuild/containerfile/build-metadata.json']
    for name, value in args.items():
        command += ['--build-arg', name + '=' + value]
    env = dict(os.environ)
    env.pop('SOURCE_DATE_EPOCH', None)
    # Build only an allowlisted context: no .git, checkout credentials, event
    # payload, workflow environment, or unrelated runner files are transmitted.
    with tempfile.TemporaryDirectory(prefix='finite-containerfile-') as temporary:
        context = Path(temporary)
        for directory in ('files', 'experiments/containerfile'):
            shutil.copytree(root / directory, context / directory,
                            ignore=shutil.ignore_patterns('__pycache__'), symlinks=True)
        for name in ('scripts/bluebuild/verify-image.sh', 'cosign.pub', '.bluebuild/containerfile/plan.json'):
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
        subprocess.run(command + [str(context)], cwd=root, env=env, check=True)
    result = subprocess.check_output(['docker', 'image', 'inspect', tag], text=True)
    info = json.loads(result)[0]
    image_id = info.get('Id', '')
    if not DIGEST.fullmatch(image_id):
        raise ValueError('Docker inspection did not return an immutable image ID')
    labels = info['Config']['Labels']
    expected = {'io.finite.build-inputs': plan['experimentIdentity'],
                'io.finite.reference-build-inputs': plan['referenceIdentity'],
                'org.opencontainers.image.revision': plan['sourceRevision'],
                'org.opencontainers.image.base.digest': plan['baseDigest'],
                'io.finite.profile': profile, 'io.finite.foundation': plan['foundation'],
                'org.opencontainers.image.base.name': plan['baseImage'],
                'org.opencontainers.image.created': plan['created'],
                'org.opencontainers.image.version': plan['version'],
                'org.opencontainers.image.description': plan['description'],
                'org.opencontainers.image.url': plan['url'],
                'io.finite.production-eligible': 'false'}
    if any(labels.get(k) != v for k, v in expected.items()):
        raise ValueError('Experimental image labels do not match prepared inputs')
    (root / '.bluebuild/containerfile/image-inspect.json').write_text(result)
    subprocess.run(['docker', 'run', '--rm', '--network=none', '--entrypoint', 'bash',
                    '-v', str(root / 'scripts/bluebuild/verify-image.sh') + ':/verify.sh:ro',
                    image_id, '/verify.sh', profile], check=True)
    inventory = subprocess.check_output(
        ['docker', 'run', '--rm', '--network=none', '--entrypoint', 'rpm', image_id,
         '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n'], text=True)
    packages, digest = rpm_inventory(inventory)
    receipt = {'schema': 1, 'sourceRevision': plan['sourceRevision'], 'imageId': image_id,
               'experimentIdentity': plan['experimentIdentity'], 'profile': profile,
               'packageCount': len(packages), 'packages': packages, 'packagesSha256': digest,
               'canonicalization': 'UTF-8 JSON packages array, sorted object keys, separators comma/colon'}
    (root / '.bluebuild/containerfile/rpm-inventory.json').write_text(json.dumps(receipt, indent=2) + '\n')
    observed = json.loads(subprocess.check_output(
        ['docker', 'run', '--rm', '--network=none', '--entrypoint', 'python3', image_id,
         '-c', PROVENANCE_QUERY], text=True))
    provenance = validate_provenance(observed, plan['foundationSource'], packages)
    provenance.update(schema=1, sourceRevision=plan['sourceRevision'], imageId=image_id,
                      experimentIdentity=plan['experimentIdentity'], profile=profile,
                      bootValidated=False, userSessionValidated=False)
    (root / '.bluebuild/containerfile/installed-provenance.json').write_text(
        json.dumps(provenance, indent=2) + '\n')


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
