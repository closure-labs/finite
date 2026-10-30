#!/usr/bin/env python3
"""Select premerge VM work from boot, installer and test-harness changes."""
import json
import os
import re
import subprocess
from pathlib import Path

from impact import changed_paths, revisions

PREFIXES = ('files/system/usr/lib/systemd/', 'files/system/usr/lib/tmpfiles.d/',
            'files/system/usr/lib/udev/', 'files/system/usr/lib/NetworkManager/',
            'files/system/usr/lib/bootc/', 'files/system/usr/lib/dracut/',
            'files/system/usr/lib/kernel/', 'files/system/usr/share/selinux/', 'files/system/usr/libexec/', 'files/system/etc/',
            'files/installer/', 'files/security/', 'scripts/bluebuild/', 'tests/nix/',
            'recipes/', 'files/scripts/', 'modules/nix/', 'lib/image-payload', 'sources/bluefin')
FILES = {'.github/actions/setup-cosign/action.yml', '.github/actions/setup-cosign/download/.curlrc', 'flake.lock', 'sources/determinate-nix.json', 'scripts/ci/nix-resources.py',
         'sources/bluebuild-installer.json', 'sources/installer-security.json',
         '.github/workflows/build.yml', '.github/workflows/image.yml',
         '.github/workflows/qualification.yml', 'scripts/ci/vm-selection.py',
         'lib/vm-tools.nix', 'scripts/ci/vm_tools.py', 'scripts/ci/vm-host.py', '.github/actions/setup-vm-tools/action.yml',
         'scripts/ci/local_vm.py'}


# Exact reviewed host-only entry points, not a blanket qualification exemption.
# Keep source/security contracts and publication/reuse identities unchanged.
# New helpers and mixed installer/guest changes retain the conservative route.
HOST_CONTROLLER_ONLY = frozenset({
    'scripts/bluebuild/prune-qualified-isos.py',
    'scripts/bluebuild/audit-published.sh',
    'scripts/bluebuild/publication-current.py',
})


def required(paths, *, lock_metadata_only=False):
    return paths is None or any((path in FILES or path.startswith(PREFIXES))
                               and path not in HOST_CONTROLLER_ONLY
                               and not (path == 'flake.lock' and lock_metadata_only) for path in paths)


def resolved_lock(value):
    # Ignore only the requested reference metadata. Resolved revisions, hashes,
    # graph edges, follows, node sets and all other fields remain significant.
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 7
            or not isinstance(value.get('nodes'), dict) or not value['nodes']
            or not isinstance(value.get('root'), str) or value['root'] not in value['nodes']):
        raise ValueError('Unsupported lock structure')
    nodes = {}
    for name, node in value['nodes'].items():
        if not isinstance(node, dict) or ('original' in node and not isinstance(node['original'], dict)):
            raise ValueError('Invalid lock node')
        if name != value['root'] and not isinstance(node.get('locked'), dict):
            raise ValueError('Unresolved lock node')
        nodes[name] = {key: item for key, item in node.items() if key != 'original'}
    return {**value, 'nodes': nodes}


def lock_metadata_only(event_name, event, head):
    comparison = revisions(event_name, event)
    if comparison is None:
        raise ValueError('Missing checkout comparison')
    if not re.fullmatch(r'[0-9a-f]{40,64}', head):
        raise ValueError('Invalid checkout revision')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate lock key')
            value[key] = item
        return value
    def read(revision):
        data = subprocess.check_output(['git', 'show', revision + ':flake.lock'], timeout=30)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('Oversized lock file')
        return resolved_lock(json.loads(data, object_pairs_hook=unique))
    return read(comparison[0]) == read(head)


def main():
    event = os.environ['GITHUB_EVENT_NAME']
    selected = False
    metadata_only = False
    if event in ('pull_request', 'merge_group'):
        try:
            metadata = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            paths = changed_paths(event, metadata)
            metadata_only = ('flake.lock' in (paths or [])
                             and lock_metadata_only(event, metadata, os.environ['GITHUB_SHA']))
            selected = required(paths, lock_metadata_only=metadata_only)
        except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
            print(f'::warning::Premerge comparison unavailable; requiring both VM profiles ({type(error).__name__}).')
            selected = True
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('vm=' + str(selected).lower(), file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('\nPremerge VM validation: ' + ('required for both profiles.' if selected else 'not selected for this change.') + '\n')
        if metadata_only:
            summary.write('\nLock comparison: only original reference metadata changed; resolved inputs and graph match.\n')


if __name__ == '__main__':
    main()
