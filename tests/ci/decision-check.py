#!/usr/bin/env python3
import importlib.util
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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

    def test_target_discovery_is_read_only_and_keeps_review_fallback(self):
        for event in ('pull_request', 'pull_request_review'):
            api = GitHub()
            api.collector.update(event=event, pull_requests=[])
            self.assertEqual(mod.resolve_targets(REPO, 1, api),
                             {'include': [{'number': 7, 'head': HEAD, 'target': HEAD}]})
            self.assertFalse(any('/contents/' in endpoint or '/orgs/' in endpoint for endpoint in api.calls))
        api = GitHub()
        api.pr['state'] = 'closed'
        self.assertEqual(mod.resolve_targets(REPO, 1, api), {'include': []})

    def test_discovery_retains_distinct_queue_identity_and_fails_closed(self):
        api = GitHub()
        api.collector.update(event='merge_group', head_branch='gh-readonly-queue/main/pr-7-abcdef0', head_sha=MERGE)
        self.assertEqual(mod.resolve_targets(REPO, 1, api),
                         {'include': [{'number': 7, 'head': HEAD, 'target': MERGE}]})
        api.pr['head']['sha'] = 'bad'
        with self.assertRaises(mod.authority.AuthorityError):
            mod.resolve_targets(REPO, 1, api)
        api.collector['path'] = 'attacker.yml'
        with self.assertRaises(mod.authority.AuthorityError):
            mod.resolve_targets(REPO, 1, api)

    def test_worker_revalidates_live_review_instead_of_reusing_old_event_result(self):
        api = GitHub()
        posted = []
        def post(endpoint, body):
            posted.append(body)
            return {'app': {'id': 123}}
        expected = (7, HEAD, HEAD)
        self.assertEqual(mod.run_checks(REPO, 1, BOT, 123, api, post, expected=expected)['checks'][0]['status'], 'authorized')
        api.reviews.clear()
        self.assertEqual(mod.run_checks(REPO, 2, BOT, 123, api, post, expected=expected)['checks'][0]['status'], 'review-required')
        self.assertEqual([body['conclusion'] for body in posted], ['success', 'failure'])
        self.assertTrue(all(body['head_sha'] == HEAD for body in posted))

    def test_obsolete_head_before_or_during_validation_never_posts(self):
        for during in (False, True):
            api = GitHub()
            if during:
                self.packet_validator.side_effect = lambda _: api.pr['head'].update(sha='e' * 40)
            else:
                api.pr['head']['sha'] = 'e' * 40
            with self.subTest(during=during):
                result = mod.run_checks(REPO, 1, BOT, 123, api,
                    lambda *_: self.fail('Obsolete worker must not post'), expected=(7, HEAD, HEAD))
                self.assertEqual(result['checks'][0]['status'], 'obsolete')

    def test_worker_cannot_choose_unrelated_pr_or_target(self):
        for expected in ((8, HEAD, HEAD), (7, HEAD, MERGE), (7, 'bad', HEAD), (True, HEAD, HEAD)):
            with self.subTest(expected=expected), self.assertRaises(mod.authority.AuthorityError):
                mod.run_checks(REPO, 1, BOT, 123, GitHub(),
                    lambda *_: self.fail('Invalid worker must not post'), expected=expected)

    def test_replaced_queue_reference_never_receives_a_late_result(self):
        api = GitHub()
        api.collector.update(event='merge_group', head_branch='gh-readonly-queue/main/pr-7-abcdef0', head_sha=MERGE)
        self.packet_validator.side_effect = lambda _: setattr(api, 'queue_sha', HEAD)
        with self.assertRaises(mod.authority.AuthorityError):
            mod.run_checks(REPO, 1, BOT, 123, api,
                lambda *_: self.fail('Replaced queue must not post'), expected=(7, HEAD, MERGE))

    def test_discovery_bound_is_explicit_instead_of_truncating_targets(self):
        api = GitHub()
        with mock.patch.object(mod, 'collector_targets', return_value=[(7, None)] * 65):
            with self.assertRaisesRegex(mod.authority.AuthorityError, 'bounded matrix'):
                mod.resolve_targets(REPO, 1, api)

    def test_authority_workflow_serializes_writers_after_cheap_native_discovery(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/decision-authority.yml').read_text())
        discover = workflow['jobs']['discover']
        self.assertEqual(discover['permissions'], {'contents': 'read', 'actions': 'read', 'pull-requests': 'read', 'checks': 'read'})
        self.assertFalse(any(s.get('uses') == '$/.github/actions/setup-nix'
                             or s.get('uses', '').startswith('actions/create-github-app-token@')
                             for s in discover['steps']))
        writer = workflow['jobs']['authority']
        self.assertEqual(writer['needs'], 'discover')
        self.assertFalse(writer['strategy']['fail-fast'])
        self.assertFalse(writer['concurrency']['cancel-in-progress'])
        group = writer['concurrency']['group']
        self.assertIn('matrix.number', group)
        self.assertIn('matrix.target', group)
        self.assertNotIn('workflow_run.id', group)
        command = next(s['run'] for s in writer['steps'] if '--expected-head' in s.get('run', ''))
        self.assertIn('--target-sha', command)

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


class RecoveryGitHub(GitHub):
    def __init__(self):
        super().__init__()
        self.controller = {'id': 55, 'path': mod.CONTROLLER, 'repository': {'full_name': REPO},
                           'head_repository': {'full_name': REPO}, 'head_branch': 'main',
                           'head_sha': 'e' * 40, 'status': 'in_progress', 'event': 'schedule', 'run_attempt': 1}
        self.checks = {}
        self.refs = []
        self.pr['number'] = 7

    def __call__(self, endpoint):
        if endpoint.endswith('/actions/runs/55'): return self.controller
        if '/git/matching-refs/' in endpoint: return self.refs
        if '/check-runs?' in endpoint:
            target = endpoint.split('/commits/')[1].split('/')[0]
            values = self.checks.get(target, [])
            return {'total_count': len(values), 'check_runs': deepcopy(values)}
        return super().__call__(endpoint)


class ApprovalRecovery(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(mod, 'validate_proposal_packet', return_value={})
        self.validator = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = RecoveryGitHub()
        self.now = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
        self.posts = []

    def post(self, endpoint, body):
        self.assertEqual(endpoint, f'repos/{REPO}/check-runs')
        self.posts.append(body)
        return {'app': {'id': 123}}

    def stamp(self, state='success', target=HEAD, *, minutes=20, app=123):
        fingerprint = mod.review_fingerprint(self.api, REPO, 7, HEAD)
        row = {'id': 90, 'name': mod.CHECK_NAME, 'head_sha': target, 'app': {'id': app},
               'status': 'completed', 'conclusion': 'success' if state == 'success' else 'failure',
               'completed_at': (self.now - timedelta(minutes=minutes)).isoformat(),
               'external_id': mod.REVIEW_STAMP + fingerprint + ':' + state}
        self.api.checks[target] = [row]
        return row

    def targets(self, **kwargs):
        return mod.recovery_targets(REPO, 55, 123, kwargs.pop('api', self.api), now=self.now, **kwargs)

    def worker(self, target=HEAD, **kwargs):
        return mod.run_checks(REPO, 55, BOT, 123, kwargs.pop('api', self.api), self.post,
                              expected=(7, HEAD, target), recovery=True)

    def test_late_approval_replaces_old_rejection_with_fresh_validation(self):
        approved = deepcopy(self.api.reviews)
        self.api.reviews = []
        self.stamp('review-required', minutes=3)
        self.assertEqual(self.targets(), {'include': []})
        self.api.reviews = approved
        self.api.reviews[0]['submitted_at'] = '2000-01-01T00:00:00Z'
        self.assertEqual(self.targets()['include'], [{'number': 7, 'head': HEAD, 'target': HEAD}])
        self.worker()
        self.assertEqual(self.posts[0]['conclusion'], 'success')
        self.assertTrue(self.posts[0]['external_id'].endswith(':success'))
        self.assertEqual(self.api.calls.count(f'repos/{REPO}/pulls/7/reviews?per_page=100&page=1') > 0, True)

    def test_recent_unchanged_review_result_avoids_duplicate_worker(self):
        for state in ('success', 'review-required', 'invalid'):
            with self.subTest(state=state):
                self.stamp(state, minutes=3)
                self.assertEqual(self.targets(), {'include': []})
        self.assertEqual(self.posts, [])

    def test_unchanged_reviews_periodically_revalidate_live_membership(self):
        for state in ('success', 'review-required', 'invalid'):
            with self.subTest(state=state):
                self.stamp(state, minutes=10)
                self.assertEqual(len(self.targets()['include']), 1)
        self.stamp('success', minutes=10000)
        self.api.members = []
        self.assertEqual(len(self.targets()['include']), 1)
        self.worker()
        self.assertEqual(self.posts[-1]['conclusion'], 'failure')
        self.assertTrue(self.posts[-1]['external_id'].endswith(':review-required'))

    def test_missing_foreign_or_unstamped_check_is_selected(self):
        self.assertEqual(len(self.targets()['include']), 1)
        self.stamp(app=999)
        self.assertEqual(len(self.targets()['include']), 1)
        row = self.stamp()
        row['external_id'] = None
        self.assertEqual(len(self.targets()['include']), 1)
        row['head_sha'] = MERGE
        with self.assertRaisesRegex(ValueError, 'native target'): self.targets()

    def test_event_grace_and_technical_retry_are_bounded(self):
        row = self.stamp('technical-error', minutes=1)
        self.assertEqual(self.targets(), {'include': []})
        row['completed_at'] = (self.now - timedelta(minutes=3)).isoformat()
        self.assertEqual(len(self.targets()['include']), 1)
        row['completed_at'] = self.now.replace(tzinfo=None).isoformat()
        with self.assertRaisesRegex(ValueError, 'timestamp'): self.targets()

    def test_manual_recheck_is_scoped_and_forces_live_validation(self):
        self.api.controller['event'] = 'workflow_dispatch'
        self.stamp()
        with self.assertRaisesRegex(ValueError, 'one PR'): self.targets()
        self.assertEqual(self.targets(number=7)['include'], [{'number': 7, 'head': HEAD, 'target': HEAD}])
        self.worker()
        self.assertEqual(len(self.posts), 1)
        self.api.controller['event'] = 'schedule'
        with self.assertRaisesRegex(ValueError, 'native open PRs'): self.targets(number=7)

    def test_recovery_cannot_bypass_missing_approval_or_revocation(self):
        for state in ('DISMISSED', 'CHANGES_REQUESTED'):
            with self.subTest(state=state):
                self.api.reviews[0]['state'] = state
                self.posts = []
                self.worker()
                self.assertEqual(self.posts[0]['conclusion'], 'failure')
                self.assertTrue(self.posts[0]['external_id'].endswith(':review-required'))
        self.api.reviews = []
        self.posts = []
        self.worker()
        self.assertEqual(self.posts[0]['conclusion'], 'failure')

    def test_review_dismissal_and_self_approval_edit_change_snapshot(self):
        before = mod.review_fingerprint(self.api, REPO, 7, HEAD)
        self.api.reviews[0]['state'] = 'DISMISSED'
        self.assertNotEqual(mod.review_fingerprint(self.api, REPO, 7, HEAD), before)
        self.api.reviews[0].update(state='COMMENTED', body='/decider approve ' + HEAD)
        approved = mod.review_fingerprint(self.api, REPO, 7, HEAD)
        self.api.reviews[0]['body'] = '/decider withdraw ' + HEAD
        self.assertNotEqual(mod.review_fingerprint(self.api, REPO, 7, HEAD), approved)

    def test_review_change_during_validation_cannot_post_late_success(self):
        self.validator.side_effect = lambda _: self.api.reviews.clear()
        result = self.worker()
        self.assertEqual(result['checks'][0]['status'], 'obsolete')
        self.assertEqual(result['checks'][0]['reason'], 'review-changed')
        self.assertEqual(self.posts, [])

    def test_moved_head_and_queue_replacement_cannot_receive_success(self):
        self.api.pr['head']['sha'] = 'b' * 40
        self.assertEqual(self.worker()['checks'][0]['status'], 'obsolete')
        self.assertEqual(self.posts, [])
        self.api.pr['head']['sha'] = HEAD
        self.api.refs = [{'ref': 'refs/heads/gh-readonly-queue/main/pr-7-abcdef0',
                          'object': {'type': 'commit', 'sha': MERGE}}]
        self.assertEqual({row['target'] for row in self.targets()['include']}, {HEAD, MERGE})
        self.validator.side_effect = lambda _: self.api.refs.clear()
        with self.assertRaisesRegex(ValueError, 'Queue target changed'): self.worker(MERGE)
        self.assertEqual(self.posts, [])

    def test_forged_recovery_origin_is_rejected_before_discovery_or_writes(self):
        original = deepcopy(self.api.controller)
        for change in ({'event': 'pull_request'}, {'head_branch': 'topic'}, {'path': 'attacker.yml'},
                       {'status': 'completed'}, {'id': 56}, {'run_attempt': True},
                       {'head_repository': {'full_name': 'attacker/repo'}}):
            with self.subTest(change=change):
                self.api.controller = {**original, **change}
                with self.assertRaises(ValueError): self.targets()
                with self.assertRaises(ValueError): self.worker()
        self.assertEqual(self.posts, [])

    def test_discovery_is_metadata_only_and_inventory_failures_do_not_spawn_writers(self):
        self.targets()
        self.assertFalse(any('/contents/' in endpoint or endpoint.startswith('orgs/') for endpoint in self.api.calls))
        def incomplete(endpoint):
            value = self.api(endpoint)
            if '/check-runs?' in endpoint: value['total_count'] += 1
            return value
        with self.assertRaisesRegex(ValueError, 'Incomplete'): self.targets(api=incomplete)
        self.assertEqual(self.posts, [])

    def test_transient_metadata_error_is_stamped_for_recovery_not_as_stable_rejection(self):
        def unavailable(endpoint):
            if '/files?' in endpoint:
                try:
                    raise mod.authority.GitHubReadError('temporary metadata failure')
                except mod.authority.GitHubReadError as error:
                    raise mod.authority.AuthorityError('metadata unavailable') from error
            return self.api(endpoint)
        self.worker(api=unavailable)
        self.assertEqual(self.posts[0]['conclusion'], 'failure')
        self.assertTrue(self.posts[0]['external_id'].endswith(':technical-error'))

    def test_review_snapshot_ignores_irrelevant_comments_but_binds_current_head(self):
        fingerprint = mod.review_fingerprint(self.api, REPO, 7, HEAD)
        extra = {**deepcopy(self.api.reviews[0]), 'id': 999, 'state': 'COMMENTED', 'body': 'Looks good'}
        self.api.reviews.append(extra)
        self.assertEqual(mod.review_fingerprint(self.api, REPO, 7, HEAD), fingerprint)
        self.assertNotEqual(mod.review_fingerprint(self.api, REPO, 7, MERGE), fingerprint)

    def test_manual_recovery_only_refreshes_check_not_test_jobs_or_publication(self):
        self.api.controller['event'] = 'workflow_dispatch'
        result = self.worker()
        self.assertEqual(result['recoveryRun'], 55)
        self.assertNotIn('collectorRun', result)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]['name'], mod.CHECK_NAME)
        self.assertEqual(self.posts[0]['head_sha'], HEAD)
        self.assertFalse(any('/rerun' in endpoint or '/dispatches' in endpoint for endpoint in self.api.calls))

    def test_manual_closed_pr_and_inconsistent_check_result_are_not_successful_refresh(self):
        self.api.controller['event'] = 'workflow_dispatch'
        self.api.pr['state'] = 'closed'
        with self.assertRaisesRegex(ValueError, 'open main-targeting'): self.targets(number=7)
        self.api.pr['state'] = 'open'
        self.api.controller['event'] = 'schedule'
        row = self.stamp('success')
        row['conclusion'] = 'failure'
        self.assertEqual(len(self.targets()['include']), 1)

    def test_recovery_cli_reports_rejected_live_authority_as_failure(self):
        import io
        from contextlib import redirect_stdout
        env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '55',
               'GITHUB_WORKFLOW_REF': REPO + '/' + mod.CONTROLLER + '@refs/heads/main',
               'FINITE_REVIEW_BOT_LOGIN': BOT, 'FINITE_REVIEW_APP_ID': '123'}
        for status, expected in (('review-required', 1), ('authorized', 0)):
            with self.subTest(status=status), mock.patch.dict(mod.os.environ, env), \
                    mock.patch.object(sys, 'argv', ['check', '--recovery-run', '55', '--pull-request', '7',
                        '--expected-head', HEAD, '--target-sha', HEAD]), \
                    mock.patch.object(mod, 'run_checks', return_value={'checks': [{'status': status}]}), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(mod.main(), expected)

    def test_workflow_exposes_main_only_manual_recheck_and_cheap_periodic_repair(self):
        import yaml
        value = yaml.safe_load((ROOT / '.github/workflows/decision-authority.yml').read_text())
        trigger = value.get('on', value.get(True))
        self.assertTrue(trigger['workflow_dispatch']['inputs']['pull_request']['required'])
        self.assertEqual(len(trigger['schedule']), 1)
        discover = value['jobs']['discover']
        self.assertIn("github.ref == 'refs/heads/main'", discover['if'])
        self.assertFalse(any('setup-nix' in step.get('uses', '') for step in discover['steps']))
        self.assertEqual(value['jobs']['authority']['if'], "needs.discover.outputs.has-targets == 'true'")


if __name__ == '__main__':
    unittest.main()
