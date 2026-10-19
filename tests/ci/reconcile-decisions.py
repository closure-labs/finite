#!/usr/bin/env python3
"""Reconciliation reauthenticates humans and recovers ambiguous dispatches."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
SPEC = importlib.util.spec_from_file_location('reconcile_decisions', ROOT / 'scripts/ci/reconcile-decisions.py')
reconcile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconcile)
SHA = 'a' * 40
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64


class Journal:
    def __init__(self):
        self.state = None
        self.version = None
        self.calls = 0
        self.fail_at = None

    def read_journal(self, identity):
        return deepcopy(self.state), self.version

    def write_journal(self, identity, state, version):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError('CAS or journal transport failure')
        if version != self.version:
            raise RuntimeError('CAS conflict')
        self.version = str(self.calls)
        self.state = deepcopy(state)
        return self.version


class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        ledger = self.root / 'automation/decisions/security'
        ledger.mkdir(parents=True)
        policy = self.root / 'automation/security/image-policy.json'
        policy.parent.mkdir(parents=True)
        policy.write_text(json.dumps({'mode': 'maintainer-decision'}))
        self.origin = {'workflow': 'build.yml', 'runId': 123, 'runAttempt': 1, 'headSha': SHA}
        proposal = {'schema': 1, 'kind': 'security-findings',
                    'payload': {'profiles': ['finite'], 'supersedes': [],
                                'packet': {'reference': 'packet', 'sha256': 'c' * 64, 'producer': self.origin}}}
        self.identity = reconcile.canonical_hash(proposal)
        self.proposal = proposal
        (ledger / (self.identity + '.json')).write_text(json.dumps(proposal))
        self.run = {'id': 123, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                    'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'push',
                    'head_sha': SHA, 'run_attempt': 1, 'status': 'completed'}
        self.artifacts = [{'name': f'{kind}-finite-123-1', 'expired': False} for kind in ('image', 'security')]
        self.observed = []
        self.dispatched = []
        self.journal = Journal()
        self.current_sha = SHA
        self.ambiguous_dispatch = False
        self.verify_results = None
        self.verifications = 0
        self.native_scan = {'status': 'complete', 'scannerHealth': 'healthy', 'image': IMAGE}
        self.patches = [patch.object(reconcile.controller, 'ROOT', self.root),
                        patch.object(reconcile.controller, 'api', side_effect=self.api),
                        patch.object(reconcile.controller, 'collection', side_effect=self.collection),
                        patch.object(reconcile.decision_packets, 'fetch', side_effect=self.fetch),
                        patch.object(reconcile.controller, 'native_result', side_effect=lambda *a, **k: deepcopy(self.native_scan)),
                        patch.object(reconcile, 'GitHubClient', return_value=self.journal),
                        patch.object(reconcile, 'verify', side_effect=self.verify),
                        patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                                                'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA,
                                                'FINITE_REVIEW_BOT_LOGIN': 'finite-decisions[bot]'})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def fetch(self, reference, directory, digest):
        location = directory / 'finite'
        location.mkdir(parents=True)
        (location / 'vulnerabilities.json').write_text(json.dumps({'descriptor': {'timestamp': '2026-01-01T00:00:00Z'}}))
        (location / 'security-result.json').write_text(json.dumps({'status': 'complete', 'scannerHealth': 'healthy', 'image': IMAGE}))

    def verify(self, *args, **kwargs):
        self.verifications += 1
        if self.verify_results:
            return self.verify_results.pop(0)
        return {'status': 'covered', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}

    def collection(self, path, key):
        if path.endswith('/artifacts'): return deepcopy(self.artifacts)
        if '/actions/workflows/build.yml/runs?' in path: return deepcopy(self.observed)
        raise AssertionError(path)

    def api(self, path, method='GET', payload=None):
        if path.endswith('/actions/runs/123'):
            return deepcopy(self.run)
        if path.endswith('/git/ref/heads/main'):
            return {'object': {'sha': self.current_sha}}
        if path.endswith('/dispatches'):
            self.assertEqual(method, 'POST')
            self.assertEqual(self.journal.state['status'], 'claimed')
            self.dispatched.append(deepcopy(payload))
            self.observed = [{'id': 999, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                              'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'workflow_dispatch',
                              'display_title': 'Build Finite [decision:' + payload['inputs']['decision_request'] + ']',
                              'status': 'in_progress'}]
            if self.ambiguous_dispatch: raise RuntimeError('Lost dispatch response')
            return None
        raise AssertionError(path)

    def execute(self, clock=1000):
        return reconcile.reconcile(now=lambda: clock)

    def test_claim_before_dispatch_and_live_authority_rechecked(self):
        result = self.execute()
        self.assertEqual(result[0]['status'], 'dispatched')
        self.assertEqual(self.verifications, 2)
        self.assertEqual(self.dispatched[0]['inputs']['resume_run'], '123')
        self.assertEqual(self.dispatched[0]['inputs']['resume_digest'], IMAGE.split('@')[1])
        self.assertRegex(self.dispatched[0]['inputs']['decision_request'], r'^[0-9a-f]{64}$')
        self.assertEqual(self.journal.state['status'], 'dispatched')

    def test_legacy_packet_reconstructs_cvss_and_uses_real_admission_identity(self):
        from security_decisions import evaluate, normalize_findings, TechnicalError
        finding = {'component': 'pkg:rpm/fedora/openssl@3.0?arch=x86_64',
                   'advisory': 'CVE-2026-12345', 'aliases': [], 'severity': 'High',
                   'cvss': 8.1, 'knownExploited': False, 'locations': ['/usr/bin/openssl'],
                   'locationCoverage': 'complete', 'fixVersions': []}
        self.native_scan['observations'] = [finding]
        accepted = normalize_findings(self.native_scan, 'finite')
        legacy = deepcopy(self.native_scan)
        del legacy['observations'][0]['cvss']
        with self.assertRaisesRegex(TechnicalError, 'CVSS evidence disappeared'):
            evaluate(legacy, 'finite', accepted)

        def admission(scan, profile, *args):
            result = evaluate(scan, profile, accepted)
            return {**result, 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}
        with patch.object(reconcile, 'verify', side_effect=admission):
            self.assertEqual(self.execute()[0]['status'], 'dispatched')
        snapshot = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reconcile.controller.native_result.assert_called_once()
        call = reconcile.controller.native_result.call_args
        self.assertEqual(call.args[1:], (snapshot, snapshot))
        self.assertEqual(call.kwargs, {'profile': 'finite'})
        self.assertEqual(len(self.dispatched), 1)

    def test_native_evidence_failure_stops_before_authority_or_dispatch(self):
        reconcile.controller.native_result.side_effect = ValueError('Invalid native evidence')
        with self.assertRaisesRegex(ValueError, 'Invalid native evidence'):
            self.execute()
        self.assertEqual(self.verifications, 0)
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_wrong_decision_identity_never_dispatches(self):
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': 'f' * 64}}]
        with self.assertRaisesRegex(ValueError, 'differs from authenticated'):
            self.execute()
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_changed_decision_identity_after_claim_never_dispatches(self):
        self.verify_results = [self.verify(), {'status': 'covered', 'decision': {'proposalHash': 'f' * 64}}]
        with self.assertRaisesRegex(ValueError, 'authority changed'):
            self.execute()
        self.assertEqual(self.dispatched, [])

    def test_genuinely_missing_native_cvss_remains_a_technical_failure(self):
        from security_decisions import evaluate, normalize_findings, TechnicalError
        finding = {'component': 'pkg:rpm/fedora/openssl@3.0?arch=x86_64',
                   'advisory': 'CVE-2026-12345', 'aliases': [], 'severity': 'High',
                   'cvss': 8.1, 'knownExploited': False, 'locations': ['/usr/bin/openssl'],
                   'locationCoverage': 'complete', 'fixVersions': []}
        self.native_scan['observations'] = [finding]
        accepted = normalize_findings(self.native_scan, 'finite')
        del finding['cvss']
        with patch.object(reconcile, 'verify', side_effect=lambda scan, profile, *a: evaluate(scan, profile, accepted)):
            with self.assertRaisesRegex(TechnicalError, 'CVSS evidence disappeared'):
                self.execute()
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_future_or_unzoned_snapshot_never_dispatches(self):
        original = self.fetch
        for timestamp in ('2999-01-01T00:00:00Z', '2026-01-01T00:00:00', None):
            def fetch(reference, directory, digest):
                original(reference, directory, digest)
                (directory / 'finite/vulnerabilities.json').write_text(json.dumps({'descriptor': {'timestamp': timestamp}}))
            with self.subTest(timestamp=timestamp), patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch):
                with self.assertRaisesRegex(ValueError, 'scan time'):
                    self.execute()
            self.assertEqual(self.journal.calls, 0)
            self.assertEqual(self.dispatched, [])

    def test_shadow_bootstrap_never_dispatches_before_explicit_policy_cutover(self):
        (self.root / 'automation/security/image-policy.json').write_text(json.dumps({'mode': 'desktop-critical-only'}))
        self.assertEqual(self.execute()[0]['status'], 'awaiting-policy-cutover')
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.verifications, 0)

    def test_ambiguous_post_is_observed_without_duplicate_dispatch(self):
        self.ambiguous_dispatch = True
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.ambiguous_dispatch = False
        self.assertEqual(self.execute()[0]['status'], 'already-dispatched')
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.journal.state['observedRun'], 999)

    def test_crash_writing_success_receipt_is_recovered_by_run_marker(self):
        self.journal.fail_at = 2
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.journal.fail_at = None
        self.execute()
        self.assertEqual(len(self.dispatched), 1)

    def test_unobserved_claim_waits_for_lease_before_bounded_retry(self):
        self.ambiguous_dispatch = True
        with self.assertRaises(RuntimeError): self.execute()
        self.ambiguous_dispatch = False
        self.observed = []
        self.assertEqual(self.execute(clock=1001)[0]['status'], 'dispatch-pending')
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.execute(clock=2000)[0]['status'], 'dispatched')
        self.assertEqual(len(self.dispatched), 2)

    def test_observed_success_is_idempotent_without_journal_churn(self):
        self.execute()
        self.execute()
        writes = self.journal.calls
        self.execute()
        self.assertEqual(self.journal.calls, writes)
        self.assertEqual(len(self.dispatched), 1)

    def test_claim_conflict_stops_before_any_dispatch(self):
        self.journal.fail_at = 1
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_busy_publisher_defers_without_consuming_pending_slot(self):
        self.observed = [{'id': 456, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                          'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'schedule', 'status': 'queued'}]
        self.assertEqual(self.execute()[0]['status'], 'publisher-busy')
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.journal.calls, 0)

    def test_expired_missing_or_rerun_origin_uses_full_build(self):
        for mutation in ('expired', 'missing', 'attempt', 'source'):
            self.journal = Journal()
            reconcile.GitHubClient.return_value = self.journal
            self.artifacts = [{'name': f'{kind}-finite-123-1', 'expired': False} for kind in ('image', 'security')]
            self.run.update(head_sha=SHA, run_attempt=1)
            if mutation == 'expired': self.artifacts[0]['expired'] = True
            if mutation == 'missing': self.artifacts.pop()
            if mutation == 'attempt': self.run['run_attempt'] = 2
            if mutation == 'source': self.run['head_sha'] = 'd' * 40
            with self.subTest(mutation=mutation):
                self.execute()
                inputs = self.dispatched[-1]['inputs']
                self.assertNotIn('resume_run', inputs)
                self.assertNotIn('resume_digest', inputs)

    def test_failed_resume_with_expired_artifacts_retries_full_build_once(self):
        self.execute()
        first = self.dispatched[0]['inputs']['decision_request']
        self.observed[0].update(status='completed', conclusion='failure')
        self.artifacts[0]['expired'] = True
        self.execute()
        self.assertEqual(len(self.dispatched), 2)
        self.assertNotIn('resume_run', self.dispatched[-1]['inputs'])
        self.assertNotEqual(first, self.dispatched[-1]['inputs']['decision_request'])
        self.execute()
        self.assertEqual(len(self.dispatched), 2)

    def test_completed_success_does_not_rebuild_when_artifacts_expire(self):
        self.execute()
        self.observed[0].update(status='completed', conclusion='success')
        self.artifacts[0]['expired'] = True
        self.execute()
        self.assertEqual(len(self.dispatched), 1)

    def test_revocation_between_claim_and_dispatch_stops_publication(self):
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}, {'status': 'revoked', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}]
        with self.assertRaisesRegex(ValueError, 'authority changed'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_main_advancement_stops_stale_reconciliation(self):
        self.current_sha = 'e' * 40
        with self.assertRaisesRegex(ValueError, 'Main changed'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_review_required_never_dispatches_or_writes_journal(self):
        self.verify_results = [{'status': 'review-required', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}]
        self.assertEqual(self.execute()[0]['status'], 'review-required')
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_untrusted_context_stops_before_api_or_packet_fetch(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/branch'}), self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.verifications, 0)

    def test_foreign_origin_does_not_fall_back_under_false_identity(self):
        self.run['head_repository']['full_name'] = 'fork/finite'
        with self.assertRaisesRegex(ValueError, 'trusted main build'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_build_workflow_exposes_request_marker_and_validates_it(self):
        import yaml
        document = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        events = document.get('on', document.get(True))
        self.assertIn('decision_request', events['workflow_dispatch']['inputs'])
        self.assertIn('[decision:', document['run-name'])
        validation = next(step for step in document['jobs']['impact']['steps'] if step.get('name') == 'Validate decision reconciliation request')
        self.assertIn('DECISION_REQUEST', validation['env'])
        self.assertIn('^[0-9a-f]{64}$', validation['run'])
        self.assertNotIn('${{', validation['run'])


if __name__ == '__main__':
    unittest.main()
