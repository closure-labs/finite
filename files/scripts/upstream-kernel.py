#!/usr/bin/env python3
"""Preserve the authenticated Bluefin kernel, modules and storage RPMs unchanged.

The initramfs is a derived boot artifact regenerated for Finite's encrypted-root
and FIDO2 support. Its content is checked separately by check-initramfs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

MAX_RECEIPT = 16 * 1024**2
MAX_FILE = 512 * 1024**2
MAX_TREE = 16 * 1024**3
MAX_ENTRIES = 65536
RECEIPT = Path('/usr/share/finite/upstream-kernel.json')


def run(command):
    with tempfile.TemporaryFile() as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
        stream.seek(0, 2)
        size = stream.tell()
        if result.returncode or not 0 < size <= 2 * 1024**2:
            raise ValueError('Cannot read bounded upstream kernel RPM inventory')
        stream.seek(0)
        return stream.read().decode()


def protected(name):
    return (name in ('kernel', 'akmods', 'zfs', 'python3-pyzfs')
            or name.startswith(('kernel-', 'akmod-', 'kmod-', 'zfs-',
                                'libzfs', 'libzpool', 'libnvpair', 'libuutil')))


def packages(runner):
    values = {}
    for line in runner(['rpm', '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n']).splitlines():
        fields = line.split('\t')
        if len(fields) != 3:
            raise ValueError('Malformed RPM inventory')
        name, evr, arch = fields
        if protected(name):
            if (not re.fullmatch(r'[0-9]+:[A-Za-z0-9._+~^]+-[A-Za-z0-9._+~^]+', evr)
                    or not re.fullmatch(r'[A-Za-z0-9_]+', arch)):
                raise ValueError('Malformed protected upstream RPM')
            values.setdefault(name, []).append([evr, arch])
    if any(name not in values for name in ('kernel', 'kernel-core', 'kernel-modules-core')):
        raise ValueError('Upstream has no complete kernel package set')
    if len(values['kernel-core']) != 1:
        raise ValueError('Upstream must provide one authoritative kernel')
    return {name: sorted(records) for name, records in sorted(values.items())}


def module_tree(root, release):
    root = Path(root)
    if (any(path.is_symlink() for path in (root, *root.parents)) or not root.is_dir()
            or (root / release).is_symlink() or (root / release / 'vmlinuz').is_symlink()
            or not (root / release / 'vmlinuz').is_file()):
        raise ValueError('Upstream kernel has no authoritative module tree')
    info = root.stat()
    entries = {'.': {'directory': True, 'mode': stat.S_IMODE(info.st_mode),
                     'uid': info.st_uid, 'gid': info.st_gid}}
    total = 0

    def failure(error):
        raise ValueError('Cannot inspect upstream module tree') from error

    for parent, folders, files in os.walk(root, followlinks=False, onerror=failure):
        for name in sorted([*folders, *files]):
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            if path.parent == root / release and name == 'initramfs.img':
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                # Kernel-devel build/source links are metadata; loadable module
                # links must resolve to bytes covered by this same receipt.
                if re.search(r'\.ko(?:\.(?:xz|gz|zst))?$', name):
                    target = path.resolve(strict=True)
                    if not target.is_relative_to(root) or not target.is_file():
                        raise ValueError('Loadable module link escapes preserved bytes')
                value = {'link': str(path.readlink()), 'uid': info.st_uid, 'gid': info.st_gid}
            elif stat.S_ISDIR(info.st_mode):
                value = {'directory': True, 'mode': stat.S_IMODE(info.st_mode),
                         'uid': info.st_uid, 'gid': info.st_gid}
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_size > MAX_FILE or total > MAX_TREE:
                    raise ValueError('Upstream module bytes exceed preservation bounds')
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                value = {'sha256': digest, 'bytes': info.st_size,
                         'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            else:
                raise ValueError('Unexpected upstream module entry type')
            entries[relative] = value
            if len(entries) > MAX_ENTRIES:
                raise ValueError('Upstream module tree exceeds entry bound')
    if not entries:
        raise ValueError('Upstream module preservation has no entries')
    return entries


def state(root, runner):
    inventory = packages(runner)
    evr, arch = inventory['kernel-core'][0]
    release = evr.split(':', 1)[1] + '.' + arch
    if not re.fullmatch(r'[A-Za-z0-9._+~^-]+', release):
        raise ValueError('Invalid upstream kernel release')
    return {'schema': 1, 'kernelRelease': release, 'packages': inventory,
            'modules': module_tree(root, release)}


def snapshot(output=RECEIPT, root=Path('/usr/lib/modules'), runner=run):
    output = Path(output)
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('Upstream receipt cannot use symlinks')
    value = state(root, runner)
    encoded = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(encoded) > MAX_RECEIPT:
        raise ValueError('Upstream preservation receipt exceeds bound')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(encoded)
    return value


def verify(receipt=RECEIPT, root=Path('/usr/lib/modules'), runner=run):
    receipt = Path(receipt)
    if (any(path.is_symlink() for path in (receipt, *receipt.parents))
            or not receipt.is_file() or not 0 < receipt.stat().st_size <= MAX_RECEIPT):
        raise ValueError('Missing, linked or oversized upstream preservation receipt')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate upstream preservation field')
            result[key] = value
        return result

    expected = json.loads(receipt.read_text(), object_pairs_hook=unique)
    if (not isinstance(expected, dict) or type(expected.get('schema')) is not int
            or expected['schema'] != 1 or set(expected) != {'schema', 'kernelRelease', 'packages', 'modules'}
            or expected != state(root, runner)):
        raise ValueError('Finite changed the inherited Bluefin kernel/module/storage set')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('snapshot', 'verify'))
    parser.add_argument('--receipt', type=Path, default=RECEIPT)
    args = parser.parse_args()
    value = snapshot(args.receipt) if args.operation == 'snapshot' else verify(args.receipt)
    print('Preserved upstream Bluefin kernel/module/storage set: ' + value['kernelRelease'])


if __name__ == '__main__':
    main()
