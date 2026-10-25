#!/usr/bin/env python3
"""Exercise authority against a fake GitHub API; local JSON is never enough."""
import base64
import hashlib
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('authority', ROOT / 'scripts/ci/decision-authority.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
REPO = 'closure-labs/finite'
BOT = 'finite-review[bot]'
HEAD, MERGE, MAIN = 'a' * 40, 'b' * 40, 'c' * 40
PROPOSAL = {'schema': 1, 'kind': 'security-findings', 'payload': {'profiles': {'finite': []}, 'disposition': 'accepted'}}


class GitHub:
    def __init__(self):
        self.proposal = copy.deepcopy(PROPOSAL)
        self.pr = {'number': 7, 'user': {'type': 'Bot', 'login': BOT},
                   'head': {'sha': HEAD, 'repo': {'full_name': REPO}},
                   'base': {'ref': 'main', 'repo': {'full_name': REPO}},
                   'merged': True, 'state': 'closed', 'merge_commit_sha': MERGE, 'changed_files': 1}
        self.reviews = [{'id': 10, 'state': 'APPROVED', 'commit_id': HEAD,
                         'user': {'id': 1, 'login': 'maintainer', 'type': 'User'}}]
        self.roles = {'maintainer': 'maintain', 'submitter': 'write'}
        self.submitters = [{'id': 3, 'login': 'submitter', 'type': 'User'}]
        self.team = {'id': 20196962, 'slug': 'super-admins', 'organization': {'login': 'closure-labs'}}
        self.members = [{'id': 1, 'login': 'maintainer', 'type': 'User'}, {'id': 2, 'login': 'other', 'type': 'User'}]
        self.memberships = {}
        self.files = [{'filename': mod.proposal_path(PROPOSAL), 'status': 'added'}]
        self.blobs = {}
        self.compare = 'ahead'
        self.main = MAIN
        self.fail = None
        self.calls = []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        if self.fail and self.fail in endpoint:
            raise mod.AuthorityError('API unavailable')
        if endpoint == 'orgs/closure-labs/teams/maintainers':
            return {'id': 20196828, 'slug': 'maintainers', 'organization': {'login': 'closure-labs'}}
        if '/teams/maintainers/members?' in endpoint:
            return copy.deepcopy(self.submitters)
        if '/teams/maintainers/memberships/' in endpoint:
            login = endpoint.rsplit('/', 1)[-1]
            return copy.deepcopy(self.memberships.get(login.lower(), {'state': 'active', 'role': 'member'}))
        if endpoint == 'orgs/closure-labs/teams/super-admins':
            return copy.deepcopy(self.team)
        if '/teams/super-admins/members?' in endpoint:
            return copy.deepcopy(self.members)
        if '/teams/super-admins/memberships/' in endpoint:
            login = endpoint.rsplit('/', 1)[-1]
            return copy.deepcopy(self.memberships.get(login.lower(), {'state': 'active', 'role': 'member'}))
        if endpoint == f'repos/{REPO}/pulls/7':
            return copy.deepcopy(self.pr)
        if '/pulls/7/reviews?' in endpoint:
            return copy.deepcopy(self.reviews)
        if '/pulls/7/files?' in endpoint:
            return copy.deepcopy(self.files)
        if '/collaborators/' in endpoint:
            login = endpoint.split('/collaborators/')[1].split('/')[0]
            return {'permission': 'write', 'role_name': self.roles.get(login.lower(), 'read')}
        if '/contents/' in endpoint:
            revision = endpoint.split('?ref=')[1]
            data = json.dumps(self.blobs.get(revision, self.proposal)).encode()
            return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
                    'encoding': 'base64', 'size': len(data),
                    'content': base64.b64encode(data).decode()}
        if endpoint.endswith('/git/ref/heads/main'):
            return {'object': {'sha': self.main}}
        if '/compare/' in endpoint:
            return {'status': self.compare}
        raise AssertionError('Unexpected API call: ' + endpoint)


def verify(api, **kwargs):
    return mod.verify_proposal(PROPOSAL, 7, REPO, BOT, github=api, **kwargs)


class ImmutableDocuments(unittest.TestCase):
    def test_same_binding_reuses_verified_bytes_and_returns_fresh_objects(self):
        api = GitHub()
        path = mod.proposal_path(PROPOSAL)
        with mod.immutable_documents():
            first = mod.document_at(api, REPO, path, HEAD)
            first['payload']['disposition'] = 'rejected'
            self.assertEqual(mod.document_at(api, REPO, path, HEAD), PROPOSAL)
            self.assertEqual(len(api.calls), 1)
            for repo, name, revision in [('other/repo', path, HEAD), (REPO, 'other.json', HEAD),
                                         (REPO, path, MERGE)]:
                self.assertEqual(mod.document_at(api, repo, name, revision), PROPOSAL)
            self.assertEqual(len(api.calls), 4)

    def test_invocations_nested_scopes_and_errors_do_not_leak_documents(self):
        api = GitHub()
        path = mod.proposal_path(PROPOSAL)
        with mod.immutable_documents():
            mod.document_at(api, REPO, path, HEAD)
            with mod.immutable_documents():
                mod.document_at(api, REPO, path, HEAD)
            mod.document_at(api, REPO, path, HEAD)
            self.assertEqual(len(api.calls), 2)
        with self.assertRaisesRegex(RuntimeError, 'stop'), mod.immutable_documents():
            mod.document_at(api, REPO, path, HEAD)
            raise RuntimeError('stop')
        mod.document_at(api, REPO, path, HEAD)
        mod.document_at(api, REPO, path, HEAD)
        self.assertEqual(len(api.calls), 5)

    def test_full_budget_falls_back_to_original_reads(self):
        for limit in ('DOCUMENT_BYTES', 'DOCUMENT_ENTRIES'):
            api = GitHub()
            with self.subTest(limit=limit), patch.object(mod, limit, 0), mod.immutable_documents():
                for _ in range(2):
                    self.assertEqual(mod.document_at(api, REPO, 'proposal.json', HEAD), PROPOSAL)
                self.assertEqual(len(api.calls), 2)

    def test_budget_boundary_retains_first_binding_and_reads_overflow(self):
        for limit, maximum in [('DOCUMENT_BYTES', len(json.dumps(PROPOSAL).encode())), ('DOCUMENT_ENTRIES', 1)]:
            api = GitHub()
            with self.subTest(limit=limit), patch.object(mod, limit, maximum), mod.immutable_documents():
                for revision in (HEAD, MERGE, HEAD, MERGE):
                    self.assertEqual(mod.document_at(api, REPO, 'proposal.json', revision), PROPOSAL)
                self.assertEqual(len(api.calls), 3)

    def test_invalid_bytes_are_never_reused(self):
        for raw in (b'{"duplicate":1,"duplicate":2}', b'{"number":NaN}'):
            calls = []
            api = GitHub()
            def github(endpoint):
                calls.append(endpoint)
                if len(calls) == 1:
                    return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                            'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
                return api(endpoint)
            with self.subTest(raw=raw), mod.immutable_documents():
                with self.assertRaises(mod.AuthorityError):
                    mod.document_at(github, REPO, 'proposal.json', HEAD)
                self.assertEqual(mod.document_at(github, REPO, 'proposal.json', HEAD), PROPOSAL)
                self.assertEqual(len(calls), 2)

    def test_invalid_object_identity_is_never_reused(self):
        api = GitHub()
        calls = []
        def github(endpoint):
            value = api(endpoint)
            calls.append(endpoint)
            return {**value, 'sha': 'f' * 40} if len(calls) == 1 else value
        with mod.immutable_documents():
            with self.assertRaises(mod.AuthorityError):
                mod.document_at(github, REPO, 'proposal.json', HEAD)
            self.assertEqual(mod.document_at(github, REPO, 'proposal.json', HEAD), PROPOSAL)
            self.assertEqual(len(calls), 2)

    def test_warm_documents_do_not_reuse_live_authority(self):
        api = GitHub()
        with mod.immutable_documents():
            self.assertEqual(verify(api)['status'], 'authorized')
            self.assertEqual(verify(api)['status'], 'authorized')
            self.assertEqual(sum('/contents/' in call for call in api.calls), 3)
            self.assertEqual(sum('/reviews?' in call for call in api.calls), 2)
            self.assertEqual(sum('/compare/' in call for call in api.calls), 2)
            api.reviews.clear()
            with self.assertRaises(mod.HumanDecisionRequired):
                verify(api)
            self.assertEqual(sum('/reviews?' in call for call in api.calls), 3)

    def test_warm_documents_preserve_membership_permission_and_main_failures(self):
        mutations = [lambda api: api.members.clear(), lambda api: api.roles.update(maintainer='read'),
                     lambda api: api.memberships.update(maintainer={'state': 'pending', 'role': 'member'}),
                     lambda api: setattr(api, 'compare', 'behind'), lambda api: setattr(api, 'fail', '/reviews?'),
                     lambda api: api.pr.update(merged=False, state='open')]
        for mutate in mutations:
            api = GitHub()
            with self.subTest(mutation=mutations.index(mutate)), mod.immutable_documents():
                verify(api)
                mutate(api)
                with self.assertRaises(mod.AuthorityError):
                    verify(api)

    def test_new_head_requires_new_content_and_approval(self):
        api = GitHub()
        with mod.immutable_documents():
            verify(api)
            api.pr['head']['sha'] = 'd' * 40
            with self.assertRaises(mod.HumanDecisionRequired):
                verify(api)
            self.assertEqual(sum('/contents/' in call for call in api.calls), 4)

    def test_new_main_fetches_new_binding_and_rejects_changed_decision(self):
        for changed in (False, True):
            api = GitHub()
            with self.subTest(changed=changed), mod.immutable_documents():
                verify(api)
                api.main = 'e' * 40
                if changed:
                    api.blobs[api.main] = {**PROPOSAL, 'payload': {'disposition': 'rejected'}}
                    with self.assertRaisesRegex(mod.AuthorityError, 'no longer unchanged on main'):
                        verify(api)
                else:
                    self.assertEqual(verify(api)['status'], 'authorized')
                self.assertEqual(sum('/contents/' in call for call in api.calls), 4)


class OriginFallback(unittest.TestCase):
    def fixture(self, *, commit=HEAD, transient=True):
        api = GitHub()
        pull = {**copy.deepcopy(api.pr), 'merged_at': '2026-10-20T00:00:00Z'}
        inventory = [pull]
        calls = []
        def github(endpoint):
            calls.append(endpoint)
            if '/commits?path=' in endpoint:
                return [{'sha': commit}]
            if '/commits/' in endpoint and '/pulls?' in endpoint:
                try:
                    raise mod.GitHubReadError('association read exhausted', transient=transient)
                except mod.GitHubReadError as error:
                    raise mod.AuthorityError(str(error)) from error
            if endpoint.startswith(f'repos/{REPO}/pulls?'):
                return copy.deepcopy(inventory)
            return api(endpoint)
        return api, inventory, calls, github

    def test_transient_association_failure_recovers_exact_head_or_merge(self):
        for commit in (HEAD, MERGE):
            with self.subTest(commit=commit):
                api, _, calls, github = self.fixture(commit=commit)
                number = mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
                self.assertEqual(number, 7)
                self.assertIn(f'repos/{REPO}/pulls/7', calls)
                self.assertEqual(mod.verify_proposal(PROPOSAL, number, REPO, BOT, github=github)['status'], 'authorized')

    def test_terminal_association_failure_never_uses_inventory(self):
        _, _, calls, github = self.fixture(transient=False)
        with self.assertRaises(mod.AuthorityError):
            mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
        self.assertFalse(any(endpoint.startswith(f'repos/{REPO}/pulls?') for endpoint in calls))

    def test_successful_empty_association_never_uses_inventory(self):
        _, _, calls, original = self.fixture()
        def github(endpoint):
            if '/commits/' in endpoint and '/pulls?' in endpoint:
                return []
            return original(endpoint)
        with self.assertRaises(mod.AuthorityError):
            mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
        self.assertFalse(any(endpoint.startswith(f'repos/{REPO}/pulls?') for endpoint in calls))

    def test_ambiguous_or_unrelated_candidates_fail_closed(self):
        for variant in ('duplicate', 'unrelated', 'unmerged', 'foreign', 'wrong-base', 'unknown-bot'):
            with self.subTest(variant=variant):
                _, inventory, _, github = self.fixture()
                if variant == 'duplicate':
                    inventory.append({**copy.deepcopy(inventory[0]), 'number': 8})
                elif variant == 'unrelated':
                    inventory[0]['head']['sha'] = 'd' * 40
                elif variant == 'unmerged':
                    inventory[0]['merged_at'] = None
                elif variant == 'foreign':
                    inventory[0]['head']['repo']['full_name'] = 'other/repo'
                elif variant == 'wrong-base':
                    inventory[0]['base']['ref'] = 'other'
                else:
                    inventory[0]['user']['login'] = 'other[bot]'
                with self.assertRaises(mod.AuthorityError):
                    mod.find_origin_pr(PROPOSAL, REPO, BOT, github)

    def test_incomplete_inventory_is_not_provenance(self):
        _, inventory, calls, github = self.fixture()
        inventory[:] = inventory * 100
        with self.assertRaisesRegex(mod.AuthorityError, 'bounded pagination'):
            mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
        self.assertEqual(sum(endpoint.startswith(f'repos/{REPO}/pulls?') for endpoint in calls), 10)

    def test_changed_native_candidate_is_rejected(self):
        api, _, _, github = self.fixture()
        api.pr['head']['sha'] = 'd' * 40
        with self.assertRaises(mod.AuthorityError):
            mod.find_origin_pr(PROPOSAL, REPO, BOT, github)

    def test_fallback_does_not_replace_fresh_approval(self):
        api, _, _, github = self.fixture()
        number = mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
        api.reviews.clear()
        with self.assertRaises(mod.HumanDecisionRequired):
            mod.verify_proposal(PROPOSAL, number, REPO, BOT, github=github)

    def test_fallback_does_not_authorize_changed_reviewed_bytes(self):
        api, _, _, github = self.fixture()
        number = mod.find_origin_pr(PROPOSAL, REPO, BOT, github)
        api.blobs[HEAD] = {**PROPOSAL, 'payload': {'disposition': 'rejected'}}
        with self.assertRaisesRegex(mod.AuthorityError, 'exact reviewed PR head'):
            mod.verify_proposal(PROPOSAL, number, REPO, BOT, github=github)


class Authority(unittest.TestCase):
    def test_origin_lookup_accepts_human_pr_and_rejects_unknown_bot(self):
        api = GitHub()
        original = api.__call__
        def github(endpoint):
            if '/commits?path=' in endpoint:
                return [{'sha': MERGE}]
            if '/commits/' in endpoint and '/pulls?' in endpoint:
                return [{**api.pr, 'merged_at': '2026-10-20T00:00:00Z'}]
            return original(endpoint)
        api.pr['user'] = {'id': 3, 'login': 'submitter', 'type': 'User'}
        self.assertEqual(mod.find_origin_pr(PROPOSAL, REPO, BOT, github), 7)
        api.pr['user'] = {'type': 'Bot', 'login': 'other[bot]'}
        with self.assertRaises(mod.AuthorityError):
            mod.find_origin_pr(PROPOSAL, REPO, BOT, github)

    def test_submitter_revocation_during_authorization_fails_closed(self):
        api = GitHub()
        api.pr['user'] = {'id': 3, 'login': 'submitter', 'type': 'User'}
        def github(endpoint):
            result = api(endpoint)
            if '/pulls/7/reviews?' in endpoint:
                api.submitters.clear()
            return result
        with self.assertRaises(mod.AuthorityError):
            mod.verify_proposal(PROPOSAL, 7, REPO, BOT, github=github)

    def test_team_members_can_submit_and_only_super_admins_can_approve(self):
        for user in ({'id': 1, 'login': 'maintainer', 'type': 'User'},
                     {'id': 3, 'login': 'submitter', 'type': 'User'}):
            api = GitHub()
            api.pr['user'] = user
            self.assertEqual(verify(api)['status'], 'authorized')
        api.reviews = [{'id': 12, 'state': 'APPROVED', 'commit_id': HEAD,
                        'user': api.pr['user']}]
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)

    def test_submitter_requires_live_pinned_membership_identity_and_permission(self):
        user = {'id': 3, 'login': 'submitter', 'type': 'User'}
        for mutate in (lambda a: a.pr['user'].update(id=999),
                       lambda a: a.submitters.clear(),
                       lambda a: a.memberships.update(submitter={'state': 'pending', 'role': 'member'}),
                       lambda a: a.roles.update(submitter='read')):
            api = GitHub()
            api.pr['user'] = copy.deepcopy(user)
            mutate(api)
            with self.subTest(mutate=mutate), self.assertRaises(mod.AuthorityError):
                verify(api)
        api = GitHub()
        api.pr['user'] = user
        api.fail = '/teams/maintainers'
        with self.assertRaises(mod.AuthorityError):
            verify(api)

    def test_super_admin_can_explicitly_approve_own_exact_head(self):
        api = GitHub()
        api.pr['user'] = copy.deepcopy(api.reviews[0]['user'])
        api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD)
        receipt = verify(api)
        self.assertEqual(receipt['status'], 'authorized')
        self.assertEqual(receipt['approvalMethod'], 'comment-review')

    def test_comment_approval_requires_explicit_current_head_and_super_admin(self):
        for body, commit in (('approve', HEAD), ('/decider approve ' + MERGE, HEAD),
                             ('/decider approve ' + HEAD, MERGE),
                             ('quoted: /decider approve ' + HEAD, HEAD)):
            api = GitHub()
            api.reviews[0].update(state='COMMENTED', body=body, commit_id=commit)
            with self.subTest(body=body, commit=commit), self.assertRaises(mod.HumanDecisionRequired):
                verify(api)
        api = GitHub()
        api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD,
                              user={'id': 3, 'login': 'submitter', 'type': 'User'})
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)

    def test_edited_comment_and_other_super_admin_rejection_remove_authority(self):
        api = GitHub()
        api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD)
        self.assertEqual(verify(api)['status'], 'authorized')
        api.reviews[0]['body'] = 'withdrawn'
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)
        api.reviews[0]['body'] = '/decider approve ' + HEAD
        api.roles['other'] = 'maintain'
        api.reviews.append({'id': 11, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD,
                            'user': {'id': 2, 'type': 'User', 'login': 'other'}})
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)

    def test_comment_withdrawal_dismissal_and_changes_requested_revoke_approval(self):
        for state, body in (('COMMENTED', '/decider withdraw ' + HEAD),
                            ('DISMISSED', '/decider approve ' + HEAD), ('CHANGES_REQUESTED', '')):
            api = GitHub()
            api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD)
            api.reviews.append({**api.reviews[0], 'id': 11, 'state': state, 'body': body})
            with self.subTest(state=state), self.assertRaises(mod.HumanDecisionRequired):
                verify(api)

    def test_exact_human_maintainer_approval(self):
        result = verify(GitHub())
        self.assertEqual(result['status'], 'authorized')
        self.assertEqual(result['reviewId'], 10)
        self.assertEqual(result['proposalHash'], mod.canonical_hash(PROPOSAL))

    def test_administrator_allowed_without_expiry(self):
        api = GitHub()
        api.roles['maintainer'] = 'admin'
        api.reviews[0]['submitted_at'] = '2000-01-01T00:00:00Z'
        self.assertEqual(verify(api)['status'], 'authorized')

    def test_repository_admin_outside_super_admins_cannot_approve(self):
        api = GitHub()
        api.roles['maintainer'] = 'admin'
        api.members = [member for member in api.members if member['login'] != 'maintainer']
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)
        self.assertFalse(any('/memberships/maintainer' in call for call in api.calls))

    def test_active_team_member_or_maintainer_with_repo_permission_can_approve(self):
        for role in ('member', 'maintainer'):
            api = GitHub()
            api.memberships['maintainer'] = {'state': 'active', 'role': role}
            with self.subTest(role=role):
                result = verify(api)
                self.assertEqual(result['approverTeam']['id'], 20196962)
                self.assertEqual(result['permissionPolicy'], 'current-super-admins-and-maintain-or-admin')

    def test_removed_or_pending_team_membership_withdraws_existing_approval(self):
        api = GitHub()
        self.assertEqual(verify(api)['status'], 'authorized')
        api.memberships['maintainer'] = {'state': 'pending', 'role': 'member'}
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)
        api.members = []
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)

    def test_team_identity_visibility_and_membership_errors_fail_closed(self):
        mutations = [('team', None), ('team', {'id': 999, 'slug': 'super-admins', 'organization': {'login': 'closure-labs'}}),
                     ('team', {'id': 20196962, 'slug': 'renamed', 'organization': {'login': 'closure-labs'}}),
                     ('team', {'id': 20196962, 'slug': 'super-admins', 'organization': None}),
                     ('members', {'hidden': True}), ('members', [{'id': 1, 'login': 'maintainer', 'type': 'Bot'}]),
                     ('members', [{'id': True, 'login': 'maintainer', 'type': 'User'}]),
                     ('members', [{'id': 1, 'login': 'maintainer', 'type': 'User'}] * 2)]
        for field, value in mutations:
            api = GitHub()
            setattr(api, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(mod.AuthorityError):
                verify(api)
        for membership in (None, {}, {'state': 'unknown', 'role': 'member'}, {'state': 'active', 'role': 'admin'}):
            api = GitHub()
            api.memberships['maintainer'] = membership
            with self.subTest(membership=membership), self.assertRaises(mod.AuthorityError):
                verify(api)
        for endpoint in ('orgs/closure-labs/teams/super-admins', '/members?', '/memberships/'):
            api = GitHub()
            api.fail = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(mod.AuthorityError):
                verify(api)

    def test_only_current_eligible_team_changes_request_blocks_approval(self):
        api = GitHub()
        api.roles['outside'] = 'admin'
        api.reviews.append({'id': 11, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD,
                            'user': {'id': 3, 'login': 'outside', 'type': 'User'}})
        self.assertEqual(verify(api)['status'], 'authorized')
        api.members.append({'id': 3, 'login': 'outside', 'type': 'User'})
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)
        api.memberships['outside'] = {'state': 'pending', 'role': 'member'}
        self.assertEqual(verify(api)['status'], 'authorized')

    def test_membership_change_during_authorization_fails_closed(self):
        for phase in ('inventory', 'final-selected-membership'):
            api = GitHub()
            team_reads = 0
            membership_reads = 0
            def changing(endpoint):
                nonlocal team_reads, membership_reads
                if '/members?' in endpoint:
                    team_reads += 1
                    if phase == 'inventory' and team_reads == 2:
                        api.members = []
                if '/memberships/maintainer' in endpoint:
                    membership_reads += 1
                    if phase == 'final-selected-membership' and membership_reads == 3:
                        api.memberships['maintainer'] = {'state': 'pending', 'role': 'member'}
                return api(endpoint)
            with self.subTest(phase=phase), self.assertRaises(mod.AuthorityError):
                verify(changing)

    def test_complete_bounded_team_pagination_is_required(self):
        api = GitHub()
        first = [{'id': index + 10, 'login': 'member' + str(index), 'type': 'User'} for index in range(100)]
        def paged(endpoint):
            if '/members?' in endpoint:
                if endpoint.endswith('&page=1'):
                    return first
                if endpoint.endswith('&page=2'):
                    return api.members
                self.fail('Unexpected pagination')
            return api(endpoint)
        self.assertEqual(verify(paged)['status'], 'authorized')
        def unbounded(endpoint):
            return first if '/members?' in endpoint else api(endpoint)
        with self.assertRaisesRegex(mod.AuthorityError, 'bounded pagination'):
            verify(unbounded)

    def test_human_reviewer_requires_exact_positive_immutable_member_id(self):
        for value in (None, True, 0, -1, '1', 999):
            api = GitHub()
            if value is None:
                api.reviews[0]['user'].pop('id')
            else:
                api.reviews[0]['user']['id'] = value
            with self.subTest(value=value), self.assertRaises(mod.AuthorityError):
                verify(api)
        # A newly created account reusing the former approver's login must not
        # inherit that deleted account's historical review.
        api = GitHub()
        api.members[0]['id'] = 500
        with self.assertRaisesRegex(mod.AuthorityError, 'differs from current'):
            verify(api)
        for value in (None, True, 0, -1, '1'):
            user = {'type': 'User', 'login': 'maintainer', 'id': value}
            with self.subTest(direct=value), self.assertRaises(mod.AuthorityError):
                mod.eligible(GitHub(), REPO, user)

    def test_case_only_login_change_cannot_resurrect_dismissed_review(self):
        api = GitHub()
        api.reviews.append({'id': 11, 'state': 'DISMISSED', 'commit_id': HEAD,
                            'user': {'id': 1, 'type': 'User', 'login': 'Maintainer'}})
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)
        # The same immutable user's later approval clears their earlier rejection,
        # even when GitHub returns different username capitalization.
        api.reviews[0]['state'] = 'CHANGES_REQUESTED'
        api.reviews[1]['state'] = 'APPROVED'
        self.assertEqual(verify(api)['reviewId'], 11)

    def test_new_login_for_same_immutable_user_does_not_resurrect_old_review(self):
        api = GitHub()
        api.members[0]['login'] = 'renamed'
        api.roles['renamed'] = 'maintain'
        api.reviews.append({'id': 11, 'state': 'DISMISSED', 'commit_id': HEAD,
                            'user': {'id': 1, 'type': 'User', 'login': 'renamed'}})
        with self.assertRaises(mod.HumanDecisionRequired):
            verify(api)

    def test_current_permission_required(self):
        api = GitHub()
        api.roles['maintainer'] = 'write'
        with self.assertRaises(mod.AuthorityError):
            verify(api)

    def test_bot_review_and_wrong_head_do_not_authorize(self):
        for field, value in [('commit_id', 'd' * 40), ('state', 'DISMISSED'),
                             ('user', {'type': 'Bot', 'login': BOT})]:
            api = GitHub()
            api.reviews[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(mod.AuthorityError):
                    verify(api)

    def test_latest_review_and_other_maintainer_rejection(self):
        for user in ('maintainer', 'other'):
            api = GitHub()
            api.roles[user] = 'maintain'
            api.reviews.append({'id': 11, 'state': 'CHANGES_REQUESTED', 'commit_id': HEAD,
                                'user': {'id': 1 if user == 'maintainer' else 2, 'type': 'User', 'login': user}})
            with self.assertRaises(mod.AuthorityError):
                verify(api)

    def test_new_approval_clears_same_reviewers_rejection(self):
        api = GitHub()
        api.reviews.append({**api.reviews[0], 'id': 11, 'state': 'CHANGES_REQUESTED'})
        api.reviews.append({**api.reviews[0], 'id': 12})
        self.assertEqual(verify(api)['reviewId'], 12)

    def test_untrusted_bot_or_repository_or_base_rejected(self):
        for mutate in (lambda p: p['user'].update(login='attacker[bot]'),
                       lambda p: p['head']['repo'].update(full_name='attacker/finite'),
                       lambda p: p['base'].update(ref='other')):
            api = GitHub()
            mutate(api.pr)
            with self.assertRaises(mod.AuthorityError):
                verify(api)

    def test_merged_json_alone_and_changed_merged_blob_rejected(self):
        for revision in (HEAD, MERGE, MAIN):
            api = GitHub()
            api.blobs[revision] = {**PROPOSAL, 'payload': {'forged': True}}
            with self.subTest(revision=revision):
                with self.assertRaises(mod.AuthorityError):
                    verify(api)
        api = GitHub()
        api.reviews = []
        with self.assertRaises(mod.AuthorityError):
            verify(api)

    def test_merge_must_be_ancestor_of_main(self):
        api = GitHub()
        api.compare = 'diverged'
        with self.assertRaises(mod.AuthorityError):
            verify(api)

    def test_open_approval_only_usable_for_premerge_check(self):
        api = GitHub()
        api.pr.update(merged=False, state='open', merge_commit_sha=None)
        with self.assertRaises(mod.AuthorityError):
            verify(api)
        self.assertEqual(verify(api, require_merged=False)['status'], 'authorized')

    def test_unexpected_renamed_deleted_or_missing_files_rejected(self):
        for files in ([], [{'filename': 'scripts/backdoor.py', 'status': 'added'}],
                      [{'filename': mod.proposal_path(PROPOSAL), 'status': 'renamed'}],
                      [{'filename': mod.proposal_path(PROPOSAL), 'status': 'removed'}]):
            api = GitHub()
            api.files = files
            with self.assertRaises(mod.AuthorityError):
                verify(api)

    def test_api_failure_is_closed(self):
        for endpoint in ('reviews', 'permission', 'contents', 'compare'):
            api = GitHub()
            api.fail = endpoint
            with self.assertRaises(mod.AuthorityError):
                verify(api)

    def large_blob(self):
        proposal = {**PROPOSAL, 'payload': {'rationale': 'x' * (1024 * 1024 + 1)}}
        raw = json.dumps(proposal).encode()
        identity = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        metadata = {'type': 'file', 'sha': identity, 'size': len(raw), 'encoding': 'none', 'content': ''}
        blob = {'sha': identity, 'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
        return proposal, metadata, blob

    def test_large_proposal_uses_only_exact_git_blob_fallback(self):
        proposal, metadata, blob = self.large_blob()
        calls = []
        def api(endpoint):
            calls.append(endpoint)
            return metadata if '/contents/' in endpoint else blob
        with mod.immutable_documents():
            for _ in range(2):
                result = mod.document_at(api, REPO, 'automation/decisions/security/large.json', HEAD)
                self.assertEqual(result, proposal)
        self.assertEqual(calls[-1], f'repos/{REPO}/git/blobs/{metadata["sha"]}')
        self.assertEqual(len(calls), 2)

    def test_large_blob_metadata_encoding_size_and_object_hash_must_agree(self):
        _, metadata, original = self.large_blob()
        tampered = bytearray(base64.b64decode(original['content']))
        tampered[-4] = ord('z')
        changes = [{'sha': 'f' * 40}, {'size': original['size'] + 1}, {'size': 8 * 1024**2 + 1},
                   {'encoding': 'none'}, {'content': '#'},
                   {'content': base64.b64encode(tampered).decode()}]
        for change in changes:
            blob = {**original, **change}
            with self.subTest(change=list(change)), self.assertRaises(mod.AuthorityError):
                mod.document_at(lambda endpoint: metadata if '/contents/' in endpoint else blob,
                                REPO, 'proposal.json', HEAD)

    def test_oversize_or_nonfile_metadata_never_fetches_a_blob(self):
        _, original, blob = self.large_blob()
        for change in ({'size': 8 * 1024**2 + 1}, {'type': 'dir'}, {'sha': 'bad'}, {'size': True}):
            metadata = {**original, **change}
            calls = []
            def api(endpoint):
                calls.append(endpoint)
                return metadata if '/contents/' in endpoint else blob
            with self.subTest(change=change), self.assertRaises(mod.AuthorityError):
                mod.document_at(api, REPO, 'proposal.json', HEAD)
            self.assertEqual(len(calls), 1)

    def test_small_inline_content_also_checks_git_object_identity(self):
        data = json.dumps(PROPOSAL).encode()
        metadata = {'type': 'file', 'sha': '0' * 40, 'size': len(data), 'encoding': 'base64',
                    'content': base64.b64encode(data).decode()}
        with self.assertRaises(mod.AuthorityError):
            mod.document_at(lambda endpoint: metadata, REPO, 'proposal.json', HEAD)

    def test_requires_configured_bot_and_canonical_envelope(self):
        with self.assertRaises(mod.AuthorityError):
            mod.verify_proposal(PROPOSAL, 7, REPO, None, github=GitHub())
        with self.assertRaises(mod.AuthorityError):
            mod.proposal_path({**PROPOSAL, 'reviewedBy': 'maintainer'})


if __name__ == '__main__':
    unittest.main()
