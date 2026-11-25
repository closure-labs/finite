#!/usr/bin/env python3
"""Gate production qualification; branch VM diagnostics and installer experiments are archived."""
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
    # The manual branch diagnostics, installer compression and benchmark
    # controls are archived. Fail closed if anything still requests them.
    if env.get('FINITE_VALIDATION_ONLY', 'false') not in ('false', ''):
        raise ValueError('Validation-only qualification is archived')
    if env.get('FINITE_INSTALLER_COMPRESSION', 'default') != 'default':
        raise ValueError('Installer compression experiments are archived')
    if env.get('FINITE_INSTALLER_BENCHMARK', ''):
        raise ValueError('Installer benchmark controls are archived')
    if env.get('GITHUB_REF', '') != 'refs/heads/main':
        raise ValueError('Production qualification requires refs/heads/main')
    return {'validationOnly': False, 'revision': revision, 'main': production.require_current(revision)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    result = require_eligible(args.revision)
    print('Production qualification eligibility confirmed for revision ' + result['revision'])


if __name__ == '__main__':
    main()
