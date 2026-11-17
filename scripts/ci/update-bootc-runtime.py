#!/usr/bin/env python3
"""Replace the temporary XBOOTLDR snapshot with a qualifying official release."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import tomllib
import urllib.request

from github_api import get_json

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bootc_source', ROOT / 'scripts/bluebuild/stage-bootc-runtime.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
PREFIX = 'repos/bootc-dev/bootc/'


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('Require a stable bootc release version')
    return tuple(map(int, value.split('.')))


def download(ref):
    request = urllib.request.Request('https://codeload.github.com/bootc-dev/bootc/tar.gz/' + ref,
                                     headers={'User-Agent': 'finite-bootc-release-update'})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(32 * 1024**2 + 1)
    if not 0 < len(data) <= 32 * 1024**2:
        raise ValueError('Upstream source archive exceeds its bound')
    return data


def update(path, api=get_json, fetch=download):
    pin = source.validate(json.loads(path.read_text()))
    release = api(PREFIX + 'releases/latest')
    if release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('Require a published non-prerelease bootc release')
    tag = release.get('tag_name', '')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Invalid official bootc release tag')
    candidate = tag[1:]
    if version(candidate) < version(pin['minimumOfficialVersion']) or version(candidate) <= version(pin['version']):
        return False
    target = api(PREFIX + 'git/ref/tags/' + tag)['object']
    for _ in range(4):
        if target.get('type') == 'commit':
            break
        if target.get('type') != 'tag' or not re.fullmatch('[0-9a-f]{40}', target.get('sha', '')):
            raise ValueError('Official release does not resolve to an immutable commit')
        target = api(PREFIX + 'git/tags/' + target['sha'])['object']
    if target.get('type') != 'commit' or not re.fullmatch('[0-9a-f]{40}', target.get('sha', '')):
        raise ValueError('Official release tag has an invalid commit')
    comparison = api(PREFIX + 'compare/' + pin['requiredFix'] + '...' + target['sha'])
    if (comparison.get('status') not in ('ahead', 'identical')
            or comparison.get('merge_base_commit', {}).get('sha') != pin['requiredFix']):
        raise ValueError('Official release does not contain the required upstream XBOOTLDR fix')
    data = fetch(tag)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = [m for m in archive if m.name.endswith('/crates/lib/Cargo.toml')]
        if len(members) != 1 or not members[0].isfile() or members[0].size > 1024**2:
            raise ValueError('Official archive has no unique bootc version manifest')
        manifest = tomllib.loads(archive.extractfile(members[0]).read().decode())
        if manifest['package']['version'] != candidate:
            raise ValueError('Official archive version differs from the published release')
    pin.update(kind='release', version=candidate, ref=tag, revision=target['sha'],
               archiveSha256=hashlib.sha256(data).hexdigest(), rpmRelease='0.1.finite',
               purpose='Official upstream bootc release with XBOOTLDR support, shared by installer and OS')
    source.validate(pin)
    # No pin changes occur until metadata, ancestry and source bytes all pass.
    fd, temporary = tempfile.mkstemp(prefix='.bootc-runtime-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(pin, indent=2) + '\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pin', type=Path, default=ROOT / 'sources/bootc-runtime.json')
    args = parser.parse_args()
    changed = update(args.pin)
    print('Selected qualifying official bootc release' if changed else 'Waiting for an official bootc release after 1.17.4 containing XBOOTLDR support')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            print('changed=' + str(changed).lower(), file=stream)
