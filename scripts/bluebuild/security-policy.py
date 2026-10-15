#!/usr/bin/env python3
"""Evaluate digest-bound native Syft/Grype evidence; scanner errors fail separately."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
IMAGE = re.compile(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}')
ADVISORY = re.compile(r'(?:CVE-[0-9]{4}-[0-9]{4,}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|GO-[0-9]{4}-[0-9]+)')
RELATED_ADVISORY = re.compile(r'(?:' + ADVISORY.pattern + r'|FEDORA(?:-EPEL)?-[0-9]{4}-[0-9a-f]{10}|'
                              r'(?:PYSEC|RUSTSEC|OSV)-[0-9]{4}-[0-9]+)')
RISK_CLASSES = {'desktop-takeover', 'local-privilege-escalation', 'container-escape',
                'authentication-bypass', 'tls-identity-bypass', 'major-data-loss', 'unresolved-serious'}
PROFILES = {'finite', 'finite-dev'}
RISK_MODES = {'upstream-maintained-risk', 'desktop-critical-only'}
SEVERITIES = {'Unknown', 'Negligible', 'Low', 'Medium', 'High', 'Critical'}


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
    validate_policy(policy)
    return policy


def nonempty(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def reviewed_rules(policy, now):
    """Validate review selectors before looking at matches, including unused rules."""
    ids, aliases = set(), set()
    serious, dispositions = {}, []
    common = {'id', 'advisories', 'reason', 'officialSources', 'reviewedBy', 'reviewedAt'}
    for field, extra in [('seriousAdvisories', {'riskClass'}), ('reviewedDispositions',
                          {'digest', 'component', 'platform', 'locations', 'disposition', 'evidence', 'expiresAt'})]:
        entries = policy.get(field)
        if not isinstance(entries, list):
            raise ValueError('Risk policy requires explicit reviewed rule lists')
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != common | extra:
                raise ValueError('Reviewed rule requires exact documented scope')
            if (not all(nonempty(entry[key]) for key in common - {'advisories', 'officialSources'})
                    or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', entry['id'])
                    or entry['id'] in ids):
                raise ValueError('Invalid or duplicate reviewed rule identity')
            ids.add(entry['id'])
            group = entry['advisories']
            if (not isinstance(group, list) or not group or len(group) > 64 or
                    any(not isinstance(value, str) or not ADVISORY.fullmatch(value) for value in group)
                    or len(set(group)) != len(group)):
                raise ValueError('Reviewed rule requires bounded exact advisory aliases')
            sources = entry['officialSources']
            if not isinstance(sources, list) or not sources or len(sources) > 32:
                raise ValueError('Reviewed rule requires official source links')
            for source in sources:
                if not nonempty(source):
                    raise ValueError('Invalid official source link')
                url = urlsplit(source)
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError('Official source links must use HTTPS without credentials')
            reviewed = timestamp(entry['reviewedAt'])
            if reviewed > now:
                raise ValueError('Review cannot be from the future')
            if field == 'seriousAdvisories':
                if (not isinstance(entry['riskClass'], str) or entry['riskClass'] not in RISK_CLASSES
                        or aliases.intersection(group)):
                    raise ValueError('Invalid risk class or overlapping serious advisory groups')
                aliases.update(group)
                serious.update({alias: entry for alias in group})
            else:
                expires = timestamp(entry['expiresAt'])
                if (expires <= reviewed or expires - reviewed > timedelta(days=policy['maxExceptionDays'])
                        or not isinstance(entry['digest'], str)
                        or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['digest'])
                        or not nonempty(entry['component']) or '*' in entry['component']
                        or (entry['component'].startswith('pkg:') and '@' not in entry['component'])
                        or entry['platform'] != 'linux/amd64'
                        or not isinstance(entry['locations'], list) or not entry['locations']
                        or len(entry['locations']) > 1024
                        or any(not canonical_location(v) for v in entry['locations'])
                        or len(set(entry['locations'])) != len(entry['locations'])
                        or not isinstance(entry['disposition'], str)
                        or entry['disposition'] not in {'nonapplicable', 'backported', 'routine'}
                        or not isinstance(entry['evidence'], list) or not entry['evidence']
                        or len(entry['evidence']) > 64 or not all(nonempty(v) for v in entry['evidence'])):
                    raise ValueError('Invalid reviewed disposition evidence, scope or expiry')
                dispositions.append(entry)
    scopes = set()
    for entry in dispositions:
        for advisory in entry['advisories']:
            scope = entry['digest'], entry['component'], entry['platform'], advisory
            if scope in scopes or (advisory in serious and entry['disposition'] == 'routine'):
                raise ValueError('Conflicting reviewed disposition or routine waiver of serious risk')
            scopes.add(scope)
    return serious, dispositions


def release_blockers(policy, now):
    """Validate source concerns; explicit Critical holds survive missing scanner matches."""
    entries = policy.get('releaseBlockers', [])
    fields = {'id', 'profiles', 'riskClass', 'reason', 'officialSources', 'reviewedBy',
              'reviewedAt', 'unblockEvidence'}
    if not isinstance(entries, list) or len(entries) > 128:
        raise ValueError('Release blockers must be a bounded reviewed list')
    critical_only = policy.get('mode') == 'desktop-critical-only'
    if critical_only:
        fields |= {'severity', 'advisories'}
    ids = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != fields
                or not all(nonempty(entry[key]) for key in fields - {'profiles', 'officialSources', 'advisories'})
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', entry['id']) or entry['id'] in ids
                or entry['riskClass'] not in RISK_CLASSES):
            raise ValueError('Release blocker requires exact documented review')
        if critical_only:
            aliases = entry['advisories']
            if (entry['severity'] not in SEVERITIES or not isinstance(aliases, list)
                    or len(aliases) > 64
                    or any(not isinstance(v, str) or not ADVISORY.fullmatch(v) for v in aliases)
                    or len(set(aliases)) != len(aliases)
                    or (entry['severity'] == 'Critical' and not aliases)):
                raise ValueError('Source concern requires exact severity and advisory classification')
        ids.add(entry['id'])
        profiles = entry['profiles']
        if (not isinstance(profiles, list) or not profiles or len(profiles) > len(PROFILES)
                or any(not isinstance(value, str) or value not in PROFILES for value in profiles)
                or len(set(profiles)) != len(profiles)):
            raise ValueError('Release blocker requires exact supported profiles')
        sources = entry['officialSources']
        if not isinstance(sources, list) or not sources or len(sources) > 32:
            raise ValueError('Release blocker requires official source links')
        for source in sources:
            if not nonempty(source):
                raise ValueError('Invalid release blocker source link')
            url = urlsplit(source)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('Release blocker sources must use HTTPS without credentials')
        if timestamp(entry['reviewedAt']) > now:
            raise ValueError('Release blocker review cannot be from the future')
    return entries



def confirmed_desktop_risks(policy, now):
    """Review receipts establish risk; scanner advisory pairs alone do not."""
    entries = policy['confirmedDesktopRisks']
    lists = {'advisories', 'locations', 'officialSources', 'severityEvidence',
             'affectedCodeEvidence', 'preconditions', 'selinuxEvidence'}
    fields = lists | {'id', 'digest', 'profile', 'platform', 'component', 'severity',
                      'impact', 'reason', 'attackerPath', 'selinuxAssessment', 'reviewedBy', 'reviewedAt'}
    if not isinstance(entries, list) or len(entries) > 128:
        raise ValueError('Confirmed desktop risks require a bounded reviewed list')
    ids = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != fields
                or not all(nonempty(entry[key]) and len(entry[key]) <= 8192 for key in fields - lists)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', entry['id']) or entry['id'] in ids
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['digest'])
                or entry['profile'] not in PROFILES or entry['platform'] != 'linux/amd64'
                or '*' in entry['component']
                or (entry['component'].startswith('pkg:') and '@' not in entry['component'])
                or entry['severity'] != 'Critical'):
            raise ValueError('Confirmed desktop risk requires exact Critical candidate scope and review')
        ids.add(entry['id'])
        for key in lists:
            values = entry[key]
            if (not isinstance(values, list) or not values or len(values) > 64
                    or any(not nonempty(v) or len(v) > 8192 for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError('Confirmed desktop risk requires bounded evidence: ' + key)
        if (any(not ADVISORY.fullmatch(v) for v in entry['advisories'])
                or any(not canonical_location(v) for v in entry['locations'])):
            raise ValueError('Confirmed desktop risk requires exact advisories and shipped paths')
        for source in entry['officialSources']:
            url = urlsplit(source)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('Confirmed desktop risk requires official HTTPS sources')
        if timestamp(entry['reviewedAt']) > now:
            raise ValueError('Confirmed desktop risk review cannot be from the future')
    return entries



def validate_confirmed_findings(findings, holds):
    """Bind blocked scanner observations to independently validated exact-image holds."""
    if not isinstance(findings, list):
        raise ValueError('Confirmed findings must be a list')
    for finding in findings:
        if (not isinstance(finding, dict) or finding.get('disposition') != 'blocked'
                or finding.get('reason') != 'confirmed-desktop-exploitability'
                or not nonempty(finding.get('component')) or finding.get('locationCoverage') != 'complete'):
            raise ValueError('Blocked observation lacks confirmed desktop risk binding')
        for key in ('confirmedRiskReviews', 'aliases', 'locations'):
            values = finding.get(key)
            if (not isinstance(values, list) or not values or not all(nonempty(v) for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError('Invalid confirmed observation selectors')
        if any(not canonical_location(v) for v in finding['locations']):
            raise ValueError('Confirmed observation requires canonical shipped paths')
        expected = sorted(entry['id'] for entry in holds
                          if entry['component'] == finding['component']
                          and set(finding['aliases']).intersection(entry['advisories'])
                          and set(finding['locations']).intersection(entry['locations']))
        if not expected or finding['confirmedRiskReviews'] != expected:
            raise ValueError('Confirmed observation differs from reviewed source risk')


def validate_policy(policy, now=None):
    if not isinstance(policy, dict) or type(policy.get('schema')) is not int or policy['schema'] != 1:
        raise ValueError('Unsupported image security policy')
    mode = policy.get('mode', 'fixable-severity')
    if not isinstance(mode, str) or mode not in {'fixable-severity', *RISK_MODES}:
        raise ValueError('Unsupported image security policy mode')
    if mode in RISK_MODES:
        expected = {'schema', 'mode', 'maxDatabaseAgeHours', 'maxEvidenceAgeHours', 'maxExceptionDays',
                    'distributionAliases', 'requiredReleasePackage', 'minimumRpmPackages', 'requiredProviders',
                    'blockedFixableSeverities', 'blockKnownExploited', 'exceptions', 'coverageProbePackage',
                    'seriousAdvisories', 'reviewedDispositions', 'releaseBlockers'}
        if 'blockingBasis' in policy or 'confirmedDesktopRisks' in policy:
            if mode != 'desktop-critical-only' or policy.get('blockingBasis') != 'reviewed-desktop-exploitability':
                raise ValueError('Unsupported desktop release blocking basis')
            expected |= {'blockingBasis', 'confirmedDesktopRisks'}
        if not expected - {'releaseBlockers'} <= set(policy) <= expected:
            raise ValueError('Risk policy requires exact supported fields')
        if mode == 'upstream-maintained-risk' and policy.get('blockKnownExploited') is not True:
            raise ValueError('Upstream risk policy cannot disable known exploitation protection')
        if mode == 'desktop-critical-only' and (policy.get('blockKnownExploited') is not False
                or policy.get('blockedFixableSeverities') != ['Critical']):
            raise ValueError('Desktop policy must explicitly track lower severity exploitation without blocking')
        if type(policy.get('maxExceptionDays')) is not int or not 1 <= policy['maxExceptionDays'] <= 30:
            raise ValueError('Risk review windows cannot exceed 30 days')
        reviewed_rules(policy, now or datetime.now(timezone.utc))
        release_blockers(policy, now or datetime.now(timezone.utc))
        if 'blockingBasis' in policy:
            confirmed_desktop_risks(policy, now or datetime.now(timezone.utc))
    return mode


def canonical_location(value):
    return (nonempty(value) and value.startswith('/') and value != '/'
            and '..' not in PurePosixPath(value).parts and str(PurePosixPath(value)) == value)


def component_locations(artifact, sbom):
    """Normalize scanner paths lexically; missing/unknown evidence can never prove absence."""
    entries = artifact.get('locations', [])
    if not isinstance(entries, list):
        raise ValueError('Invalid component locations')
    paths, complete = set(), bool(entries)
    source = sbom['source']
    prefix = source['metadata']['path'] if source['type'] == 'directory' else None
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid component location record')
        values = [entry[key] for key in ('path', 'accessPath', 'realPath') if key in entry]
        if not values:
            complete = False
        for value in values:
            if not canonical_location(value):
                complete = False
                continue
            if prefix and value.startswith(prefix + '/'):
                value = value[len(prefix):]
            if not canonical_location(value):
                complete = False
                continue
            paths.add(value)
    return sorted(paths), complete


def scanner_fix(fix):
    """Grype 0.112's presenter can emit zero-value state with allocated empty versions."""
    if (not isinstance(fix, dict) or not isinstance(fix.get('state'), str)
            or not isinstance(fix.get('versions'), list)
            or not all(nonempty(value) for value in fix['versions'])):
        raise ValueError('Invalid scanner fix metadata')
    state, versions = fix['state'], fix['versions']
    if state == '':
        if versions:
            raise ValueError('Unspecified scanner fix state cannot claim fixed versions')
        state = 'unknown'
    elif state not in {'fixed', 'not-fixed', 'unknown', 'wont-fix'}:
        raise ValueError('Unsupported scanner fix state')
    return state, list(versions)


def baseline_context(context, image):
    """Check binding of a caller-authenticated publisher receipt, never infer trust from distro."""
    fields = {'schema', 'status', 'image', 'profile', 'sourceRevision', 'buildIdentity',
              'baseImage', 'trustPolicySha256'}
    if (not isinstance(context, dict) or set(context) != fields or type(context['schema']) is not int
            or context['schema'] != 1 or context['status'] != 'verified' or context['image'] != image
            or not isinstance(context['profile'], str) or context['profile'] not in PROFILES
            or not isinstance(context['sourceRevision'], str)
            or not re.fullmatch(r'[0-9a-f]{40}', context['sourceRevision'])
            or not isinstance(context['buildIdentity'], str)
            or not re.fullmatch(r'v1:[0-9a-f]{64}', context['buildIdentity'])
            or not isinstance(context['trustPolicySha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', context['trustPolicySha256'])
            or not isinstance(context['baseImage'], str)
            or not re.fullmatch(r'ghcr\.io/ublue-os/bluefin(?:-dx)?@sha256:[0-9a-f]{64}', context['baseImage'])):
        raise ValueError('Upstream risk policy requires authenticated, digest-bound approved baseline context')
    foundation = {'finite': 'bluefin', 'finite-dev': 'bluefin-dx'}[context['profile']]
    if not context['baseImage'].startswith('ghcr.io/ublue-os/' + foundation + '@'):
        raise ValueError('Approved baseline does not match candidate profile')
    return dict(context)


def baseline_binding(context, image, manifests):
    context = baseline_context(context, image)
    if not isinstance(manifests, dict) or 'config' not in manifests:
        raise ValueError('Risk policy requires immutable image configuration evidence')
    manifest_binding(image, manifests)
    selected = manifest_document(manifests.get('child') or manifests['parent'])
    descriptor = selected.get('config')
    raw = manifests['config']
    if (not isinstance(raw, str) or len(raw.encode()) > MANIFEST_LIMIT
            or not isinstance(descriptor, dict)
            or descriptor.get('mediaType') not in {'application/vnd.oci.image.config.v1+json',
                                                    'application/vnd.docker.container.image.v1+json'}
            or type(descriptor.get('size')) is not int or descriptor['size'] != len(raw.encode())
            or descriptor.get('digest') != 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()):
        raise ValueError('Image configuration does not match the immutable manifest descriptor')
    config = json.loads(raw)
    if (not isinstance(config, dict) or config.get('os') != 'linux' or config.get('architecture') != 'amd64'
            or config.get('variant', '') not in ('', 'v1')):
        raise ValueError('Risk policy image configuration must be linux/amd64')
    runtime = config.get('config')
    labels = runtime.get('Labels') if isinstance(runtime, dict) else None
    expected = {'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                'org.opencontainers.image.revision': context['sourceRevision'],
                'io.finite.profile': context['profile'], 'io.finite.build-inputs': context['buildIdentity'],
                'org.opencontainers.image.base.name': context['baseImage'].replace('@', ':stable@', 1),
                'org.opencontainers.image.base.digest': context['baseImage'].split('@')[1]}
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError('Approved baseline does not match immutable candidate configuration labels')
    return context


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
    for key, name in [('parent', 'image-manifest.json'), ('child', 'platform-manifest.json'),
                      ('config', 'image-config.json')]:
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


def read_baseline(directory, path=None):
    path = path or directory / 'approved-baseline.json'
    if not path.exists():
        return None
    if path.stat().st_size > MANIFEST_LIMIT:
        raise ValueError('Approved baseline receipt exceeds the metadata limit')
    return json.loads(path.read_text())


def production_baseline(directory, image, policy, manifests, context):
    """Require the protected producer's publisher receipt as well as bound context."""
    if policy.get('mode', 'fixable-severity') not in RISK_MODES:
        return context
    context = baseline_binding(context, image, manifests)
    spec = importlib.util.spec_from_file_location('security_approved_baseline',
                                                 ROOT / 'scripts/ci/approved-baseline.py')
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    receipt, _ = producer.read(directory / 'upstream-verification.json')
    verified = producer.context(json.loads(manifests['config']), image, receipt, ROOT)
    if verified != context:
        raise ValueError('Approved baseline differs from protected publisher verification receipt')
    return verified


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


def evaluate(sbom, scan, image, policy, now=None, database_coverage=None, manifests=None,
             approved_baseline=None):
    now = now or datetime.now(timezone.utc)
    mode = validate_policy(policy, now)
    baseline = baseline_binding(approved_baseline, image, manifests) if mode in RISK_MODES else None
    serious, dispositions = reviewed_rules(policy, now) if baseline else ({}, [])
    holds = [entry for entry in release_blockers(policy, now)
             if baseline['profile'] in entry['profiles']] if baseline else []
    reviewed_basis = policy.get('blockingBasis') == 'reviewed-desktop-exploitability'
    tracked_holds = []
    if reviewed_basis:
        tracked_holds = holds
        holds = [entry for entry in confirmed_desktop_risks(policy, now)
                 if entry['digest'] == image.split('@')[1] and entry['profile'] == baseline['profile']]
    elif mode == 'desktop-critical-only':
        tracked_holds = [entry for entry in holds if entry['severity'] != 'Critical']
        holds = [entry for entry in holds if entry['severity'] == 'Critical']
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
    blocked, waived, advisories, observations = [], [], [], []
    matches = scan['matches']
    if not isinstance(matches, list):
        raise ValueError('Invalid scanner matches')
    # Grype's built-in suppressions do not override our reviewed policy.
    matches = [*matches, *scan.get('ignoredMatches', [])]
    for match in matches:
        if (not isinstance(match, dict) or not isinstance(match.get('vulnerability'), dict)
                or not isinstance(match.get('artifact'), dict)):
            raise ValueError('Invalid scanner vulnerability match')
        vulnerability, artifact = match['vulnerability'], match['artifact']
        related = match.get('relatedVulnerabilities')
        related = [] if related is None else related
        if not isinstance(related, list) or any(not isinstance(v, dict) for v in related):
            raise ValueError('Invalid related vulnerability aliases')
        if baseline and any(not nonempty(v.get('id')) or not RELATED_ADVISORY.fullmatch(v['id']) for v in related):
            raise ValueError('Risk policy requires valid related advisory identifiers')
        if any('severity' in v and (not isinstance(v['severity'], str) or v['severity'] not in SEVERITIES)
               for v in related):
            raise ValueError('Invalid related vulnerability severity')
        alias_ids = sorted({v['id'] for v in [vulnerability, *related] if nonempty(v.get('id'))})
        known = any(v.get('knownExploited') for v in [vulnerability, *related])
        fix_state, fix_versions = scanner_fix(vulnerability['fix'])
        if (not isinstance(vulnerability.get('severity'), str)
                or vulnerability['severity'] not in SEVERITIES or not nonempty(vulnerability.get('id'))):
            raise ValueError('Invalid scanner vulnerability severity or advisory')
        fixable = fix_state == 'fixed' and bool(fix_versions)
        known_blocked = known and policy['blockKnownExploited']
        # Artifact ID remains usable for embedded components lacking a PURL;
        # it is scoped to this exact digest, never to a package-name wildcard.
        component = artifact.get('purl') or artifact['id']
        if not nonempty(component):
            raise ValueError('Finding lacks an exact component identity')
        locations, location_complete = component_locations(artifact, sbom)
        finding = {'component': component, 'advisory': vulnerability['id'],
                   'severity': vulnerability['severity'], 'knownExploited': bool(known),
                   'fixVersions': fix_versions, 'fixState': fix_state, 'aliases': alias_ids,
                   'locations': locations, 'locationCoverage': 'complete' if location_complete else 'unknown'}
        if baseline:
            rules = {serious[alias]['id']: serious[alias] for alias in alias_ids if alias in serious}
            critical_aliases = sorted({v['id'] for v in [vulnerability, *related]
                                       if v.get('severity') == 'Critical'})
            critical = bool(critical_aliases)
            if mode == 'desktop-critical-only':
                finding['criticalSeverityAdvisories'] = critical_aliases
            proof = [entry for entry in dispositions
                     if entry['digest'] == image.split('@')[1] and entry['component'] == component
                     and timestamp(entry['expiresAt']) > now
                     and set(alias_ids).issubset(entry['advisories'])
                     and location_complete and set(locations).issubset(entry['locations'])]
            if len(proof) > 1:
                raise ValueError('Multiple reviewed dispositions match one occurrence')
            reviewed = proof[0] if proof else None
            if mode == 'desktop-critical-only':
                cleared = reviewed and reviewed['disposition'] in {'nonapplicable', 'backported'}
                if critical and not cleared:
                    disposition, reason = ('advisory', 'critical-applicability-unresolved') if reviewed_basis else (
                        'blocked', 'critical-applicability-pending-review')
                else:
                    disposition = 'advisory'
                    reason = 'reviewed-' + reviewed['disposition'] if cleared else 'below-critical-release-threshold'
            elif known_blocked:
                disposition, reason = 'blocked', 'known-exploited'
            elif rules and not (reviewed and reviewed['disposition'] in {'nonapplicable', 'backported'}):
                disposition, reason = 'blocked', 'reviewed-serious-risk'
            elif critical and not reviewed:
                disposition, reason = 'blocked', 'untriaged-critical'
            else:
                disposition = 'advisory'
                reason = 'reviewed-' + reviewed['disposition'] if reviewed else 'maintained-upstream-advisory'
            if reviewed_basis:
                confirmed = [entry['id'] for entry in holds if entry['component'] == component
                             and set(alias_ids).intersection(entry['advisories'])
                             and location_complete and set(locations).intersection(entry['locations'])]
                if confirmed:
                    disposition, reason = 'blocked', 'confirmed-desktop-exploitability'
                    finding['confirmedRiskReviews'] = sorted(confirmed)
            finding.update(disposition=disposition, reason=reason, reviewRules=sorted(rules),
                           riskClasses=sorted({entry['riskClass'] for entry in rules.values()}))
            if reviewed and disposition == 'advisory':
                finding['reviewedDisposition'] = reviewed['id']
            (blocked if disposition == 'blocked' else advisories).append(finding)
        else:
            severity_blocked = fixable and vulnerability['severity'] in policy['blockedFixableSeverities']
            exception_applies = ((component, vulnerability['id']) in exceptions
                                 and not known_blocked and severity_blocked)
            disposition = 'blocked' if known_blocked or (severity_blocked and not exception_applies) else (
                'exception' if exception_applies else 'advisory')
            finding.update(disposition=disposition, reason='known-exploited' if known_blocked else (
                'fixable-severity' if severity_blocked else 'outside-legacy-blocking-scope'))
            {'blocked': blocked, 'exception': waived, 'advisory': advisories}[disposition].append(finding)
        # Exceptions and scanner suppressions never erase observations.
        # Desktop-critical mode explicitly tracks lower-severity exploitation.
        observations.append(finding)
    result = {'schema': 1, 'status': 'blocked' if blocked or holds else 'pass', 'image': image,
            'scannedAt': descriptor['timestamp'], 'scanner': descriptor['version'],
            'database': db, 'coverage': coverage, 'databaseCoverageRecords': len(database_coverage),
            'matches': len(matches),
            'mode': mode, 'approvedBaseline': baseline,
            'releaseBlockers': holds,
            'blocked': blocked, 'exceptionsApplied': waived, 'advisories': advisories,
            'observations': observations}
    if mode == 'desktop-critical-only':
        result['trackedReleaseConcerns'] = tracked_holds
    if reviewed_basis:
        validate_confirmed_findings(blocked, holds)
        result['blockingBasis'] = policy['blockingBasis']
    return result


def verify(directory, image, policy_path=ROOT / 'automation/security/image-policy.json',
           approved_baseline=None):
    policy = load_policy(policy_path)
    # Representative local copies are useful diagnostics, but cannot qualify
    # registry candidates for signing or release even when native policy passes.
    for name in ('extraction.json', 'source-provenance.json', 'security-result.json'):
        path = directory / name
        if path.exists():
            record = json.loads(path.read_text())
            if not isinstance(record, dict):
                raise ValueError('Invalid release evidence provenance')
            if (record.get('releaseEligible') is False
                    or record.get('sourceType') == 'locally-built-unpublished'):
                raise ValueError('Diagnostic local candidate evidence cannot qualify a release')
    if approved_baseline is None:
        approved_baseline = read_baseline(directory)
    manifests = read_manifests(directory)
    approved_baseline = production_baseline(directory, image, policy, manifests, approved_baseline)
    sbom = json.loads((directory / 'sbom.syft.json').read_text())
    scan = json.loads((directory / 'vulnerabilities.json').read_text())
    result = evaluate(sbom, scan, image, policy,
                      database_coverage=json.loads((directory / 'database-coverage.json').read_text()),
                      manifests=manifests, approved_baseline=approved_baseline)
    if result['status'] != 'pass':
        raise ValueError('Candidate violates image vulnerability policy')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('image')
    parser.add_argument('--policy', type=Path, default=ROOT / 'automation/security/image-policy.json')
    parser.add_argument('--approved-baseline', type=Path,
                        help='Receipt independently authenticated by the invoking release workflow')
    args = parser.parse_args()
    try:
        policy = load_policy(args.policy)
        manifests = read_manifests(args.directory)
        baseline = production_baseline(args.directory, args.image, policy, manifests,
                                       read_baseline(args.directory, args.approved_baseline))
        result = evaluate(json.loads((args.directory / 'sbom.syft.json').read_text()),
                          json.loads((args.directory / 'vulnerabilities.json').read_text()),
                          args.image, policy, database_coverage=
                          json.loads((args.directory / 'database-coverage.json').read_text()),
                          manifests=manifests, approved_baseline=baseline)
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
