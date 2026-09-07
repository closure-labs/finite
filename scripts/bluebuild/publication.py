#!/usr/bin/env python3
"""Prepare isolated candidate tags and promote only a verified image digest."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

spec = importlib.util.spec_from_file_location('bluefin_upstream', Path(__file__).resolve().parents[1] / 'ci/bluefin-upstream.py')
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def prepare(profile, publish, root=upstream.ROOT):
    recipe = upstream.recipes(root)[profile]
    build_identity = upstream.image_identity(profile, root)
    mode = os.environ.get('FINITE_QUALIFICATION_MODE', 'shadow')
    if mode not in ('shadow', 'enforce'):
        raise ValueError('Qualification mode must be shadow or enforce')
    previous = upstream.inspect(upstream.REPOSITORY + ':' + recipe['tags'][0], allow_missing=True) if publish else None
    previous_digest = upstream.digest(previous['Digest']) if previous else ''
    if previous_digest:
        subprocess.run(['cosign', 'verify', '--key', str(root / 'cosign.pub'),
                        upstream.REPOSITORY + '@' + previous_digest],
                       check=True, stdout=subprocess.DEVNULL, timeout=150)
    weekly = os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and datetime.now(timezone.utc).weekday() == 0
    qualify = publish and (os.environ.get('FORCE_QUALIFICATION') == 'true' or weekly or not previous or
                          (previous.get('Labels') or {}).get('io.finite.build-inputs') != build_identity)
    evidence = root / '.bluebuild'
    evidence.mkdir(exist_ok=True)
    (evidence / f'{profile}-image-ref.txt').unlink(missing_ok=True)
    (evidence / f'{profile}-acceptance.json').unlink(missing_ok=True)
    # Publication workflows share finite-publication concurrency. A stable
    # candidate tag per profile also preserves BlueBuild's per-tag layer cache.
    candidate = f'candidate-{profile}'
    record = {**recipe, 'profile': profile, 'candidate': candidate,
              'revision': os.environ.get('GITHUB_SHA', 'local'), 'publish': publish,
              'buildIdentity': build_identity, 'previousDigest': previous_digest,
              'qualify': qualify, 'qualificationMode': mode}
    (evidence / f'{profile}-publication.json').write_text(json.dumps(record, indent=2) + '\n')
    if publish:
        path = root / 'recipes' / f'{profile}.yml'
        content, count = re.subn(r'^alt-tags: \[[^\n]+\]$', 'alt-tags: [' + candidate + ']', path.read_text(), flags=re.M)
        if count != 1:
            raise ValueError('Expected one inline alt-tags field')
        path.write_text(content)
    path = root / 'recipes' / f'{profile}.yml'
    content = path.read_text().replace('labels:\n', 'labels:\n  io.finite.build-inputs: "' + build_identity + '"\n', 1)
    path.write_text(content)
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            for name, value in {'qualify': str(qualify).lower(), 'previous': previous_digest,
                                'identity': build_identity}.items():
                print(f'{name}={value}', file=stream)


def promote(profile, root=upstream.ROOT):
    evidence = root / '.bluebuild'
    record = json.loads((evidence / f'{profile}-publication.json').read_text())
    if not record['publish'] or record['profile'] != profile or record['tags'] != upstream.PROFILES[profile][1]:
        raise ValueError('Invalid publication record')
    if record['revision'] != os.environ['GITHUB_SHA']:
        raise ValueError('Publication record is from a different revision')
    # This file is written only after signature, provenance and runtime checks
    # succeed. Never resolve the mutable candidate tag again for promotion.
    image = (evidence / f'{profile}-image-ref.txt').read_text().strip()
    prefix = upstream.REPOSITORY + '@'
    if not image.startswith(prefix):
        raise ValueError('Verified image must belong to the Finite repository')
    expected = upstream.digest(image.removeprefix(prefix))
    if record['qualificationMode'] != os.environ.get('FINITE_QUALIFICATION_MODE', 'shadow'):
        raise ValueError('Qualification policy changed between build and promotion')
    acceptance_path = evidence / f'{profile}-acceptance.json'
    accepted = False
    if record['qualify'] and acceptance_path.exists():
        acceptance = json.loads(acceptance_path.read_text())
        accepted = all((acceptance.get('accepted') is True,
                        acceptance.get('candidate') == image,
                        acceptance.get('previousDigest') == record['previousDigest'],
                        acceptance.get('profile') == profile,
                        acceptance.get('revision') == record['revision'],
                        acceptance.get('buildIdentity') == record['buildIdentity'],
                        acceptance.get('secureBoot') is True))
    if record['qualify'] and not accepted:
        if record['qualificationMode'] == 'enforce':
            raise ValueError('Candidate lacks matching successful Secure Boot qualification')
        print('::warning::Shadow qualification did not pass; mandatory gating is not enabled')
    for tag in record['tags']:
        target = upstream.REPOSITORY + ':' + tag
        subprocess.run(['skopeo', '--command-timeout', '90s', 'copy', '--retry-times', '3',
                        '--all', '--preserve-digests', 'docker://' + image, 'docker://' + target],
                       check=True, timeout=150)
        if upstream.inspect(target)['Digest'] != expected:
            raise RuntimeError(f'{target}: promoted digest does not match verified candidate')
    (evidence / f'{profile}-promoted.json').write_text(json.dumps(
        {**record, 'image': image, 'accepted': accepted}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'promote'])
    parser.add_argument('profile', choices=upstream.PROFILES)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.profile, args.publish)
    else:
        promote(args.profile)


if __name__ == '__main__':
    main()
