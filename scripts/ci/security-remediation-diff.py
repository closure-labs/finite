#!/usr/bin/env python3
"""Compare policy finding summaries without treating non-observation as a fix."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('security_policy', ROOT / 'scripts/bluebuild/security-policy.py')
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)
SEVERITIES = ['Unknown', 'Negligible', 'Low', 'Medium', 'High', 'Critical']
DISPOSITIONS = ('blocked', 'exception', 'advisory')


def read(path):
    with path.open('rb') as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('Expected a small ledger/result summary, not a full SBOM')
    return json.loads(data), hashlib.sha256(data).hexdigest()


def findings(entries):
    if not isinstance(entries, list):
        raise ValueError('Findings must be a list')
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Finding must be an object')
        key = entry['component'], entry['advisory']
        if not all(isinstance(value, str) and value.strip() for value in key):
            raise ValueError('Finding requires exact component and advisory')
        severity = entry['severity']
        if severity not in SEVERITIES or type(entry['knownExploited']) is not bool:
            raise ValueError('Invalid finding severity or exploitation flag')
        count = entry.get('occurrences', 1)
        fixes = entry['fixVersions']
        if (type(count) is not int or count < 1 or not isinstance(fixes, list) or
                not all(isinstance(value, str) and value for value in fixes)):
            raise ValueError('Invalid occurrence count or fix versions')
        aggregate = result.setdefault(key, {'component': key[0], 'advisory': key[1],
                                           'severity': severity, 'knownExploited': False,
                                           'fixVersions': [], 'occurrences': 0})
        aggregate['severity'] = max(aggregate['severity'], severity, key=SEVERITIES.index)
        aggregate['knownExploited'] |= entry['knownExploited']
        aggregate['fixVersions'] = sorted(set(aggregate['fixVersions']) | set(fixes))
        aggregate['occurrences'] += count
    return result


def previous_dispositions(ledger, previous):
    """Retain stated dispositions; identify legacy blocking-ledger inference."""
    result = {key: set() for key in previous}
    for entry in ledger['findings']:
        dispositions = entry.get('dispositions')
        if dispositions is None and 'disposition' in entry:
            dispositions = [entry['disposition']]
        if dispositions is not None:
            if (not isinstance(dispositions, list) or not dispositions or
                    any(value not in DISPOSITIONS for value in dispositions)):
                raise ValueError('Invalid baseline finding dispositions')
            result[(entry['component'], entry['advisory'])].update(dispositions)
    for key, values in result.items():
        if not values:
            values.add('blocked' if ledger['status'] == 'blocked' else 'unknown')
    return {key: sorted(values) for key, values in result.items()}


def compare(ledger, result, image, policy, policy_sha256, now=None):
    now = now or datetime.now(timezone.utc)
    if (not security.IMAGE.fullmatch(image) or result.get('image') != image or
            not security.IMAGE.fullmatch(ledger.get('image', '')) or image == ledger['image']):
        raise ValueError('Comparison requires a different, explicitly expected immutable image')
    if (type(ledger.get('schema')) is not int or type(result.get('schema')) is not int or
            ledger.get('schema') != 1 or result.get('schema') != 1 or
            ledger.get('status') not in ('pass', 'blocked') or result.get('status') not in ('pass', 'blocked')):
        raise ValueError('Comparison requires completed native policy results')
    if result['policySha256'] != policy_sha256:
        raise ValueError('Result was not evaluated against the current reviewed policy')
    security.fresh(result['scannedAt'], policy['maxEvidenceAgeHours'], now, 'Comparison scan')
    if security.timestamp(result['scannedAt']) <= security.timestamp(ledger['scannedAt']):
        raise ValueError('Candidate scan must be newer than the baseline scan')
    db = result['database']
    if db['status']['valid'] is not True:
        raise ValueError('Invalid scanner database')
    security.fresh(db['status']['built'], policy['maxDatabaseAgeHours'], now, 'Database')
    for provider in policy['requiredProviders']:
        security.fresh(db['providers'][provider]['captured'], policy['maxDatabaseAgeHours'], now, provider)
    coverage = result['coverage']
    if (coverage['signedDigest'] != image.split('@')[1] or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', coverage['scannedManifestDigest']) or
            not re.fullmatch(r'fedora:[0-9]{2}', coverage['effective']) or
            type(coverage['rpmPackages']) is not int or coverage['rpmPackages'] < policy['minimumRpmPackages'] or
            type(result['databaseCoverageRecords']) is not int or result['databaseCoverageRecords'] < 1):
        raise ValueError('Result lacks validated digest/distribution/inventory coverage')
    previous = findings(ledger['findings'])
    risk_mode = policy.get('mode') == 'upstream-maintained-risk'
    if risk_mode and result.get('mode') != 'upstream-maintained-risk':
        raise ValueError('Result does not identify the reviewed risk policy mode')
    if risk_mode and 'advisories' not in result:
        raise ValueError('Risk policy result must retain advisory observations')
    if risk_mode and 'releaseBlockers' not in result:
        raise ValueError('Risk policy result must retain reviewed source release blockers')
    holds = security.release_blockers({'releaseBlockers': result.get('releaseBlockers', [])}, now)
    advisory_entries = result.get('advisories', [])
    blocked, waived, advisories = (findings(result['blocked']), findings(result['exceptionsApplied']),
                                   findings(advisory_entries))
    if (result['status'] == 'blocked') != bool(blocked or holds):
        raise ValueError('Result status contradicts its blocking findings or source release blockers')
    current = findings([*result['blocked'], *result['exceptionsApplied'], *advisory_entries])
    previous_groups = previous_dispositions(ledger, previous)
    explicit_previous = {(entry['component'], entry['advisory']) for entry in ledger['findings']
                         if 'dispositions' in entry or 'disposition' in entry}
    for key, entry in current.items():
        entry['dispositions'] = [name for name, group in [('blocked', blocked), ('exception', waived),
                                                         ('advisory', advisories)]
                                 if key in group]
    persistent = sorted(previous.keys() & current.keys())
    return {'schema': 1, 'status': 'comparison-complete', 'baselineImage': ledger['image'],
            'image': image, 'scannedAt': result['scannedAt'], 'scanStatus': result['status'],
            'baselinePolicySha256': ledger['policySha256'], 'policySha256': policy_sha256,
            'policyChanged': ledger['policySha256'] != policy_sha256,
            'releaseBlockers': holds,
            'scope': 'Exact component/advisory pairs observed in blocking findings, reviewed exceptions, and advisories. Policy disposition changes do not resolve findings.',
            'counts': {'blockingRecords': sum(entry['occurrences'] for entry in blocked.values()),
                       'exceptionRecords': sum(entry['occurrences'] for entry in waived.values()),
                       'advisoryRecords': sum(entry['occurrences'] for entry in advisories.values()),
                       'releaseBlockerRecords': len(holds),
                       'observedPairs': len(current)},
            'note': 'Not observed does not mean resolved: package versions, advisory matching, coverage or policy may change. Expanded advisory observation scope can add new pairs without new vulnerable content. A changed disposition does not mean a fix. This summary comparison does not replace native evidence verification or remediation review.',
            'persistent': [current[key] for key in persistent],
            'new': [current[key] for key in sorted(current.keys() - previous.keys())],
            'notObserved': [{**previous[key], 'remediationStatus': 'review-required'}
                            for key in sorted(previous.keys() - current.keys())],
            'dispositionChanges': [{'component': key[0], 'advisory': key[1],
                                    'previous': previous_groups[key], 'current': current[key]['dispositions'],
                                    'previousBasis': 'explicit' if key in explicit_previous
                                        else 'legacy-blocking-ledger' if ledger['status'] == 'blocked' else 'unknown',
                                    'remediationStatus': 'review-required'}
                                   for key in persistent if set(previous_groups[key]) != set(current[key]['dispositions'])],
            'severityChanges': [{'component': key[0], 'advisory': key[1],
                                 'previous': previous[key]['severity'], 'current': current[key]['severity']}
                                for key in persistent if previous[key]['severity'] != current[key]['severity']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('result', type=Path)
    parser.add_argument('image')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        ledger, ledger_hash = read(args.ledger)
        result, result_hash = read(args.result)
        policy, policy_hash = read(ROOT / 'automation/security/image-policy.json')
        comparison = compare(ledger, result, args.image, policy, policy_hash)
        comparison.update(baselineLedgerSha256=ledger_hash, sourceResultSha256=result_hash)
        encoded = json.dumps(comparison, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded)
        else:
            print(encoded, end='')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
