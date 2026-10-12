#!/usr/bin/env python3
"""Scan an immutable registry image without executing it or receiving signing keys."""
import argparse
import importlib.util
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('security_policy', Path(__file__).with_name('security-policy.py'))
policy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy_module)


def run(args, output=None):
    if output:
        with output.open('w') as stream:
            subprocess.run(args, stdout=stream, check=True, timeout=1800)
    else:
        subprocess.run(args, check=True, timeout=1800)


def prepare_layout(layout, image, evidence):
    """Flatten only the local layout pointer; retain both authenticated blobs."""
    parent_digest = image.split('@')[1]
    parent_path = layout / 'blobs/sha256' / parent_digest.removeprefix('sha256:')
    if parent_path.stat().st_size > policy_module.MANIFEST_LIMIT:
        raise ValueError('Image manifest exceeds the metadata limit')
    parent_raw = parent_path.read_bytes().decode('utf-8')
    document = policy_module.manifest_document(parent_raw)
    # Authenticate the parent before interpreting any descriptor as a file path.
    if 'sha256:' + hashlib.sha256(parent_raw.encode()).hexdigest() != parent_digest:
        raise ValueError('Downloaded parent manifest digest mismatch')
    (evidence / 'image-manifest.json').write_text(parent_raw)
    child_raw = None
    if document.get('mediaType') in policy_module.INDEX_TYPES:
        selected = [entry for entry in document['manifests']
                    if entry.get('platform', {}).get('os') == 'linux' and
                    entry.get('platform', {}).get('architecture') == 'amd64']
        if len(selected) != 1 or selected[0].get('platform', {}).get('variant', '') not in ('', 'v1'):
            raise ValueError('Signed index requires one linux/amd64 platform')
        descriptor = selected[0]
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', descriptor['digest']):
            raise ValueError('Invalid platform descriptor digest')
        child_path = layout / 'blobs/sha256' / descriptor['digest'].removeprefix('sha256:')
        if child_path.stat().st_size > policy_module.MANIFEST_LIMIT:
            raise ValueError('Image manifest exceeds the metadata limit')
        child_raw = child_path.read_bytes().decode('utf-8')
        (evidence / 'platform-manifest.json').write_text(child_raw)
        policy_module.manifest_binding(image, {'parent': parent_raw, 'child': child_raw})
        # Select the unique authenticated amd64 manifest under a known local
        # extraction tag. This changes no blob or remote reference.
        descriptor = {**descriptor, 'annotations': {**descriptor.get('annotations', {}),
                          'org.opencontainers.image.ref.name': 'audit'}}
        (layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [descriptor]}))
    else:
        policy_module.manifest_binding(image, {'parent': parent_raw, 'child': None})
    return {'parent': parent_raw, 'child': child_raw}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('directory', type=Path)
    parser.add_argument('--profile')
    parser.add_argument('--identity')
    args = parser.parse_args()
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=False)
    try:
        if not policy_module.IMAGE.fullmatch(args.image):
            raise ValueError('Security scan requires an immutable Finite image')
        if args.profile:
            inspected = json.loads(subprocess.check_output(
                ['skopeo', '--command-timeout', '90s', 'inspect', '--no-tags', '--no-creds', 'docker://' + args.image],
                text=True, timeout=150))
            labels = inspected['Labels']
            if (inspected['Digest'] != args.image.split('@')[1] or
                    labels['org.opencontainers.image.revision'] != os.environ['GITHUB_SHA'] or
                    labels['org.opencontainers.image.source'] != 'https://github.com/closure-labs/finite' or
                    labels['io.finite.profile'] != args.profile or
                    labels['io.finite.build-inputs'] != args.identity):
                raise ValueError('Registry candidate identity does not match the requested build')
        # Stereoscope's registry materialization exceeded the hosted memory
        # cap before cataloging this OS image. Stream layers to disk serially,
        # preserving the signed manifest, then inventory the local OCI image.
        with tempfile.TemporaryDirectory(prefix='finite-security-image-') as temporary:
            temporary = Path(temporary)
            digest_file = temporary / 'image.digest'
            run(['skopeo', '--command-timeout', '1800s', 'copy', '--all', '--preserve-digests', '--src-no-creds',
                 '--image-parallel-copies', '1', '--retry-times', '3', '--digestfile', str(digest_file),
                 'docker://' + args.image, 'oci:' + str(temporary / 'image') + ':audit'])
            if digest_file.read_text().strip() != args.image.split('@')[1]:
                raise ValueError('Local OCI inventory source changed the requested image digest')
            manifests = prepare_layout(temporary / 'image', args.image, directory)
            # Extract without executing image code. Stereoscope retains a
            # cumulative in-memory tree per layer, exceeding 10 GiB for this OS.
            # Rootless extraction preserves package bytes, not runtime ownership.
            version = subprocess.check_output(['umoci', '--version'], text=True, timeout=30).strip()
            rootfs = temporary / 'bundle/rootfs'
            run(['umoci', 'unpack', '--rootless', '--image', str(temporary / 'image') + ':audit',
                 str(temporary / 'bundle')])
            run(['syft', 'dir:' + str(rootfs), '--base-path', str(rootfs),
                 '--override-default-catalogers', 'image', '-o',
                 'syft-json=' + str(directory / 'sbom.syft.json'),
                 '-o', 'spdx-json=' + str(directory / 'sbom.spdx.json')])
            extraction = {'schema': 1, 'method': 'umoci-rootless', 'toolVersion': version,
                          'signedDigest': args.image.split('@')[1],
                          'scannedManifestDigest': policy_module.manifest_binding(args.image, manifests),
                          'sourcePath': str(rootfs), 'basePath': str(rootfs), 'catalogers': 'image',
                          'sbomSha256': policy_module.file_sha256(directory / 'sbom.syft.json')}
            (directory / 'extraction.json').write_text(json.dumps(extraction, indent=2) + '\n')
            manifests = policy_module.read_manifests(directory)
        policy = policy_module.load_policy(policy_module.ROOT / 'automation/security/image-policy.json')
        sbom = json.loads((directory / 'sbom.syft.json').read_text())
        coverage = policy_module.inventory(sbom, args.image, policy, manifests)
        (directory / 'coverage.json').write_text(json.dumps(coverage, indent=2) + '\n')
        # Explicit update failures are fatal; never silently fall back to an old
        # DB. Policy separately validates both build age and provider freshness.
        run(['grype', 'db', 'update'])
        run(['grype', 'db', 'search', '--distro', coverage['effective'], '--ecosystem', 'rpm',
             '--pkg', policy['coverageProbePackage'], '-o', 'json'], directory / 'database-coverage.json')
        run(['grype', 'sbom:' + str(directory / 'sbom.syft.json'),
             '--distro', coverage['effective'], '--show-suppressed', '-o', 'json'],
            directory / 'vulnerabilities.json')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        (directory / 'security-result.json').write_text(json.dumps(
            {'schema': 1, 'status': 'scanner-error', 'image': args.image, 'error': str(error)}, indent=2) + '\n')
        print('Image security scan failed: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(subprocess.call(['python3', str(Path(__file__).with_name('security-policy.py')),
                                     str(directory), args.image]))


if __name__ == '__main__':
    main()
