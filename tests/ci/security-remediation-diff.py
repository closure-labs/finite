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


def hold():
    return {'id': 'next-kernel-source-hold', 'profiles': ['bluefin-next'],
            'riskClass': 'local-privilege-escalation', 'reason': 'Unqualified source fix',
            'officialSources': ['https://kernel.org/'], 'reviewedBy': 'Security reviewer',
            'reviewedAt': STAMP, 'unblockEvidence': 'Authenticated compatible fix and boot qualification'}


def confirmed_risk(image, profile='bluefin-generic'):
    return {'id': 'confirmed-fixture', 'digest': image.split('@')[1], 'profile': profile,
            'platform': 'linux/amd64', 'component': 'pkg:rpm/fedora/example@1', 'severity': 'Critical',
            'impact': 'Host compromise', 'reason': 'Fixture review', 'attackerPath': 'Hostile imported file',
            'selinuxAssessment': 'Applicable confinement does not prevent the confirmed path',
            'reviewedBy': 'Fixture reviewer', 'reviewedAt': '2026-10-12T00:00:00Z',
            'advisories': ['CVE-2026-1234'], 'locations': ['/usr/bin/example'],
            'officialSources': ['https://example.org/advisory'], 'severityEvidence': ['Official Critical rating'],
            'affectedCodeEvidence': ['Exact binary and vulnerable code reviewed'],
            'preconditions': ['Supported desktop import'], 'selinuxEvidence': ['Relevant domain reviewed']}


class Remediation(unittest.TestCase):
    def setUp(self):
        self.policy, self.policy_hash = remediation.read(ROOT / 'automation/security/image-policy.json')
        # These original fixtures exercise the legacy result contract regardless
        # of the live repository policy selected by a later remediation.
        self.policy.pop('mode', None)
        self.policy.pop('blockingBasis', None)
        self.policy.pop('confirmedDesktopRisks', None)
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

    def test_policy_transition_to_advisory_remains_observed_and_requires_review(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        self.ledger['policySha256'] = 'c' * 64
        self.result.update(mode='upstream-maintained-risk', status='pass', blocked=[],
                           advisories=[finding(), finding(advisory='CVE-2026-2')], releaseBlockers=[])
        result = self.compare()
        self.assertTrue(result['policyChanged'])
        self.assertEqual(len(result['persistent']), 2)
        self.assertEqual(result['notObserved'], [])
        self.assertEqual(result['new'], [])
        self.assertTrue(all(entry['dispositions'] == ['advisory'] for entry in result['persistent']))
        self.assertTrue(all(change['previous'] == ['blocked'] and change['current'] == ['advisory']
                            and change['remediationStatus'] == 'review-required'
                            for change in result['dispositionChanges']))
        self.assertNotIn('resolved', result)
        self.assertNotIn('fixed', result)

    def test_critical_only_exact_mode_and_classified_source_holds(self):
        self.policy['mode'] = 'desktop-critical-only'
        self.result.update(mode='desktop-critical-only', status='blocked', blocked=[], advisories=[finding()],
                           trackedReleaseConcerns=[{**hold(), 'severity': 'Unknown', 'advisories': []}],
                           releaseBlockers=[{**hold(), 'severity': 'Critical', 'advisories': ['CVE-2026-1234']}])
        self.assertEqual(len(self.compare()['releaseBlockers']), 1)
        self.assertEqual(self.compare()['trackedReleaseConcerns'][0]['severity'], 'Unknown')
        self.result['mode'] = 'upstream-maintained-risk'
        with self.assertRaisesRegex(ValueError, 'policy mode'):
            self.compare()
        self.result['mode'] = 'desktop-critical-only'
        self.result['releaseBlockers'] = [hold()]
        with self.assertRaises(ValueError):
            self.compare()

    def test_critical_only_source_concern_misclassification_fails_closed(self):
        self.policy['mode'] = 'desktop-critical-only'
        classified = {**hold(), 'severity': 'Critical', 'advisories': ['CVE-2026-1234']}
        for blocked, tracked in [([], [classified]), ([{**classified, 'severity': 'Unknown'}], [])]:
            self.result.update(mode='desktop-critical-only', status='blocked' if blocked else 'pass',
                               blocked=[], advisories=[], releaseBlockers=blocked, trackedReleaseConcerns=tracked)
            with self.assertRaisesRegex(ValueError, 'disposition'):
                self.compare()
        self.result.update(releaseBlockers=[])
        self.result.pop('trackedReleaseConcerns')
        with self.assertRaisesRegex(ValueError, 'retain advisory source'):
            self.compare()

    def test_reviewed_basis_requires_confirmed_candidate_risk_not_pairs(self):
        basis = 'reviewed-desktop-exploitability'
        self.policy.update(mode='desktop-critical-only', blockingBasis=basis, confirmedDesktopRisks=[])
        self.result.update(mode='desktop-critical-only', blockingBasis=basis, status='pass', blocked=[],
                           advisories=[finding(severity='Critical')], releaseBlockers=[],
                           approvedBaseline={'image': NEW, 'profile': 'bluefin-generic'},
                           trackedReleaseConcerns=[{**hold(), 'severity': 'Critical', 'advisories': ['CVE-2026-1234']}])
        result = self.compare()
        self.assertEqual(result['blockingBasis'], basis)
        self.assertEqual(result['trackedReleaseConcerns'][0]['severity'], 'Critical')
        self.assertEqual(result['counts']['blockingRecords'], 0)
        self.result.pop('blockingBasis')
        with self.assertRaisesRegex(ValueError, 'blocking basis'):
            self.compare()
        self.result.update(blockingBasis=basis, status='blocked')
        risk = confirmed_risk(NEW)
        self.policy['confirmedDesktopRisks'] = [risk]
        self.result['releaseBlockers'] = [deepcopy(risk)]
        self.assertEqual(self.compare()['releaseBlockers'], [risk])
        self.result['blocked'] = [{**finding(advisory='CVE-2026-1234'),
            'aliases': ['CVE-2026-1234'], 'locations': ['/usr/bin/example'], 'locationCoverage': 'complete',
            'reason': 'confirmed-desktop-exploitability', 'disposition': 'blocked', 'confirmedRiskReviews': [risk['id']]}]
        self.assertEqual(self.compare()['counts']['blockingRecords'], 1)
        for mutate in [lambda: self.result.update(releaseBlockers=[]),
                       lambda: self.result['releaseBlockers'][0].update(profile='bluefin-next'),
                       lambda: self.result['releaseBlockers'][0].update(digest=OLD.split('@')[1]),
                       lambda: self.result['releaseBlockers'][0].pop('selinuxEvidence')]:
            self.result['releaseBlockers'] = [deepcopy(risk)]
            mutate()
            with self.assertRaises(ValueError):
                self.compare()

    def test_duplicate_advisories_are_counted_without_losing_exact_pair_scope(self):
        self.result['advisories'] = [finding(advisory='CVE-2026-3'), finding(advisory='CVE-2026-3'),
                                     finding(component='pkg:rpm/fedora/example@2')]
        result = self.compare()
        self.assertEqual(result['counts'], {'blockingRecords': 2, 'exceptionRecords': 0,
                                            'advisoryRecords': 3, 'releaseBlockerRecords': 0, 'observedPairs': 3})
        duplicate = next(entry for entry in result['new'] if entry['advisory'] == 'CVE-2026-3')
        self.assertEqual(duplicate['occurrences'], 3)
        self.assertEqual(duplicate['dispositions'], ['blocked', 'advisory'])
        self.assertEqual(len(result['new']), 2)
        self.assertIn('advisories', result['scope'])

    def test_missing_malformed_or_wrong_mode_advisories_fail_closed(self):
        for change in (lambda result: result.pop('advisories'),
                       lambda result: result.update(advisories=None),
                       lambda result: result.update(advisories={}),
                       lambda result: result.update(advisories=['not-an-object']),
                       lambda result: result.update(advisories=[{**finding(), 'knownExploited': 1}]),
                       lambda result: result.update(mode='legacy')):
            with self.subTest(change=change):
                self.setUp()
                self.policy['mode'] = 'upstream-maintained-risk'
                self.result.update(mode='upstream-maintained-risk', advisories=[], releaseBlockers=[])
                change(self.result)
                with self.assertRaises(ValueError):
                    self.compare()

    def test_explicit_previous_disposition_is_preserved(self):
        self.ledger['findings'][0]['dispositions'] = ['advisory']
        self.result['advisories'] = [finding(advisory='CVE-2026-2')]
        result = self.compare()
        change = next(entry for entry in result['dispositionChanges'] if entry['advisory'] == 'CVE-2026-1')
        self.assertEqual(change['previous'], ['advisory'])
        self.assertEqual(change['current'], ['blocked'])
        self.assertEqual(change['previousBasis'], 'explicit')

    def test_advisory_presence_cannot_hide_status_contradiction_or_stale_digest(self):
        self.result.update(status='pass', advisories=[finding()])
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            self.compare()
        self.result.update(blocked=[], image=OLD)
        with self.assertRaisesRegex(ValueError, 'immutable image'):
            self.compare()

    def test_summary_hash_binds_exact_input_bytes(self):
        path = ROOT / 'docs/security-remediation-2026-10-12.json'
        ledger, checksum = remediation.read(path)
        self.assertEqual(checksum, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(ledger['schema'], 1)

    def test_source_hold_blocks_without_fabricating_vulnerability_records(self):
        self.policy['mode'] = 'upstream-maintained-risk'
        self.result.update(mode='upstream-maintained-risk', blocked=[], advisories=[finding()],
                           releaseBlockers=[hold()])
        result = self.compare()
        self.assertEqual(result['scanStatus'], 'blocked')
        self.assertEqual(result['releaseBlockers'], [hold()])
        self.assertEqual(result['counts']['releaseBlockerRecords'], 1)
        self.assertEqual(result['counts']['blockingRecords'], 0)
        self.assertEqual(result['counts']['advisoryRecords'], 1)
        self.assertEqual(len(result['persistent']), 1)
        self.assertNotIn('fixed', result)

    def test_missing_malformed_or_contradictory_holds_fail_closed(self):
        for change in (lambda result: result.pop('releaseBlockers'),
                       lambda result: result.update(releaseBlockers=None),
                       lambda result: result.update(releaseBlockers=[{}]),
                       lambda result: result.update(releaseBlockers=[hold(), hold()]),
                       lambda result: result.update(status='pass'),
                       lambda result: result.update(releaseBlockers=[])):
            with self.subTest(change=change):
                self.setUp()
                self.policy['mode'] = 'upstream-maintained-risk'
                self.result.update(mode='upstream-maintained-risk', blocked=[], advisories=[],
                                   releaseBlockers=[hold()])
                change(self.result)
                with self.assertRaises(ValueError):
                    self.compare()


if __name__ == '__main__':
    unittest.main()
