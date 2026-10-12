#!/usr/bin/env python3
"""Small result-only remediation comparisons fail closed and never resolve issues."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('remediation', ROOT / 'scripts/ci/security-remediation-diff.py')
remediation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remediation)
OLD = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
NEW = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64
STAMP = '2026-10-12T12:00:00Z'
NOW = datetime(2026, 10, 12, 13, tzinfo=timezone.utc)


def finding(component='pkg:rpm/fedora/example@1', advisory='CVE-2026-1', severity='High'):
    return {'component': component, 'advisory': advisory, 'severity': severity,
            'knownExploited': False, 'fixVersions': ['2']}


class Remediation(unittest.TestCase):
    def setUp(self):
        self.policy, self.policy_hash = remediation.read(ROOT / 'automation/security/image-policy.json')
        self.ledger = {'schema': 1, 'status': 'blocked', 'image': OLD,
                       'scannedAt': '2026-10-12T10:00:00Z', 'policySha256': self.policy_hash,
                       'findings': [finding(), finding(advisory='CVE-2026-2')]}
        self.result = {'schema': 1, 'status': 'blocked', 'image': NEW,
                       'scannedAt': STAMP, 'policySha256': self.policy_hash,
                       'database': {'status': {'valid': True, 'built': STAMP},
                                    'providers': {'fedora': {'captured': STAMP}, 'kev': {'captured': STAMP}}},
                       'coverage': {'signedDigest': NEW.split('@')[1], 'scannedManifestDigest': NEW.split('@')[1],
                                    'effective': 'fedora:44', 'rpmPackages': 100}, 'databaseCoverageRecords': 1,
                       'blocked': [finding(severity='Critical'), finding(advisory='CVE-2026-3')],
                       'exceptionsApplied': []}

    def compare(self):
        return remediation.compare(self.ledger, self.result, NEW, self.policy, self.policy_hash, NOW)

    def test_deduplicates_and_reports_changes_without_resolving(self):
        self.result['blocked'].append(finding())
        self.ledger['findings'][0]['occurrences'] = 4
        result = self.compare()
        self.assertEqual([x['advisory'] for x in result['persistent']], ['CVE-2026-1'])
        self.assertEqual(result['persistent'][0]['severity'], 'Critical')
        self.assertEqual(result['persistent'][0]['occurrences'], 2)
        self.assertEqual([x['advisory'] for x in result['new']], ['CVE-2026-3'])
        self.assertEqual([x['advisory'] for x in result['notObserved']], ['CVE-2026-2'])
        self.assertEqual(result['notObserved'][0]['remediationStatus'], 'review-required')
        self.assertEqual(result['severityChanges'][0]['previous'], 'High')
        self.assertEqual(result['severityChanges'][0]['current'], 'Critical')
        self.assertNotIn('resolved', result)

    def test_exceptions_remain_observed_and_version_changes_are_exact(self):
        self.result['exceptionsApplied'] = [finding()]
        self.result['blocked'] = [finding(component='pkg:rpm/fedora/example@2')]
        result = self.compare()
        self.assertEqual(result['persistent'][0]['dispositions'], ['exception'])
        self.assertEqual(result['new'][0]['component'], 'pkg:rpm/fedora/example@2')
        self.assertEqual(len(result['notObserved']), 1)
        self.result.update(status='pass', blocked=[])
        self.assertEqual(len(self.compare()['persistent']), 1)

    def test_completed_pass_still_requires_review_of_non_observation(self):
        self.result.update(status='pass', blocked=[], exceptionsApplied=[])
        result = self.compare()
        self.assertEqual(result['scanStatus'], 'pass')
        self.assertEqual(len(result['notObserved']), 2)
        self.assertTrue(all(x['remediationStatus'] == 'review-required' for x in result['notObserved']))

    def test_wrong_same_mutable_digest_and_scanner_error_rejected(self):
        for key, value in [('schema', True), ('status', 'scanner-error'), ('status', 'running'),
                           ('image', OLD), ('image', 'ghcr.io/closure-labs/finite:finite'),
                           ('policySha256', '0' * 64)]:
            with self.subTest(key=key, value=value):
                original = deepcopy(self.result)
                self.result[key] = value
                with self.assertRaises(ValueError): self.compare()
                self.result = original
        self.ledger['image'] = NEW
        with self.assertRaises(ValueError): self.compare()

    def test_incomplete_coverage_stale_or_older_result_rejected(self):
        changes = [lambda d: d['coverage'].update(signedDigest='sha256:' + 'c' * 64),
                   lambda d: d['coverage'].update(rpmPackages=0),
                   lambda d: d['coverage'].update(rpmPackages=True),
                   lambda d: d['coverage'].update(effective='unknown:44'),
                   lambda d: d.update(databaseCoverageRecords=0),
                   lambda d: d['database']['status'].update(valid=False),
                   lambda d: d['database']['providers']['kev'].update(captured='2026-09-01T12:00:00Z'),
                   lambda d: d.update(scannedAt='2026-09-01T12:00:00Z'),
                   lambda d: d.update(scannedAt='2026-10-12T09:00:00Z'),
                   lambda d: d.update(scannedAt='2026-10-13T12:00:00Z'),
                   lambda d: d.update(status='pass')]
        for change in changes:
            self.setUp()
            change(self.result)
            with self.assertRaises(ValueError): self.compare()

    def test_policy_changes_are_visible_and_inputs_not_mutated(self):
        self.ledger['policySha256'] = 'c' * 64
        before = deepcopy((self.ledger, self.result))
        self.assertTrue(self.compare()['policyChanged'])
        self.assertEqual(before, (self.ledger, self.result))

    def test_summary_hash_binds_exact_input_bytes(self):
        path = ROOT / 'docs/security-remediation-2026-10-12.json'
        ledger, checksum = remediation.read(path)
        self.assertEqual(checksum, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(ledger['schema'], 1)


if __name__ == '__main__':
    unittest.main()
