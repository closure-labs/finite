#!/usr/bin/env python3
"""Early validation and App authority share exact changed-tree semantics."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import governed_tree as tree
spec = importlib.util.spec_from_file_location('preflight', ROOT / 'scripts/ci/validation-preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
HEAD, TARGET = 'a' * 40, 'b' * 40
REPO = 'closure-labs/finite'


class Preflight(unittest.TestCase):
    def setUp(self):
        self.pull = {'state': 'open', 'head': {'sha': HEAD},
                     'base': {'ref': 'main', 'repo': {'full_name': REPO}}, 'changed_files': 1}
        self.files = [{'filename': 'scripts/ci/example.py', 'status': 'modified'}]
        self.reviewed = [{'path': self.files[0]['filename'], 'type': 'blob', 'mode': '100644', 'sha': 'c' * 40}]
        self.target = deepcopy(self.reviewed)
        self.env = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REPOSITORY': REPO, 'GITHUB_SHA': TARGET}
        self.env['FINITE_REVIEW_BOT_LOGIN'] = 'cl-decider[bot]'
        self.event = {'number': 7, 'pull_request': {'head': {'sha': HEAD}}}
        self.reads, self.move = 0, False
        self.tree_reads = 0

    def api(self, endpoint):
        if endpoint.endswith('/pulls/7'):
            self.reads += 1
            value = deepcopy(self.pull)
            if self.move and self.reads > 1:
                value['head']['sha'] = 'd' * 40
            return value
        if '/files?' in endpoint:
            return self.files
        if '/git/ref/' in endpoint:
            return {'object': {'sha': TARGET}}
        if '/git/trees/' in endpoint:
            self.tree_reads += 1
            return {'truncated': False, 'tree': self.reviewed if HEAD in endpoint else self.target}
        raise AssertionError(endpoint)

    def check(self):
        return preflight.inspect(self.event, self.env, self.api)

    def test_equal_tree_passes_without_granting_authority(self):
        self.assertFalse(self.check()['authorizesPublication'])

    def test_unsupported_bot_governed_update_stops_before_tree_or_image_work(self):
        for author in ('dependabot[bot]', 'other[bot]'):
            self.pull['user'] = {'type': 'Bot', 'login': author}
            with self.subTest(author=author), self.assertRaisesRegex(ValueError, 'unsupported bot.*Adopt'):
                self.check()
        self.assertEqual(self.tree_reads, 0)
        self.env['GITHUB_EVENT_NAME'] = 'merge_group'
        self.event = {'merge_group': {'head_sha': TARGET, 'base_ref': 'refs/heads/main',
                      'head_ref': 'refs/heads/gh-readonly-queue/main/pr-7-abcdef0'}}
        with self.assertRaisesRegex(ValueError, 'unsupported bot'):
            self.check()

    def test_non_governed_bot_changes_and_configured_app_grant_no_authority(self):
        self.pull['user'] = {'type': 'Bot', 'login': 'cl-decider[bot]'}
        self.assertFalse(self.check()['authorizesPublication'])
        self.pull['user']['login'] = 'dependabot[bot]'
        self.files = [{'filename': 'docs/example.md', 'status': 'modified'}]
        self.assertFalse(self.check()['authorizesPublication'])

    def test_missing_public_bot_setting_defers_to_authoritative_app_check(self):
        self.pull['user'] = {'type': 'Bot', 'login': 'dependabot[bot]'}
        for value in ('', 'malformed', 'app[bot]\ninjected'):
            self.env['FINITE_REVIEW_BOT_LOGIN'] = value
            self.assertFalse(self.check()['authorizesPublication'])

    def test_renaming_governed_content_into_docs_still_rejects_unsupported_bot(self):
        self.pull['user'] = {'type': 'Bot', 'login': 'dependabot[bot]'}
        self.files = [{'filename': 'docs/moved.md', 'previous_filename': 'scripts/ci/example.py',
                       'status': 'renamed'}]
        with self.assertRaisesRegex(ValueError, 'unsupported bot'):
            self.check()

    def test_content_mode_addition_deletion_and_rename_mismatches(self):
        for kind in ('content', 'mode', 'added', 'deleted', 'renamed'):
            self.setUp()
            if kind == 'content': self.target[0]['sha'] = 'd' * 40
            if kind == 'mode': self.target[0]['mode'] = '100755'
            if kind == 'added': self.reviewed = []
            if kind == 'deleted': self.target = []
            if kind == 'renamed':
                self.files[0].update(filename='docs/moved.md', previous_filename='scripts/ci/example.py')
                self.reviewed = []
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'scripts/ci/example.py.*Rebase'):
                self.check()

    def test_moved_heads_rejected_before_and_during_read(self):
        self.pull['head']['sha'] = 'd' * 40
        with self.assertRaisesRegex(ValueError, 'head moved'): self.check()
        self.pull['head']['sha'] = HEAD
        self.move, self.reads = True, 0
        with self.assertRaisesRegex(ValueError, 'changed during'): self.check()

    def test_queue_identity_and_tree_are_checked(self):
        self.env['GITHUB_EVENT_NAME'] = 'merge_group'
        self.event = {'merge_group': {'head_sha': TARGET, 'base_ref': 'refs/heads/main',
                      'head_ref': 'refs/heads/gh-readonly-queue/main/pr-7-abcdef0'}}
        self.assertEqual(self.check()['head'], HEAD)
        self.event['merge_group']['head_sha'] = HEAD
        with self.assertRaisesRegex(ValueError, 'exact single-PR'): self.check()

    def test_truncated_duplicate_malformed_trees_rejected(self):
        for response in ({'tree': [], 'truncated': True},
                         {'tree': self.reviewed * 2, 'truncated': False},
                         {'tree': [dict(self.reviewed[0], sha='not-a-sha')], 'truncated': False}):
            with self.assertRaises(ValueError):
                tree.tree(lambda _: response, REPO, HEAD)

    def test_diagnostics_list_all_paths(self):
        self.files.append({'filename': '.github/workflows/example.yml', 'status': 'added'})
        self.pull['changed_files'] = 2
        self.reviewed.append({'path': self.files[1]['filename'], 'sha': 'e' * 40, 'type': 'blob', 'mode': '100644'})
        self.target = []
        with self.assertRaisesRegex(ValueError, '.github/workflows/example.yml, scripts/ci/example.py'):
            self.check()


if __name__ == '__main__':
    unittest.main()
