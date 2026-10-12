#!/usr/bin/env python3
"""Remove only proven unowned generated artifacts from retired kernel trees."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

inventory_spec = importlib.util.spec_from_file_location('kernel_rpm_inventory', Path(__file__).with_name('security-remediate.py'))
rpm_inventory = importlib.util.module_from_spec(inventory_spec)
inventory_spec.loader.exec_module(rpm_inventory)
# Retire host pool tools, kernel modules and Python bindings. Shared ZFS
# libraries remain protected with other unrelated packages; no autoremove.
ZFS_PACKAGES = ('kmod-zfs', 'zfs', 'python3-pyzfs')
TRANSACTION_PACKAGES = frozenset((
    'kernel', 'kernel-core', 'kernel-modules-core', 'kernel-modules', 'kernel-modules-extra',
    'kernel-devel', 'kernel-devel-matched', 'kmod-v4l2loopback', 'v4l2loopback',
))

GENERATED_MODULE_FILES = frozenset((
    'initramfs.img', 'modules.alias', 'modules.alias.bin',
    'modules.builtin.alias.bin', 'modules.builtin.bin', 'modules.dep',
    'modules.dep.bin', 'modules.devname', 'modules.softdep',
    'modules.symbols', 'modules.symbols.bin', 'modules.weakdep',
))


def run(args):
    with tempfile.TemporaryFile(mode='w+') as output:
        result = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, text=True,
                                timeout=900, env={**os.environ, 'LC_ALL': 'C'})
        output.seek(0, 2)
        size = output.tell()
        if result.returncode:
            output.seek(max(0, size - 65536))
            diagnostic = output.read()
            expected_unowned = (args[:2] == ['rpm', '-qf'] and result.returncode == 1
                                and diagnostic.strip() == f'file {args[-1]} is not owned by any package')
            if not expected_unowned:
                print(diagnostic, file=sys.stderr)
            raise subprocess.CalledProcessError(result.returncode, args, output=diagnostic)
        if size > 2 * 1024 * 1024:
            raise ValueError('Kernel command output exceeded the reviewed limit')
        output.seek(0)
        return output.read().strip()


def prune_modules(root, release, old_releases, runner):
    root = Path(root)
    current = root / release
    if (root.is_symlink() or current.is_symlink() or not current.is_dir()
            or (current / 'vmlinuz').is_symlink() or not (current / 'vmlinuz').is_file()):
        raise ValueError('Verified kernel has no authoritative module directory')
    runner(['depmod', '-a', release])
    if (current / 'modules.dep').is_symlink() or not (current / 'modules.dep').is_file():
        raise ValueError('Kernel module dependencies were not generated')
    stale = []
    for directory in sorted(root.iterdir()):
        if directory.name == release:
            continue
        if directory.is_symlink() or not directory.is_dir() or directory.name not in old_releases:
            raise ValueError('Unrecognized stale module directory: ' + directory.name)
        stale.append(directory)
    # Preflight every old tree before deleting any. RPM package invariance is
    # insufficient: a retained package may still own a file in an old tree.
    # After removing old RPMs only a small set of generated files may remain.
    def traversal_error(error):
        raise ValueError('Cannot inspect stale module directory: ' + str(error)) from error

    for directory in stale:
        for parent, folders, files in os.walk(directory, followlinks=False, onerror=traversal_error):
            for name in folders:
                if (Path(parent) / name).is_symlink():
                    raise ValueError('Symlink in stale module directory: ' + str(Path(parent) / name))
            for name in files:
                path = Path(parent) / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError('Unexpected file type in stale module directory: ' + str(path))
                try:
                    owner = runner(['rpm', '-qf', '--qf', '%{NAME}\n', '--', str(path)])
                except subprocess.CalledProcessError as error:
                    diagnostic = error.output if isinstance(error.output, str) else ''
                    if error.returncode != 1 or diagnostic.strip() != f'file {path} is not owned by any package':
                        raise ValueError('Cannot establish stale module file ownership: ' + str(path)) from error
                else:
                    if not owner:
                        raise ValueError('Empty ownership probe for stale module file: ' + str(path))
                    raise ValueError('Still installed package owns stale module file: ' + str(path) + ': ' + owner)
                if path.parent != directory or name not in GENERATED_MODULE_FILES:
                    raise ValueError('Unreviewed unowned file in stale module directory: ' + str(path))
    for directory in stale:
        shutil.rmtree(directory)



def snapshot_inventory(path, runner):
    # The reused native parser preserves signing-key pseudo-packages and rejects
    # malformed records. run() bounds captured RPM output to 2 MiB.
    document = {'schema': 1, 'packages': rpm_inventory.inventory(runner)}
    text = json.dumps(document, sort_keys=True) + '\n'
    if len(text.encode()) > 2 * 1024 * 1024:
        raise ValueError('Kernel RPM snapshot exceeds the reviewed size limit')
    with Path(path).open('x') as stream:
        stream.write(text)


def check_inventory_snapshot(path, runner):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Kernel RPM snapshot must be a bounded regular file')
    with path.open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Kernel RPM snapshot exceeds the reviewed size limit')
    document = json.loads(raw)
    if (not isinstance(document, dict) or set(document) != {'schema', 'packages'}
            or type(document['schema']) is not int or document['schema'] != 1
            or not isinstance(document['packages'], dict) or not document['packages']):
        raise ValueError('Invalid kernel RPM snapshot')
    before = document['packages']
    after = {name: [list(value) for value in values]
             for name, values in rpm_inventory.inventory(runner).items()}
    for name in before.keys() | after.keys():
        if name in ZFS_PACKAGES:
            if after.get(name) is not None and before.get(name) != after.get(name):
                raise ValueError('Authorized ZFS transition must remove the package: ' + name)
            continue
        if name not in TRANSACTION_PACKAGES and before.get(name) != after.get(name):
            raise ValueError('Unapproved package mutation during next kernel transaction: ' + name)
    if any(name in after for name in ZFS_PACKAGES):
        raise ValueError('Host ZFS packages remain after authorized cleanup')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument('--snapshot', type=Path)
    operations.add_argument('--check-snapshot', type=Path)
    parser.add_argument('--release')
    parser.add_argument('--root', type=Path, default=Path('/usr/lib/modules'))
    parser.add_argument('--old-release', action='append')
    args = parser.parse_args()
    if args.snapshot or args.check_snapshot:
        if args.release or args.old_release:
            raise ValueError('RPM snapshot operation cannot also prune module directories')
        if args.snapshot:
            snapshot_inventory(args.snapshot, run)
        else:
            check_inventory_snapshot(args.check_snapshot, run)
        return
    release = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.fc[0-9]+\.(?:x86_64|aarch64)')
    if (not args.release or not args.old_release or not release.fullmatch(args.release)
            or any(not release.fullmatch(value) for value in args.old_release)):
        raise ValueError('Kernel module cleanup requires recorded canonical Fedora releases')
    prune_modules(args.root, args.release, set(args.old_release), run)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f'Kernel module cleanup failed: {error}')
