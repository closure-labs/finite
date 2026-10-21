#!/usr/bin/env python3
"""Select premerge VM work from boot, installer and test-harness changes."""
import json
import os
import subprocess
from pathlib import Path

from impact import changed_paths

PREFIXES = ('files/system/usr/lib/systemd/', 'files/system/usr/lib/tmpfiles.d/',
            'files/system/usr/lib/udev/', 'files/system/usr/lib/NetworkManager/',
            'files/system/usr/lib/bootc/', 'files/system/usr/lib/dracut/',
            'files/system/usr/lib/kernel/', 'files/system/usr/share/selinux/', 'files/system/usr/libexec/', 'files/system/etc/',
            'files/installer/', 'files/security/', 'scripts/bluebuild/', 'tests/nix/',
            'recipes/', 'files/scripts/', 'modules/nix/', 'lib/image-payload', 'sources/bluefin')
FILES = {'flake.lock', 'sources/determinate-nix.json', 'scripts/ci/nix-resources.py',
         'sources/bluebuild-installer.json', 'sources/installer-security.json',
         '.github/workflows/build.yml', '.github/workflows/image.yml',
         '.github/workflows/qualification.yml', 'scripts/ci/vm-selection.py',
         'scripts/ci/local_vm.py'}


def required(paths):
    return paths is None or any(path in FILES or path.startswith(PREFIXES) for path in paths)


def main():
    event = os.environ['GITHUB_EVENT_NAME']
    selected = False
    if event in ('pull_request', 'merge_group'):
        try:
            selected = required(changed_paths(event, json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())))
        except (KeyError, ValueError, OSError, subprocess.SubprocessError):
            selected = True
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('vm=' + str(selected).lower(), file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('\nPremerge VM validation: ' + ('required for both profiles.' if selected else 'not selected for this change.') + '\n')


if __name__ == '__main__':
    main()
