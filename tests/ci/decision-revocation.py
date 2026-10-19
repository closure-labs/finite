#!/usr/bin/env python3
"""Human rejection/revocation remains usable when accepted evidence has expired."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import decision_revocation as module
import decision_controller as controller
from security_decisions import canonical_hash


def accepted():
    return {'schema': 1, 'kind': 'security-findings', 'payload': {
        'profiles': ['finite', 'finite-dev'], 'findings': [], 'disposition': 'accepted', 'supersedes': [],
        'rationale': 'Original human acceptance', 'packet': {
            'reference': 'ghcr.io/closure-labs/finite-decisions@sha256:' + 'a' * 64, 'sha256': 'b' * 64,
            'producer': {'repository': 'closure-labs/finite', 'workflow': 'build.yml', 'runId': 1,
                         'runAttempt': 1, 'headSha': 'c' * 40,
                         'artifacts': [{'id': 10, 'name': 'security-finite-1-1', 'digest': 'sha256:' + 'd' * 64}]}}}}


class Revocations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.records = self.root / 'automation/decisions/security'
        self.records.mkdir(parents=True)
        self.parent = accepted()
        self.identity = self.write(self.parent)
        self.origin = patch.object(module.security_admission.authority, 'find_origin_pr', return_value=42)
        self.history = patch.object(module.security_admission, '_historical_provenance', return_value={'status': 'superseded-provenance'})
        self.origin.start()
        self.historical = self.history.start()
        self.addCleanup(self.origin.stop)
        self.addCleanup(self.history.stop)

    def write(self, proposal):
        identity = canonical_hash(proposal)
        (self.records / (identity + '.json')).write_text(json.dumps(proposal))
        return identity

    def create(self):
        return module.create(self.identity, 'Withdraw acceptance after incident review',
                             'closure-labs/finite', 'review[bot]', self.records)

    def test_revocation_copies_exact_snapshot_without_live_artifact_or_former_reviewer(self):
        with patch.object(module.security_admission.authority, 'verify_proposal', side_effect=AssertionError('No current parent approver required')):
            proposal = self.create()
        for field in ('profiles', 'findings', 'packet'):
            self.assertEqual(proposal['payload'][field], self.parent['payload'][field])
        self.assertEqual(proposal['kind'], 'security-revocation')
        self.assertEqual(proposal['payload']['supersedes'], [self.identity])
        self.historical.assert_called_once()
        # The new proposal still needs its own exact-head human approval; no
        # authorized publication receipt is synthesized here.
        self.assertNotIn('authority', proposal)

    def test_partial_scope_or_alternate_packet_cannot_be_smuggled_into_revocation(self):
        proposal = self.create()
        for mutate in (lambda p: p['payload'].update(profiles=['finite']),
                       lambda p: p['payload']['packet'].update(sha256='e' * 64),
                       lambda p: p['payload'].update(disposition='accepted')):
            changed = copy.deepcopy(proposal)
            mutate(changed)
            with self.assertRaises(ValueError):
                module.validate(changed, 'closure-labs/finite', 'review[bot]', self.records)

    def test_stale_parent_and_rejected_parent_cannot_be_revoked(self):
        newer = copy.deepcopy(self.parent)
        newer['payload'].update(supersedes=[self.identity], rationale='Newer acceptance')
        latest = self.write(newer)
        with self.assertRaisesRegex(ValueError, 'unique active'):
            self.create()
        newer['payload']['disposition'] = 'rejected'
        rejected = self.write(newer)
        with self.assertRaisesRegex(ValueError, 'must be accepted'):
            module.create(rejected, 'Cannot revoke a rejection', 'closure-labs/finite', 'review[bot]', self.records)

    def test_app_required_check_validates_revocation_without_downloading_expired_scans(self):
        proposal = self.create()
        with patch.object(controller, 'ROOT', self.root), patch.dict(controller.os.environ, FINITE_REVIEW_BOT_LOGIN='review[bot]'), \
                patch.object(controller, 'producer', side_effect=AssertionError('No old artifact fetch')):
            controller.validate_proposal_packet(proposal)

    def test_rejection_explicitly_bypasses_covered_and_pending_acceptance_suppression(self):
        spec = importlib.util.spec_from_file_location('rejection_cli', ROOT / 'scripts/ci/decision-controller.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        directory = self.root / 'fresh-packet'
        with patch.object(sys, 'argv', ['decision-controller.py', 'collect', '--run', '5', '--packet-directory', str(directory),
                                       '--disposition', 'rejected', '--rationale', 'Reject actual exposed risk']), \
                patch.object(controller, 'trusted_context'), patch.object(controller, 'collect', return_value=({'runId': 5}, [])), \
                patch.object(controller, 'current_admission', side_effect=AssertionError('Covered cannot suppress rejection')), \
                patch.object(controller, 'pending_proposal', side_effect=AssertionError('Pending acceptance cannot suppress rejection')), \
                patch.object(controller, 'has_reused_evidence', return_value=False), \
                patch.object(controller, 'decision_ids', return_value=[self.identity]), \
                patch.object(cli.decision_packets, 'push', return_value=self.parent['payload']['packet']), \
                patch.object(controller, 'propose', return_value='https://example.test/review') as propose:
            cli.main()
        proposal = propose.call_args.args[0]
        self.assertEqual(proposal['payload']['disposition'], 'rejected')
        self.assertEqual(proposal['payload']['rationale'], 'Reject actual exposed risk')
        self.assertEqual(proposal['payload']['supersedes'], [self.identity])


if __name__ == '__main__':
    unittest.main()
