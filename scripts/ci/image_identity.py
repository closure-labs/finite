#!/usr/bin/env python3
"""Versioned identities for image inputs, independent of documentation revisions."""
import hashlib
import json
from pathlib import Path
import subprocess


# This is the hashed contract version, not the evidence transport version.
# A contract change requires new image bytes/evidence; never relabel old images.
IMAGE_INPUT_SCHEMA = 4

# These reviewed inputs run after an immutable OS image has been assembled.
# qualification-context.py binds the VM/ISO inputs separately. Keep this list
# explicit: a newly added BlueBuild helper remains an image input until reviewed.
QUALIFICATION_ONLY = {
    'files/installer/lorax-zstd.conf',
    'scripts/bluebuild/installer-compression.py', 'scripts/bluebuild/installer-provenance.py',
    'scripts/bluebuild/benchmark-controls.py',
    "scripts/bluebuild/check-vm-gdm-labels.sh", "scripts/bluebuild/local-vm.sh",
    'automation/security/image-policy.json', 'automation/security/decision-proposal.schema.json', '.github/workflows/publication.yml',
    '.github/workflows/iso.yml', '.github/workflows/vm-acceptance.yml',
    '.github/workflows/qualification.yml', 'sources/bluebuild-installer.json',
    'sources/installer-security.json',
    'files/installer/Containerfile', 'files/installer/install_finite_fstab',
    'files/installer/secure-boot.pem',
    'scripts/bluebuild/security-policy.py', 'scripts/bluebuild/security-scan.py',
    'scripts/bluebuild/security-run.sh', 'scripts/bluebuild/audit-published.sh',
    'scripts/bluebuild/check-vm-desktop.py', 'scripts/bluebuild/check-vm-encryption.sh',
    'scripts/bluebuild/check-vm-mok.sh', 'scripts/bluebuild/check-vm-security.sh',
    'scripts/bluebuild/check-vm-user-labels.sh', 'scripts/bluebuild/desktop-qualification.py',
    'scripts/bluebuild/iso.sh', 'scripts/bluebuild/prepare-installer.sh',
    'scripts/bluebuild/prepare-vm-firmware.sh', 'scripts/bluebuild/prepare-vm-iso.sh',
    'scripts/bluebuild/prepare-vm-predecessor-home.sh',
    'scripts/bluebuild/prepare-vm-predecessor-policy.sh',
    'scripts/bluebuild/prune-qualified-isos.py', 'scripts/bluebuild/qualification-context.py',
    'scripts/bluebuild/publication-current.py',
    'scripts/bluebuild/qualification-preflight.py', 'scripts/bluebuild/qualify.sh',
    'scripts/bluebuild/redact-vm-logs.py', 'scripts/bluebuild/release-evidence.py',
    'scripts/bluebuild/reuse-predecessor-iso.py', 'scripts/bluebuild/reuse-qualification.py',
    'scripts/bluebuild/sign-release.sh', 'scripts/bluebuild/unlock-vm.py',
    'scripts/bluebuild/vm-acceptance.sh', 'scripts/bluebuild/vm-diagnostics.sh',
    'scripts/bluebuild/vm-upgrade.py', 'scripts/bluebuild/wait-nix.sh',
}


def identity(profile, root, payload=None):
    if profile not in ('finite', 'finite-dev'):
        raise ValueError('Unsupported image profile')
    root = Path(root)
    if payload is None:
        payload = subprocess.check_output(
            ['nix', 'eval', '--impure', '--accept-flake-config', '--no-update-lock-file',
             '--no-write-lock-file', '--file', 'lib/ci-payload.nix', '--raw', 'payload.drvPath'],
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
    for path in sorted(set(paths)):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        # Python imports generate host/checkout-specific bytecode for these
        # build helpers. Exclude only their caches, never similarly named files
        # under shipped payload inputs such as files/system or files/scripts.
        if (relative_path.parts[:2] == ('scripts', 'bluebuild') and
                path.suffix in ('.pyc', '.pyo')):
            continue
        # Installer files build a separate Lorax ISO container, never the OS
        # image: recipes copy files/system and the staged Nix payload instead.
        # Current security policy remains bound by policySha256 before signing.
        if relative in QUALIFICATION_ONLY:
            continue
        content = str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        entries.append([relative, bool(path.lstat().st_mode & 0o111), hashlib.sha256(content).hexdigest()])
    # Schema 4 binds the two upstream-kernel variants; v1 remains the transport
    # format accepted by existing evidence readers. Old hashes are not migrated:
    # candidates built under the former contract must be rebuilt and qualified.
    value = {'schema': IMAGE_INPUT_SCHEMA, 'profile': profile, 'payload': payload, 'files': entries}
    return 'v1:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
