#!/usr/bin/env python3
"""Apply public cache policy to both flake and lightweight Nix consumers."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


def policy():
    config = json.loads(subprocess.check_output(
        ['nix', 'eval', '--json', '--file', 'lib/project-policy.nix', 'nixConfig'], text=True, timeout=30))
    for key, pattern in [('extra-substituters', r'https://[a-z0-9-]+\.cachix\.org'),
                         ('extra-trusted-public-keys', r'[a-z0-9-]+\.cachix\.org-1:[A-Za-z0-9+/]+={0,2}')]:
        values = config.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not re.fullmatch(pattern, v) for v in values):
            raise ValueError('Invalid public cache policy: ' + key)
    return config


def configuration(config):
    return '\n'.join(key + ' = ' + ' '.join(config[key]) for key in
                     ('extra-substituters', 'extra-trusted-public-keys')) + '\n'


def verify(config, env=None):
    actual = json.loads(subprocess.check_output(['nix', 'config', 'show', '--json'],
                                               text=True, timeout=30, env=env))
    for key in ('substituters', 'trusted-public-keys'):
        if not set(config['extra-' + key]).issubset(actual.get(key, {}).get('value', [])):
            raise ValueError('Nix did not apply the public ' + key)
    # Full configuration may contain credentials. Log only approved public values.
    print(json.dumps(config, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure', action='store_true')
    args = parser.parse_args()
    config = policy()
    if args.configure:
        existing = os.environ.get('NIX_CONFIG', '')
        value = existing.rstrip('\n') + '\n' + configuration(config)
        verify(config, dict(os.environ, NIX_CONFIG=value))
        marker = 'FINITE_PUBLIC_CACHE_' + uuid.uuid4().hex
        with Path(os.environ['GITHUB_ENV']).open('a') as output:
            output.write('NIX_CONFIG<<' + marker + '\n' + value + marker + '\n')
    else:
        verify(config)


if __name__ == '__main__':
    main()
