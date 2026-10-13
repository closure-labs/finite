#!/usr/bin/env python3
"""Hosted native vulnerability evidence for an unpublished local OCI candidate.

This diagnostic does not execute image code, authenticate a release signature,
or grant publication eligibility. The production vulnerability policy is reused.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('candidate_security_scan', ROOT / 'scripts/bluebuild/security-scan.py')
scan_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_module)
policy_module = scan_module.policy_module
LIMIT = policy_module.MANIFEST_LIMIT
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
PROFILES = {'bluefin-generic', 'bluefin-dx-generic', 'bluefin-next', 'bluefin-dx-next'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'}
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.oci.image.layer.v1.tar+zstd', 'application/vnd.docker.image.rootfs.diff.tar',
               'application/vnd.docker.image.rootfs.diff.tar.gzip'}


def absolute_path(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Parent traversal is forbidden in evidence paths')
    return path


def no_symlinks(path, missing=False):
    """Reject symlinks in every existing input/output path component."""
    path = absolute_path(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if missing:
                continue
            raise ValueError('Evidence input is missing: ' + str(current)) from None
        if stat.S_ISLNK(mode):
            raise ValueError('Symlinked evidence path is forbidden: ' + str(current))
    return path


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key in OCI metadata: ' + key)
        result[key] = value
    return result


def raw_document(path):
    path = no_symlinks(path)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > LIMIT:
        raise ValueError('OCI metadata must be a bounded regular file')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT or len(raw) != metadata.st_size:
        raise ValueError('OCI metadata exceeds limit or changed while reading')
    document = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_keys)
    if not isinstance(document, dict):
        raise ValueError('OCI metadata must be a JSON object')
    return raw, document


def descriptor_blob(layout, descriptor, media_types, metadata=False):
    if (not isinstance(descriptor, dict) or not isinstance(descriptor.get('digest'), str) or
            not DIGEST.fullmatch(descriptor['digest']) or type(descriptor.get('size')) is not int or
            descriptor['size'] <= 0 or descriptor.get('mediaType') not in media_types or
            descriptor.get('urls')):
        raise ValueError('Invalid local OCI descriptor')
    path = no_symlinks(layout / 'blobs/sha256' / descriptor['digest'][7:])
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor['size']:
        raise ValueError('Local OCI blob size/type does not match descriptor')
    if metadata:
        raw, document = raw_document(path)
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != descriptor['digest']:
            raise ValueError('Local OCI metadata blob digest mismatch')
        return path, raw, document
    # Authenticate every layer before extraction or cataloging. The production
    # helper streams 1 MiB chunks, so this adds disk I/O without loading layers
    # into memory or relying on extractor-specific hash-validation behavior.
    if 'sha256:' + policy_module.file_sha256(path) != descriptor['digest']:
        raise ValueError('Local OCI layer blob digest mismatch')
    return path, None, None


def validate_candidate(layout, profile, identity, revision):
    layout = no_symlinks(layout)
    if not layout.is_dir():
        raise ValueError('Local OCI layout must be a directory')
    if profile not in PROFILES or not re.fullmatch(r'v1:[0-9a-f]{64}', identity or ''):
        raise ValueError('Invalid expected candidate profile or build-input identity')
    if not re.fullmatch(r'[0-9a-f]{40}', revision or ''):
        raise ValueError('Candidate validation requires an exact GitHub source revision')
    _, layout_document = raw_document(layout / 'oci-layout')
    if layout_document != {'imageLayoutVersion': '1.0.0'}:
        raise ValueError('Unsupported OCI layout version')
    index_raw, index = raw_document(layout / 'index.json')
    if type(index.get('schemaVersion')) is not int or index['schemaVersion'] != 2 or not isinstance(index.get('manifests'), list):
        raise ValueError('Invalid local OCI index')
    descriptors = index['manifests']
    selected = [entry for entry in descriptors if isinstance(entry, dict) and
                isinstance(entry.get('annotations'), dict) and
                entry['annotations'].get('org.opencontainers.image.ref.name') == 'audit']
    if len(descriptors) != 1 or len(selected) != 1:
        raise ValueError('Local OCI layout requires one unambiguous audit descriptor')
    parent = selected[0]
    parent_path, parent_raw, document = descriptor_blob(
        layout, parent, policy_module.IMAGE_TYPES | policy_module.INDEX_TYPES, metadata=True)
    if type(document.get('schemaVersion')) is not int or document['schemaVersion'] != 2 or document.get('mediaType') != parent['mediaType']:
        raise ValueError('Parent manifest media type/schema does not match descriptor')
    image = 'ghcr.io/closure-labs/finite@' + parent['digest']
    paths = [parent_path]
    child_raw = None
    if parent['mediaType'] in policy_module.INDEX_TYPES:
        if not isinstance(document.get('manifests'), list):
            raise ValueError('Candidate platform index lacks manifest descriptors')
        selected = [entry for entry in document['manifests'] if isinstance(entry, dict) and
                    isinstance(entry.get('platform'), dict) and entry['platform'].get('os') == 'linux' and
                    entry['platform'].get('architecture') == 'amd64']
        if len(selected) != 1 or selected[0]['platform'].get('variant', '') not in ('', 'v1'):
            raise ValueError('Candidate index requires one supported linux/amd64 manifest')
        child_path, child_raw, document = descriptor_blob(layout, selected[0], policy_module.IMAGE_TYPES, metadata=True)
        paths.append(child_path)
    manifests = {'parent': parent_raw.decode('utf-8'), 'child': child_raw.decode('utf-8') if child_raw else None}
    platform_digest = policy_module.manifest_binding(image, manifests)
    config_descriptor = document.get('config')
    config_path, config_raw, config = descriptor_blob(layout, config_descriptor, CONFIG_TYPES, metadata=True)
    paths.append(config_path)
    if not isinstance(config.get('config'), dict) or not isinstance(config.get('rootfs'), dict):
        raise ValueError('Candidate configuration lacks native config/rootfs objects')
    labels = config['config'].get('Labels', {})
    expected = {'org.opencontainers.image.revision': revision,
                'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                'io.finite.profile': profile, 'io.finite.build-inputs': identity}
    if (config.get('os') != 'linux' or config.get('architecture') != 'amd64' or
            not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items())):
        raise ValueError('Local candidate configuration platform/source/revision/profile/identity mismatch')
    layers = document.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 1024:
        raise ValueError('Local image requires a bounded nonempty layer list')
    diff_ids = config.get('rootfs', {}).get('diff_ids')
    if (config.get('rootfs', {}).get('type') != 'layers' or not isinstance(diff_ids, list) or
            len(diff_ids) != len(layers) or any(not isinstance(value, str) or not DIGEST.fullmatch(value) for value in diff_ids)):
        raise ValueError('Configuration does not bind the expected layer inventory')
    for descriptor in layers:
        path, _, _ = descriptor_blob(layout, descriptor, LAYER_TYPES)
        paths.append(path)
    return {'image': image, 'descriptor': parent, 'paths': paths, 'indexRaw': index_raw,
            'manifestRaw': parent_raw, 'configRaw': config_raw, 'platformDigest': platform_digest,
            'configurationDigest': config_descriptor['digest'], 'layers': len(layers)}


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2) + '\n')


def approved_baseline_context(path, candidate, profile, identity, revision):
    """Bind an externally authenticated receipt; this helper cannot create trust."""
    raw, document = raw_document(path)
    context = policy_module.baseline_context(document, candidate['image'])
    if (context['profile'] != profile or context['sourceRevision'] != revision or
            context['buildIdentity'] != identity or context['trustPolicySha256'] !=
            policy_module.file_sha256(ROOT / 'sources/bluefin-trust.json')):
        raise ValueError('Approved baseline receipt does not match candidate inputs/trust policy')
    labels = json.loads(candidate['configRaw'])['config']['Labels']
    repository, digest = context['baseImage'].split('@')
    if (labels.get('org.opencontainers.image.base.digest') != digest or
            labels.get('org.opencontainers.image.base.name') != repository + ':stable@' + digest):
        raise ValueError('Approved baseline receipt differs from candidate base labels')
    return raw, context


def scan_candidate(layout, directory, candidate, approved_baseline=None):
    # Hard links retain exact blob bytes without copying gigabytes or mutating
    # the build layout. The temporary directory is on the input filesystem.
    with tempfile.TemporaryDirectory(prefix='finite-candidate-scan-', dir=layout.parent) as temporary:
        temporary = Path(temporary)
        pointer = temporary / 'image'
        blobs = pointer / 'blobs/sha256'
        blobs.mkdir(parents=True)
        write_json(pointer / 'oci-layout', {'imageLayoutVersion': '1.0.0'})
        write_json(pointer / 'index.json', {'schemaVersion': 2, 'manifests': [candidate['descriptor']]})
        for source in set(candidate['paths']):
            os.link(source, blobs / source.name)
        manifests = scan_module.prepare_layout(pointer, candidate['image'], directory)
        version = subprocess.check_output(['umoci', '--version'], text=True, timeout=30).strip()
        rootfs = temporary / 'bundle/rootfs'
        scan_module.run(['umoci', 'unpack', '--rootless', '--image', str(pointer) + ':audit', str(temporary / 'bundle')])
        scan_module.run(['syft', 'dir:' + str(rootfs), '--base-path', str(rootfs), '--override-default-catalogers', 'image',
                         '-o', 'syft-json=' + str(directory / 'sbom.syft.json'), '-o', 'spdx-json=' + str(directory / 'sbom.spdx.json')])
        if approved_baseline is not None:
            scan_module.run(['python3', str(ROOT / 'scripts/ci/rpm-file-evidence.py'),
                             '--rootfs', str(rootfs), '--sbom', str(directory / 'sbom.syft.json'),
                             '--image', candidate['image'], '--output', str(directory / 'rpm-file-evidence.json')])
            scan_module.run(['python3', str(ROOT / 'scripts/ci/applicability-evidence.py'),
                             '--rootfs', str(rootfs), '--manifest-dir', str(directory),
                             '--image', candidate['image'], '--profile', approved_baseline['profile'],
                             '--revision', approved_baseline['sourceRevision'],
                             '--identity', approved_baseline['buildIdentity'],
                             '--sbom', str(directory / 'sbom.syft.json'),
                             '--output', str(directory / 'applicability-evidence.json')])
        # signedDigest is a legacy policy field binding the input digest. This
        # candidate is unsigned/unpublished; explicit provenance forbids release.
        write_json(directory / 'extraction.json', {
            'schema': 1, 'method': 'umoci-rootless', 'toolVersion': version,
            'signedDigest': candidate['image'].split('@')[1],
            'scannedManifestDigest': policy_module.manifest_binding(candidate['image'], manifests),
            'sourcePath': str(rootfs), 'basePath': str(rootfs), 'catalogers': 'image',
            'sbomSha256': policy_module.file_sha256(directory / 'sbom.syft.json'),
            'sourceType': 'locally-built-unpublished', 'signatureVerified': False, 'releaseEligible': False})
        manifests = policy_module.read_manifests(directory)
    policy_path = ROOT / 'automation/security/image-policy.json'
    policy = policy_module.load_policy(policy_path)
    sbom = json.loads((directory / 'sbom.syft.json').read_text())
    coverage = policy_module.inventory(sbom, candidate['image'], policy, manifests)
    write_json(directory / 'coverage.json', coverage)
    scan_module.run(['grype', 'db', 'update'])
    scan_module.run(['grype', 'db', 'search', '--distro', coverage['effective'], '--ecosystem', 'rpm',
                     '--pkg', policy['coverageProbePackage'], '-o', 'json'], directory / 'database-coverage.json')
    scan_module.run(['grype', 'sbom:' + str(directory / 'sbom.syft.json'), '--distro', coverage['effective'],
                     '--show-suppressed', '-o', 'json'], directory / 'vulnerabilities.json')
    result = policy_module.evaluate(sbom, json.loads((directory / 'vulnerabilities.json').read_text()),
                                    candidate['image'], policy,
                                    database_coverage=json.loads((directory / 'database-coverage.json').read_text()),
                                    manifests=manifests, approved_baseline=approved_baseline)
    result['policySha256'] = policy_module.file_sha256(policy_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--approved-baseline', type=Path,
                        help='Caller-authenticated baseline receipt; required by upstream risk policy')
    args = parser.parse_args(argv)
    # This boundary precedes any evidence-directory creation or scanner launch.
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        print('Local candidate scanning requires the hosted Finite validation runner', file=sys.stderr)
        return 2
    image = 'local-oci-unvalidated'
    created = False
    try:
        layout = no_symlinks(args.layout)
        directory = no_symlinks(args.directory, missing=True)
        if directory == layout or layout in directory.parents:
            raise ValueError('Evidence output must be outside the input OCI layout')
        directory.mkdir(parents=True, exist_ok=False)
        created = True
        policy = policy_module.load_policy(ROOT / 'automation/security/image-policy.json')
        risk_mode = policy.get('mode') == 'upstream-maintained-risk'
        if risk_mode and args.approved_baseline is None:
            raise ValueError('Upstream risk policy requires caller-authenticated approved baseline evidence')
        candidate = validate_candidate(layout, args.profile, args.identity, os.environ.get('GITHUB_SHA'))
        image = candidate['image']
        context, context_hash = None, None
        if args.approved_baseline is not None:
            context_raw, context = approved_baseline_context(
                args.approved_baseline, candidate, args.profile, args.identity, os.environ['GITHUB_SHA'])
            context_hash = hashlib.sha256(context_raw).hexdigest()
            (directory / 'approved-baseline.json').write_bytes(context_raw)
        (directory / 'local-index.json').write_bytes(candidate['indexRaw'])
        (directory / 'image-config.json').write_bytes(candidate['configRaw'])
        write_json(directory / 'source-provenance.json', {
            'schema': 1, 'sourceType': 'locally-built-unpublished', 'signatureVerified': False,
            'releaseEligible': False, 'image': image, 'immutableManifestDigest': image.split('@')[1],
            'scannedManifestDigest': candidate['platformDigest'], 'configurationDigest': candidate['configurationDigest'],
            'revision': os.environ['GITHUB_SHA'], 'repository': 'closure-labs/finite',
            'profile': args.profile, 'identity': args.identity, 'layers': candidate['layers'],
            'layerDigestsVerified': True,
            'approvedBaselineEvidenceSha256': context_hash,
            'runId': os.environ.get('GITHUB_RUN_ID'), 'runAttempt': os.environ.get('GITHUB_RUN_ATTEMPT')})
        result = scan_candidate(layout, directory, candidate, approved_baseline=context)
        if result.get('status') not in ('pass', 'blocked') or result.get('image') != image:
            raise ValueError('Native policy returned inconsistent candidate evidence')
        if ((risk_mode and ('advisories' not in result or result.get('mode') != 'upstream-maintained-risk' or
                           result.get('approvedBaseline') != context)) or
                not isinstance(result.get('advisories', []), list)):
            raise ValueError('Native risk policy result does not retain advisory observations')
        if risk_mode and 'releaseBlockers' not in result:
            raise ValueError('Native risk policy result does not retain reviewed source release blockers')
        holds = policy_module.release_blockers(
            {'releaseBlockers': result.get('releaseBlockers', [])}, datetime.now(timezone.utc))
        if (result['status'] == 'blocked') != bool(result['blocked'] or holds):
            raise ValueError('Native policy status contradicts blocking findings or source release blockers')
        result.update({'sourceType': 'locally-built-unpublished', 'signatureVerified': False, 'releaseEligible': False})
        code = 0 if result['status'] == 'pass' else 1
        write_json(directory / 'security-result.json', result)
        summary = {key: result[key] for key in ('schema', 'status', 'image', 'scannedAt', 'scanner', 'policySha256',
                                                'sourceType', 'signatureVerified', 'releaseEligible')}
        summary.update({'blockingRecords': len(result['blocked']), 'exceptionRecords': len(result['exceptionsApplied']),
                        'advisoryRecords': len(result.get('advisories', [])),
                        'releaseBlockers': holds, 'releaseBlockerRecords': len(holds),
                        'observationRecords': len(result.get('observations', [])),
                        'coverage': result['coverage'], 'matches': result['matches']})
        write_json(directory / 'security-summary.json', summary)
        print(json.dumps(summary))
        return code
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OSError, subprocess.SubprocessError) as error:
        # An existing output directory must never be overwritten with new/stale
        # evidence. Write a failure record only into the directory we created.
        result = {'schema': 1, 'status': 'scanner-error', 'image': image, 'error': str(error),
                  'sourceType': 'locally-built-unpublished', 'signatureVerified': False, 'releaseEligible': False}
        if created:
            write_json(directory / 'security-result.json', result)
        print('Local candidate scan failed: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
