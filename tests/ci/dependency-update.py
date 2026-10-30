#!/usr/bin/env python3
"""Dependency identity is not authority; only authenticated immutable pin changes qualify."""
import base64
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import dependency_update as dependency

BASE, HEAD, MERGE_BASE = 'a' * 40, 'b' * 40, 'c' * 40
OLD, NEW, TAG = 'd' * 40, 'e' * 40, 'f' * 40
PATH = '.github/workflows/example.yml'
BEFORE = 'name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@' + OLD + ' # v7.0.0\n      - run: echo safe\n'
AFTER = BEFORE.replace(OLD, NEW).replace('v7.0.0', 'v7.0.1')


class GitHub:
    def __init__(self, before=BEFORE, after=AFTER, path=PATH):
        repo = {'id': dependency.REPOSITORY_ID, 'full_name': dependency.REPOSITORY}
        self.pull = {'number': 7, 'state': 'open', 'draft': True, 'user': deepcopy(dependency.BOT),
                     'base': {'sha': BASE, 'ref': 'main', 'repo': deepcopy(repo)},
                     'head': {'sha': HEAD, 'ref': 'dependabot/actions', 'repo': deepcopy(repo)}, 'changed_files': 1}
        self.files = [{'filename': path, 'status': 'modified'}]
        self.blobs, self.trees = {}, {}
        for commit, text in ((MERGE_BASE, before), (HEAD, after)):
            raw = text.encode()
            sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            self.blobs[sha] = {'sha': sha, 'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
            self.trees[commit] = {'truncated': False, 'tree': [{'path': path, 'type': 'blob', 'mode': '100644', 'sha': sha}]}
        self.ref = {'ref': 'refs/tags/v7.0.1', 'object': {'type': 'commit', 'sha': NEW}}
        self.tag = {'sha': TAG, 'object': {'type': 'commit', 'sha': NEW}}
        self.calls = []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        prefix = 'repos/' + dependency.REPOSITORY
        if endpoint == prefix + '/pulls/7': return deepcopy(self.pull)
        if endpoint.startswith(prefix + '/pulls/7/files?'): return deepcopy(self.files)
        if endpoint == prefix + f'/compare/{BASE}...{HEAD}':
            return {'base_commit': {'sha': BASE}, 'merge_base_commit': {'sha': MERGE_BASE}}
        if '/git/trees/' in endpoint:
            return deepcopy(self.trees[endpoint.split('/git/trees/')[1].split('?')[0]])
        if '/git/blobs/' in endpoint: return deepcopy(self.blobs[endpoint.rsplit('/', 1)[1]])
        if endpoint == 'repos/actions/checkout/git/ref/tags/v7.0.1': return deepcopy(self.ref)
        if endpoint == 'repos/actions/checkout/git/tags/' + TAG: return deepcopy(self.tag)
        raise AssertionError(endpoint)

    def inspect(self):
        return dependency.inspect(self, dependency.REPOSITORY, self.pull)

    def classify(self):
        return dependency.classify(self, self.inspect())


class Boundaries(unittest.TestCase):
    def test_exact_official_pin_change_and_annotated_tag(self):
        api = GitHub()
        self.assertEqual(api.classify(), [{'path': PATH, 'action': 'actions/checkout', 'old': OLD, 'new': NEW, 'version': 'v7.0.1'}])
        api.ref['object'] = {'type': 'tag', 'sha': TAG}
        self.assertEqual(len(api.classify()), 1)
        self.assertFalse(any('/commits/' in call for call in api.calls))

    def test_composite_and_existing_reusable_workflow_nodes(self):
        examples = [('.github/actions/test/action.yml', 'name: Test\nruns:\n  using: composite\n  steps:\n    - uses: actions/checkout@'),
                    (PATH, 'name: Test\non: push\njobs:\n  test:\n    uses: actions/checkout@')]
        for path, prefix in examples:
            before = prefix + OLD + ' # v7.0.0\n'
            with self.subTest(path=path):
                self.assertEqual(len(GitHub(before, before.replace(OLD, NEW).replace('v7.0.0', 'v7.0.1'), path).classify()), 1)

    def test_identity_is_numeric_and_same_repository(self):
        mutations = [lambda p: p['user'].update(id=1), lambda p: p['user'].update(id=True),
                     lambda p: p['user'].update(type='User'), lambda p: p['user'].update(login='other[bot]'),
                     lambda p: p['head']['repo'].update(id=1), lambda p: p['base']['repo'].update(full_name='fork/finite'),
                     lambda p: p['base'].update(ref='other'), lambda p: p['head'].update(sha='main'),
                     lambda p: p.update(state='closed')]
        for mutate in mutations:
            api = GitHub(); mutate(api.pull)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): api.inspect()

    def test_shape_remains_stdlib_and_grants_no_authority(self):
        api = GitHub()
        with mock.patch.dict(sys.modules, {'yaml': None}):
            context = api.inspect()
        self.assertNotIn('approved', context)
        self.assertEqual(context['mergeBase'], MERGE_BASE)

    def test_incomplete_inventories_hidden_files_modes_and_truncated_trees(self):
        for kind in ('count', 'duplicate', 'rename', 'new', 'mode', 'symlink', 'hidden', 'truncated', 'otherfile'):
            api = GitHub()
            if kind == 'count': api.pull['changed_files'] = 2
            if kind == 'duplicate': api.files *= 2; api.pull['changed_files'] = 2
            if kind == 'rename': api.files[0].update(previous_filename='other.yml', status='renamed')
            if kind == 'new': api.trees[MERGE_BASE]['tree'] = []
            if kind == 'mode': api.trees[HEAD]['tree'][0]['mode'] = '100755'
            if kind == 'symlink': api.trees[HEAD]['tree'][0]['mode'] = '120000'
            if kind == 'hidden': api.trees[HEAD]['tree'].append({'path': 'secret', 'mode': '100644', 'type': 'blob', 'sha': TAG})
            if kind == 'truncated': api.trees[HEAD]['truncated'] = True
            if kind == 'otherfile': api.files[0]['filename'] = 'flake.lock'
            with self.subTest(kind=kind), self.assertRaises(ValueError): api.inspect()

    def test_blob_identity_size_and_encoding_are_authenticated(self):
        for update in ({'sha': TAG}, {'size': 1}, {'content': '!!!!'}, {'encoding': 'none'}):
            api = GitHub(); next(iter(api.blobs.values())).update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): api.inspect()

    def test_every_other_workflow_change_is_rejected(self):
        mutations = [lambda s: s.replace('on: push', 'on: pull_request_target'),
                     lambda s: s.replace('echo safe', 'echo malicious'),
                     lambda s: s.replace('runs-on: ubuntu-24.04', 'runs-on: self-hosted'),
                     lambda s: s + 'permissions: write-all\n', lambda s: s + 'env:\n  TOKEN: value\n',
                     lambda s: s.replace('actions/checkout', 'attacker/checkout'),
                     lambda s: s.replace('actions/checkout@', 'actions/checkout/other@'),
                     lambda s: s.replace('      - run:', '        with:\n          token: value\n      - run:'),
                     lambda s: s.replace('steps:', 'steps:\n      - uses: actions/checkout@' + OLD + ' # v7.0.0')]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, AssertionError)):
                GitHub(after=mutate(AFTER)).classify()

    def test_yaml_ambiguity_and_run_scalar_lookalikes_are_rejected(self):
        prefixes = ['extra: &alias value\n', 'extra: !!str value\n', 'name: Duplicate\n',
                    'extra: {same: a, same: b}\n', 'extra: {<<: {a: b}}\n',
                    'extra: {1: a, 01: b}\n', 'extra: {true: a, True: b}\n']
        for prefix in prefixes:
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                GitHub(prefix + BEFORE, prefix + AFTER).classify()
        for suffix in ('---\nname: Other\n', '\n---\n'):
            with self.assertRaises(ValueError): GitHub(BEFORE + suffix, AFTER + suffix).classify()
        before = 'name: Test\njobs:\n  test:\n    steps:\n      - run: |\n          uses: actions/checkout@' + OLD + ' # v7.0.0\n'
        with self.assertRaises(ValueError):
            GitHub(before, before.replace(OLD, NEW).replace('v7.0.0', 'v7.0.1')).classify()

    def test_unsupported_comments_and_comment_only_changes_do_not_qualify(self):
        for value in ('main', 'v7.0.1 extra', 'https://attacker', 'v7.0.1\n# extra'):
            with self.subTest(value=value), self.assertRaises(ValueError): GitHub(after=AFTER.replace('v7.0.1', value)).classify()
        with self.assertRaises(ValueError): GitHub(after=BEFORE.replace('v7.0.0', 'v7.0.1')).classify()

    def test_missing_moved_fork_only_cyclic_and_wrong_type_tags_fail(self):
        for change in ('name', 'sha', 'cycle', 'type', 'wrongtag'):
            api = GitHub()
            if change == 'name': api.ref['ref'] = 'refs/tags/v7'
            if change == 'sha': api.ref['object']['sha'] = OLD
            if change == 'type': api.ref['object']['type'] = 'blob'
            if change in ('cycle', 'wrongtag'):
                api.ref['object'] = {'type': 'tag', 'sha': TAG}
                if change == 'cycle': api.tag['object'] = deepcopy(api.ref['object'])
                else: api.tag['sha'] = OLD
            with self.subTest(change=change), self.assertRaises(ValueError): api.classify()
        api = GitHub()
        def unavailable(endpoint):
            if '/git/ref/' in endpoint: raise RuntimeError('404 / fork-only commit')
            return api(endpoint)
        with self.assertRaises(RuntimeError): dependency.classify(unavailable, api.inspect())

    def test_final_head_base_and_author_are_revalidated(self):
        for side in ('head', 'base', 'user'):
            api = GitHub(); context = api.inspect()
            if side == 'user': api.pull['user']['id'] = 1
            else: api.pull[side]['sha'] = TAG
            with self.subTest(side=side), self.assertRaises(ValueError):
                dependency.revalidate(api, dependency.REPOSITORY, context)


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


authority_fixture = load('dependency_authority_fixture', 'tests/ci/decision-authority.py')
check = load('dependency_check', 'scripts/ci/decision-check.py')
admission = load('dependency_admission', 'scripts/ci/ci-run-admission.py')
preflight = load('dependency_preflight', 'scripts/ci/validation-preflight.py')


class Integration(unittest.TestCase):
    def setUp(self):
        self.source = GitHub()
        self.humans = authority_fixture.GitHub()
        self.humans.reviews[0]['commit_id'] = HEAD
        self.review_reads = 0
        self.revoke_at = None
        self.posts = []
        self.run = {'id': 40, 'run_attempt': 1, 'workflow_id': 50, 'path': '.github/workflows/build.yml',
                    'repository': self.source.pull['base']['repo'], 'head_repository': self.source.pull['head']['repo'],
                    'head_sha': HEAD, 'head_branch': self.source.pull['head']['ref'], 'event': 'pull_request',
                    'status': 'completed', 'conclusion': 'action_required', 'pull_requests': [{'number': 7}]}
        self.collector = {**deepcopy(self.run), 'id': 41, 'workflow_id': 51, 'event': 'pull_request_review',
                          'path': '.github/workflows/decision-events.yml', 'conclusion': 'success'}
        self.recovery = {**deepcopy(self.run), 'id': 42, 'workflow_id': 52, 'event': 'schedule',
                         'head_branch': 'main', 'head_sha': BASE,
                         'path': '.github/workflows/decision-authority.yml', 'conclusion': 'success'}

    def api(self, endpoint):
        if '/reviews?' in endpoint:
            self.review_reads += 1
            if self.revoke_at and self.review_reads >= self.revoke_at:
                self.humans.members = []
            return deepcopy(self.humans.reviews)
        if '/teams/' in endpoint or '/collaborators/' in endpoint:
            return self.humans(endpoint)
        if endpoint.endswith('/actions/runs/40'): return deepcopy(self.run)
        if endpoint.endswith('/actions/runs/41'): return deepcopy(self.collector)
        if endpoint.endswith('/actions/runs/42'): return deepcopy(self.recovery)
        if endpoint.endswith('/actions/workflows/50'):
            return {'id': 50, 'path': self.run['path'], 'state': 'active'}
        if endpoint.endswith('/actions/workflows/52'):
            return {'id': 52, 'path': self.recovery['path'], 'state': 'active'}
        if '/pulls?state=open&base=main&' in endpoint:
            return [{'number': 7, 'user': deepcopy(dependency.BOT)}]
        if '/actions/runs?' in endpoint:
            return {'total_count': 1, 'workflow_runs': [deepcopy(self.run)]}
        return self.source(endpoint)

    def check(self):
        return check.check_pr(dependency.REPOSITORY, 7, 'cl-decider[bot]', github=self.api)

    def admit(self):
        return admission.approve(admission.policy(), 7, HEAD, [40], api=self.api, post=self.posts.append)

    def test_automatic_execution_without_review_preserves_human_merge_requirement(self):
        self.humans.reviews = []
        for draft in (True, False):
            with self.subTest(draft=draft):
                self.source.pull['draft'] = draft
                result = self.admit()
                self.assertEqual(result['runs'][0]['status'], 'execution-approved')
                self.assertFalse(result['grantsMergeApproval'])
                self.assertFalse(result['authorizesPublication'])
        self.assertEqual(self.review_reads, 0)
        self.assertEqual(self.posts, ['repos/closure-labs/finite/actions/runs/40/approve'] * 2)
        with self.assertRaises(check.authority.HumanDecisionRequired): self.check()
        self.humans.reviews = deepcopy(authority_fixture.GitHub().reviews)
        self.humans.reviews[0]['commit_id'] = HEAD
        self.assertEqual(self.check()['status'], 'authorized')

    def test_stale_dismissed_withdrawn_and_ineligible_reviews_still_block_merge(self):
        for case in ('head', 'dismissed', 'changes', 'role', 'membership'):
            self.setUp()
            if case == 'head': self.humans.reviews[0]['commit_id'] = BASE
            if case == 'dismissed': self.humans.reviews[0]['state'] = 'DISMISSED'
            if case == 'changes': self.humans.reviews[0]['state'] = 'CHANGES_REQUESTED'
            if case == 'role': self.humans.roles['maintainer'] = 'write'
            if case == 'membership': self.humans.members = []
            with self.subTest(case=case):
                self.assertEqual(self.admit()['runs'][0]['status'], 'execution-approved')
                self.assertEqual(self.review_reads, 0)
                with self.assertRaises(check.authority.HumanDecisionRequired): self.check()

    def test_live_dependency_identity_rechecked_immediately_before_admission(self):
        for mutation in ('head', 'base', 'author', 'fork', 'branch', 'closed'):
            self.setUp()
            validations = 0
            original = admission.dependency.revalidate
            def revalidate(api, repository, context):
                nonlocal validations
                validations += 1
                if validations == 3:
                    if mutation == 'author': self.source.pull['user']['id'] = 1
                    elif mutation == 'fork': self.source.pull['head']['repo']['id'] = 9
                    elif mutation == 'branch': self.source.pull['head']['ref'] = 'moved'
                    elif mutation == 'closed': self.source.pull['state'] = 'closed'
                    else: self.source.pull[mutation]['sha'] = TAG
                return original(api, repository, context)
            with self.subTest(mutation=mutation), mock.patch.object(admission.dependency, 'revalidate', revalidate):
                with self.assertRaises(ValueError): self.admit()
            self.assertEqual(self.posts, [])

    def test_forged_official_identity_and_fork_never_admit(self):
        for mutation in ('login', 'id', 'bool-id', 'fork'):
            self.setUp()
            if mutation == 'login': self.source.pull['user']['login'] = 'imposter[bot]'
            elif mutation == 'id': self.source.pull['user']['id'] = 1
            elif mutation == 'bool-id': self.source.pull['user']['id'] = True
            else:
                self.source.pull['head']['repo'] = {'id': 9, 'full_name': 'fork/finite'}
                self.run['head_repository'] = deepcopy(self.source.pull['head']['repo'])
            with self.subTest(mutation=mutation):
                if mutation == 'fork':
                    with self.assertRaises(ValueError): self.admit()
                else:
                    self.assertEqual(self.admit()['status'], 'manual-execution-approval-required')
                self.assertEqual(self.posts, [])

    def test_actor_and_triggering_actor_never_substitute_for_live_pr_author(self):
        identities = [deepcopy(dependency.BOT), {'login': 'outsider', 'id': 9, 'type': 'User'}]
        for actor in identities:
            for triggering_actor in identities:
                for official in (True, False):
                    self.setUp()
                    self.humans.reviews = []
                    self.run.update(actor=actor, triggering_actor=triggering_actor)
                    if not official:
                        self.source.pull['user'] = {'login': 'imposter[bot]', 'id': 9, 'type': 'Bot'}
                    # Forged event identity is a wake-up, never author authority.
                    event = {'number': 7, 'sender': deepcopy(dependency.BOT),
                             'pull_request': {'head': {'sha': HEAD}, 'user': deepcopy(dependency.BOT)}}
                    env = {'GITHUB_REPOSITORY': dependency.REPOSITORY,
                           'GITHUB_EVENT_NAME': 'pull_request_target',
                           'GITHUB_ACTOR': actor['login'], 'GITHUB_ACTOR_ID': str(actor['id']),
                           'GITHUB_TRIGGERING_ACTOR': triggering_actor['login']}
                    with self.subTest(actor=actor, triggering_actor=triggering_actor, official=official), \
                            mock.patch.dict(admission.os.environ, env):
                        self.assertEqual(admission.discover(event, env, admission.policy(), self.api),
                                         {'include': [{'number': 7, 'head': HEAD, 'runs': [40]}]})
                        result = self.admit()
                        self.assertEqual(len(self.posts), int(official))
                        self.assertEqual(result['status'], 'checked' if official else 'manual-execution-approval-required')
                        self.assertEqual(self.review_reads, 0)

    def test_non_pin_change_does_not_reach_review_or_execution(self):
        self.source = GitHub(after=AFTER.replace('echo safe', 'echo other'))
        with self.assertRaisesRegex(ValueError, 'outside immutable'): self.check()
        with self.assertRaisesRegex(ValueError, 'outside immutable'): self.admit()
        self.assertEqual(self.review_reads, 0)
        self.assertEqual(self.posts, [])

    def test_preflight_only_checks_shape_and_exact_tree_without_authority(self):
        env = {'GITHUB_REPOSITORY': dependency.REPOSITORY, 'GITHUB_SHA': HEAD,
               'GITHUB_EVENT_NAME': 'pull_request', 'FINITE_REVIEW_BOT_LOGIN': 'cl-decider[bot]'}
        event = {'number': 7, 'pull_request': {'head': {'sha': HEAD}}}
        with mock.patch.object(dependency, 'classify', side_effect=AssertionError('No parser in preflight')):
            self.assertFalse(preflight.inspect(event, env, self.api)['authorizesPublication'])
        self.assertEqual(self.review_reads, 0)

    def test_successful_review_collector_reconciles_previously_blocked_runs(self):
        env = {'GITHUB_REPOSITORY': dependency.REPOSITORY, 'GITHUB_EVENT_NAME': 'workflow_run'}
        event = {'workflow_run': {'id': 41}}
        result = admission.discover(event, env, admission.policy(), self.api)
        self.assertEqual(result, {'include': [{'number': 7, 'head': HEAD, 'runs': [40]}]})
        self.assertEqual(self.posts, [])
        self.collector['head_sha'] = BASE
        with self.assertRaises(ValueError): admission.discover(event, env, admission.policy(), self.api)

    def test_dependency_exception_never_changes_proposal_submitters(self):
        self.assertFalse(check.authority.submitter(self.api, dependency.REPOSITORY, dependency.BOT, 'cl-decider[bot]'))
        self.humans.pr['user'] = deepcopy(dependency.BOT)
        with self.assertRaisesRegex(authority_fixture.mod.AuthorityError, 'Proposal must be authored'):
            authority_fixture.mod.verify_proposal(authority_fixture.PROPOSAL, 7, dependency.REPOSITORY,
                                                 'cl-decider[bot]', github=self.humans)

    def test_authority_recovery_is_a_native_wakeup_not_authorization(self):
        env = {'GITHUB_REPOSITORY': dependency.REPOSITORY, 'GITHUB_EVENT_NAME': 'workflow_run'}
        event = {'workflow_run': {'id': 42}}
        self.humans.reviews = []
        for conclusion in ('success', 'failure'):
            self.recovery['conclusion'] = conclusion
            result = admission.discover(event, env, admission.policy(), self.api)
            self.assertEqual(result, {'include': [{'number': 7, 'head': HEAD, 'runs': [40]}]})
        self.assertEqual(self.review_reads, 0)
        self.assertEqual(self.admit()['runs'][0]['status'], 'execution-approved')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.review_reads, 0)
        mutations = [{'head_branch': 'attacker'}, {'event': 'pull_request'}, {'conclusion': 'cancelled'},
                     {'conclusion': 'timed_out'},
                     {'run_attempt': True}, {'repository': {'id': 9, 'full_name': dependency.REPOSITORY}},
                     {'head_repository': {'id': 9, 'full_name': dependency.REPOSITORY}}]
        for change in mutations:
            with self.subTest(change=change):
                previous = deepcopy(self.recovery)
                self.recovery.update(change)
                with self.assertRaises(ValueError): admission.discover(event, env, admission.policy(), self.api)
                self.recovery = previous

    def test_parser_tool_precedes_credentials_and_permissions_do_not_expand(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci-run-admission.yml').read_text())
        steps = workflow['jobs']['approve-execution']['steps']
        prepared = next(i for i, value in enumerate(steps) if value.get('id') == 'dependency-tools')
        first_secret = next(i for i, value in enumerate(steps) if 'secrets.' in str(value))
        self.assertLess(prepared, first_secret)
        self.assertIn('image-tools --no-link --print-out-paths', steps[prepared]['run'])
        command = next(value['run'] for value in steps if '--pull-request' in value.get('run', ''))
        self.assertIn('"$DEPENDENCY_TOOLS/bin/python3"', command)
        token = next(value['with'] for value in steps if value.get('id') == 'ci-token')
        self.assertEqual({k: v for k, v in token.items() if k.startswith('permission-')},
                         {'permission-actions': 'write', 'permission-contents': 'read',
                          'permission-pull-requests': 'read', 'permission-members': 'read'})
        self.assertIs(admission.policy()['dependabot']['requiresCurrentHeadHumanApproval'], False)


if __name__ == '__main__':
    unittest.main()
