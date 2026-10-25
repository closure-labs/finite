#!/usr/bin/env python3
import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('check', ROOT / 'scripts/ci/decision-check.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'tests/ci/decision-authority.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
REPO, BOT, HEAD, MERGE = fixtures.REPO, fixtures.BOT, fixtures.HEAD, fixtures.MERGE


class GitHub(fixtures.GitHub):
    def __init__(self):
        super().__init__()
        self.pr.update(merged=False, state='open', merge_commit_sha=None)
        self.collector = {'path': mod.COLLECTOR, 'repository': {'full_name': REPO},
                          'status': 'completed', 'conclusion': 'success', 'event': 'pull_request',
                          'head_sha': HEAD, 'head_branch': 'feature', 'pull_requests': [{'number': 7}]}
        self.head_tree = {'truncated': False, 'tree': [{'path': self.files[0]['filename'],
                          'type': 'blob', 'mode': '100644', 'sha': 'd' * 40}]}
        self.queue_tree = self.head_tree
        self.queue_sha = MERGE

    def __call__(self, endpoint):
        if '/actions/runs/' in endpoint:
            return self.collector
        if endpoint.endswith('?state=open&base=main&per_page=100&page=1'):
            return [{'number': 7}]
        if '/git/ref/heads/gh-readonly-queue/' in endpoint:
            return {'object': {'sha': self.queue_sha}}
        if endpoint == f'repos/{REPO}/git/trees/{HEAD}?recursive=1':
            return self.head_tree
        if endpoint == f'repos/{REPO}/git/trees/{MERGE}?recursive=1':
            return self.queue_tree
        return super().__call__(endpoint)


class Checks(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(mod, 'validate_proposal_packet', return_value={})
        self.packet_validator = patcher.start()
        self.addCleanup(patcher.stop)

    def test_regular_pr_passes_without_approval(self):
        api = GitHub()
        api.files = [{'filename': 'recipes/finite.yml', 'status': 'modified'}]
        api.reviews = []
        self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'not-required')

    def test_governance_requires_current_exact_human_review(self):
        for path in ('.github/workflows/build.yml', 'lib/vm-tools.nix'):
            with self.subTest(path=path):
                api = GitHub()
                api.files = [{'filename': path, 'status': 'modified'}]
                self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'authorized')
                api.reviews = []
                with self.assertRaises(mod.authority.AuthorityError):
                    mod.check_pr(REPO, 7, BOT, github=api)

    def test_team_author_can_submit_governance_and_proposals(self):
        api = GitHub()
        api.pr['user'] = {'id': 1, 'type': 'User', 'login': 'maintainer'}
        self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'authorized')
        api.files = [{'filename': 'scripts/bluebuild/security-policy.py', 'status': 'modified'}]
        self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'authorized')

    def test_outside_author_cannot_submit_governed_changes(self):
        api = GitHub()
        api.pr['user'] = {'id': 99, 'type': 'User', 'login': 'outsider'}
        api.files = [{'filename': 'scripts/ci/decision-authority.py', 'status': 'modified'}]
        with self.assertRaises(mod.authority.AuthorityError):
            mod.check_pr(REPO, 7, BOT, github=api)

    def test_self_approval_comment_review_passes_governed_check(self):
        api = GitHub()
        api.pr['user'] = api.reviews[0]['user'].copy()
        api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD)
        self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'authorized')

    def test_exact_canonical_bot_proposal(self):
        self.assertEqual(mod.check_pr(REPO, 7, BOT, github=GitHub())['status'], 'authorized')

    def test_proposal_and_nonproposal_governance_each_validate_review_once(self):
        for proposal in (True, False):
            api = GitHub()
            if not proposal:
                api.files = [{'filename': '.github/workflows/build.yml', 'status': 'modified'}]
            with self.subTest(proposal=proposal), mock.patch.object(
                    mod.authority, 'approval', wraps=mod.authority.approval) as approval:
                self.assertEqual(mod.check_pr(REPO, 7, BOT, github=api)['status'], 'authorized')
                self.assertEqual(approval.call_count, 1)
                self.assertEqual(sum('/reviews?' in call for call in api.calls), 1)

    def test_consolidated_proposal_check_rejects_withdrawal_stale_head_and_lost_eligibility(self):
        mutations = [lambda api: api.reviews.clear(),
                     lambda api: api.reviews[0].update(commit_id='e' * 40),
                     lambda api: api.reviews[0].update(state='DISMISSED'),
                     lambda api: api.members.clear(),
                     lambda api: api.roles.update(maintainer='read')]
        for number, mutate in enumerate(mutations):
            api = GitHub()
            mutate(api)
            with self.subTest(case=number), self.assertRaises(mod.authority.AuthorityError):
                mod.check_pr(REPO, 7, BOT, github=api)
        self.packet_validator.assert_not_called()

    def test_each_proposal_retains_independent_document_and_review_validation(self):
        api = GitHub()
        second = {**fixtures.PROPOSAL, 'payload': {'profiles': {'finite-dev': []}, 'disposition': 'accepted'}}
        path = mod.authority.proposal_path(second)
        api.files.append({'filename': path, 'status': 'added'})
        api.pr['changed_files'] = 2
        def github(endpoint):
            if '/contents/' + path in endpoint:
                raw = json.dumps(second).encode()
                return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                        'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
            return api(endpoint)
        with mock.patch.object(mod.authority, 'approval', wraps=mod.authority.approval) as approval:
            self.assertEqual(mod.check_pr(REPO, 7, BOT, github=github)['status'], 'authorized')
            self.assertEqual(approval.call_count, 2)
        self.assertEqual(self.packet_validator.call_count, 2)

    def test_packet_validation_is_required_after_authority(self):
        self.packet_validator.side_effect = mod.authority.AuthorityError('Invalid immutable scan packet')
        with self.assertRaises(mod.authority.AuthorityError):
            mod.check_pr(REPO, 7, BOT, github=GitHub())
        self.packet_validator.assert_called_once_with(fixtures.PROPOSAL)

    def test_renamed_governed_path_cannot_hide_review_requirement(self):
        api = GitHub()
        api.files = [{'filename': 'docs/policy.txt', 'previous_filename': 'scripts/ci/decision-authority.py', 'status': 'renamed'}]
        api.reviews = []
        with self.assertRaises(mod.authority.AuthorityError):
            mod.check_pr(REPO, 7, BOT, github=api)

    def test_queue_requires_exact_reviewed_governed_tree(self):
        api = GitHub()
        self.assertEqual(mod.check_pr(REPO, 7, BOT, MERGE, api)['status'], 'authorized')
        api.queue_tree = {'truncated': False, 'tree': []}
        with self.assertRaises(mod.authority.AuthorityError):
            mod.check_pr(REPO, 7, BOT, MERGE, api)

    def test_queue_truncation_fails_closed(self):
        api = GitHub()
        api.queue_tree = {'truncated': True, 'tree': []}
        with self.assertRaises(mod.authority.AuthorityError):
            mod.check_pr(REPO, 7, BOT, MERGE, api)

    def test_collector_metadata_only_and_review_fallback(self):
        api = GitHub()
        self.assertEqual(mod.collector_targets(api.collector, REPO, api), [(7, None)])
        api.collector.update(event='pull_request_review', pull_requests=[])
        self.assertEqual(mod.collector_targets(api.collector, REPO, api), [(7, None)])
        api.collector['path'] = '.github/workflows/attacker.yml'
        with self.assertRaises(mod.authority.AuthorityError):
            mod.collector_targets(api.collector, REPO, api)

    def test_queue_identity_and_changed_ref_rejected(self):
        api = GitHub()
        api.collector.update(event='merge_group', head_branch='gh-readonly-queue/main/pr-7-abcdef0', head_sha=MERGE)
        self.assertEqual(mod.collector_targets(api.collector, REPO, api), [(7, MERGE)])
        api.queue_sha = HEAD
        with self.assertRaises(mod.authority.AuthorityError):
            mod.collector_targets(api.collector, REPO, api)
        api.collector['head_branch'] = 'attacker/pr-7-abcdef0'
        with self.assertRaises(mod.authority.AuthorityError):
            mod.collector_targets(api.collector, REPO, api)

    def test_app_origin_checked_and_missing_approval_posts_failure(self):
        api = GitHub()
        api.reviews = []
        calls = []
        def post(endpoint, body):
            calls.append((endpoint, body))
            return {'app': {'id': 123}}
        result = mod.run_checks(REPO, 1, BOT, 123, api, post)
        self.assertEqual(result['checks'][0]['status'], 'review-required')
        self.assertEqual(calls[0][1]['conclusion'], 'failure')
        with self.assertRaises(mod.authority.AuthorityError):
            mod.run_checks(REPO, 1, BOT, 999, api, post)

    def test_security_authority_boundary_paths(self):
        for path in ('scripts/ci/applicability-evidence.py', 'scripts/bluebuild/future-scan-helper.py', 'flake.lock', 'flake.nix', 'cosign.pub', 'lib/mk-pkgs.nix',
                     'lib/project-policy.nix', 'lib/secretspec.nix', 'sources/bluefin-trust.json',
                     'sources/bluefin.pub', 'sources/cosign-runtime.json', 'secretspec.toml', 'lib/ci-tools.nix', 'lib/ci-secrets.nix',
                     'scripts/ci/security_decisions.py', '.github/actions/setup-nix/action.yml',
                     'scripts/bluebuild/publication.py', 'scripts/ci/release-recovery.py',
                     'automation/github/repository-security.json'):
            self.assertTrue(mod.governed(path), path)
        for boundary in ('verify-security-admission.py', 'reconcile-decisions.py',
                         'verify-attestation-subject.py', 'inventory-evidence.py'):
            self.assertTrue(mod.governed('scripts/ci/' + boundary))
        self.assertTrue(mod.governed('scripts/ci/decision_revocation.py'))
        self.assertTrue(mod.governed('scripts/ci/execute-release-set.py'))
        self.assertFalse(mod.governed('docs/README.md'))


if __name__ == '__main__':
    unittest.main()
