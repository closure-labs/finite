#!/usr/bin/env python3
"""Immutable inventory identity; vulnerability results and policy are never cached here."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    'image-manifest.json': 16, 'platform-manifest.json': 16, 'image-config.json': 16,
    'extraction.json': 16, 'extraction-manifest.json': 16, 'extraction-layout.json': 16,
    'sbom.syft.json': 256, 'sbom.spdx.json': 256, 'rpm-file-evidence.json': 128,
    'applicability-evidence.json': 16,
}
REQUIRED = {'image-manifest.json', 'image-config.json', 'extraction.json', 'sbom.syft.json', 'sbom.spdx.json'}
IMPLEMENTATIONS = (
    'scripts/bluebuild/security-scan.py', 'scripts/bluebuild/security-policy.py',
    'scripts/ci/inventory-evidence.py', 'scripts/ci/rpm-file-evidence.py',
    'scripts/ci/applicability-evidence.py', 'scripts/ci/approved-baseline.py',
    # Conservative probe compatibility: a policy edit rebuilds native probes
    # while every reuse still runs the current vulnerability policy afresh.
    'automation/security/image-policy.json',
)
MAX_AGE = timedelta(days=7)


class Unavailable(ValueError):
    """Missing, legacy, expired or incompatible inventory; rebuild it."""


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def generation():
    return {'platform': 'linux/amd64', 'catalogers': 'image',
            'tools': {tool: subprocess.check_output([tool, '--version'], text=True, timeout=30).strip()
                      for tool in ('syft', 'umoci')},
            'implementations': {name: sha256(ROOT / name) for name in IMPLEMENTATIONS}}


def read(path, limit=16 * 1024**2):
    if (any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file()
            or not 0 < path.stat().st_size <= limit):
        raise ValueError('Inventory evidence has missing, symlinked or oversized bytes: ' + path.name)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate inventory metadata key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def write(directory, image, platform_digest, risk_mode):
    files = {name: sha256(directory / name) for name in FILES if (directory / name).exists()}
    record = {'schema': 1, 'image': image, 'platformDigest': platform_digest,
              'generatedAt': datetime.now(timezone.utc).isoformat(), 'riskEvidence': risk_mode,
              'generation': generation(), 'files': files}
    (directory / 'inventory-provenance.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def verify(directory, image, security, risk_mode, now=None):
    provenance = directory / 'inventory-provenance.json'
    if not provenance.exists():
        raise Unavailable('Legacy artifact has no reusable inventory identity')
    record = read(provenance)
    if (type(record.get('schema')) is not int or record['schema'] != 1 or record.get('image') != image
            or type(record.get('riskEvidence')) is not bool or not isinstance(record.get('files'), dict)):
        raise ValueError('Inventory identity differs from the requested immutable image')
    files = record['files']
    if (not REQUIRED.issubset(files) or set(files) - FILES.keys()
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                   for value in files.values())):
        raise ValueError('Inventory has missing, unexpected or malformed content bindings')
    # Validate all bytes before treating age/version incompatibility as a miss.
    for name, expected in files.items():
        path = directory / name
        if (any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file()
                or not 0 < path.stat().st_size <= FILES[name] * 1024**2 or sha256(path) != expected):
            raise ValueError('Inventory content hash/size/path mismatch: ' + name)
    if {name for name in FILES if (directory / name).exists()} != set(files):
        raise ValueError('Inventory contains unbound native evidence')
    manifests = security.read_manifests(directory)
    platform = security.manifest_binding(image, manifests)
    if platform != record.get('platformDigest'):
        raise ValueError('Inventory platform manifest differs from its identity')
    if not isinstance(record.get('generatedAt'), str):
        raise ValueError('Malformed inventory generation timestamp')
    stamp = datetime.fromisoformat(record['generatedAt'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Inventory timestamp lacks a timezone')
    age = (now or datetime.now(timezone.utc)) - stamp
    if age < timedelta(0):
        raise ValueError('Inventory timestamp is from the future')
    if age > MAX_AGE:
        raise Unavailable('Inventory retention eligibility expired')
    if record.get('generation') != generation():
        raise Unavailable('Inventory tool/probe generation changed')
    if risk_mode and (record['riskEvidence'] is not True or
                      not {'rpm-file-evidence.json', 'applicability-evidence.json'}.issubset(files)):
        raise Unavailable('Current policy requires additional inventory probes')
    return record


def copy(directory, output, record):
    for name in (*record['files'], 'inventory-provenance.json'):
        shutil.copyfile(directory / name, output / name)
    origin = directory / 'inventory-origin.json'
    if origin.exists():
        shutil.copyfile(origin, output / origin.name)
