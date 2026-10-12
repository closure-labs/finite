#!/usr/bin/env python3
"""Evaluate digest-bound native Syft/Grype evidence; scanner errors fail separately."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
IMAGE = re.compile(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}')


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Security timestamps must include a timezone')
    return result


def fresh(value, hours, now, label):
    age = now - timestamp(value)
    if age < -timedelta(minutes=5) or age > timedelta(hours=hours):
        raise ValueError(label + ' is stale or from the future')


def load_policy(path):
    policy = json.loads(path.read_text())
    if policy.get('schema') != 1:
        raise ValueError('Unsupported image security policy')
    return policy


MANIFEST_LIMIT = 1024 * 1024
IMAGE_TYPES = {'application/vnd.oci.image.manifest.v1+json',
               'application/vnd.docker.distribution.manifest.v2+json'}
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json'}


def manifest_document(raw):
    if not isinstance(raw, str) or len(raw.encode()) > MANIFEST_LIMIT:
        raise ValueError('Image manifest exceeds the metadata limit')
    document = json.loads(raw)
    if document.get('schemaVersion') != 2:
        raise ValueError('Unsupported image manifest schema')
    return document


def manifest_binding(image, manifests):
    """Authenticate a platform manifest through the exact signed OCI index."""
    expected = image.split('@')[1]
    parent = manifests['parent']
    document = manifest_document(parent)
    if 'sha256:' + hashlib.sha256(parent.encode()).hexdigest() != expected:
        raise ValueError('Raw parent manifest does not match the signed image digest')
    if document.get('mediaType') in IMAGE_TYPES:
        if manifests.get('child') is not None:
            raise ValueError('Direct image cannot claim a different platform manifest')
        return expected
    if document.get('mediaType') not in INDEX_TYPES:
        raise ValueError('Unsupported image manifest media type')
    selected = [entry for entry in document['manifests']
                if entry.get('platform', {}).get('os') == 'linux' and
                entry.get('platform', {}).get('architecture') == 'amd64']
    if (len(selected) != 1 or selected[0].get('mediaType') not in IMAGE_TYPES or
            selected[0].get('platform', {}).get('variant', '') not in ('', 'v1')):
        raise ValueError('Signed index requires one supported linux/amd64 image manifest')
    descriptor = selected[0]
    child = manifests['child']
    child_document = manifest_document(child)
    digest = 'sha256:' + hashlib.sha256(child.encode()).hexdigest()
    if (digest != descriptor['digest'] or len(child.encode()) != descriptor['size'] or
            child_document.get('mediaType') != descriptor['mediaType']):
        raise ValueError('Raw platform manifest does not match its signed index descriptor')
    return digest


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_manifests(directory):
    parent = directory / 'image-manifest.json'
    if not parent.exists():
        raise ValueError('Missing raw image manifest evidence')
    result = {'parent': None, 'child': None}
    for key, name in [('parent', 'image-manifest.json'), ('child', 'platform-manifest.json')]:
        path = directory / name
        if path.exists():
            if path.stat().st_size > MANIFEST_LIMIT:
                raise ValueError('Image manifest exceeds the metadata limit')
            result[key] = path.read_bytes().decode('utf-8')
    extraction = directory / 'extraction.json'
    if extraction.exists():
        if extraction.stat().st_size > MANIFEST_LIMIT:
            raise ValueError('Extraction provenance exceeds the metadata limit')
        result['extraction'] = json.loads(extraction.read_text())
        if result['extraction']['sbomSha256'] != file_sha256(directory / 'sbom.syft.json'):
            raise ValueError('Extraction provenance does not bind the native SBOM bytes')
    return result


def inventory(sbom, image, policy, manifests=None):
    if not IMAGE.fullmatch(image):
        raise ValueError('Security scan requires an immutable Finite image')
    source = sbom['source']
    expected = manifest_binding(image, manifests) if manifests is not None else image.split('@')[1]
    if source['type'] == 'directory':
        extraction = (manifests or {}).get('extraction')
        if (not extraction or extraction['schema'] != 1 or extraction['method'] != 'umoci-rootless' or
                not re.fullmatch(r'umoci version [0-9]+\.[0-9]+\.[0-9]+(?:[^\s]*)', extraction['toolVersion'].split('\n', 1)[0]) or
                extraction['signedDigest'] != image.split('@')[1] or
                extraction['scannedManifestDigest'] != expected or extraction['catalogers'] != 'image' or
                not Path(extraction['sourcePath']).is_absolute() or
                str(Path(extraction['sourcePath'])) != extraction['sourcePath'] or
                '..' in Path(extraction['sourcePath']).parts or
                extraction['basePath'] != extraction['sourcePath'] or
                source['metadata']['path'] != extraction['sourcePath']):
            raise ValueError('Native directory SBOM lacks matching authenticated extraction provenance')
    elif source['type'] != 'image' or source['metadata']['manifestDigest'] != expected:
        raise ValueError('SBOM source is not the requested image digest')
    distro = sbom['distro']
    version = distro['versionID']
    effective = policy['distributionAliases'].get(distro['id'])
    if effective != 'fedora' or not re.fullmatch(r'[0-9]{2}', version):
        raise ValueError('Unsupported or missing image distribution')
    rpms = [a for a in sbom['artifacts'] if a['type'] == 'rpm' and a.get('foundBy') == 'rpm-db-cataloger']
    if len(rpms) < policy['minimumRpmPackages']:
        raise ValueError('Missing or implausibly incomplete RPM inventory')
    # Bluefin branding is not itself a distribution match. Prove the Fedora
    # release using the installed RPM inventory before using the reviewed alias.
    release = [a for a in rpms if a['name'] == policy['requiredReleasePackage']]
    if len(release) != 1 or not re.fullmatch(re.escape(version) + r'-[^\s]+', release[0]['version']):
        raise ValueError('Fedora distribution version lacks matching release RPM evidence')
    return {'signedDigest': image.split('@')[1], 'scannedManifestDigest': expected,
            'original': distro, 'effective': effective + ':' + version,
            'rpmPackages': len(rpms), 'totalPackages': len(sbom['artifacts']),
            'releasePackage': {k: release[0][k] for k in ('name', 'version')}}


def exception_keys(policy, image, now):
    keys = set()
    required = {'digest', 'component', 'advisory', 'approvedAt', 'expiresAt', 'reviewedBy', 'reason'}
    for entry in policy['exceptions']:
        if set(entry) != required or not all(isinstance(v, str) and v.strip() for v in entry.values()):
            raise ValueError('Exception requires exact scope and documented review')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['digest']):
            raise ValueError('Exception digest must be exact')
        approved, expires = timestamp(entry['approvedAt']), timestamp(entry['expiresAt'])
        if approved > now or expires <= approved or expires - approved > timedelta(days=policy['maxExceptionDays']):
            raise ValueError('Invalid exception review/expiry window')
        if entry['digest'] == image.split('@')[1] and expires > now:
            keys.add((entry['component'], entry['advisory']))
    return keys


def evaluate(sbom, scan, image, policy, now=None, database_coverage=None, manifests=None):
    now = now or datetime.now(timezone.utc)
    coverage = inventory(sbom, image, policy, manifests)
    descriptor = scan['descriptor']
    if descriptor['name'] != 'grype' or not descriptor['version']:
        raise ValueError('Missing scanner version')
    fresh(descriptor['timestamp'], policy['maxEvidenceAgeHours'], now, 'Scan evidence')
    native = sbom['source']
    if native['type'] == 'directory':
        if scan['source'] != {'type': 'directory', 'target': native['metadata']['path']}:
            raise ValueError('Scanner directory source does not match native SBOM metadata')
    elif (scan['source']['type'] != 'image' or
          scan['source']['target']['manifestDigest'] != native['metadata']['manifestDigest']):
        raise ValueError('Scanner source does not match native SBOM image metadata')
    db = descriptor['db']
    if db['status']['valid'] is not True:
        raise ValueError('Scanner database is invalid')
    fresh(db['status']['built'], policy['maxDatabaseAgeHours'], now, 'Scanner database')
    for provider in policy['requiredProviders']:
        fresh(db['providers'][provider]['captured'], policy['maxDatabaseAgeHours'], now, provider + ' provider')
    expected_name, expected_version = coverage['effective'].split(':')
    if scan['distro']['name'] != expected_name or scan['distro']['version'] != expected_version:
        raise ValueError('Scanner did not use the validated Fedora distribution')
    # Prove the fresh DB actually contains this Fedora RPM namespace. An
    # inventory alone is not coverage, and zero image matches can be legitimate.
    if not isinstance(database_coverage, list) or not any(
            entry['vulnerability']['provider'] == 'fedora' and any(
                package['os'] == {'name': expected_name, 'version': expected_version} and
                package['package'] == {'name': policy['coverageProbePackage'], 'ecosystem': 'rpm'}
                for package in entry['packages']) for entry in database_coverage):
        raise ValueError('Database has no proven Fedora RPM advisory coverage for this version')
    exceptions = exception_keys(policy, image, now)
    blocked, waived = [], []
    matches = scan['matches']
    if not isinstance(matches, list):
        raise ValueError('Invalid scanner matches')
    # Grype's built-in suppressions do not override our reviewed policy.
    matches = [*matches, *scan.get('ignoredMatches', [])]
    for match in matches:
        vulnerability, artifact = match['vulnerability'], match['artifact']
        related = match.get('relatedVulnerabilities') or []
        known = any(v.get('knownExploited') for v in [vulnerability, *related])
        fix = vulnerability['fix']
        fixable = fix['state'] == 'fixed' and bool(fix['versions'])
        if not ((known and policy['blockKnownExploited']) or
                (fixable and vulnerability['severity'] in policy['blockedFixableSeverities'])):
            continue
        # Artifact ID remains usable for embedded components lacking a PURL;
        # it is scoped to this exact digest, never to a package-name wildcard.
        component = artifact.get('purl') or artifact['id']
        finding = {'component': component, 'advisory': vulnerability['id'],
                   'severity': vulnerability['severity'], 'knownExploited': bool(known),
                   'fixVersions': fix['versions']}
        (waived if (component, vulnerability['id']) in exceptions else blocked).append(finding)
    return {'schema': 1, 'status': 'blocked' if blocked else 'pass', 'image': image,
            'scannedAt': descriptor['timestamp'], 'scanner': descriptor['version'],
            'database': db, 'coverage': coverage, 'databaseCoverageRecords': len(database_coverage),
            'matches': len(matches),
            'blocked': blocked, 'exceptionsApplied': waived}


def verify(directory, image, policy_path=ROOT / 'automation/security/image-policy.json'):
    policy = load_policy(policy_path)
    sbom = json.loads((directory / 'sbom.syft.json').read_text())
    scan = json.loads((directory / 'vulnerabilities.json').read_text())
    result = evaluate(sbom, scan, image, policy,
                      database_coverage=json.loads((directory / 'database-coverage.json').read_text()),
                      manifests=read_manifests(directory))
    if result['status'] != 'pass':
        raise ValueError('Candidate violates image vulnerability policy')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('image')
    parser.add_argument('--policy', type=Path, default=ROOT / 'automation/security/image-policy.json')
    args = parser.parse_args()
    try:
        result = evaluate(json.loads((args.directory / 'sbom.syft.json').read_text()),
                          json.loads((args.directory / 'vulnerabilities.json').read_text()),
                          args.image, load_policy(args.policy), database_coverage=
                          json.loads((args.directory / 'database-coverage.json').read_text()),
                          manifests=read_manifests(args.directory))
        result['policySha256'] = hashlib.sha256(args.policy.read_bytes()).hexdigest()
        code = 0 if result['status'] == 'pass' else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        result = {'schema': 1, 'status': 'scanner-error', 'image': args.image, 'error': str(error)}
        code = 2
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / 'security-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
