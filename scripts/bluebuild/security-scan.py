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
baseline_spec = importlib.util.spec_from_file_location('approved_baseline_producer',
    Path(__file__).resolve().parents[1] / 'ci/approved-baseline.py')
baseline_module = importlib.util.module_from_spec(baseline_spec)
baseline_spec.loader.exec_module(baseline_module)


def run(args, output=None):
    if output:
        with output.open('w') as stream:
            subprocess.run(args, stdout=stream, check=True, timeout=1800)
    else:
        subprocess.run(args, check=True, timeout=1800)


def candidate_identity(inspected, image, profile, identity, source_revision):
    """Bind resumed bytes to their original source; policy revision stays separate."""
    if not re.fullmatch(r'[0-9a-f]{40}', source_revision):
        raise ValueError('Candidate scan requires an exact image source revision')
    labels = inspected['Labels']
    if (inspected['Digest'] != image.split('@')[1]
            or labels['org.opencontainers.image.revision'] != source_revision
            or labels['org.opencontainers.image.source'] != 'https://github.com/closure-labs/finite'
            or labels['io.finite.profile'] != profile
            or labels['io.finite.build-inputs'] != identity):
        raise ValueError('Registry candidate identity does not match the requested build')


OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
OCI_CONFIG = 'application/vnd.oci.image.config.v1+json'
DOCKER_MANIFEST = 'application/vnd.docker.distribution.manifest.v2+json'
DOCKER_CONFIG = 'application/vnd.docker.container.image.v1+json'
LAYER_PROJECTION = {
    'application/vnd.docker.image.rootfs.diff.tar': 'application/vnd.oci.image.layer.v1.tar',
    'application/vnd.docker.image.rootfs.diff.tar.gzip': 'application/vnd.oci.image.layer.v1.tar+gzip',
    'application/vnd.oci.image.layer.v1.tar': 'application/vnd.oci.image.layer.v1.tar',
    'application/vnd.oci.image.layer.v1.tar+gzip': 'application/vnd.oci.image.layer.v1.tar+gzip',
    'application/vnd.oci.image.layer.v1.tar+zstd': 'application/vnd.oci.image.layer.v1.tar+zstd',
}


def metadata_blob(path):
    """Read bounded immutable metadata without ambiguous keys or symlink paths."""
    if (any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file()
            or not 0 < path.stat().st_size <= policy_module.MANIFEST_LIMIT):
        raise ValueError('Missing, symlinked or oversized image metadata blob')
    raw = path.read_bytes()
    if len(raw) > policy_module.MANIFEST_LIMIT:
        raise ValueError('Image metadata exceeds the read limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate immutable image metadata key')
            result[key] = value
        return result
    document = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(document, dict):
        raise ValueError('Image metadata must be an object')
    return raw, document


def extraction_projection(manifest):
    """Change known media-type metadata only; never serialize config/layer bytes."""
    if (type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 2
            or manifest.get('mediaType') not in policy_module.IMAGE_TYPES or 'manifests' in manifest):
        raise ValueError('Unsupported or mixed immutable image manifest')
    derived = json.loads(json.dumps(manifest))
    derived['mediaType'] = OCI_MANIFEST
    config = derived['config']
    if config.get('mediaType') not in (OCI_CONFIG, DOCKER_CONFIG):
        raise ValueError('Unsupported immutable configuration media type')
    config['mediaType'] = OCI_CONFIG
    layers = derived.get('layers')
    if not isinstance(layers, list) or len(layers) > 1024:
        raise ValueError('Extraction requires a bounded layer list')
    for layer in layers:
        if (not isinstance(layer, dict) or layer.get('mediaType') not in LAYER_PROJECTION
                or 'urls' in layer or not isinstance(layer.get('digest'), str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', layer['digest'])
                or type(layer.get('size')) is not int or not 0 < layer['size'] <= 64 * 1024**3):
            raise ValueError('Unsupported distributable layer type/digest/size')
        layer['mediaType'] = LAYER_PROJECTION[layer['mediaType']]
    # Check that the reversible metadata projection has preserved every field,
    # digest, size, order and annotation except the three defined media types.
    restored = json.loads(json.dumps(derived))
    restored['mediaType'] = manifest['mediaType']
    restored['config']['mediaType'] = manifest['config']['mediaType']
    for old, new in zip(manifest['layers'], restored['layers']):
        new['mediaType'] = old['mediaType']
    if restored != manifest:
        raise ValueError('Extraction projection changed authenticated image content')
    return derived


def prepare_layout(layout, image, evidence):
    """Retain original digest evidence; select a local umoci-compatible pointer."""
    if not policy_module.IMAGE.fullmatch(image):
        raise ValueError('Extraction requires an immutable Finite image')
    parent_digest = image.split('@')[1]
    parent_path = layout / 'blobs/sha256' / parent_digest.removeprefix('sha256:')
    parent_bytes, document = metadata_blob(parent_path)
    parent_raw = parent_bytes.decode('utf-8')
    # Authenticate the parent before interpreting any descriptor as a file path.
    if 'sha256:' + hashlib.sha256(parent_raw.encode()).hexdigest() != parent_digest:
        raise ValueError('Downloaded parent manifest digest mismatch')
    child_raw = None
    platform_descriptor = None
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
        child_bytes, _ = metadata_blob(child_path)
        child_raw = child_bytes.decode('utf-8')
        policy_module.manifest_binding(image, {'parent': parent_raw, 'child': child_raw})
        # Select the unique authenticated amd64 manifest under a known local
        # extraction tag. This changes no blob or remote reference.
        platform_descriptor = {**descriptor, 'annotations': {**descriptor.get('annotations', {}),
                          'org.opencontainers.image.ref.name': 'audit'}}
    else:
        policy_module.manifest_binding(image, {'parent': parent_raw, 'child': None})
    manifest = json.loads(child_raw) if child_raw else document
    descriptor = manifest['config']
    if (descriptor.get('mediaType') not in ('application/vnd.oci.image.config.v1+json',
            'application/vnd.docker.container.image.v1+json')
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', descriptor.get('digest', ''))
            or type(descriptor.get('size')) is not int or not 0 < descriptor['size'] <= policy_module.MANIFEST_LIMIT):
        raise ValueError('Invalid immutable image configuration descriptor')
    config_path = layout / 'blobs/sha256' / descriptor['digest'][7:]
    config_raw, _ = metadata_blob(config_path)
    if len(config_raw) != descriptor['size']:
        raise ValueError('Missing or mismatched immutable configuration blob')
    if 'sha256:' + hashlib.sha256(config_raw).hexdigest() != descriptor['digest']:
        raise ValueError('Image configuration does not match its immutable manifest')
    # umoci requires both OCI outer descriptors and OCI inner manifest media
    # types. Docker v2 bytes remain the authenticated source. The derived
    # manifest is a local extraction adapter, never a signed upstream digest.
    layers = manifest.get('layers', [])
    requires_projection = (manifest.get('mediaType') == DOCKER_MANIFEST or descriptor['mediaType'] == DOCKER_CONFIG
                           or not isinstance(layers, list) or any(not isinstance(layer, dict)
                               or layer.get('mediaType') not in {value for value in LAYER_PROJECTION.values()}
                               or 'urls' in layer
                               for layer in layers))
    projected = extraction_projection(manifest) if requires_projection else manifest
    if projected != manifest:
        raw = (json.dumps(projected, sort_keys=True, separators=(',', ':')) + '\n').encode()
        if len(raw) > policy_module.MANIFEST_LIMIT:
            raise ValueError('Projected extraction manifest exceeds metadata limit')
        extraction_digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        extraction_descriptor = {'mediaType': OCI_MANIFEST, 'digest': extraction_digest, 'size': len(raw),
                                 'annotations': {'org.opencontainers.image.ref.name': 'audit'}}
        trace = {'schema': 1, 'method': 'media-type-only-oci-extraction',
                 'originalImageDigest': parent_digest,
                 'originalPlatformManifestDigest': policy_module.manifest_binding(image, {'parent': parent_raw, 'child': child_raw}),
                 'originalManifestSha256': hashlib.sha256((child_raw or parent_raw).encode()).hexdigest(),
                 'extractionManifest': extraction_descriptor, 'configurationDigest': descriptor['digest'],
                 'configBytesSha256': hashlib.sha256(config_raw).hexdigest(),
                 'configurationBytesChanged': False, 'layerBytesChanged': False,
                 'layers': [{'digest': old['digest'], 'size': old['size'], 'originalMediaType': old['mediaType'],
                             'extractionMediaType': new['mediaType']} for old, new in zip(manifest['layers'], projected['layers'])],
                 'extractionManifestIsAuthenticatedSource': False}
        trace_raw = (json.dumps(trace, indent=2) + '\n').encode()
        if len(trace_raw) > policy_module.MANIFEST_LIMIT:
            raise ValueError('Extraction layout trace exceeds metadata limit')
        derived_path = layout / 'blobs/sha256' / extraction_digest[7:]
        if derived_path.exists() or derived_path.is_symlink():
            existing, _ = metadata_blob(derived_path)
            if existing != raw:
                raise ValueError('Existing extraction blob differs from derived digest')
        else:
            with derived_path.open('xb') as stream:
                stream.write(raw)
        (evidence / 'extraction-manifest.json').write_bytes(raw)
        (evidence / 'extraction-layout.json').write_bytes(trace_raw)
        platform_descriptor = extraction_descriptor
    # No configuration or layer blob is overwritten, including hardlinks to an
    # original builder layout. Only the private local index pointer changes.
    if platform_descriptor is not None:
        index_path = layout / 'index.json'
        if index_path.is_symlink():
            raise ValueError('Symlinked extraction index is forbidden')
        temporary_index = layout / 'index.extraction.json'
        with temporary_index.open('x') as stream:
            json.dump({'schemaVersion': 2, 'manifests': [platform_descriptor]}, stream)
        temporary_index.replace(index_path)
    (evidence / 'image-manifest.json').write_bytes(parent_bytes)
    if child_raw is not None:
        (evidence / 'platform-manifest.json').write_text(child_raw)
    (evidence / 'image-config.json').write_bytes(config_raw)
    return {'parent': parent_raw, 'child': child_raw, 'config': config_raw.decode('utf-8')}


def output_directory(path):
    """Make caller-relative outputs absolute without resolving away symlinks."""
    directory = path.absolute()
    value = str(directory)
    if ('..' in directory.parts or value.startswith('//') or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part.is_symlink() for part in (directory, *directory.parents))):
        raise ValueError('Security output must have a canonical path without symlinks')
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('directory', type=Path)
    parser.add_argument('--profile')
    parser.add_argument('--identity')
    parser.add_argument('--source-revision')
    parser.add_argument('--upstream-receipt', type=Path)
    args = parser.parse_args()
    try:
        directory = output_directory(args.directory)
    except ValueError as error:
        parser.error(str(error))
    directory.mkdir(parents=True, exist_ok=False)
    try:
        if not policy_module.IMAGE.fullmatch(args.image):
            raise ValueError('Security scan requires an immutable Finite image')
        source_revision = args.source_revision or os.environ.get('GITHUB_SHA', '')
        if args.profile and not re.fullmatch(r'[0-9a-f]{40}', source_revision):
            raise ValueError('Candidate scan requires an exact image source revision')
        if args.source_revision and not args.profile:
            raise ValueError('An explicit image source revision requires a candidate profile')
        policy = policy_module.load_policy(policy_module.ROOT / 'automation/security/image-policy.json')
        risk_mode = policy.get('mode') in policy_module.RISK_MODES
        baseline = None
        receipt = None
        if args.profile or risk_mode:
            inspected = json.loads(subprocess.check_output(
                ['skopeo', '--command-timeout', '90s', 'inspect', '--no-tags', '--no-creds', 'docker://' + args.image],
                text=True, timeout=150))
            labels = inspected['Labels']
            if inspected['Digest'] != args.image.split('@')[1]:
                raise ValueError('Registry metadata changed the requested immutable image')
            if args.profile:
                candidate_identity(inspected, args.image, args.profile, args.identity, source_revision)
            if risk_mode:
                receipt = (baseline_module.read(args.upstream_receipt)[0] if args.upstream_receipt
                           else baseline_module.authenticate(inspected))
                baseline = baseline_module.context(inspected, args.image, receipt)
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
            if risk_mode:
                bound = baseline_module.context(json.loads(manifests['config']), args.image, receipt)
                if bound != baseline:
                    raise ValueError('Materialized configuration differs from inspected approved baseline')
                (directory / 'approved-baseline.json').write_text(json.dumps(bound, indent=2) + '\n')
                (directory / 'upstream-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
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
            if risk_mode:
                run(['python3', str(policy_module.ROOT / 'scripts/ci/rpm-file-evidence.py'),
                     '--rootfs', str(rootfs), '--sbom', str(directory / 'sbom.syft.json'),
                     '--image', args.image, '--output', str(directory / 'rpm-file-evidence.json')])
                # Collect positive file/platform evidence while the authenticated
                # rootfs already exists. Current catalog paths select probes;
                # this diagnostic never changes the policy or grants clearance.
                run(['python3', str(policy_module.ROOT / 'scripts/ci/applicability-evidence.py'),
                     '--rootfs', str(rootfs), '--manifest-dir', str(directory), '--image', args.image,
                     '--profile', bound['profile'], '--revision', bound['sourceRevision'],
                     '--identity', bound['buildIdentity'],
                     '--sbom', str(directory / 'sbom.syft.json'),
                     '--output', str(directory / 'applicability-evidence.json')])
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
