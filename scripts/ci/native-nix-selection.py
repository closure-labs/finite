"""Conservative selector for the extra persisted-Nix migration VM."""
import json
import os
from pathlib import Path
import subprocess

from impact import revisions

PREFIXES = ('patches/nix/', 'tests/nix/', 'files/scripts/', 'files/system/usr/libexec/finite/',
            'files/system/usr/lib/systemd/', 'scripts/bluebuild/', 'lib/native-nix-backport')
FILES = {'flake.nix', 'flake.lock', 'lib/image-payload.nix', 'lib/ci-payload.nix',
         'sources/determinate-nix.json', 'recipes/shared/base.yml', 'scripts/ci/native-nix-selection.py'}


def required(paths):
    return paths is None or any(path in FILES or path.startswith(PREFIXES) for path in paths)


if __name__ == '__main__':
    paths = None
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        comparison = revisions(os.environ['GITHUB_EVENT_NAME'], event)
        if comparison is not None:
            paths = subprocess.check_output(['git', 'diff', '--name-only', comparison[0],
                                             os.environ['GITHUB_SHA']], text=True, timeout=30).splitlines()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    print(str(required(paths)).lower())
