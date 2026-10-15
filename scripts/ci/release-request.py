#!/usr/bin/env python3
"""Validate a per-channel release request before tools, downloads or credentials."""
import os
import json
from pathlib import Path
import re
import subprocess
import sys

CHANNELS = ('finite', 'finite-dev')


def validate(channel, tag, version, build_run, iso_run=''):
    if channel not in CHANNELS:
        raise ValueError('Unsupported release channel')
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('VERSION must be a canonical numeric release version')
    if tag != f'finite-{channel}-{version}':
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
    tag = validate(os.environ['CHANNEL'], os.environ['RELEASE_TAG'],
                   Path('VERSION').read_text().strip(), os.environ['BUILD_RUN'],
                   os.environ.get('ISO_RUN', ''))
    if sys.argv[1:] != ['--check-tag']:
        raise ValueError('Hosted release request requires --check-tag')
    require_new_tag(tag)
    print('Release request matches channel and checkout version')
