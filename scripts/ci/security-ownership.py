#!/usr/bin/env python3
"""Report RPM ownership evidence; run large native SBOM processing on hosted CI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def owner(artifact):
    return {'name': artifact['name'], 'version': artifact['version'],
            'purl': artifact.get('purl'), 'sourceRpm': artifact.get('metadata', {}).get('sourceRpm')}


def path_value(value, root):
    if not isinstance(value, str) or not value.startswith('/'):
        return None
    if root and value.startswith(root.rstrip('/') + '/'):
        value = value[len(root.rstrip('/')):]
    # Do not resolve links or access the host filesystem while reading evidence.
    if '..' in value.split('/'):
        return None
    return value


def report(sbom, ledger, extraction, sbom_hash):
    image = ledger['image']
    if extraction.get('sbomSha256') != sbom_hash:
        raise ValueError('Native SBOM hash does not match extraction evidence')
    if extraction.get('signedDigest') != image.split('@', 1)[1]:
        raise ValueError('Extraction digest differs from baseline ledger')
    if extraction.get('method') != 'umoci-rootless':
        raise ValueError('Unsupported extraction provenance')
    if not isinstance(sbom.get('artifacts'), list) or not isinstance(ledger.get('findings'), list):
        raise ValueError('Missing native artifacts or ledger findings')
    root = extraction.get('sourcePath')
    if not isinstance(root, str) or not root.startswith('/'):
        raise ValueError('Missing extraction source path')
    source = sbom.get('source', {})
    if source.get('type') != 'directory' or source.get('metadata', {}).get('path') != root:
        raise ValueError('Native SBOM source does not match extraction')
    wanted = {finding['component'] for finding in ledger['findings']}
    components = {purl: [] for purl in wanted}
    rpms = {}
    locations = {}
    for artifact in sbom['artifacts']:
        if artifact.get('type') == 'rpm':
            rpms[artifact['id']] = artifact
        purl = artifact.get('purl')
        if purl in wanted:
            components[purl].append(artifact)
            for location in artifact.get('locations', []):
                for field in ('path', 'accessPath', 'realPath'):
                    path = path_value(location.get(field), root)
                    if path:
                        locations.setdefault(path, {})
    # Only retain ownership for relevant paths, avoiding a second full file map.
    for artifact_id, artifact in rpms.items():
        for entry in artifact.get('metadata', {}).get('files', []):
            path = path_value(entry.get('path') if isinstance(entry, dict) else entry, root)
            if path in locations:
                locations[path][artifact_id] = owner(artifact)
    related = {}
    for relation in sbom.get('artifactRelationships', []):
        left, right = relation.get('parent'), relation.get('child')
        for component_id, rpm_id, direction in ((left, right, 'component-to-rpm'), (right, left, 'rpm-to-component')):
            if rpm_id in rpms and component_id != rpm_id:
                related.setdefault(component_id, []).append({
                    'rpm': owner(rpms[rpm_id]), 'type': relation.get('type'), 'direction': direction})
    findings = []
    for finding in ledger['findings']:
        artifacts = components[finding['component']]
        paths, owners, relationships = {}, {}, []
        for artifact in artifacts:
            if artifact.get('type') == 'rpm':
                owners[artifact['id']] = {**owner(artifact), 'evidence': 'rpm-artifact-itself'}
            relationships.extend(related.get(artifact['id'], []))
            for location in artifact.get('locations', []):
                for field in ('path', 'accessPath', 'realPath'):
                    path = path_value(location.get(field), root)
                    if not path:
                        continue
                    kind = 'ostree-object' if re.match(r'^/(?:sysroot/)?ostree/repo/objects/', path) else 'live-path'
                    path_owners = list(locations[path].values())
                    paths[path] = {'path': path, 'kind': kind, 'rpmOwners': path_owners,
                                   'ownership': 'rpm-file-list' if path_owners else 'unknown'}
                    for rpm_id, evidence in locations[path].items():
                        owners[rpm_id] = {**evidence, 'evidence': 'rpm-file-list'}
        findings.append({**finding, 'remediationStatus': 'pending-rescan',
                         'sbomMatch': 'exact-purl' if artifacts else 'not-found',
                         'owners': sorted(owners.values(), key=lambda x: (x['name'], x['version'])),
                         'paths': [paths[p] for p in sorted(paths)],
                         'rpmRelationships': relationships,
                         'ownership': 'identified' if owners else 'unknown'})
    return {'schema': 1, 'image': image, 'sourceRun': ledger.get('sourceRun'),
            'sbomSha256': sbom_hash, 'status': 'triage-only',
            'note': 'Exact native evidence only. Relationships are recorded without assuming ownership. No finding is resolved; unknown paths and OSTree reachability require investigation.',
            'findingCount': len(findings), 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory-dir', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Large native SBOM processing must run in hosted GitHub Actions')
    candidates = list(args.inventory_dir.rglob('sbom.syft.json'))
    if len(candidates) != 1:
        raise ValueError('Inventory must contain exactly one native sbom.syft.json')
    sbom_path = candidates[0]
    extraction = json.loads(sbom_path.with_name('extraction.json').read_text())
    actual = digest(sbom_path)
    if actual != extraction.get('sbomSha256'):
        raise ValueError('Native SBOM hash does not match extraction evidence')
    result = report(json.loads(sbom_path.read_text()), json.loads(args.ledger.read_text()), extraction, actual)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
