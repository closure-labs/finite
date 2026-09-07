#!/usr/bin/env python3
"""Prepare isolated candidate tags and promote only a verified image digest."""
import argparse
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
    evidence = root / '.bluebuild'
    evidence.mkdir(exist_ok=True)
    (evidence / f'{profile}-image-ref.txt').unlink(missing_ok=True)
    # Publication workflows share finite-publication concurrency. A stable
    # candidate tag per profile also preserves BlueBuild's per-tag layer cache.
    candidate = f'candidate-{profile}'
    record = {**recipe, 'profile': profile, 'candidate': candidate,
              'revision': os.environ.get('GITHUB_SHA', 'local'), 'publish': publish}
    (evidence / f'{profile}-publication.json').write_text(json.dumps(record, indent=2) + '\n')
    if publish:
        path = root / 'recipes' / f'{profile}.yml'
        content, count = re.subn(r'^alt-tags: \[[^\n]+\]$', 'alt-tags: [' + candidate + ']', path.read_text(), flags=re.M)
        if count != 1:
            raise ValueError('Expected one inline alt-tags field')
        path.write_text(content)


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
    for tag in record['tags']:
        target = upstream.REPOSITORY + ':' + tag
        subprocess.run(['skopeo', '--command-timeout', '90s', 'copy', '--retry-times', '3',
                        '--all', '--preserve-digests', 'docker://' + image, 'docker://' + target],
                       check=True, timeout=150)
        if upstream.inspect(target)['Digest'] != expected:
            raise RuntimeError(f'{target}: promoted digest does not match verified candidate')
    (evidence / f'{profile}-promoted.json').write_text(json.dumps({'image': image, 'tags': record['tags']}, indent=2) + '\n')


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
