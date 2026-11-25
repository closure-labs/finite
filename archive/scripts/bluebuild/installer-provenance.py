#!/usr/bin/env python3
"""Observe diagnostic Lorax inputs; preserve its calls, arguments and exit status."""
import argparse
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

MARKER = 'FINITE_INSTALLER_PROVENANCE_V1:'
LIMIT = 65536


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(raw):
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError('Missing or oversized installer inventory')
    lines = raw.decode('utf-8').splitlines()
    if not lines or len(lines) > 10000 or any(not line or len(line) > 4096 for line in lines):
        raise ValueError('Invalid installer inventory')
    return {'count': len(lines), 'sha256': digest(sorted(lines))}


def file_inventory(roots, pattern):
    roots = [roots] if isinstance(roots, (str, Path)) else list(roots)
    if not 0 < len(roots) <= 32:
        return None
    hashes, entries, total = [], 0, 0
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            entries += 1 + len(dirs) + len(files)
            if entries > 10000:
                raise ValueError('Oversized installer metadata tree')
            dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if not path.match(pattern):
                    continue
                size = path.stat().st_size
                total += size
                if path.is_symlink() or not path.is_file() or size > 4 * 1024 * 1024 or total > 16 * 1024 * 1024:
                    raise ValueError('Invalid or oversized installer metadata file')
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return {'count': len(hashes), 'sha256': digest(sorted(hashes))} if hashes else None


def limited_output(command):
    with tempfile.TemporaryFile() as output:
        subprocess.run(command, stdout=output, check=True, timeout=30)
        output.seek(0)
        return output.read(2 * 1024 * 1024 + 1)


def observe_runtime(builder):
    config = builder.dbo.get_config()
    query = ['rpm', '-qa', '--qf', '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH} %{SIGMD5}\n']
    # Run before runtime cleanup removes the RPM database. No guest is seeded.
    return {'runtimeRpms': inventory(limited_output(query[:1] + ['--root', str(config.installroot)] + query[1:])),
            'installerRpms': inventory(limited_output(query)),
            'repositoryMetadata': file_inventory(str(config.cachedir), 'repomd.xml'),
            'repositoryConfiguration': file_inventory(config.reposdir, '*.repo')}


def validate(value):
    if value.get('schema') != 1 or value.get('authorizesPublication') is not False:
        raise ValueError('Invalid runtime provenance schema')
    core = {name: value[name] for name in ('runtimeRpms', 'installerRpms', 'repositoryMetadata', 'repositoryConfiguration')}
    for name, item in core.items():
        if item is None and name.startswith('repository'):
            continue  # Missing metadata stays unknown, never a matched cohort.
        if (not isinstance(item, dict) or set(item) != {'count', 'sha256'}
                or type(item['count']) is not int or not 0 < item['count'] <= 10000
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid runtime inventory')
    if digest(core) != value.get('cohortSha256'):
        raise ValueError('Runtime provenance hash differs from its inventories')
    compression = value.get('compression', {})
    if compression.get('type') not in ('xz', 'zstd') or not isinstance(compression.get('args'), list):
        raise ValueError('Invalid observed runtime compression')
    return value


def hook(lorax='/usr/bin/lorax'):
    # The pinned Lorax 44.6-1 calls install once and then creates a plain
    # squashfs runtime. Instrument those methods without changing either call.
    import pylorax.treebuilder as treebuilder
    builder = treebuilder.RuntimeBuilder
    install, create = builder.install, builder.create_squashfs_runtime
    observed = {}

    def installed(self, *args, **kwargs):
        result = install(self, *args, **kwargs)
        observed[id(self)] = observe_runtime(self)
        return result

    def created(self, *args, **kwargs):
        arguments = inspect.signature(create).bind(self, *args, **kwargs)
        arguments.apply_defaults()
        core = observed.pop(id(self))
        value = {**core, 'schema': 1, 'authorizesPublication': False,
            'cohortSha256': digest(core), 'compression': {
                'type': arguments.arguments['compression'],
                'args': arguments.arguments['compressargs'] or []}}
        validate(value)
        raw = json.dumps(value, sort_keys=True).encode()
        print(MARKER + base64.b64encode(raw).decode() + ':END', flush=True)
        return create(self, *args, **kwargs)

    builder.install, builder.create_squashfs_runtime = installed, created
    try:
        runpy.run_path(lorax, run_name='__main__')
    finally:
        builder.install, builder.create_squashfs_runtime = install, create


def capture(command, output, expected=None):
    output.unlink(missing_ok=True)
    found = []
    # Stream logs while retaining only bounded marker lines. This also retains
    # partial evidence when Lorax or the outer job fails after the marker.
    invalid = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        for line in iter(lambda: process.stdout.readline(LIMIT + 1), b''):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            if MARKER.encode() not in line:
                continue
            try:
                if len(line) > LIMIT:
                    raise ValueError('Oversized runtime provenance marker')
                match = re.search(re.escape(MARKER).encode() + rb'([A-Za-z0-9+/=]+):END', line)
                if not match:
                    raise ValueError('Malformed runtime provenance marker')
                value = validate(json.loads(base64.b64decode(match[1], validate=True)))
                if found:
                    raise ValueError('Multiple runtime provenance records')
                found.append(value)
            except (ValueError, KeyError, TypeError) as error:
                invalid = error
        status = process.wait()
    if found:
        output.write_text(json.dumps(found[0], indent=2) + '\n')
    if status:
        return status if status > 0 else 128 - status
    if invalid:
        raise ValueError("Invalid runtime provenance") from invalid
    if len(found) != 1:
        raise ValueError('Successful diagnostic ISO has no runtime provenance')
    if expected and (found[0]['cohortSha256'] != expected or any(
            found[0][name] is None for name in ('repositoryMetadata', 'repositoryConfiguration'))):
        raise ValueError('Runtime inputs differ from the predeclared cohort; stop before VM work')
    return 0


def smoke():
    """Check the real pinned Python/RPM/CLI APIs without ISO or VM work."""
    import libdnf5
    from pylorax.treebuilder import RuntimeBuilder
    names = inspect.signature(RuntimeBuilder.create_squashfs_runtime).parameters
    if not {'self', 'compression', 'compressargs'} <= set(names):
        raise ValueError('Pinned Lorax runtime API differs from the observer')
    with tempfile.TemporaryDirectory(prefix='finite-observer-smoke-') as directory:
        root = Path(directory)
        for name in ('cache', 'repos'):
            (root / name).mkdir()
        (root / 'cache/repomd.xml').write_text('smoke fixture, not resolved repository metadata\n')
        (root / 'repos/smoke.repo').write_text('[smoke]\nenabled=0\n')
        base = libdnf5.base.Base()
        config = base.get_config()
        config.installroot, config.cachedir, config.reposdir = '/', str(root / 'cache'), [str(root / 'repos')]
        builder = object.__new__(RuntimeBuilder); builder.dbo = base
        value = observe_runtime(builder)
        if value['repositoryMetadata']['count'] != 1 or value['repositoryConfiguration']['count'] != 1:
            raise ValueError('Pinned DNF metadata paths differ from the observer')
    subprocess.run(['/usr/local/bin/lorax', '--help'], check=True, timeout=30)
    print('Pinned Lorax, DNF and RPM observer APIs passed; smoke fixtures are not runtime cohort evidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('smoke')
    wrapped = sub.add_parser('hook')
    wrapped.add_argument('command', nargs=argparse.REMAINDER)
    captured = sub.add_parser('capture')
    captured.add_argument('--output', type=Path, required=True)
    captured.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == 'smoke':
        smoke()
    elif args.operation == 'hook':
        # Keep argv[1:] identical to the original Lorax invocation.
        sys.argv = ['/usr/bin/lorax', *(args.command[1:] if args.command[:1] == ['--'] else args.command)]
        hook()
    else:
        command = args.command
        if command and command[0] == '--':
            command = command[1:]
        if not command or not args.output:
            parser.error('capture needs an output and command')
        expected = None
        if raw := os.environ.get('FINITE_INSTALLER_BENCHMARK'):
            expected = json.loads(raw)['runtimeCohorts'][os.environ['FINITE_BENCHMARK_PHASE']]
        sys.exit(capture(command, args.output, expected))


if __name__ == '__main__':
    main()
