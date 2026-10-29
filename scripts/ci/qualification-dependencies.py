#!/usr/bin/env python3
"""Record source dependency boundaries; never authorize reuse or publication."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ('image', 'iso-generation', 'vm-acceptance', 'policy', 'host-controller')
# Exact reviewed paths only. Unknown/new inputs retain every domain. These are
# observations, NOT exclusions from any existing identity or eligibility check.
REVIEWED = {}


def assign(domains, paths):
    for path in paths.split():
        if path in REVIEWED:
            raise ValueError('Duplicate dependency classification: ' + path)
        REVIEWED[path] = tuple(domain for domain in DOMAINS if domain in domains)


assign(('iso-generation', 'vm-acceptance'), '''
files/installer/Containerfile files/installer/install_finite_fstab
files/installer/lorax-zstd.conf sources/bluebuild-installer.json
scripts/bluebuild/iso.sh scripts/bluebuild/prepare-installer.sh
scripts/bluebuild/installer-compression.py
scripts/bluebuild/installer-provenance.py
.github/workflows/iso.yml .github/actions/setup-vm-tools/action.yml
lib/vm-tools.nix scripts/ci/vm_tools.py
''')
assign(('iso-generation', 'vm-acceptance', 'policy'), '''
files/installer/secure-boot.pem
sources/installer-security.json .github/actions/setup-cosign/action.yml
.github/actions/setup-cosign/download/.curlrc
''')
assign(('iso-generation', 'vm-acceptance', 'host-controller'), '''
.github/workflows/qualification.yml scripts/bluebuild/qualify.sh
scripts/bluebuild/qualification-preflight.py
scripts/bluebuild/benchmark-controls.py
''')
assign(('image', 'iso-generation', 'vm-acceptance', 'policy'), '''
scripts/bluebuild/install-cli.sh sources/bluebuild-cli.json
sources/bluebuild-cli.pub cosign.pub
''')
assign(('image', 'iso-generation', 'vm-acceptance', 'host-controller'), '''
scripts/bluebuild/measure.py
''')
assign(('image',), '''
scripts/bluebuild/build.sh scripts/bluebuild/stage.sh
''')
assign(('image', 'policy'), '''
scripts/bluebuild/inspect-built.sh scripts/bluebuild/verify-image.sh
''')
assign(('image', 'vm-acceptance'), '''
files/system/usr/libexec/finite/check-initramfs
files/system/usr/libexec/finite/desktop-integration
files/system/usr/libexec/finite/fix-home-selinux-contexts
files/system/usr/libexec/finite/home-first-login
files/system/usr/libexec/finite/home-init
files/system/usr/libexec/finite/install-determinate-nix-selinux-policy
files/system/usr/libexec/finite/password-manager-setup
files/system/usr/libexec/finite/provision-determinate-nix
files/system/usr/libexec/finite/require-determinate-nix-version
files/system/usr/libexec/finite/run-firstboot-rpm-ostree
files/system/usr/libexec/finite/wifi-ac-power
''')
assign(('vm-acceptance',), '''
.github/workflows/vm-acceptance.yml scripts/bluebuild/vm-acceptance.sh
scripts/bluebuild/check-vm-desktop.py scripts/bluebuild/check-vm-encryption.sh
scripts/bluebuild/check-vm-gdm-labels.sh scripts/bluebuild/check-vm-mok.sh
scripts/bluebuild/check-vm-security.sh scripts/bluebuild/check-vm-user-labels.sh
scripts/bluebuild/prepare-vm-firmware.sh scripts/bluebuild/prepare-vm-iso.sh
scripts/bluebuild/prepare-vm-predecessor-home.sh
scripts/bluebuild/prepare-vm-predecessor-policy.sh scripts/bluebuild/unlock-vm.py
scripts/bluebuild/vm-upgrade.py scripts/bluebuild/wait-nix.sh
scripts/bluebuild/guest-timings.py scripts/ci/vm-host.py
''')
assign(('vm-acceptance', 'host-controller'), '''
scripts/bluebuild/qualification-context.py scripts/bluebuild/desktop-qualification.py
scripts/bluebuild/collect-qualification.py scripts/bluebuild/local-vm.sh
scripts/bluebuild/vm-diagnostics.sh scripts/bluebuild/redact-vm-logs.py
''')
assign(('policy', 'host-controller'), '''
scripts/bluebuild/publication-current.py scripts/bluebuild/publication.py
scripts/bluebuild/reuse-qualification.py scripts/bluebuild/reuse-predecessor-iso.py
scripts/bluebuild/release-evidence.py scripts/bluebuild/sign-release.sh
scripts/bluebuild/audit-published.sh scripts/bluebuild/security-policy.py
scripts/bluebuild/security-scan.py scripts/bluebuild/security-run.sh
scripts/bluebuild/prune-qualified-isos.py automation/security/image-policy.json
 automation/security/decision-proposal.schema.json
''')
# The report intentionally does not claim that these source projections close
# the runtime dependency graph. A future eligibility design must bind these too.
RUNTIME_REQUIREMENTS = (
    'verified immutable OS image digest, profile, source revision and build identity',
    'actual BlueBuild executable and pinned installer image identity',
    'actual Docker engine, host kernel, tool executables and firmware identities',
    'generate-iso arguments: run-driver=docker, variant=kinoite, output/name/channel',
    'validated compression and validation-only mode; diagnostic wrappers when enabled',
    'generated certificate DER bytes, installer hook and effective Containerfile',
    'installation tag, volume ID and original installation metadata (not reproducible ISO bytes)',
    'registry content/signature binding before and after generation',
)
# Keep the existing qualification collector untouched. Inventory its whole
# directory scope recursively, then supplement known transitive generator inputs.
LEGACY_ADDITIONAL = frozenset(('scripts/ci/nix-resources.py', 'scripts/ci/bluefin-upstream.py',
    'scripts/ci/ci-options.py', 'scripts/ci/foundation_timings.py'))
DIRECTORIES = ('scripts/bluebuild', 'files/installer', 'files/system/usr/libexec/finite',
               '.github/actions/setup-cosign', '.github/actions/setup-vm-tools')
SUPPLEMENTAL = frozenset(('sources/bluebuild-cli.pub', 'flake.lock', 'lib/ci-tools.nix',
    'lib/mk-pkgs.nix', 'lib/project-policy.nix', 'scripts/ci/qualification-dependencies.py',
    'scripts/ci/image_identity.py', 'scripts/ci/impact.py',
    'automation/security/image-policy.json', 'automation/security/decision-proposal.schema.json'))


def load_qualification(root):
    path = root / 'scripts/bluebuild/qualification-context.py'
    spec = importlib.util.spec_from_file_location('dependency_qualification', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def entry(root, relative):
    path = root / relative
    # Internal file symlinks are represented by both target text and bytes.
    # External/dangling links or symlinked parents cannot be safe observations.
    if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
        raise ValueError('Symlinked input parent: ' + relative)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError('Input must resolve to a file within the checkout: ' + relative)
    mode = path.lstat().st_mode
    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
        raise ValueError('Unsupported input type: ' + relative)
    return {'sha256': hashlib.sha256(resolved.read_bytes()).hexdigest(),
            'executable': bool(resolved.stat().st_mode & 0o111),
            'symlink': os.readlink(path) if path.is_symlink() else None}


def report(root=ROOT):
    root = root.resolve(strict=True)
    qualification = load_qualification(root)
    paths = set(LEGACY_ADDITIONAL | SUPPLEMENTAL | set(REVIEWED))
    for directory in DIRECTORIES:
        for path in (root / directory).rglob('*'):
            if path.is_file() or path.is_symlink():
                relative = path.relative_to(root).as_posix()
                if path.suffix not in ('.pyc', '.pyo'):
                    paths.add(relative)
    source_entries = {path: entry(root, path) for path in sorted(paths)}
    legacy = qualification.source_inputs(root)
    if not set(legacy) <= source_entries.keys():
        raise ValueError('Legacy qualification scope expanded; update source inventory')
    entries = {}
    for path in sorted(paths):
        entries[path] = {**source_entries[path], 'domains': list(REVIEWED.get(path, DOMAINS)),
                         'reviewed': path in REVIEWED, 'inLegacyQualificationInputs': path in legacy}
    projections = {domain: {path: {key: value[key] for key in ('sha256', 'executable', 'symlink')}
                            for path, value in entries.items() if domain in value['domains']}
                   for domain in DOMAINS}
    return {'schema': 1, 'kind': 'finite-qualification-source-boundaries',
            'status': 'observation-only', 'authorizesReuse': False, 'authorizesPublication': False,
            'scope': 'qualification-related source inventory, not a replacement image identity',
            'legacyQualificationInputsSha256': digest(legacy),
            'sourceProjectionSha256': {domain: digest(value) for domain, value in projections.items()},
            'unresolvedRuntimeRequirements': list(RUNTIME_REQUIREMENTS), 'inputs': entries}


def write_report(path, value):
    path = path.absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Report destination has symlinked parents')
    payload = canonical(value) + b'\n'
    if len(payload) > 1024 * 1024:
        raise ValueError('Oversized dependency report')
    # Do not overwrite previous evidence or expose a partial final JSON.
    with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.dependency-report-') as stream:
        stream.write(payload)
        stream.flush()
        os.link(stream.name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    write_report(args.output, report())


if __name__ == '__main__':
    main()
