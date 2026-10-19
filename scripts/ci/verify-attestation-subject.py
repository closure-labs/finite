#!/usr/bin/env python3
"""Bind the native SPDX bytes to the exact immutable subject before OIDC attestation."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]


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
            'sbomSha256': files['sbom.spdx.json']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--digest', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.directory, args.profile, args.digest), sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Attestation subject verification failed: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
