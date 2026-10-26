#!/usr/bin/env python3
"""Execution approval never becomes review, queue or publication authority."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('admission', ROOT / 'scripts/ci/ci-run-admission.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
HEAD = 'a' * 40


class Admission(unittest.TestCase):
    def setUp(self):
        self.rules = mod.policy()
        self.repo = {'id': self.rules['repositoryId'], 'full_name': self.rules['repository']}
        self.author = {'type': 'Bot', 'login': 'cl-decider[bot]', 'id': 344936881}
        self.pr = {'number': 7, 'state': 'open', 'draft': True, 'user': deepcopy(self.author),
                   'base': {'ref': 'main', 'repo': self.repo},
                   'head': {'sha': HEAD, 'ref': 'topic', 'repo': {'id': 99, 'full_name': 'fork/finite'}}}
        self.run = {'id': 40, 'run_attempt': 1, 'repository': self.repo,
                    'event': 'pull_request', 'path': '.github/workflows/build.yml', 'workflow_id': 50,
                    'head_sha': HEAD, 'head_branch': 'topic', 'head_repository': self.pr['head']['repo'],
                    'status': 'completed', 'conclusion': 'action_required', 'pull_requests': [{'number': 7}]}
        self.workflow = {'id': 50, 'path': self.run['path'], 'state': 'active'}
        self.members = {'human': 123}
        self.membership = {'state': 'active', 'role': 'member'}
        self.permission = {'permission': 'admin', 'role_name': 'admin'}
        self.posts = []
        self.pr_reads = self.run_reads = 0
        self.move = self.revoke = False
        self.env = {'GITHUB_REPOSITORY': self.rules['repository'], 'GITHUB_EVENT_NAME': 'pull_request_target'}
        self.event = {'number': 7, 'pull_request': {'head': {'sha': HEAD}}}

    def api(self, endpoint):
        if endpoint.endswith('/pulls/7'):
            self.pr_reads += 1
            value = deepcopy(self.pr)
            if self.move and self.pr_reads > 1: value['head']['sha'] = 'b' * 40
            return value
        if endpoint.endswith('/actions/runs/40'):
            self.run_reads += 1
            return deepcopy(self.run)
        if endpoint.endswith('/actions/workflows/50'): return deepcopy(self.workflow)
        if '/actions/runs?' in endpoint:
            return {'total_count': 1, 'workflow_runs': [deepcopy(self.run)]}
        if '/commits/' in endpoint and '/pulls?' in endpoint: return [{'number': 7}]
        if endpoint.endswith('/teams/super-admins'):
            return {'id': 20196962, 'slug': 'super-admins', 'organization': {'login': 'closure-labs'}}
        if '/teams/super-admins/members?' in endpoint:
            if self.revoke and self.pr_reads > 2: return []
            return [{'id': identity, 'login': login, 'type': 'User'} for login, identity in self.members.items()]
        if '/teams/super-admins/memberships/' in endpoint: return deepcopy(self.membership)
        if '/collaborators/' in endpoint: return deepcopy(self.permission)
        raise AssertionError(endpoint)

    def approve(self, **kwargs):
        return mod.approve(self.rules, 7, HEAD, [40], api=kwargs.get('api', self.api),
                           post=kwargs.get('post', self.posts.append))

    def human(self):
        self.pr['user'] = {'id': 123, 'login': 'human', 'type': 'User'}

    def test_draft_and_ready_decider_runs_are_approved_without_review(self):
        for draft in (True, False):
            self.pr['draft'] = draft
            result = self.approve()
            self.assertEqual(result['runs'][0]['status'], 'execution-approved')
            self.assertFalse(result['grantsMergeApproval'])
            self.assertFalse(result['authorizesPublication'])
        self.assertEqual(self.posts, ['repos/closure-labs/finite/actions/runs/40/approve'] * 2)

    def test_live_super_admin_membership_and_permission_are_required(self):
        self.human()
        self.assertEqual(self.approve()['status'], 'checked')
        self.assertEqual(len(self.posts), 1)
        for change in ('removed', 'pending', 'maintainer-only', 'write-only'):
            with self.subTest(change=change):
                self.setUp();self.human()
                if change in ('removed', 'maintainer-only'): self.members = {}
                elif change == 'pending': self.membership['state'] = 'pending'
                else: self.permission['role_name'] = 'write'
                self.assertEqual(self.approve()['status'], 'manual-execution-approval-required')
                self.assertEqual(self.posts, [])

    def test_bot_login_or_type_spoof_and_wrong_immutable_id_cannot_approve(self):
        for change in ({'id': 999}, {'login': 'other[bot]'}, {'id': True}):
            with self.subTest(change=change):
                self.setUp();self.pr['user'].update(change)
                self.assertEqual(self.approve()['status'], 'manual-execution-approval-required')
                self.assertEqual(self.posts, [])

    def test_invalid_human_identity_is_rejected_before_approval(self):
        self.pr['user']['type'] = 'User'
        with self.assertRaisesRegex(ValueError, 'Invalid immutable human'): self.approve()
        self.assertEqual(self.posts, [])

    def test_all_reviewed_ci_workflows_can_start_but_no_other_workflow_can(self):
        for path in self.rules['workflows']:
            with self.subTest(path=path):
                self.setUp();self.run['path'] = self.workflow['path'] = path
                self.assertEqual(self.approve()['status'], 'checked')
                self.assertEqual(len(self.posts), 1)

    def test_forged_super_admin_team_identity_is_rejected(self):
        self.human()
        def api(endpoint):
            value = self.api(endpoint)
            if endpoint.endswith('/teams/super-admins'): value['id'] = 999
            return value
        with self.assertRaisesRegex(ValueError, 'pinned team'): self.approve(api=api)
        self.assertEqual(self.posts, [])

    def test_native_author_identity_swap_cannot_reuse_membership(self):
        self.human();self.pr['user']['id'] = 999
        with self.assertRaisesRegex(ValueError, 'identity differs'): self.approve()
        self.assertEqual(self.posts, [])

    def test_revoked_or_moved_pr_cannot_be_approved(self):
        for change in ('head', 'closed', 'base', 'base-repository'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'head': self.move = True
                elif change == 'closed': self.pr['state'] = 'closed'
                elif change == 'base': self.pr['base']['ref'] = 'other'
                else: self.pr['base']['repo'] = {'id': 9, 'full_name': 'attacker/repo'}
                with self.assertRaises(ValueError): self.approve()
                self.assertEqual(self.posts, [])
        self.setUp();self.human();self.revoke = True
        with self.assertRaisesRegex(ValueError, 'authority changed'): self.approve()
        self.assertEqual(self.posts, [])

    def test_forged_or_mismatched_run_origins_cannot_be_approved(self):
        for change in ({'head_sha': 'b' * 40}, {'event': 'workflow_dispatch'}, {'event': 'merge_group'},
                       {'head_branch': 'other'}, {'path': '.github/workflows/publication.yml'},
                       {'repository': {'id': 99, 'full_name': 'closure-labs/finite'}},
                       {'head_repository': {'id': 98, 'full_name': 'fork/finite'}}, {'run_attempt': True}):
            with self.subTest(change=change):
                self.setUp();self.run.update(change)
                with self.assertRaises(ValueError): self.approve()
                self.assertEqual(self.posts, [])

    def test_workflow_identity_and_approval_state_are_revalidated(self):
        self.workflow['path'] = '.github/workflows/release-set.yml'
        with self.assertRaisesRegex(ValueError, 'workflow identity'): self.approve()
        self.assertEqual(self.posts, [])
        self.setUp()
        def api(endpoint):
            value = self.api(endpoint)
            if endpoint.endswith('/actions/runs/40') and self.run_reads > 1: value['run_attempt'] = 2
            return value
        with self.assertRaisesRegex(ValueError, 'execution changed'): self.approve(api=api)
        self.assertEqual(self.posts, [])

    def test_missing_fork_association_is_resolved_through_native_commit_metadata(self):
        self.run['pull_requests'] = []
        self.assertEqual(self.approve()['status'], 'checked')
        self.assertEqual(len(self.posts), 1)

    def test_ambiguous_or_foreign_pr_associations_cannot_approve(self):
        self.run['pull_requests'] = [{'number': 7}, {'number': 7}]
        with self.assertRaisesRegex(ValueError, 'one current native PR'): self.approve()
        self.assertEqual(self.posts, [])

    def test_running_failed_and_environment_waiting_runs_are_not_approved(self):
        for status, conclusion in (('in_progress', None), ('waiting', None), ('queued', None),
                                   ('completed', 'failure'), ('completed', 'success')):
            with self.subTest(status=status, conclusion=conclusion):
                self.setUp();self.run.update(status=status, conclusion=conclusion)
                self.assertEqual(self.approve()['runs'][0]['status'], 'already-started-or-no-approval-required')
                self.assertEqual(self.posts, [])

    def test_uncertain_approval_response_reconciles_native_state_without_post_retry(self):
        def post(endpoint):
            self.posts.append(endpoint)
            self.run.update(status='in_progress', conclusion=None)
            raise RuntimeError('lost response')
        result = self.approve(post=post)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(result['runs'][0]['status'], 'native-state-reconciled-after-uncertain-response')
        self.setUp()
        def missing(endpoint):
            self.posts.append(endpoint)
            raise RuntimeError('lost response')
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'): self.approve(post=missing)
        self.assertEqual(len(self.posts), 1)

    def test_metadata_failures_do_not_approve(self):
        self.human()
        def failed(endpoint):
            if '/memberships/' in endpoint: raise RuntimeError('unavailable')
            return self.api(endpoint)
        with self.assertRaises(RuntimeError): self.approve(api=failed)
        self.assertEqual(self.posts, [])

    def test_discovery_handles_draft_ready_and_native_blocked_completion(self):
        for draft in (True, False):
            self.pr['draft'] = draft
            result = mod.discover(self.event, self.env, self.rules, self.api)
            self.assertEqual(result, {'include': [{'number': 7, 'head': HEAD, 'runs': [40]}]})
        result = mod.discover({'workflow_run': {'id': 40}}, {**self.env, 'GITHUB_EVENT_NAME': 'workflow_run'}, self.rules, self.api)
        self.assertEqual(result['include'][0]['runs'], [40])
        self.run.update(status='completed', conclusion='success')
        self.assertEqual(mod.discover({'workflow_run': {'id': 40}}, {**self.env, 'GITHUB_EVENT_NAME': 'workflow_run'}, self.rules, self.api), {'include': []})

    def test_discovery_does_not_approve_or_accept_incomplete_inventory(self):
        def incomplete(endpoint):
            value = self.api(endpoint)
            if '/actions/runs?' in endpoint: value['total_count'] = 2
            return value
        with self.assertRaisesRegex(ValueError, 'Incomplete'): mod.discover(self.event, self.env, self.rules, incomplete)
        self.assertEqual(self.posts, [])

    def test_newest_worker_reconciles_all_blocked_current_head_runs(self):
        other = {**deepcopy(self.run), 'id': 41, 'workflow_id': 51, 'path': '.github/workflows/codeql.yml'}
        def api(endpoint):
            if endpoint.endswith('/actions/runs/41'): return deepcopy(other)
            if endpoint.endswith('/actions/workflows/51'):
                return {'id': 51, 'path': other['path'], 'state': 'active'}
            if '/actions/runs?' in endpoint:
                return {'total_count': 2, 'workflow_runs': [deepcopy(self.run), deepcopy(other)]}
            return self.api(endpoint)
        # Only the newest event's run is passed in. The older pending worker
        # may have been replaced; both native blocked executions must progress.
        result = mod.approve(self.rules, 7, HEAD, [41], api=api, post=self.posts.append)
        self.assertEqual([row['runId'] for row in result['runs']], [40, 41])
        self.assertEqual(self.posts, ['repos/closure-labs/finite/actions/runs/40/approve',
                                      'repos/closure-labs/finite/actions/runs/41/approve'])

    def test_worker_requires_complete_blocked_inventory_before_any_mutation(self):
        def incomplete(endpoint):
            value = self.api(endpoint)
            if '/actions/runs?' in endpoint: value['total_count'] = 2
            return value
        with self.assertRaisesRegex(ValueError, 'Incomplete'): self.approve(api=incomplete)
        self.assertEqual(self.posts, [])

    def test_invalid_target_lists_never_issue_approval(self):
        for targets in ([], [True], [40, 40], [-1], [40] * 17):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                mod.approve(self.rules, 7, HEAD, targets, api=self.api, post=self.posts.append)
        self.assertEqual(self.posts, [])

    def test_cli_rejects_pr_checkout_and_wrong_app_identity_before_mutation(self):
        env = {'GITHUB_REPOSITORY': self.rules['repository'],
               'GITHUB_WORKFLOW_REF': 'closure-labs/finite/.github/workflows/ci-run-admission.yml@refs/heads/main',
               'FINITE_CI_ADMISSION_APP_SLUG': 'cl-decider', 'FINITE_REVIEW_APP_ID': '5384448',
               'FINITE_REVIEW_BOT_LOGIN': 'cl-decider[bot]'}
        for key, value in (('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/ci-run-admission.yml@refs/pull/7/merge'),
                           ('FINITE_CI_ADMISSION_APP_SLUG', 'other'), ('FINITE_REVIEW_APP_ID', '1'),
                           ('FINITE_REVIEW_BOT_LOGIN', 'other[bot]')):
            with self.subTest(key=key), patch.dict(mod.os.environ, {**env, key: value}, clear=True), \
                    patch.object(sys, 'argv', ['admission', '--pull-request', '7', '--head', HEAD, '--runs', '[40]']), \
                    patch.object(mod, 'approve') as approve, self.assertRaises(ValueError):
                mod.main()
            approve.assert_not_called()

    def test_workflow_uses_only_trusted_main_and_narrow_credentialed_worker(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci-run-admission.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertIn('converted_to_draft', triggers['pull_request_target']['types'])
        self.assertIn('ready_for_review', triggers['pull_request_target']['types'])
        discovery = workflow['jobs']['discover']
        self.assertFalse(any('setup-nix' in step.get('uses', '') for step in discovery['steps']))
        self.assertNotIn('secrets.', json.dumps(discovery))
        worker = workflow['jobs']['approve-execution']
        self.assertEqual(worker['if'], "needs.discover.outputs.has-targets == 'true'")
        self.assertFalse(worker['concurrency']['cancel-in-progress'])
        token = next(step['with'] for step in worker['steps'] if step.get('id') == 'ci-token')
        self.assertEqual({k: v for k, v in token.items() if k.startswith('permission-')},
                         {'permission-actions': 'write', 'permission-contents': 'read',
                          'permission-pull-requests': 'read', 'permission-members': 'read'})
        for job in workflow['jobs'].values():
            checkout = next(step['with'] for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
            self.assertEqual(checkout, {'ref': 'main', 'persist-credentials': False})
            self.assertNotIn('draft', str(job.get('if', '')))
        self.assertIn('python3 tests/ci/ci-run-admission.py', (ROOT / 'lib/bluebuild-checks.nix').read_text())


if __name__ == '__main__':
    unittest.main()
