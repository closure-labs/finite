#!/usr/bin/env python3
"""Export only declared nonsecret CI switches after scoped SecretSpec resolution."""
import argparse
import json
import os
from pathlib import Path

OPTIONS = ('FINITE_OPTIMIZED_CACHES', 'FINITE_CACHIX_WRITER', 'FINITE_REUSE_INVENTORY',
           'FINITE_GRYPE_DB_CACHE', 'FINITE_QUALIFICATION_REUSE', 'FINITE_QUALIFIED_ISO_PRESERVATION')


def options(env):
    result = {}
    for key in OPTIONS:
        value = env.get(key, 'false') or 'false'
        if value not in ('true', 'false'):
            raise ValueError('Expected true or false for ' + key)
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--github-env', action='store_true')
    args = parser.parse_args()
    result = options(os.environ)
    if args.github_env:
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise ValueError('GitHub export is hosted-only')
        with Path(os.environ['GITHUB_ENV']).open('a') as output:
            output.write(''.join(key + '=' + value + '\n' for key, value in result.items()))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
