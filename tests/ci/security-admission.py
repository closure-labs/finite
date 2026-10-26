#!/usr/bin/env python3
"""Security admission requires authenticated, unambiguous human decision chains."""
import copy
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import security_admission as module
from security_decisions import canonical_hash, normalize_findings, TechnicalError


def scan(severity='Low'):
    return {'status': 'pass', 'image': 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64,
            'observations': [{'component': 'pkg:rpm/fedora/demo@1', 'advisory': 'CVE-2026-12345',
                              'aliases': [], 'locations': ['/usr/bin/demo'], 'locationCoverage': 'complete',
                              'severity': severity, 'cvss': 2.0, 'knownExploited': False, 'fixVersions': []}]}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = Path(self.tmp.name)
        self.allowed = set()
        self.calls = []
        self.remote = patch.object(module.authority, 'github_api', self.github)
        self.remote.start()
        self.addCleanup(self.remote.stop)
        self.find = patch.object(module.authority, 'find_origin_pr', self.origin)
        self.auth = patch.object(module.authority, 'verify_proposal', self.authorize)
        self.history = patch.object(module, '_historical_provenance', self.historical)
        self.history.start()
        self.addCleanup(self.history.stop)
        self.find.start()
        self.auth.start()
        self.addCleanup(self.find.stop)
        self.addCleanup(self.auth.stop)

    def tree(self):
        entries = []
        for path in self.records.glob('*.json'):
            raw = path.read_bytes()
            entries.append({'path': 'automation/decisions/security/' + path.name,
                            'type': 'blob', 'mode': '100644', 'size': len(raw),
                            'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
        return {'truncated': False, 'tree': entries}

    def github(self, endpoint):
        if endpoint.endswith('/git/ref/heads/main'):
            return {'object': {'sha': 'd' * 40}}
        if endpoint.endswith('?recursive=1'):
            return self.tree()
        self.fail('Unexpected live inventory API: ' + endpoint)

    def origin(self, proposal, repository, expected_bot, github=None):
        self.calls.append(('origin', canonical_hash(proposal)))
        return 42

    def authorize(self, proposal, pr, repository, bot, require_merged=True, github=None):
        identity = canonical_hash(proposal)
        self.assertTrue(require_merged)
        self.calls.append(('verify', identity))
        if identity not in self.allowed:
            raise module.authority.AuthorityError('No current maintain/admin exact-head review')
        return {'schema': 1, 'status': 'authorized', 'proposalHash': identity, 'pullRequest': pr,
                'reviewer': 'maintainer', 'mergeCommit': 'b' * 40}

    def historical(self, proposal, number, repository, bot_login, github=None):
        identity = canonical_hash(proposal)
        self.calls.append(('history', identity))
        return {'status': 'superseded-provenance', 'proposalHash': identity, 'pullRequest': number}

    def proposal(self, disposition='accepted', supersedes=None, profiles=None, current=None):
        profiles = profiles or ['finite', 'finite-dev']
        findings = []
        for profile in profiles:
            findings += normalize_findings(current or scan(), profile)
        producer = {'repository': 'closure-labs/finite', 'workflow': 'build.yml',
                    'runId': '1', 'runAttempt': '1', 'headSha': 'a' * 40,
                    'artifacts': [{'id': 10, 'name': 'security-finite-1-1', 'digest': 'sha256:' + 'c' * 64}]}
        return {'schema': 1, 'kind': 'security-revocation' if disposition == 'revoked' else 'security-findings',
                'payload': {'profiles': profiles, 'findings': findings, 'disposition': disposition,
                            'supersedes': supersedes or [], 'rationale': 'Reviewed actual exposure',
                            'packet': {'reference': 'ghcr.io/closure-labs/finite-decisions@sha256:' + 'd' * 64,
                                       'sha256': 'e' * 64, 'producer': producer}}}

    def write(self, proposal, authorize=True):
        identity = canonical_hash(proposal)
        (self.records / (identity + '.json')).write_text(json.dumps(proposal))
        if authorize:
            self.allowed.add(identity)
        return identity

    def verify(self, current=None, profile='finite', **options):
        return module.verify(current or scan(), profile, 'closure-labs/finite', 'finite-review[bot]', self.records, **options)

    def chain(self, length=8):
        identities = []
        for _ in range(length):
            identities.append(self.write(self.proposal(supersedes=identities[-1:])))
        return identities

    def test_serial_and_parallel_history_return_identical_receipts(self):
        self.chain()
        serial = self.verify(historical_workers=1)
        parallel = self.verify(historical_workers=4)
        self.assertEqual(serial, parallel)
        self.assertEqual(sum(c[0] == 'verify' for c in self.calls), 2)
        self.assertEqual(sum(c[0] == 'history' for c in self.calls), 14)

    def test_parallel_history_is_bounded_and_finishes_before_live_authority(self):
        identities = self.chain()
        lock, ready = threading.Lock(), threading.Event()
        state = {'active': 0, 'maximum': 0, 'done': set()}
        owner = threading.get_ident()
        def history(proposal, *args, **kwargs):
            identity = canonical_hash(proposal)
            self.assertNotEqual(threading.get_ident(), owner)
            with lock:
                state['active'] += 1
                state['maximum'] = max(state['maximum'], state['active'])
                if state['active'] == 4:
                    ready.set()
            self.assertTrue(ready.wait(2), 'Independent historical reads did not overlap')
            with lock:
                state['active'] -= 1
                state['done'].add(identity)
            return self.historical(proposal, *args, **kwargs)
        def authorize(*args, **kwargs):
            self.assertEqual(threading.get_ident(), owner)
            self.assertEqual(state['active'], 0)
            self.assertEqual(state['done'], set(identities[:-1]))
            return self.authorize(*args, **kwargs)
        with patch.object(module, '_historical_provenance', side_effect=history), \
                patch.object(module.authority, 'verify_proposal', side_effect=authorize):
            self.assertEqual(self.verify(historical_workers=4)['status'], 'covered')
        self.assertEqual(state['maximum'], 4)

    def test_failed_parallel_history_cannot_reach_live_acceptance(self):
        identities = self.chain()
        def history(proposal, *args, **kwargs):
            if canonical_hash(proposal) == identities[0]:
                raise TechnicalError('Historical provenance unavailable')
            return self.historical(proposal, *args, **kwargs)
        with patch.object(module, '_historical_provenance', side_effect=history), \
                patch.object(module.authority, 'verify_proposal') as active, \
                self.assertRaisesRegex(TechnicalError, 'Historical provenance unavailable'):
            self.verify(historical_workers=4)
        active.assert_not_called()

    def test_parallel_history_does_not_cache_current_authority_between_profiles(self):
        identities = self.chain()
        self.assertEqual(self.verify(historical_workers=4)['status'], 'covered')
        self.allowed.remove(identities[-1])
        with self.assertRaises(module.authority.AuthorityError):
            self.verify(profile='finite-dev', historical_workers=4)
        self.assertEqual(sum(c[0] == 'verify' for c in self.calls), 2)

    def test_parallel_history_cannot_hide_changed_live_ledger(self):
        self.chain()
        before = self.tree()
        with patch.object(self, 'tree', side_effect=[before, {'truncated': False, 'tree': []}]), \
                self.assertRaisesRegex(TechnicalError, 'complete current main inventory'):
            self.verify(historical_workers=4)

    def test_invalid_worker_limits_fail_before_authority_reads(self):
        self.chain()
        for value in (True, 0, 2, 3, 5, '4', None):
            with self.subTest(value=value), self.assertRaises(TechnicalError):
                self.verify(historical_workers=value)
        self.assertEqual(self.calls, [])

    def test_new_live_revocation_and_deleted_record_reject_stale_checkout(self):
        accepted = self.write(self.proposal())
        tree = self.tree()
        revocation = self.proposal('revoked', [accepted])
        raw = json.dumps(revocation).encode()
        tree['tree'].append({'path': 'automation/decisions/security/' + canonical_hash(revocation) + '.json',
                             'type': 'blob', 'mode': '100644', 'size': len(raw),
                             'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
        with patch.object(self, 'tree', return_value=tree):
            with self.assertRaisesRegex(TechnicalError, 'complete current main inventory'):
                self.verify()
        self.assertEqual(self.calls, [])
        with patch.object(self, 'tree', return_value={'truncated': False, 'tree': []}):
            with self.assertRaisesRegex(TechnicalError, 'complete current main inventory'):
                self.verify()

    def test_empty_local_ledger_cannot_omit_live_decision(self):
        self.write(self.proposal())
        tree = self.tree()
        for path in self.records.glob('*.json'):
            path.unlink()
        with patch.object(self, 'tree', return_value=tree):
            with self.assertRaisesRegex(TechnicalError, 'complete current main inventory'):
                self.verify()
        self.assertEqual(self.calls, [])

    def test_ledger_change_during_review_validation_cannot_return_covered(self):
        accepted = self.write(self.proposal())
        original = self.tree()
        changed = copy.deepcopy(original)
        entry = copy.deepcopy(changed['tree'][0])
        entry['path'] = 'automation/decisions/security/' + 'f' * 64 + '.json'
        changed['tree'].append(entry)
        with patch.object(self, 'tree', side_effect=[original, changed]):
            with self.assertRaisesRegex(TechnicalError, 'complete current main inventory'):
                self.verify()
        self.assertIn(('verify', accepted), self.calls)

    def test_docs_only_main_advance_preserves_covered_ledger(self):
        self.write(self.proposal())
        heads = iter(['d' * 40, 'e' * 40])
        def github(endpoint):
            if endpoint.endswith('/git/ref/heads/main'):
                return {'object': {'sha': next(heads)}}
            return self.tree()
        self.assertEqual(module.verify(scan(), 'finite', 'closure-labs/finite', 'finite-review[bot]', self.records, github)['status'], 'covered')

    def test_live_inventory_api_errors_truncation_and_malformed_entries_fail_closed(self):
        self.write(self.proposal())
        original = self.tree()
        cases = []
        for field, value in [('mode', '120000'), ('mode', '100755'), ('type', 'tree'), ('sha', 'mutable'),
                             ('size', 8 * 1024 * 1024 + 1), ('path', 'automation/decisions/security/nested/' + 'f'*64 + '.json'),
                             ('path', 'automation/decisions/security/not-canonical.json')]:
            tree = copy.deepcopy(original)
            tree['tree'][0][field] = value
            cases.append(tree)
        cases += [{'truncated': True, 'tree': original['tree']},
                  {'tree': original['tree']}, {'truncated': False, 'tree': None},
                  {'truncated': False, 'tree': original['tree'] * 2},
                  {'truncated': False, 'tree': original['tree'] + [{'path': 'automation/decisions/security', 'type': 'blob', 'mode': '120000'}]}]
        for tree in cases:
            with self.subTest(tree=tree), patch.object(self, 'tree', return_value=tree):
                with self.assertRaises(TechnicalError):
                    self.verify()
        with patch.object(module.authority, 'github_api', side_effect=module.authority.AuthorityError('API unavailable')):
            with self.assertRaises(module.authority.AuthorityError):
                self.verify()
        self.assertEqual(self.calls, [])

    def test_remote_content_change_cannot_hide_under_same_canonical_filename(self):
        self.write(self.proposal())
        tree = self.tree()
        tree['tree'][0]['sha'] = 'e' * 40
        with patch.object(self, 'tree', return_value=tree), patch.object(module.authority, 'document_at', return_value=self.proposal('rejected')):
            with self.assertRaisesRegex(TechnicalError, 'canonical local identity'):
                self.verify()
        self.assertEqual(self.calls, [])
        # Harmless JSON formatting can change the Git blob without changing the decision.
        with patch.object(self, 'tree', return_value=tree), patch.object(module.authority, 'document_at', return_value=self.proposal()):
            self.assertEqual(self.verify()['status'], 'covered')

    def test_initial_decision_required_even_for_empty_scan(self):
        result = self.verify({'status': 'pass', 'observations': []})
        self.assertEqual(result['status'], 'review-required')
        self.assertIsNone(result['authority'])
        self.assertEqual(self.calls, [])

    def test_merged_json_and_self_reported_approval_never_grant_authority(self):
        self.write(self.proposal(), authorize=False)
        with self.assertRaises(module.authority.AuthorityError):
            self.verify()
        self.assertEqual(len(self.calls), 2)

    def test_accepted_all_severities_carry_but_new_worsening_requires_review(self):
        self.write(self.proposal())
        self.assertEqual(self.verify()['status'], 'covered')
        updated = scan()
        updated['observations'][0]['component'] = 'pkg:rpm/fedora/demo@2'
        self.assertEqual(self.verify(updated)['status'], 'covered')
        self.assertEqual(self.verify(scan('High'))['status'], 'review-required')
        self.assertGreaterEqual(sum(c[0] == 'verify' for c in self.calls), 3)

    def test_revocation_then_explicit_new_acceptance_overrides(self):
        accepted = self.write(self.proposal())
        revoked = self.write(self.proposal('revoked', [accepted]))
        self.assertEqual(self.verify()['status'], 'revoked')
        renewed = self.write(self.proposal('accepted', [revoked]))
        result = self.verify()
        self.assertEqual(result['status'], 'covered')
        self.assertEqual(result['decision']['proposalHash'], renewed)
        self.assertEqual(len(result['authorityChain']), 3)

    def test_departed_ancestor_approver_does_not_invalidate_new_authorized_leaf(self):
        former = self.write(self.proposal())
        self.allowed.remove(former)
        renewed = self.write(self.proposal('accepted', [former]))
        result = self.verify()
        self.assertEqual(result['status'], 'covered')
        self.assertEqual(result['authority']['proposalHash'], renewed)
        self.assertIn(('history', former), self.calls)
        self.assertNotIn(('verify', former), self.calls)
        self.allowed.remove(renewed)
        with self.assertRaises(module.authority.AuthorityError):
            self.verify()

    def test_retired_provenance_accepts_human_or_app_merge_without_current_role(self):
        proposal = self.proposal()
        path = module.authority.proposal_path(proposal)
        head, merge, current = 'a' * 40, 'b' * 40, 'c' * 40
        pull = {'number': 42, 'merged': True, 'state': 'closed', 'merge_commit_sha': merge,
                'user': {'type': 'Bot', 'login': 'finite-review[bot]'},
                'head': {'sha': head, 'repo': {'full_name': 'closure-labs/finite'}},
                'base': {'ref': 'main', 'repo': {'full_name': 'closure-labs/finite'}}, 'changed_files': 1}
        def github(endpoint):
            if endpoint.endswith('/pulls/42'):
                return copy.deepcopy(pull)
            if '/pulls/42/files?' in endpoint:
                return [{'filename': path, 'status': 'added'}]
            if endpoint.endswith('/git/ref/heads/main'):
                return {'object': {'sha': current}}
            if '/compare/' in endpoint:
                return {'status': 'ahead'}
            if '/contents/' in endpoint:
                raw = json.dumps(proposal).encode()
                return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                        'encoding': 'base64', 'size': len(raw),
                        'content': base64.b64encode(raw).decode()}
            self.fail('Historical provenance must not query current reviewer roles: ' + endpoint)
        self.history.stop()
        try:
            receipt = module._historical_provenance(proposal, 42, 'closure-labs/finite', 'finite-review[bot]', github)
            self.assertEqual(receipt['status'], 'superseded-provenance')
            self.assertNotIn('reviewer', receipt)
            pull['user'] = {'id': 3, 'type': 'User', 'login': 'former-maintainer'}
            receipt = module._historical_provenance(proposal, 42, 'closure-labs/finite', 'finite-review[bot]', github)
            self.assertEqual(receipt['status'], 'superseded-provenance')
            pull['user'] = {'type': 'Bot', 'login': 'attacker[bot]'}
            with self.assertRaises(TechnicalError):
                module._historical_provenance(proposal, 42, 'closure-labs/finite', 'finite-review[bot]', github)
        finally:
            self.history.start()

    def test_rejected_disposition_is_not_publication_authority(self):
        self.write(self.proposal('rejected'))
        self.assertEqual(self.verify()['status'], 'rejected')

    def test_unrelated_leaves_fail_until_explicitly_superseded(self):
        first = self.write(self.proposal())
        second_proposal = self.proposal('rejected')
        second = self.write(second_proposal)
        with self.assertRaisesRegex(TechnicalError, 'unrelated live decisions'):
            self.verify()
        self.write(self.proposal('accepted', [first, second]))
        self.assertEqual(self.verify()['status'], 'covered')

    def test_profile_specific_decisions_do_not_conflict(self):
        finite = self.write(self.proposal(profiles=['finite']))
        self.write(self.proposal('rejected', profiles=['finite-dev']))
        self.assertEqual(self.verify()['decision']['proposalHash'], finite)
        self.assertEqual(self.verify(profile='finite-dev')['status'], 'rejected')

    def test_missing_parent_and_revocation_without_accepted_target_fail(self):
        self.write(self.proposal('revoked', ['f' * 64]))
        with self.assertRaisesRegex(TechnicalError, 'missing from ledger'):
            self.verify()
        for path in self.records.glob('*.json'):
            path.unlink()
        rejected = self.write(self.proposal('rejected'))
        self.write(self.proposal('revoked', [rejected]))
        with self.assertRaisesRegex(TechnicalError, 'accepted decision'):
            self.verify()

    def test_packet_profile_and_canonical_filename_tampering_fail(self):
        for mutate in (lambda p: p['payload']['packet'].update(reference='mutable:latest'),
                       lambda p: p['payload']['packet']['producer'].update(repository='attacker/repo'),
                       lambda p: p['payload'].update(profiles=['finite']),
                       lambda p: p['payload'].update(disposition=True)):
            proposal = self.proposal()
            mutate(proposal)
            self.write(proposal)
            with self.assertRaises((TechnicalError, module.authority.AuthorityError)):
                self.verify()
            for path in self.records.glob('*.json'):
                path.unlink()
        proposal = self.proposal()
        (self.records / ('f' * 64 + '.json')).write_text(json.dumps(proposal))
        with self.assertRaisesRegex(TechnicalError, 'filename'):
            self.verify()

    def test_scan_technical_failure_cannot_be_waived(self):
        self.write(self.proposal())
        with self.assertRaises(TechnicalError):
            self.verify({'status': 'scanner-error'})
        self.assertEqual(self.calls, [])

    def test_old_decision_no_ttl_but_current_role_rechecked(self):
        identity = self.write(self.proposal())
        self.assertEqual(self.verify()['status'], 'covered')
        self.allowed.remove(identity)
        with self.assertRaises(module.authority.AuthorityError):
            self.verify()


if __name__ == '__main__':
    unittest.main()
