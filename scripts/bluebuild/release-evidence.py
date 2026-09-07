#!/usr/bin/env python3
"""Assemble release evidence only from matching successful main-branch runs."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

REPOSITORY = 'closure-labs/finite'
PROFILES = {'finite': 'bluefin-generic', 'finite-next': 'bluefin-next',
            'finite-dev': 'bluefin-dx-generic', 'finite-dev-next': 'bluefin-dx-next'}


def github(path):
    return json.loads(subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], text=True, timeout=90))


def validate_run(run, workflow, revision):
    if (run['conclusion'] != 'success' or run['head_branch'] != 'main'
            or run['head_sha'] != revision or run['path'] != '.github/workflows/' + workflow
            or run['head_repository']['full_name'] != REPOSITORY):
        raise ValueError('Release evidence must come from successful matching main-branch runs')


def artifact(run_id, name, destination):
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', REPOSITORY,
                    '--name', name, '--dir', str(destination)], check=True, timeout=900)


def latest_artifact(artifacts, prefix):
    matches = [entry['name'] for entry in artifacts if not entry['expired']
               and re.fullmatch(re.escape(prefix) + r'[0-9]+', entry['name'])]
    if not matches:
        raise ValueError('Missing or expired release evidence: ' + prefix)
    return max(matches, key=lambda name: int(name.removeprefix(prefix)))


def artifact_names(run_id):
    pages = json.loads(subprocess.check_output(
        ['gh', 'api', '--paginate', '--slurp', f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100'],
        text=True, timeout=150))
    return [entry for page in pages for entry in page['artifacts']]


def validate_evidence(installation, acceptance, publication, channel, revision):
    profile = PROFILES[channel]
    image = installation['image']
    if not re.fullmatch(r'ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}', image):
        raise ValueError('Invalid release image')
    if not all((installation['profile'] == profile,
                installation['updateChannel'] == 'ghcr.io/closure-labs/finite:' + channel,
                acceptance['candidate'] == image, acceptance['profile'] == profile,
                acceptance['accepted'] is True, acceptance['secureBoot'] is True,
                acceptance['revision'] == revision,
                publication['revision'] == revision, publication['profile'] == profile,
                acceptance['buildIdentity'] == publication['buildIdentity'],
                acceptance['previousDigest'] == publication['previousDigest'],
                installation['installer']['finiteRevision'] == revision)):
        raise ValueError('Release evidence does not identify the same qualified candidate')
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('channel', choices=PROFILES)
    parser.add_argument('iso_run')
    parser.add_argument('build_run')
    args = parser.parse_args()
    for run_id in (args.iso_run, args.build_run):
        if not run_id.isdecimal():
            raise ValueError('Invalid run ID')
    revision = os.environ['GITHUB_SHA']
    iso_run = github('actions/runs/' + args.iso_run)
    build_run = github('actions/runs/' + args.build_run)
    validate_run(iso_run, 'iso.yml', revision)
    validate_run(build_run, 'build.yml', revision)
    profile = PROFILES[args.channel]
    iso_artifacts, build_artifacts = artifact_names(args.iso_run), artifact_names(args.build_run)
    destination = Path('.bluebuild/release')
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        artifact(args.iso_run, latest_artifact(iso_artifacts, f'finite-iso-{args.channel}-{args.iso_run}-'), destination)
        suffix = f'{profile}-{args.build_run}-'
        artifact(args.build_run, latest_artifact(build_artifacts, 'qualification-' + suffix), temporary / 'qualification')
        artifact(args.build_run, latest_artifact(build_artifacts, 'image-' + suffix), temporary / 'image')
        acceptance_path = temporary / 'qualification' / (profile + '-acceptance.json')
        publication_path = temporary / 'image' / (profile + '-publication.json')
        installation = json.loads((destination / 'installation.json').read_text())
        acceptance = json.loads(acceptance_path.read_text())
        publication = json.loads(publication_path.read_text())
        image = validate_evidence(installation, acceptance, publication, args.channel, revision)
        subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=destination, check=True, timeout=300)
        subprocess.run(['cosign', 'verify', '--key', 'cosign.pub', image], check=True, timeout=150)
        shutil.copy2(acceptance_path, destination / 'acceptance.json')
        shutil.copy2(publication_path, destination / 'publication.json')
        for path in (temporary / 'image').glob('*.Containerfile'):
            shutil.copy2(path, destination / path.name)
        provenance = {'schema': 1, 'image': image, 'revision': revision,
                      'buildIdentity': publication['buildIdentity'],
                      'buildRun': build_run['html_url'], 'isoRun': iso_run['html_url'],
                      'qualification': acceptance, 'installer': installation['installer']}
        (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            print('image=' + image, file=output)


if __name__ == '__main__':
    main()
