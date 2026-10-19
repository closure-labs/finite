#!/usr/bin/env python3
"""Boundary tests for human acceptance carryover; no network or registry is used."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('decisions', ROOT / 'scripts/ci/security_decisions.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def scan(**changes):
    finding = {'component': 'pkg:rpm/fedora/openssl@3.0?arch=x86_64',
               'advisory': 'CVE-2026-12345', 'aliases': ['GHSA-abcd-1234-5678', 'CVE-2026-12345'],
               'severity': 'Low', 'cvss': 2.0, 'knownExploited': False,
               'locations': ['/usr/bin/openssl'], 'locationCoverage': 'complete', 'fixVersions': []}
    finding.update(changes)
    return {'status': 'pass', 'observations': [finding], 'image': 'image@sha256:' + 'a' * 64}


class Decisions(unittest.TestCase):
    def test_complete_health_and_related_severity_are_enforced(self):
        native = scan(severity='Low', admissionSeverity='Critical')
        native.update(status='complete', scannerHealth='healthy')
        self.assertEqual(mod.normalize_findings(native, 'finite')[0]['severity'], 'Critical')
        native['scannerHealth'] = 'unknown'
        with self.assertRaises(mod.TechnicalError):
            mod.normalize_findings(native, 'finite')

    def test_initial_empty_scan_still_requires_human(self):
        empty = {'status': 'pass', 'observations': []}
        self.assertEqual(mod.evaluate(empty, 'finite')['status'], 'review-required')
        self.assertEqual(mod.evaluate(empty, 'finite', [])['status'], 'covered')

    def test_every_severity_needs_new_decision(self):
        for severity in (*mod.SEVERITIES, 'Unknown'):
            with self.subTest(severity=severity):
                self.assertEqual(mod.evaluate(scan(severity=severity), 'finite', [])['status'], 'review-required')

    def test_digest_version_fix_only_changes_carry(self):
        old = mod.normalize_findings(scan(), 'finite')
        updated = scan(component='pkg:rpm/fedora/openssl@4.0?arch=x86_64', fixVersions=['4.1'])
        updated['image'] = 'image@sha256:' + 'b' * 64
        result = mod.evaluate(updated, 'finite', old)
        self.assertEqual(result['status'], 'covered')
        self.assertEqual(result['findings'][0]['component'], 'pkg:rpm/fedora/openssl?arch=x86_64')

    def test_each_risk_worsening_requires_review(self):
        old = mod.normalize_findings(scan(), 'finite')
        for change in ({'severity': 'High'}, {'cvss': 3.0}, {'knownExploited': True},
                       {'locations': ['/usr/bin/openssl', '/usr/sbin/listener']}):
            with self.subTest(change=change):
                result = mod.evaluate(scan(**change), 'finite', old)
                self.assertEqual(result['status'], 'review-required')
                self.assertEqual(len(result['worsened']), 1)

    def test_reduced_exposure_and_risk_carry(self):
        old = mod.normalize_findings(scan(severity='Critical', cvss=10, knownExploited=True,
                                         locations=['/usr/bin/openssl', '/usr/sbin/listener']), 'finite')
        self.assertEqual(mod.evaluate(scan(), 'finite', old)['status'], 'covered')

    def test_resolution_carries_and_revocation_stops(self):
        old = mod.normalize_findings(scan(), 'finite')
        empty = {'status': 'pass', 'observations': []}
        result = mod.evaluate(empty, 'finite', old)
        self.assertEqual(result['status'], 'covered')
        self.assertEqual(len(result['resolved']), 1)
        self.assertEqual(mod.evaluate(scan(), 'finite', old, revoked=True)['status'], 'revoked')

    def test_profiles_and_components_do_not_share_acceptance(self):
        old = mod.normalize_findings(scan(), 'finite')
        self.assertEqual(mod.evaluate(scan(), 'finite-dev', old)['status'], 'review-required')
        self.assertEqual(mod.evaluate(scan(component='pkg:rpm/fedora/other@3.0?arch=x86_64'), 'finite', old)['status'], 'review-required')

    def test_missing_and_ambiguous_evidence_are_technical(self):
        old = mod.normalize_findings(scan(), 'finite')
        invalid = [scan(locationCoverage='unknown'),
                   scan(locations=['/usr/../bin/a']), scan(locations=['//usr/bin/a']),
                   scan(knownExploited=1), scan(cvss=float('nan')), scan(cvss=True),
                   {'status': 'scanner-error', 'observations': []}, {'status': 'pass'}]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(mod.TechnicalError):
                    mod.evaluate(value, 'finite', old)
        with self.assertRaises(mod.TechnicalError):
            mod.evaluate(scan(cvss=None), 'finite', old)

    def test_alias_order_and_duplicates_stable(self):
        a = scan()
        b = scan(aliases=list(reversed(a['observations'][0]['aliases'])))
        b['observations'].append(copy.deepcopy(b['observations'][0]))
        self.assertEqual(mod.normalize_findings(a, 'finite'), mod.normalize_findings(b, 'finite'))

    def test_multiple_cve_aliases_are_separate_occurrences(self):
        current = scan(aliases=['CVE-2026-12345', 'CVE-2026-99999'])
        old = mod.normalize_findings(current, 'finite')
        self.assertEqual(len(old), 2)
        self.assertEqual(mod.evaluate(current, 'finite', old)['status'], 'covered')

    def test_opaque_artifact_identity_is_bound_to_digest(self):
        native = scan(component='opaque-artifact-id')
        old = mod.normalize_findings(native, 'finite')
        self.assertTrue(old[0]['component'].startswith('artifact:sha256:'))
        self.assertEqual(mod.evaluate(native, 'finite', old)['status'], 'covered')
        native['image'] = 'image@sha256:' + 'b' * 64
        self.assertEqual(mod.evaluate(native, 'finite', old)['status'], 'review-required')
        del native['image']
        with self.assertRaises(mod.TechnicalError):
            mod.evaluate(native, 'finite', old)

    def test_forged_and_duplicate_normalized_keys_rejected(self):
        old = mod.normalize_findings(scan(), 'finite')
        bad = copy.deepcopy(old)
        bad[0]['key'] = 'forged'
        with self.assertRaises(mod.TechnicalError):
            mod.evaluate(scan(), 'finite', bad)
        with self.assertRaises(mod.TechnicalError):
            mod.evaluate(scan(), 'finite', old + old)


if __name__ == '__main__':
    unittest.main()
