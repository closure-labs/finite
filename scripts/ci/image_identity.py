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
             root / 'sources/cosign-runtime.json', root / 'scripts/ci/cosign-runtime.py',
             root / 'scripts/ci/image_identity.py']
    for directory in ('recipes/shared', 'files/scripts', 'files/security', 'files/system', 'files/dnf',
                      'files/installer', 'scripts/bluebuild'):
        paths.extend(path for path in (root / directory).rglob('*') if path.is_file() or path.is_symlink())
    paths.extend((root / 'sources').glob('bluebuild-*.json'))
    paths.extend((root / 'sources').glob('bluebuild-*.pub'))
    paths.extend((root / 'sources').glob('bluefin*'))
    paths.extend((root / 'automation/security').glob('*.json'))
    paths.extend(root / '.github/workflows' / name for name in ('image.yml', 'publication.yml', 'iso.yml', 'vm-acceptance.yml'))
    paths.extend((root / '.github/workflows').glob('*qualification*.yml'))
    entries = []
    qualification_only = {
        'automation/security/image-policy.json', '.github/workflows/publication.yml',
        'scripts/bluebuild/security-policy.py', 'scripts/bluebuild/security-scan.py',
        'scripts/bluebuild/security-run.sh', 'scripts/bluebuild/audit-published.sh',
    }
    for path in sorted(set(paths)):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        # Python imports generate host/checkout-specific bytecode for these
        # build helpers. Exclude only their caches, never similarly named files
        # under shipped payload inputs such as files/system or files/scripts.
        if (relative_path.parts[:2] == ('scripts', 'bluebuild') and
                path.suffix in ('.pyc', '.pyo')):
            continue
        # The current security policy is bound separately by policySha256 and
        # re-evaluated before signing. Changing it does not change image bytes.
        if relative in qualification_only:
            continue
        if not profile.endswith('-next') and relative in ('recipes/shared/next.yml', 'files/scripts/kernel-next.sh'):
            continue
        if profile.endswith('-next') and relative in (
                'files/scripts/kernel-generic-security.py', 'files/security/kernel-generic.json',
                'files/security/fedora-44.pub'):
            continue
        content = str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        entries.append([relative, bool(path.lstat().st_mode & 0o111), hashlib.sha256(content).hexdigest()])
    # Schema 2 changes the hashed input contract; v1 remains the transport
    # format accepted by existing evidence readers. Old hashes are not migrated:
    # candidates built under the former contract must be rebuilt and qualified.
    value = {'schema': 2, 'profile': profile, 'payload': payload, 'files': entries}
    return 'v1:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
