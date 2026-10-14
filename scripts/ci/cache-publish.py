#!/usr/bin/env python3
"""Prepare allowlisted successful proof/tool closures before exposing a write token."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
STORE = re.compile(r'/nix/store/[a-z0-9]{32}-[^/\s]+')
TOOLS = ('image-tools', 'scanner-tools', 'ci-repository-security-audit', 'ci-secrets-run')
MIB = 1024 ** 2


def boundary(env=os.environ):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_EVENT_NAME') != 'workflow_run'
            or not re.fullmatch(r'[0-9a-f]{40}', env.get('CACHE_SOURCE_REVISION', ''))):
        raise ValueError('Cache publishing requires a successful trusted main workflow')
    head = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'],
                                   cwd=ROOT, text=True, timeout=30).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', head) or head != env['CACHE_SOURCE_REVISION']:
        raise ValueError('Cache publishing checkout differs from its successful source revision')


def output(command):
    value = subprocess.check_output(command, cwd=ROOT, text=True, timeout=3600).strip()
    if not STORE.fullmatch(value):
        raise ValueError('Expected exactly one store output')
    return value


def closure_size(path):
    if not STORE.fullmatch(path):
        raise ValueError('Invalid store root')
    records = json.loads(subprocess.check_output(
        ['nix', 'path-info', '--json', '--json-format', '1', '--closure-size', path], text=True, timeout=120))
    size = records[path]['closureSize']
    if type(size) is not int or size < 0:
        raise ValueError('Invalid closure size')
    return size


def prepare(destination):
    boundary()
    if os.environ.get('CACHIX_AUTH_TOKEN'):
        raise ValueError('Do not expose the Cachix credential during realization')
    checks = output(['nix', 'build', '--accept-flake-config', '--no-link', '--print-out-paths', '.#ci-checks'])
    roots = []
    for proof in sorted(Path(checks).iterdir()):
        path = str(proof.resolve(strict=True))
        size = closure_size(path)
        if size > MIB:
            raise ValueError('Check proof exceeds the existing one-MiB closure limit: ' + proof.name)
        roots.append({'kind': 'proof', 'name': proof.name, 'path': path, 'bytes': size})
    if not roots:
        raise ValueError('Successful checks produced no proof outputs')
    for tool in TOOLS:
        path = output(['nix', 'build', '--file', 'lib/ci-tools.nix', tool, '--no-link', '--print-out-paths'])
        size = closure_size(path)
        if size > 2 * 1024 ** 3:
            raise ValueError('Tool closure exceeds the two-GiB upload bound: ' + tool)
        roots.append({'kind': 'tool', 'name': tool, 'path': path, 'bytes': size})
    destination.write_text(json.dumps({'schema': 1, 'revision': os.environ['CACHE_SOURCE_REVISION'],
                                      'cache': 'finite-os', 'roots': roots}, indent=2) + '\n')


def push(manifest):
    boundary()
    if not os.environ.get('CACHIX_AUTH_TOKEN'):
        raise ValueError('Cachix writer credential is unavailable')
    if manifest.is_symlink() or manifest.stat().st_size > MIB:
        raise ValueError('Invalid cache manifest')
    record = json.loads(manifest.read_text())
    if (record.get('schema') != 1 or record.get('revision') != os.environ['CACHE_SOURCE_REVISION']
            or record.get('cache') != 'finite-os' or not isinstance(record.get('roots'), list)
            or not 0 < len(record['roots']) <= 128):
        raise ValueError('Cache manifest identifies another source or destination')
    paths = []
    for root in record['roots']:
        kind, name, path = root['kind'], root['name'], root['path']
        limit = MIB if kind == 'proof' else 2 * 1024 ** 3
        if (kind not in ('proof', 'tool') or (kind == 'tool' and name not in TOOLS)
                or not isinstance(path, str) or not STORE.fullmatch(path)
                or type(root['bytes']) is not int or not 0 <= root['bytes'] <= limit
                or closure_size(path) != root['bytes']):
            raise ValueError('Invalid allowlisted cache root')
        paths.append(path)
    subprocess.run(['cachix', 'push', '--omit-deriver', 'finite-os', *sorted(set(paths))], check=True, timeout=1800)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'push'))
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    (prepare if args.mode == 'prepare' else push)(args.manifest)


if __name__ == '__main__':
    main()
