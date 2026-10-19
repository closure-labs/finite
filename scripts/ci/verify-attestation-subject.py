#!/usr/bin/env python3
"""Bind the native SPDX bytes to the exact immutable subject before OIDC attestation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = 'ghcr.io/closure-labs/finite'
SPDX_TYPE = 'application/spdx+json'
PREDICATE_TYPE = 'https://github.com/closure-labs/finite/blob/main/docs/automation/sbom-reference-v1.md'
MAX_MANIFEST = 2 * 1024**2


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


security = module('attestation_security', ROOT / 'scripts/bluebuild/security-policy.py')
inventory = module('attestation_inventory', ROOT / 'scripts/ci/inventory-evidence.py')


def verify(directory, profile, digest):
    if profile not in security.PROFILES or not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Attestation requires an exact supported immutable subject')
    directory = Path(directory)
    image = 'ghcr.io/closure-labs/finite@' + digest
    report = inventory.read(directory / 'security-result.json')
    complete = (report.get('status') == 'complete' and report.get('mode') == security.DECISION_MODE
                and report.get('scannerHealth') == 'healthy')
    if report.get('image') != image or (report.get('status') != 'pass' and not complete):
        raise ValueError('Attestation subject differs from a completed healthy native scan')
    record = inventory.read(directory / 'inventory-provenance.json')
    files = record.get('files')
    if (record.get('schema') != 1 or record.get('image') != image or not isinstance(files, dict)
            or not inventory.REQUIRED.issubset(files) or set(files) - inventory.FILES.keys()):
        raise ValueError('Native SBOM inventory lacks exact image content bindings')
    for name, expected in files.items():
        path = directory / name
        if (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)
                or any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file()
                or not 0 < path.stat().st_size <= inventory.FILES[name] * 1024**2
                or inventory.sha256(path) != expected):
            raise ValueError('Attestation native content hash/path mismatch: ' + name)
    manifests = security.read_manifests(directory)
    platform = security.manifest_binding(image, manifests)
    if record.get('platformDigest') != platform:
        raise ValueError('Attestation native inventory has a different platform digest')
    baseline = security.baseline_binding(report.get('approvedBaseline'), image, manifests)
    if baseline['profile'] != profile:
        raise ValueError('Attestation profile differs from immutable image configuration')
    native = inventory.read(directory / 'sbom.syft.json', inventory.FILES['sbom.syft.json'] * 1024**2)
    policy = security.load_policy(ROOT / 'automation/security/image-policy.json')
    security.inventory(native, image, policy, manifests)
    spdx = inventory.read(directory / 'sbom.spdx.json', inventory.FILES['sbom.spdx.json'] * 1024**2)
    if (spdx.get('spdxVersion') not in ('SPDX-2.2', 'SPDX-2.3') or spdx.get('SPDXID') != 'SPDXRef-DOCUMENT'
            or not isinstance(spdx.get('packages'), list)):
        raise ValueError('Native SBOM is not a supported SPDX document')
    return {'schema': 1, 'image': image, 'profile': profile, 'platformDigest': platform,
            'sbomSha256': files['sbom.spdx.json'],
            'sbomSize': (directory / 'sbom.spdx.json').stat().st_size, 'spdxVersion': spdx['spdxVersion'],
            'sourceRevision': baseline['sourceRevision']}



def registry_command(args, file_limit=MAX_MANIFEST, **kwargs):
    """Bound registry output, created files, execution time and diagnostics."""
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    with tempfile.TemporaryFile() as capture:
        subprocess.run(['oras', *args], stdout=capture, stderr=subprocess.DEVNULL,
                       check=True, timeout=300, preexec_fn=limits, **kwargs)
        if capture.tell() > MAX_MANIFEST:
            raise ValueError('Registry response exceeds attestation manifest bound')
        capture.seek(0)
        return capture.read()


def reference_predicate(receipt, manifest_raw, subject_raw):
    """Authenticate the full original SPDX descriptor, never an inline substitute."""
    if not 0 < len(manifest_raw) <= MAX_MANIFEST:
        raise ValueError('Invalid external SPDX manifest size')
    # Reuse the strict duplicate-key parser used for native metadata.
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'manifest.json'
        path.write_bytes(manifest_raw)
        manifest = inventory.read(path, MAX_MANIFEST)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('subject'), dict):
        raise ValueError('External SPDX manifest lacks an immutable subject')
    subject = manifest['subject']
    image_manifest = json.loads(subject_raw)
    if 'sha256:' + hashlib.sha256(subject_raw).hexdigest() != receipt['image'].split('@')[1]:
        raise ValueError('Native image manifest changed before external SPDX publication')
    if (manifest.get('schemaVersion') != 2
            or manifest.get('mediaType') != 'application/vnd.oci.image.manifest.v1+json'
            or manifest.get('artifactType') != SPDX_TYPE
            or subject.get('digest') != receipt['image'].split('@')[1]
            or type(subject.get('size')) is not int or subject['size'] != len(subject_raw)
            or subject.get('mediaType') != image_manifest.get('mediaType')):
        raise ValueError('External SPDX manifest has an invalid immutable subject')
    layers = manifest.get('layers')
    if not isinstance(layers, list) or len(layers) != 1 or not isinstance(layers[0], dict):
        raise ValueError('External SPDX manifest requires exactly one full document layer')
    layer = layers[0]
    if (layer.get('mediaType') != SPDX_TYPE or layer.get('digest') != 'sha256:' + receipt['sbomSha256']
            or type(layer.get('size')) is not int or layer['size'] != receipt['sbomSize']
            or not isinstance(layer.get('annotations'), dict)
            or layer['annotations'].get('org.opencontainers.image.title') != 'sbom.spdx.json'):
        raise ValueError('External SPDX descriptor differs from authenticated original')
    digest = 'sha256:' + hashlib.sha256(manifest_raw).hexdigest()
    return {'schema': 1, 'image': receipt['image'], 'profile': receipt['profile'],
            'platformDigest': receipt['platformDigest'],
            'sbom': {'name': 'sbom.spdx.json', 'mediaType': SPDX_TYPE,
                     'spdxVersion': receipt['spdxVersion'], 'sha256': receipt['sbomSha256'],
                     'size': receipt['sbomSize']},
            'artifact': {'reference': REGISTRY + '@' + digest, 'digest': digest,
                         'mediaType': manifest['mediaType'], 'size': len(manifest_raw)}}


def publish(directory, profile, digest, output):
    receipt = verify(directory, profile, digest)
    directory, output = Path(directory).resolve(), Path(output)
    if (any(path.is_symlink() for path in (output, *output.parents))
            or output.resolve().is_relative_to(directory)):
        raise ValueError('Generated attestation must be separate from native evidence')
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output.resolve() / 'sbom-manifest.json'
    registry_command(['attach', '--artifact-type', SPDX_TYPE, '--export-manifest', str(manifest_path),
                      receipt['image'], 'sbom.spdx.json:' + SPDX_TYPE], cwd=directory)
    # File/path bounds apply even if a registry client creates unexpected output.
    inventory.read(manifest_path, MAX_MANIFEST)
    manifest_raw = manifest_path.read_bytes()
    predicate = reference_predicate(receipt, manifest_raw, (directory / 'image-manifest.json').read_bytes())
    remote = registry_command(['manifest', 'fetch', predicate['artifact']['reference']])
    if remote != manifest_raw:
        raise ValueError('Published SPDX manifest digest/content mismatch')
    # Prove registry availability of unchanged bytes as well as descriptor binding.
    # Hash streamed disk bytes; never load the full document again for transport.
    with tempfile.TemporaryDirectory() as temporary:
        blob = Path(temporary) / 'sbom.spdx.json'
        registry_command(['blob', 'fetch', REGISTRY + '@sha256:' + receipt['sbomSha256'],
                          '--output', str(blob)], file_limit=receipt['sbomSize'] + 1)
        if (blob.is_symlink() or not blob.is_file() or blob.stat().st_size != receipt['sbomSize']
                or inventory.sha256(blob) != receipt['sbomSha256']):
            raise ValueError('Published full SPDX bytes differ from authenticated original')
    if inventory.sha256(directory / 'sbom.spdx.json') != receipt['sbomSha256']:
        raise ValueError('Native SPDX changed while publishing')
    data = json.dumps(predicate, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
    if len(data) > 16 * 1024**2:
        raise ValueError('External SPDX reference predicate exceeds attestation limit')
    (output / 'sbom-reference.json').write_bytes(data)
    return predicate



def generate_provenance(receipt, current_revision, resume_run):
    if (not isinstance(current_revision, str) or not re.fullmatch(r'[0-9a-f]{40}', current_revision)
            or not isinstance(resume_run, str) or (resume_run and not re.fullmatch(r'[0-9]+', resume_run))):
        raise ValueError('Build provenance requires an exact current revision and optional original run')
    return not resume_run and receipt['sourceRevision'] == current_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--digest', required=True)
    parser.add_argument('--publish-reference', type=Path, help='Publish full SPDX and write a separate signed-reference predicate')
    parser.add_argument('--current-revision', help='Current workflow revision for fresh-build provenance eligibility')
    parser.add_argument('--resume-run', default='')
    args = parser.parse_args()
    try:
        result = (publish(args.directory, args.profile, args.digest, args.publish_reference)
                  if args.publish_reference else verify(args.directory, args.profile, args.digest))
        if args.current_revision is not None:
            result['generateProvenance'] = generate_provenance(result, args.current_revision, args.resume_run)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print('Attestation subject verification failed: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
