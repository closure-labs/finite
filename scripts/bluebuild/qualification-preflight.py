#!/usr/bin/env python3
"""Gate production qualification or isolated manual branch VM diagnostics."""
import argparse
import os
from pathlib import Path
import re
import sys
import subprocess
from types import SimpleNamespace
sys.dont_write_bytecode = True

REPOSITORY = 'closure-labs/finite'
def require_current(revision):
    # The existing production ancestry rule imports PyYaml through publication.
    # Its pinned shell provides that dependency; branch diagnostics need only
    # the standard library and never invoke this production path.
    subprocess.run(['nix', 'develop', '--file', 'lib/ci-tools.nix', 'shell', '--command',
                    'python3', str(Path(__file__).with_name('publication-current.py')),
                    '--revision', revision], check=True, timeout=300)
    return revision


production = SimpleNamespace(require_current=require_current)


def require_eligible(revision, environ=None):
    env = os.environ if environ is None else environ
    if (not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision)
            or revision != env.get('GITHUB_SHA') or env.get('GITHUB_ACTIONS') != 'true'
            or env.get('GITHUB_REPOSITORY') != REPOSITORY):
        raise ValueError('Qualification requires the exact hosted Finite checkout')
    mode = env.get('FINITE_VALIDATION_ONLY', 'false')
    if mode not in ('true', 'false', ''):
        raise ValueError('Qualification validation-only mode must be an explicit boolean')
    compression = env.get('FINITE_INSTALLER_COMPRESSION', 'default')
    if compression not in ('default', 'zstd'):
        raise ValueError('Unknown installer compression experiment')
    if compression != 'default' and mode != 'true':
        raise ValueError('Installer compression experiments require validation-only qualification')
    if compression == 'zstd' and not re.fullmatch(r'sha256:[0-9a-f]{64}', env.get('PREVIOUS_DIGEST', '')):
        raise ValueError('Compression diagnostics require a predecessor for upgrade and rollback')
    ref = env.get('GITHUB_REF', '')
    if mode == 'true':
        expected = REPOSITORY + '/.github/workflows/benchmark-image-tools.yml@' + ref
        if (env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or not ref.startswith('refs/heads/')
                or ref == 'refs/heads/main' or not ref.removeprefix('refs/heads/')
                or env.get('GITHUB_WORKFLOW_REF') != expected):
            raise ValueError('Validation-only qualification requires the manual non-main benchmark workflow')
        # This authorizes VM testing only. No main eligibility, channel
        # promotion, saved ISO reuse or qualification reuse follows from it.
        return {'validationOnly': True, 'revision': revision}
    if ref != 'refs/heads/main':
        raise ValueError('Production qualification requires refs/heads/main')
    return {'validationOnly': False, 'revision': revision, 'main': production.require_current(revision)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    result = require_eligible(args.revision)
    if result['validationOnly']:
        print('Authorized manual branch VM diagnostics; acceptance is validation-only')
    else:
        print('Production qualification eligibility confirmed for revision ' + result['revision'])


if __name__ == '__main__':
    main()
