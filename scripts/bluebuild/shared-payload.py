#!/usr/bin/env python3
"""Stage one same-run payload artifact; this never authorizes publication."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile

MAX_BYTES = 2 * 1024**3
MAX_MEMBERS = 65536
CONTEXT = 'context.json'


def positive(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value)


def context(env, attempt=None):
    value = {'schema': 1, 'repository': env['GITHUB_REPOSITORY'], 'revision': env['GITHUB_SHA'],
             'runId': env['GITHUB_RUN_ID'],
             'runAttempt': env['GITHUB_RUN_ATTEMPT'] if attempt is None else attempt}
    if (value['repository'] != 'closure-labs/finite'
            or not re.fullmatch(r'[0-9a-f]{40}', value['revision'])
            or not positive(value['runId']) or not positive(value['runAttempt'])
            or not positive(env['GITHUB_RUN_ATTEMPT'])
            or int(value['runAttempt']) > int(env['GITHUB_RUN_ATTEMPT'])):
        raise ValueError('Invalid same-run payload context')
    return value


def unique(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError('Duplicate payload context field')
    return value


def members(archive, expected):
    entries = {}
    total = 0
    for entry in archive:
        name = entry.name.removeprefix('./').rstrip('/')
        if (len(entries) >= MAX_MEMBERS or not name or name.startswith('/') or '\\' in name
                or '..' in PurePosixPath(name).parts or str(PurePosixPath(name)) != name
                or name in entries or not (entry.isdir() or entry.isreg() or entry.issym())
                or entry.mode & ~0o777 or entry.size < 0 or entry.pax_headers or entry.sparse is not None
                or (not entry.isreg() and entry.size != 0)):
            raise ValueError('Invalid, duplicate or excessive payload archive member')
        if name not in ('.', CONTEXT, 'payload') and not name.startswith('payload/'):
            raise ValueError('Payload member escapes its root')
        total += entry.size
        if total > MAX_BYTES:
            raise ValueError('Payload expanded size exceeds limit')
        entries[name] = entry
    if (('.' in entries and not entries['.'].isdir())
            or not entries.get('payload') or not entries['payload'].isdir()
            or not entries.get(CONTEXT) or not entries[CONTEXT].isreg()
            or entries[CONTEXT].size > 16384):
        raise ValueError('Missing payload or bounded context')
    actual = json.loads(archive.extractfile(entries[CONTEXT]).read(), object_pairs_hook=unique)
    if actual != expected or type(actual.get('schema')) is not int:
        raise ValueError('Payload source/run/producer attempt differs from native job outputs')
    for name, entry in entries.items():
        for parent in PurePosixPath(name).parents:
            if str(parent) != '.' and (str(parent) not in entries or not entries[str(parent)].isdir()):
                raise ValueError('Payload member has a missing or linked parent')
        if entry.issym():
            target = entry.linkname
            if target.startswith('/nix/store/'):
                # Keep native runtime links byte-for-byte, but only to paths
                # actually present in the exported closure. No host-store copy.
                target = 'payload/nix-runtime/store/' + target[len('/nix/store/'):]
            elif target.startswith('/'):
                raise ValueError('Unexpected absolute payload link')
            else:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            if target not in entries or not (target == 'payload' or target.startswith('payload/')):
                raise ValueError('Payload link escapes the exported tree or is dangling')
    return len(entries), total


def check(path, expected, sha=None):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Missing, linked or oversized payload archive')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sha is not None and (not re.fullmatch(r'[0-9a-f]{64}', sha) or digest != sha):
            raise ValueError('Payload archive digest mismatch')
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode='r:') as archive:
            count, expanded = members(archive, expected)
    return {'sha256': digest, 'archiveBytes': path.stat().st_size, 'expandedBytes': expanded, 'members': count}


def binding(sha, revision, run, attempt, artifact_id, env):
    expected = context(env, attempt)
    if (revision != expected['revision'] or run != expected['runId'] or not positive(artifact_id)
            or not re.fullmatch(r'[0-9a-f]{64}', sha)):
        raise ValueError('Missing or stale native payload job outputs')
    return expected


def create(source, archive, env):
    if (source.is_symlink() or not source.is_dir()
            or not (source / 'home-manager-template').is_dir()
            or not (source / 'nix-runtime/runtime.json').is_file()):
        raise ValueError('Expected the materialized image payload')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='finite-payload-') as temporary:
        root = Path(temporary)
        # Native cp/tar preserve the same files, executable modes and symlinks
        # as stage.sh. Hard links are materialized; no special nodes are accepted.
        subprocess.run(['cp', '-a', str(source), str(root / 'payload')], check=True, timeout=300)
        (root / CONTEXT).write_text(json.dumps(context(env), sort_keys=True) + '\n')
        subprocess.run(['tar', '--format=gnu', '--hard-dereference', '-C', str(root), '-cf', str(archive.resolve()), '.'],
                       check=True, timeout=300)
    return check(archive, context(env))


def stage(archive, sha, revision, run, attempt, artifact_id, destination, env):
    expected = binding(sha, revision, run, attempt, artifact_id, env)
    result = check(archive, expected, sha)
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
        raise ValueError('Linked staging destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.finite-payload-', dir=destination.parent) as temporary:
        # Every member, parent, link and context was checked before extraction.
        # Extract into an empty directory; never through an existing tree/link.
        subprocess.run(['tar', '--no-same-owner', '-C', temporary, '-xf', str(archive.resolve())],
                       check=True, timeout=300)
        payload = Path(temporary) / 'payload'
        if not (payload / 'home-manager-template').is_dir() or not (payload / 'nix-runtime/runtime.json').is_file():
            raise ValueError('Incomplete staged image payload')
        subprocess.run(['chmod', '-R', 'u+w', str(payload)], check=True, timeout=60)
        if destination.exists():
            shutil.rmtree(destination)
        payload.rename(destination)
    return {**result, **expected, 'artifactId': artifact_id, 'consumerAttempt': env['GITHUB_RUN_ATTEMPT']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('create')
    pack.add_argument('source', type=Path)
    pack.add_argument('archive', type=Path)
    commands.add_parser('validate')
    unpack = commands.add_parser('stage')
    unpack.add_argument('archive', type=Path)
    for command in ('stage', 'validate'):
        for name in ('sha256', 'revision', 'run', 'attempt', 'artifact-id'):
            commands.choices[command].add_argument('--' + name, required=True)
    unpack.add_argument('--destination', type=Path, default=Path('files/payload'))
    args = parser.parse_args()
    if args.command == 'create':
        result = create(args.source, args.archive, os.environ)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            print('sha256=' + result['sha256'], file=output)
            for key, value in context(os.environ).items():
                if key != 'schema':
                    print(key + '=' + value, file=output)
    elif args.command == 'stage':
        result = stage(args.archive, args.sha256, args.revision, args.run, args.attempt,
                       args.artifact_id, args.destination, os.environ)
    else:
        result = binding(args.sha256, args.revision, args.run, args.attempt, args.artifact_id, os.environ)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
