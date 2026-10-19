#!/usr/bin/env python3
"""Compact hosted triage from retained native evidence, without granting clearance."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_summary_security', ROOT / 'scripts/bluebuild/security-policy.py')
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)
APP_SPEC = importlib.util.spec_from_file_location('native_summary_bounds', ROOT / 'scripts/ci/applicability-evidence.py')
bounds = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(bounds)
MAX_SBOM = 256 * 1024 * 1024
MAX_OUTPUT = 16 * 1024 * 1024


def compact(value, limit=65536):
    if len(json.dumps(value).encode()) > limit:
        raise ValueError('Selected native metadata exceeds compact evidence bound')
    return value


def path_value(value, prefix):
    if not isinstance(value, str):
        return None
    if prefix and value.startswith(prefix + '/'):
        value = value[len(prefix):]
    return value if security.canonical_location(value) else None


def locations(artifact, prefix):
    records = artifact.get('locations', [])
    if not isinstance(records, list):
        raise ValueError('Invalid native artifact locations')
    paths, complete = set(), bool(records)
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid native location object')
        values = [record[key] for key in ('path', 'accessPath', 'realPath') if key in record]
        if not values:
            complete = False
        for value in values:
            normalized = path_value(value, prefix)
            if normalized is None:
                complete = False
            else:
                paths.add(normalized)
    return sorted(paths), complete


def rpm_identity(artifact):
    metadata = artifact.get('metadata', {})
    return {key: artifact.get(key) for key in ('id', 'name', 'version', 'purl', 'foundBy')} | {
        key: metadata.get(key) for key in ('sourceRpm', 'architecture', 'epoch', 'release', 'vendor', 'signatures')}


def report(sbom, result, extraction, image, sbom_hash):
    maintainer = result.get('mode') == 'maintainer-decision'
    completed = (result.get('status') == 'complete' and result.get('scannerHealth') == 'healthy') if maintainer else result.get('status') in ('pass', 'blocked')
    if (not security.IMAGE.fullmatch(image) or result.get('image') != image
            or type(result.get('schema')) is not int or result['schema'] != 1
            or not completed or not isinstance(result.get('blocked'), list)
            or len(result['blocked']) > 16384 or not isinstance(result.get('releaseBlockers', []), list)):
        raise ValueError('Summary requires a completed exact immutable native result')
    if (type(extraction.get('schema')) is not int or extraction['schema'] != 1
            or extraction.get('sbomSha256') != sbom_hash or extraction.get('signedDigest') != image.split('@')[1]
            or extraction.get('method') != 'umoci-rootless' or extraction.get('catalogers') != 'image'):
        raise ValueError('Native inventory lacks exact hash/digest/extraction binding')
    prefix = extraction.get('sourcePath')
    if (not security.canonical_location(prefix) or extraction.get('basePath') != prefix
            or sbom.get('source', {}).get('type') != 'directory'
            or sbom.get('source', {}).get('metadata', {}).get('path') != prefix):
        raise ValueError('Native directory source does not match extraction')
    critical_only = result.get('mode') == 'desktop-critical-only'
    basis = result.get('blockingBasis')
    if basis is not None and (not critical_only or basis != 'reviewed-desktop-exploitability'):
        raise ValueError('Unsupported native result blocking basis')
    reviewed_basis = basis == 'reviewed-desktop-exploitability'
    tracked = result.get('trackedReleaseConcerns', [])
    if critical_only:
        if 'trackedReleaseConcerns' not in result or 'releaseBlockers' not in result:
            raise ValueError('Critical-only result must retain classified source concerns')
        # A retained scan can be reevaluated against a newer policy review.
        # Validate review timestamps now without refreshing scan evidence.
        reviewed_now = datetime.now(timezone.utc)
        if reviewed_basis:
            baseline = result.get('approvedBaseline')
            if (not isinstance(baseline, dict) or baseline.get('image') != image
                    or baseline.get('profile') not in security.PROFILES):
                raise ValueError('Confirmed desktop risks require exact candidate profile binding')
            holds = security.confirmed_desktop_risks(
                {'confirmedDesktopRisks': result['releaseBlockers']}, reviewed_now)
            if (any(entry['digest'] != image.split('@')[1] or entry['profile'] != baseline['profile']
                    for entry in holds)):
                raise ValueError('Confirmed desktop risk result contradicts candidate scope or blocking basis')
            security.validate_confirmed_findings(result['blocked'], holds)
        else:
            holds = security.release_blockers(
                {'mode': result['mode'], 'releaseBlockers': result['releaseBlockers']}, reviewed_now)
        tracked = security.release_blockers(
            {'mode': result['mode'], 'releaseBlockers': tracked}, reviewed_now)
        if not reviewed_basis and (any(entry['severity'] != 'Critical' for entry in holds) or any(
                entry['severity'] == 'Critical' for entry in tracked)):
            raise ValueError('Source concern disposition contradicts Critical-only policy')
    elif not isinstance(tracked, list):
        raise ValueError('Invalid tracked source concerns')
    if maintainer and (any(result.get(key) for key in ('blocked', 'exceptionsApplied', 'advisories', 'releaseBlockers'))
                       or not isinstance(result.get('observations'), list) or len(result['observations']) > 16384):
        raise ValueError('Maintainer summary requires raw observations without automatic dispositions')
    blocked = [{**finding, 'reason': 'human-admission-not-evaluated',
                'severity': finding.get('admissionSeverity', finding.get('severity'))}
               for finding in result['observations']] if maintainer else result['blocked']
    if not maintainer and (result['status'] == 'blocked') != bool(blocked or result.get('releaseBlockers')):
        raise ValueError('Native result status contradicts findings/source holds')
    wanted, wanted_paths, grouped = set(), set(), {}
    for finding in blocked:
        component, advisory = finding['component'], finding['advisory']
        aliases, paths = finding['aliases'], finding['locations']
        if (not security.nonempty(component) or not security.nonempty(advisory)
                or not isinstance(aliases, list) or not aliases or len(aliases) > 128
                or any(not security.nonempty(alias) for alias in aliases) or advisory not in aliases
                or not isinstance(paths, list) or len(paths) > 1024
                or any(not security.canonical_location(path) for path in paths)
                or finding.get('severity') not in security.SEVERITIES or not security.nonempty(finding.get('reason'))
                or type(finding['knownExploited']) is not bool):
            raise ValueError('Blocked finding requires complete typed component/advisory/path evidence')
        critical_aliases = finding.get('criticalSeverityAdvisories', [])
        if (not isinstance(critical_aliases, list) or len(critical_aliases) > 128
                or any(not isinstance(alias, str) or alias not in aliases for alias in critical_aliases)
                or len(set(critical_aliases)) != len(critical_aliases)
                or (critical_only and not reviewed_basis and (not critical_aliases or
                    (finding['severity'] == 'Critical' and advisory not in critical_aliases)))):
            raise ValueError('Invalid or missing Critical severity advisory evidence')
        key = component, advisory
        entry = grouped.setdefault(key, {'component': component, 'advisory': advisory, 'aliases': set(),
            'locations': set(), 'reasons': set(), 'severities': set(), 'knownExploited': False,
            'locationCoverage': 'complete', 'occurrences': 0, 'fixStates': set(), 'fixVersions': set(),
            'criticalSeverityAdvisories': set(), 'confirmedRiskReviews': set()})
        entry['aliases'].update(aliases)
        entry['criticalSeverityAdvisories'].update(critical_aliases)
        if reviewed_basis:
            entry['confirmedRiskReviews'].update(finding['confirmedRiskReviews'])
        entry['locations'].update(paths)
        entry['reasons'].add(finding['reason'])
        entry['severities'].add(finding['severity'])
        entry['knownExploited'] |= finding['knownExploited']
        fixes = finding.get('fixVersions', [])
        if not isinstance(fixes, list) or any(not security.nonempty(value) for value in fixes):
            raise ValueError('Invalid native finding fix versions')
        entry['fixVersions'].update(fixes)
        entry['fixStates'].add(finding.get('fixState', 'unknown'))
        if finding.get('locationCoverage') != 'complete' or not paths:
            entry['locationCoverage'] = 'unknown'
        entry['occurrences'] += 1
        wanted.add(component)
        wanted_paths.update(paths)
    if len(wanted_paths) > 8192:
        raise ValueError('Selected path inventory exceeds summary bound')
    artifacts = sbom.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) > 100000:
        raise ValueError('Invalid native artifact inventory')
    components, owners, package_files = {key: [] for key in wanted}, {}, {}
    artifact_ids = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not security.nonempty(artifact.get('id')) or artifact['id'] in artifact_ids:
            raise ValueError('Invalid/duplicate native artifact identity')
        artifact_ids.add(artifact['id'])
        component = artifact.get('purl') or artifact['id']
        if component in wanted:
            paths, complete = locations(artifact, prefix)
            metadata = artifact.get('metadata', {})
            if not isinstance(metadata, dict):
                raise ValueError('Invalid native artifact metadata')
            # Symbol arrays never serve as absence evidence and are omitted.
            retained = {key: value for key, value in metadata.items() if key not in ('files', 'symbols')}
            entry = {key: artifact.get(key) for key in ('id', 'name', 'version', 'type', 'purl', 'foundBy', 'metadataType', 'cpes')}
            entry.update(locations=paths, locationCoverage='complete' if complete else 'unknown',
                         metadata=compact(retained), metadataEvidence='retained-native-sbom',
                         independentFileBytesObserved=False, independentPlatformProof='unknown')
            components[component].append(entry)
        if artifact.get('type') != 'rpm':
            continue
        metadata = artifact.get('metadata', {})
        files = metadata.get('files', [])
        if not isinstance(files, list):
            raise ValueError('Invalid RPM declared file list')
        focused = artifact.get('name', '').startswith(('httpd', 'mod_', 'freerdp', 'libwinpr'))
        if focused and len(files) > 8192:
            raise ValueError('Focused RPM file list exceeds summary bound')
        declared = []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = path_value(item.get('path'), prefix)
            if path is None:
                continue
            if path in wanted_paths:
                owners.setdefault(path, []).append({'rpm': rpm_identity(artifact),
                    'declaredFile': compact(item, 16384), 'evidence': 'rpm-db-file-list',
                    'actualFileIntegrityVerified': False})
            if focused:
                declared.append({**compact(item, 16384), 'path': path})
        if focused:
            package_files[artifact['id']] = {'rpm': rpm_identity(artifact), 'declaredFiles': declared,
                                            'actualFileIntegrityVerified': False}
    # Preserve all cataloged metadata for selected paths, without traversing the
    # host or pretending catalog metadata is a fresh independent byte inspection.
    file_records = {}
    files = sbom.get('files', [])
    if not isinstance(files, list):
        raise ValueError('Invalid cataloged file inventory')
    for record in files:
        if not isinstance(record, dict) or not isinstance(record.get('location'), dict):
            raise ValueError('Invalid cataloged file metadata record')
        found = {path_value(record['location'].get(key), prefix) for key in ('path', 'accessPath', 'realPath')}
        for path in found & wanted_paths:
            retained = {key: record[key] for key in ('id', 'location', 'metadata', 'digests', 'executable') if key in record}
            records = file_records.setdefault(path, [])
            if len(records) >= 32:
                raise ValueError('Ambiguous native file metadata exceeds path bound')
            records.append(compact(retained))
    findings = []
    for key in sorted(grouped):
        entry = grouped[key]
        for field in ('aliases', 'locations', 'reasons', 'severities', 'fixStates', 'fixVersions', 'criticalSeverityAdvisories', 'confirmedRiskReviews'):
            entry[field] = sorted(entry[field])
        matches = components[entry['component']]
        observed = {path for match in matches for path in match['locations']}
        entry.update(artifacts=matches, nativeComponentMatch='exact' if matches else 'unknown',
            findingPathsMissingFromArtifactLocations=sorted(set(entry['locations']) - observed),
            paths=[{'path': path, 'kind': 'ostree-object' if re.match(r'^/(?:sysroot/)?ostree/repo/objects/', path) else 'live-path',
                    'rpmFileOwners': owners.get(path, []), 'ownership': 'rpm-file-list' if owners.get(path) else 'unknown',
                    'catalogedFileMetadata': file_records.get(path, []),
                    'independentFileBytesObserved': False, 'independentPlatformProof': 'unknown'} for path in entry['locations']],
            dispositionGranted=False)
        findings.append(entry)
    return {'schema': 1, 'status': 'triage-only', 'image': image, 'nativePolicyStatus': result['status'],
            'scannedAt': result['scannedAt'], 'policySha256': result['policySha256'], 'sbomSha256': sbom_hash,
            'blockingRecords': 0 if maintainer else len(blocked), 'blockingPairs': 0 if maintainer else len(findings),
            **({'scannerHealth': 'healthy', 'admissionStatus': 'not-evaluated',
                'observationRecords': len(blocked), 'observationPairs': len(findings)} if maintainer else {}), 'releaseBlockers': result.get('releaseBlockers', []),
            'blockingBasis': basis, 'trackedReleaseConcerns': tracked, 'policyMode': result.get('mode', 'fixable-severity'),
            'findings': findings, 'focusedRpmPackages': list(package_files.values()),
            'releaseEligible': False, 'dispositionsGranted': [], 'newScanPerformed': False,
            'releaseFreshnessReevaluated': False,
            'limits': ['Metadata and expected RPM digests are native evidence, not verification of current file bytes.',
                       'RPM relationships are not used to infer ownership; unmatched locations remain unknown.',
                       'Historical OSTree locations require their own reachability/source/byte proof.',
                       'GOOS/build metadata and absent symbols cannot independently clear findings.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite':
        parser.error('Native SBOM processing requires the hosted Finite runner')
    try:
        directory = args.directory
        result_raw, result = bounds.read(directory / 'security-result.json', MAX_OUTPUT)
        extraction_raw, extraction = bounds.read(directory / 'extraction.json')
        parent, _ = bounds.read(directory / 'image-manifest.json')
        child = bounds.read(directory / 'platform-manifest.json')[0] if (directory / 'platform-manifest.json').exists() else None
        manifests = {'parent': parent.decode(), 'child': child.decode() if child else None}
        platform = security.manifest_binding(args.image, manifests)
        if extraction.get('scannedManifestDigest') != platform:
            raise ValueError('Extraction platform manifest does not match exact requested image')
        config_raw, config = bounds.read(directory / 'image-config.json')
        descriptor = json.loads(manifests['child'] or manifests['parent'])['config']
        if (descriptor.get('digest') != 'sha256:' + hashlib.sha256(config_raw).hexdigest()
                or type(descriptor.get('size')) is not int or descriptor['size'] != len(config_raw)
                or config.get('os') != 'linux' or config.get('architecture') != 'amd64'):
            raise ValueError('Native configuration hash/size/platform binding failed')
        stream, info = bounds.regular(directory / 'sbom.syft.json', MAX_SBOM)
        with stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            if digest.hexdigest() != extraction.get('sbomSha256'):
                raise ValueError('Native SBOM hash differs from retained extraction')
            stream.seek(0)
            sbom = json.load(stream, object_pairs_hook=bounds.unique)
            after = os.fstat(stream.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('Native SBOM changed during summary generation')
        output = report(sbom, result, extraction, args.image, digest.hexdigest())
        output.update(sourceResultSha256=hashlib.sha256(result_raw).hexdigest(),
                      extractionSha256=hashlib.sha256(extraction_raw).hexdigest(),
                      configurationDigest=descriptor['digest'], scannedManifestDigest=platform,
                      configLabels=config.get('config', {}).get('Labels', {}),
                      collectorSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        encoded = json.dumps(output, indent=2) + '\n'
        if len(encoded.encode()) > MAX_OUTPUT:
            raise ValueError('Native summary exceeds compact evidence bound')
        with args.output.open('x') as stream:
            stream.write(encoded)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
