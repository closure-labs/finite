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
                         'user': {'login': 'maintainer', 'type': 'User'}}]
        self.roles = {'maintainer': 'maintain'}
        self.files = [{'filename': mod.proposal_path(PROPOSAL), 'status': 'added'}]
        self.blobs = {}
        self.compare = 'ahead'
        self.fail = None
        self.calls = []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        if self.fail and self.fail in endpoint:
            raise mod.AuthorityError('API unavailable')
        if endpoint == f'repos/{REPO}/pulls/7':
            return copy.deepcopy(self.pr)
        if '/pulls/7/reviews?' in endpoint:
            return copy.deepcopy(self.reviews)
        if '/pulls/7/files?' in endpoint:
            return copy.deepcopy(self.files)
        if '/collaborators/' in endpoint:
            login = endpoint.split('/collaborators/')[1].split('/')[0]
            return {'permission': 'write', 'role_name': self.roles.get(login, 'read')}
        if '/contents/' in endpoint:
            revision = endpoint.split('?ref=')[1]
            data = json.dumps(self.blobs.get(revision, self.proposal)).encode()
            return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
                    'encoding': 'base64', 'size': len(data),
                    'content': base64.b64encode(data).decode()}
        if endpoint.endswith('/git/ref/heads/main'):
            return {'object': {'sha': MAIN}}
        if '/compare/' in endpoint:
            return {'status': self.compare}
        raise AssertionError('Unexpected API call: ' + endpoint)


def verify(api, **kwargs):
    return mod.verify_proposal(PROPOSAL, 7, REPO, BOT, github=api, **kwargs)


class Authority(unittest.TestCase):
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
                                'user': {'type': 'User', 'login': user}})
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
