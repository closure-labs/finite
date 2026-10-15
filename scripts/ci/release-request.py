#!/usr/bin/env python3
"""Validate a per-channel release request before tools, downloads or credentials."""
import os
import json
from pathlib import Path
import re
import subprocess
import sys

CHANNELS = ('finite', 'finite-dev')


def canonical_tag(channel, version):
    if channel not in CHANNELS:
        raise ValueError('Unsupported release channel')
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('VERSION must be a canonical numeric release version')
    return f'{channel}-{version}'


def release_notes(version, changelog):
    canonical_tag('finite', version)
    headings = list(re.finditer(r'^## \[([^\]]+)\][^\n]*$', changelog, re.MULTILINE))
    matches = [index for index, heading in enumerate(headings) if heading[1] == version]
    if len(matches) != 1:
        raise ValueError('CHANGELOG must have exactly one entry for VERSION')
    index = matches[0]
    start = headings[index].end()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    notes = changelog[start:end].strip()
    if not notes:
        raise ValueError('Release changelog entry is empty')
    # Release bodies live on GitHub; repository-relative links need a pinned source.
    source = os.environ.get('RELEASE_SOURCE_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('Release notes require the exact source revision')
    notes = notes.replace('(docs/', f'(https://github.com/closure-labs/finite/blob/{source}/docs/')
    return notes + ('\n\nInstallation assets include signed checksums, SBOM, provenance and '
                    'qualification evidence. Large ISO images are split; concatenate parts '
                    'in filename order before use. Review all evidence before publishing.\n')


def validate(channel, tag, version, build_run, iso_run=''):
    if tag != canonical_tag(channel, version):
        raise ValueError('Release tag must match the selected channel and checkout VERSION')
    for name, value in (('build_run', build_run), ('iso_run', iso_run)):
        if name == 'iso_run' and value == '':
            continue
        if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value):
            raise ValueError('Invalid ' + name)
    return tag


def require_new_tag(tag):
    refs = json.loads(subprocess.check_output([
        'gh', 'api', 'repos/closure-labs/finite/git/matching-refs/tags/' + tag
    ], text=True, timeout=90))
    if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
        raise ValueError('Invalid release tag lookup')
    if any(ref.get('ref') == 'refs/tags/' + tag for ref in refs):
        raise ValueError('Release requires a new tag; an existing tag cannot be retargeted')


if __name__ == '__main__':
    if sys.argv[1:] == ['--write-notes']:
        Path('.bluebuild/release-notes.md').write_text(release_notes(
            Path('VERSION').read_text().strip(), Path('CHANGELOG.md').read_text()))
        sys.exit(0)
    tag = validate(os.environ['CHANNEL'], os.environ['RELEASE_TAG'],
                   Path('VERSION').read_text().strip(), os.environ['BUILD_RUN'],
                   os.environ.get('ISO_RUN', ''))
    if sys.argv[1:] != ['--check-tag']:
        raise ValueError('Hosted release request requires --check-tag')
    require_new_tag(tag)
    print('Release request matches channel and checkout version')
