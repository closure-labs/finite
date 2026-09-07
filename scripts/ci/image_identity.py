#!/usr/bin/env python3
"""Versioned identities for image inputs, independent of documentation revisions."""
import hashlib
import json
from pathlib import Path
import subprocess


def identity(profile, root, payload=None):
    root = Path(root)
    if payload is None:
        output = 'image-payload-next' if profile.endswith('-next') else 'image-payload'
        payload = subprocess.check_output(
            ['nix', 'eval', '--accept-flake-config', '--no-update-lock-file',
             '--no-write-lock-file', '--raw', '.#' + output + '.drvPath'],
            cwd=root, text=True, timeout=300).strip()
    if not payload.startswith('/nix/store/') or not payload.endswith('.drv'):
        raise ValueError('Invalid Nix payload identity')
    paths = [root / 'recipes' / (profile + '.yml'), root / 'cosign.pub',
             root / 'scripts/ci/image_identity.py']
    for directory in ('recipes/shared', 'files/scripts', 'files/system', 'files/dnf',
                      'files/installer', 'scripts/bluebuild'):
        paths.extend(path for path in (root / directory).rglob('*') if path.is_file() or path.is_symlink())
    paths.extend((root / 'sources').glob('bluebuild-*.json'))
    paths.extend((root / 'sources').glob('bluebuild-*.pub'))
    paths.extend(root / '.github/workflows' / name for name in ('image.yml', 'publication.yml', 'iso.yml', 'vm-acceptance.yml'))
    paths.extend((root / '.github/workflows').glob('*qualification*.yml'))
    entries = []
    for path in sorted(set(paths)):
        relative = path.relative_to(root).as_posix()
        if not profile.endswith('-next') and relative in ('recipes/shared/next.yml', 'files/scripts/kernel-next.sh'):
            continue
        content = str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        entries.append([relative, bool(path.lstat().st_mode & 0o111), hashlib.sha256(content).hexdigest()])
    value = {'schema': 1, 'profile': profile, 'payload': payload, 'files': entries}
    return 'v1:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
