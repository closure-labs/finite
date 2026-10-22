#!/usr/bin/env python3
"""Release-set publication contracts using an injected CAS GitHub model."""
import copy
import json
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import release_set
from release_set import execute, payload_digest, prepare


class Remote:
    def __init__(self):
        self.reservations = {}
        self.journal = None
        self.version = 0
        self.tags = {}
        self.releases = {}
        self.events = []
        self.fail_upload = False
        self.fail_publish = None

    def reserve_version(self, version, identity):
        if version in self.reservations and self.reservations[version] != identity:
            raise ValueError('Release version already reserved by another payload')
        self.reservations[version] = identity

    def read_journal(self, identity):
        return copy.deepcopy(self.journal), self.version or None

    def write_journal(self, identity, journal, version):
        if version != (self.version or None):
            raise ValueError('CAS conflict')
        self.journal = copy.deepcopy(journal)
        self.version += 1
        return self.version

    def tag_target(self, tag):
        return self.tags.get(tag)

    def create_tag(self, tag, revision):
        self.tags[tag] = revision

    def get_release(self, tag):
        return copy.deepcopy(self.releases.get(tag))

    def create_draft(self, tag, revision, identity, *, prerelease=False):
        self.releases[tag] = {'id': tag, 'payloadDigest': identity, 'draft': True,
                              'prerelease': prerelease, 'assets': {}}
        self.events.append(('draft', tag))

    def assets(self, release_id):
        return copy.deepcopy(self.releases[release_id]['assets'])

    def upload(self, release_id, path):
        if self.fail_upload:
            self.fail_upload = False
            raise RuntimeError('network upload failed')
        self.releases[release_id]['assets'][path.name] = self.record(path.name, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
        self.events.append(('upload', release_id))

    def record(self, name, digest=None, size=0, state='uploaded'):
        return {'id': name, 'name': name, 'digest': digest, 'size': size, 'state': state}

    def get_asset(self, asset_id):
        return next(copy.deepcopy(assets['assets'][asset_id]) for assets in self.releases.values()
                    if asset_id in assets['assets'])

    def delete_asset(self, asset_id):
        for release in self.releases.values():
            if asset_id in release['assets']:
                del release['assets'][asset_id]
                self.events.append(('delete', asset_id))
                return

    def publish(self, release_id, *, prerelease=False):
        if self.fail_publish == release_id:
            self.fail_publish = None
            raise RuntimeError('publish failed')
        assert len(self.releases) == 2
        assert all(v['assets'] for v in self.releases.values())
        assert self.releases[release_id]['prerelease'] == prerelease
        self.releases[release_id]['draft'] = False
        self.events.append(('publish', release_id))


class ReleaseSetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.roots = {}
        payload = {'version': '1.2.3', 'sourceRevision': 'a' * 40, 'channels': {}}
        evidence = {}
        for channel in ('finite', 'finite-dev'):
            root = Path(self.tmp.name) / channel
            root.mkdir()
            self.roots[channel] = root
            (root / 'image.iso').write_bytes(channel.encode())
            digest = hashlib.sha256(channel.encode()).hexdigest()
            payload['channels'][channel] = {'tag': channel + '-1.2.3', 'imageDigest': 'sha256:' + digest,
                                          'isoSha256': digest, 'assets': {'image.iso': digest}}
            evidence[channel] = {'status': 'qualified', 'sourceRevision': 'a' * 40,
                                 'imageDigest': 'sha256:' + digest, 'isoSha256': digest}
        self.doc = prepare(payload, evidence)
        self.remote = Remote()
        self.derived = {}
        for channel in ('finite', 'finite-dev'):
            self.derived[channel] = {}
            for name in ('SHA256SUMS', 'SHA256SUMS.bundle.json'):
                content = name.encode()
                (self.roots[channel] / name).write_bytes(content)
                self.derived[channel][name] = hashlib.sha256(content).hexdigest()

    def run_release(self, owner='run-1', phase='publish'):
        return execute(self.doc, self.remote, self.roots, payload_digest(self.doc), owner, now=lambda: 100,
                       derived_assets=self.derived, evidence_validator=lambda *args: None, phase=phase)

    def test_github_gets_have_no_body_and_mutations_keep_structured_json(self):
        result = types.SimpleNamespace(returncode=0, stdout='HTTP/2.0 200 OK\n\n{}', stderr='')
        with patch.object(release_set.subprocess, 'run', return_value=result) as run:
            client = release_set.GitHubClient('closure-labs/finite', token='fixture-publish')
            client.api('git/ref/heads/main')
            self.assertNotIn('--input', run.call_args.args[0])
            self.assertIsNone(run.call_args.kwargs.get('input'))
            result.stdout = '{}'
            client.api('git/refs', 'POST', {'ref': 'refs/tags/finite-1.2.3', 'sha': 'a' * 40})
            self.assertIn('--input', run.call_args.args[0])
            self.assertEqual(json.loads(run.call_args.kwargs['input'])['ref'], 'refs/tags/finite-1.2.3')
            self.assertEqual(run.call_args.kwargs['env']['GH_TOKEN'], 'fixture-publish')

    def test_created_draft_and_published_state_do_not_depend_on_cached_inventory(self):
        tag, identity = 'finite-1.2.3-dev', 'b' * 64
        current, cached, writes = {}, {}, []

        def request(command, **kwargs):
            endpoint = next(arg for arg in command if arg.startswith('repos/'))
            method = command[command.index('--method') + 1]
            if method == 'POST':
                data = json.loads(kwargs['input'])
                current.update(id=7, tag_name=data['tag_name'], draft=data['draft'],
                               prerelease=data['prerelease'], body=data['body'])
                writes.append(method)
                return types.SimpleNamespace(returncode=0, stdout=json.dumps(current), stderr='')
            if method == 'PATCH':
                current.update(json.loads(kwargs['input']))
                writes.append(method)
                return types.SimpleNamespace(returncode=0, stdout=json.dumps(current), stderr='')
            # A collection can lag creation even when the new resource is readable
            # by ID. Individual GETs can also retain the pre-publication draft.
            if '/releases?' in endpoint:
                body = []
            elif endpoint.endswith('/releases/7'):
                if 'Cache-Control: no-cache' in command:
                    cached[endpoint] = copy.deepcopy(current)
                body = cached.setdefault(endpoint, copy.deepcopy(current))
            else:
                self.fail('Unexpected endpoint: ' + endpoint)
            return types.SimpleNamespace(returncode=0, stderr='', stdout=
                'HTTP/2.0 200 OK\nCache-Control: private, max-age=60\n\n' + json.dumps(body))

        client = release_set.GitHubClient('closure-labs/finite')
        with patch.object(release_set.subprocess, 'run', side_effect=request):
            self.assertIsNone(client.get_release(tag))
            client.create_draft(tag, 'a' * 40, identity, prerelease=True)
            self.assertEqual(client.get_release(tag), {
                'id': 7, 'draft': True, 'prerelease': True, 'payloadDigest': identity})
            client.publish(7, prerelease=True)
            self.assertFalse(client.get_release(tag)['draft'])
        self.assertEqual(writes, ['POST', 'PATCH'])

    def test_missing_release_lookup_is_not_reported_as_foreign_ownership(self):
        self.remote.get_release = lambda tag: None
        with self.assertRaisesRegex(ValueError, 'Release lookup returned no result'):
            self.run_release(phase='stage-publication')
        self.assertFalse(any(event[0] in ('upload', 'delete', 'publish') for event in self.remote.events))

    def test_known_release_id_cannot_be_reassigned_to_another_tag(self):
        client = release_set.GitHubClient('closure-labs/finite')
        record = {'id': 7, 'tag_name': 'finite-1.2.3-dev', 'draft': True,
                  'prerelease': True, 'body': '<!-- finite-release-set:' + 'b' * 64 + ' -->'}
        with patch.object(client, 'api', return_value=record):
            client.create_draft('finite-1.2.3-dev', 'a' * 40, 'b' * 64, prerelease=True)
        for field, value in [('id', 8), ('tag_name', 'foreign-release')]:
            with self.subTest(field=field), patch.object(client, 'api', return_value={**record, field: value}):
                with self.assertRaisesRegex(ValueError, 'Release identity changed'):
                    client.get_release('finite-1.2.3-dev')

    def test_new_journal_uses_canonical_repository_endpoint(self):
        client = release_set.GitHubClient('closure-labs/finite', 'automation/decision-journal')
        responses = [
            types.SimpleNamespace(returncode=1, stdout='HTTP/2.0 404 Not Found\n\n{}', stderr='gh: Not Found (HTTP 404)'),
            types.SimpleNamespace(returncode=0, stdout='HTTP/2.0 200 OK\n\n{"default_branch":"main"}', stderr=''),
            types.SimpleNamespace(returncode=0, stdout='HTTP/2.0 200 OK\n\n'+json.dumps({'object': {'sha': 'a' * 40}}), stderr=''),
            types.SimpleNamespace(returncode=0, stdout='{}', stderr=''),
        ]
        with patch.object(release_set.subprocess, 'run', side_effect=responses) as run:
            client.ensure_journal_branch()
        calls = run.call_args_list
        self.assertEqual([next(arg for arg in call.args[0] if arg.startswith('repos/')) for call in calls], [
            'repos/closure-labs/finite/git/ref/heads/automation/decision-journal',
            'repos/closure-labs/finite',
            'repos/closure-labs/finite/git/ref/heads/main',
            'repos/closure-labs/finite/git/refs',
        ])
        self.assertEqual(json.loads(calls[-1].kwargs['input']), {
            'ref': 'refs/heads/automation/decision-journal', 'sha': 'a' * 40})

    def test_unsigned_publication_and_invalid_signed_evidence_fail_before_any_write(self):
        with self.assertRaisesRegex(ValueError, 'verified signed evidence'):
            execute(self.doc, self.remote, self.roots, payload_digest(self.doc), 'run-1')
        def invalid(*args):
            raise ValueError('signature does not verify')
        with self.assertRaisesRegex(ValueError, 'signature'):
            execute(self.doc, self.remote, self.roots, payload_digest(self.doc), 'run-1',
                    derived_assets=self.derived, evidence_validator=invalid)
        self.assertEqual(self.remote.version, 0)
        self.assertEqual(self.remote.tags, {})

    def test_authority_withdrawal_after_first_publication_stops_second_and_records_partial(self):
        calls = []
        def authority_guard(channel, *args):
            calls.append(channel)
            # Two preflight calls, then first publication, then revoked authority.
            if len(calls) == 4:
                raise ValueError('Human authority was revoked during upload')
        with self.assertRaisesRegex(ValueError, 'revoked'):
            execute(self.doc, self.remote, self.roots, payload_digest(self.doc), 'run-1',
                    derived_assets=self.derived, evidence_validator=authority_guard)
        self.assertEqual(self.remote.journal['state'], 'partial')
        self.assertFalse(self.remote.releases['finite-1.2.3']['draft'])
        self.assertTrue(self.remote.releases['finite-dev-1.2.3']['draft'])

    def test_two_channels_staged_before_first_publication_and_idempotent_retry(self):
        self.assertEqual(self.run_release()['state'], 'complete')
        first = next(i for i, v in enumerate(self.remote.events) if v[0] == 'publish')
        self.assertEqual(sum(v[0] == 'upload' for v in self.remote.events[:first]), 6)
        original = list(self.remote.events)
        self.run_release()
        self.assertEqual(self.remote.events, original)

    def test_prerelease_pair_preserves_flags_and_same_version_is_immutable(self):
        self.doc['payload']['version'] = '1.2.3-dev'
        for channel, entry in self.doc['payload']['channels'].items():
            entry['tag'] = channel + '-1.2.3-dev'
        self.assertEqual(self.run_release()['state'], 'complete')
        self.assertTrue(all(item['prerelease'] for item in self.remote.releases.values()))
        self.assertTrue(all(not item['draft'] for item in self.remote.releases.values()))
        before = copy.deepcopy(self.remote.releases)
        self.run_release()
        self.assertEqual(self.remote.releases, before)
        self.doc['payload']['sourceRevision'] = 'b' * 40
        for receipt in self.doc['evidence'].values():
            receipt['sourceRevision'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'reserved'):
            self.run_release()

    def test_prerelease_type_tampering_blocks_existing_products(self):
        self.run_release()
        self.remote.releases['finite-1.2.3']['prerelease'] = True
        with self.assertRaisesRegex(ValueError, 'release type'):
            self.run_release()

    def test_github_prereleases_never_change_latest_and_stable_defaults_remain(self):
        client = release_set.GitHubClient('closure-labs/finite')
        with patch.object(client, 'api') as api:
            api.return_value = {'id': 5, 'tag_name': 'finite-1.2.3-dev', 'draft': True,
                                'prerelease': True, 'body': '<!-- finite-release-set:' + 'b' * 64 + ' -->'}
            client.create_draft('finite-1.2.3-dev', 'a' * 40, 'b' * 64, prerelease=True)
            data = api.call_args.args[2]
            self.assertIs(data['prerelease'], True)
            self.assertEqual(data['make_latest'], 'false')
            client.publish(5, prerelease=True)
            self.assertEqual(api.call_args.args[2], {'draft': False, 'prerelease': True, 'make_latest': 'false'})
            client.publish(6)
            self.assertNotIn('make_latest', api.call_args.args[2])

    def test_evidence_refresh_does_not_change_approval_identity(self):
        other = copy.deepcopy(self.doc)
        other['evidence']['finite']['scanRun'] = 'fresh-run'
        self.assertEqual(payload_digest(other), payload_digest(self.doc))
        other['payload']['channels']['finite']['imageDigest'] = 'sha256:' + 'b' * 64
        self.assertNotEqual(payload_digest(other), payload_digest(self.doc))

    def test_partial_upload_resumes_without_duplicate_or_clobber(self):
        self.remote.fail_upload = True
        self.assertEqual(self.run_release()['state'], 'complete')

    def test_one_published_release_resumes_second(self):
        self.remote.fail_publish = 'finite-dev-1.2.3'
        with self.assertRaises(RuntimeError):
            self.run_release()
        self.assertEqual(self.remote.journal['state'], 'partial')
        self.assertFalse(self.remote.releases['finite-1.2.3']['draft'])
        self.run_release()
        self.assertEqual(sum(v == ('publish', 'finite-1.2.3') for v in self.remote.events), 1)

    def test_expected_preexisting_tag_without_release_is_safe(self):
        self.remote.tags['finite-1.2.3'] = 'a' * 40
        self.assertEqual(self.run_release()['state'], 'complete')

    def test_existing_other_tag_or_release_rejected(self):
        self.remote.tags['finite-1.2.3'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'different revision'):
            self.run_release()
        self.remote.tags.clear()
        self.remote.create_draft('finite-1.2.3', 'a' * 40, 'b' * 64)
        with self.assertRaisesRegex(ValueError, 'another payload'):
            self.run_release()

    def test_changed_remote_asset_is_never_overwritten(self):
        self.run_release()
        self.remote.releases['finite-1.2.3']['assets']['image.iso']['digest'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.run_release()

    def test_invalid_qualification_or_local_asset_fails_before_remote_write(self):
        self.doc['evidence']['finite-dev']['status'] = 'failed'
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertEqual(self.remote.version, 0)
        self.doc['evidence']['finite-dev']['status'] = 'qualified'
        (self.roots['finite'] / 'image.iso').unlink()
        (self.roots['finite'] / 'image.iso').symlink_to(self.roots['finite-dev'] / 'image.iso')
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertEqual(self.remote.version, 0)

    def test_concurrent_executor_and_cas_conflicts_fail_closed(self):
        self.remote.journal = {'schema': 1, 'payloadDigest': payload_digest(self.doc),
                               'owner': 'other', 'leaseUntil': 200, 'channels': {}}
        self.remote.version = 1
        with self.assertRaisesRegex(ValueError, 'Another executor'):
            self.run_release()
        self.remote.journal['leaseUntil'] = 0
        original = self.remote.write_journal
        def conflict(identity, journal, version):
            self.remote.version += 1
            return original(identity, journal, version)
        self.remote.write_journal = conflict
        with self.assertRaisesRegex(ValueError, 'CAS conflict'):
            self.run_release()
        self.assertEqual(self.remote.tags, {})

    def test_competing_payload_cannot_claim_reserved_version(self):
        self.run_release()
        self.doc['payload']['channels']['finite']['isoSha256'] = 'b' * 64
        self.doc['evidence']['finite']['isoSha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'version already reserved'):
            self.run_release()

    def test_stage_never_publishes_and_commit_never_transfers(self):
        self.assertEqual(self.run_release(phase='stage-publication')['state'], 'staged')
        self.assertTrue(all(r['draft'] for r in self.remote.releases.values()))
        self.remote.upload = self.remote.delete_asset = lambda *a: self.fail('Commit mutated assets')
        self.assertEqual(self.run_release(phase='commit-publication')['state'], 'complete')

    def test_commit_missing_inventory_cannot_create_or_upload(self):
        self.remote.create_draft = self.remote.create_tag = self.remote.upload = lambda *a, **kw: self.fail('Commit staged')
        with self.assertRaisesRegex(ValueError, 'different revision'):
            self.run_release(phase='commit-publication')

    def test_placeholder_and_lost_successful_response_reconcile(self):
        for lost_response in (False, True):
            with self.subTest(lost_response=lost_response):
                self.remote = Remote()
                upload = self.remote.upload
                calls = []
                def ambiguous(release_id, path):
                    calls.append(path.name)
                    if len(calls) == 1:
                        if lost_response:
                            upload(release_id, path)
                        else:
                            self.remote.releases[release_id]['assets'][path.name] = self.remote.record(path.name, state='starter')
                        raise RuntimeError('HTTP 502')
                    upload(release_id, path)
                self.remote.upload = ambiguous
                self.assertEqual(self.run_release()['state'], 'complete')
                self.assertEqual(sum(event[0] == 'delete' for event in self.remote.events), 0 if lost_response else 1)
                self.assertEqual(calls.count('image.iso'), 2 if lost_response else 3)

    def test_changed_placeholder_is_reconciled_without_deletion(self):
        self.run_release(phase='stage-publication')
        assets = self.remote.releases['finite-1.2.3']['assets']
        original = assets['image.iso']
        assets['image.iso'] = self.remote.record('image.iso', state='starter')
        def changed(asset_id):
            assets['image.iso'] = original
            return original
        self.remote.get_asset = changed
        self.run_release()
        self.assertFalse(any(event[0] == 'delete' for event in self.remote.events))

    def test_draft_published_before_cleanup_is_preserved(self):
        self.run_release(phase='stage-publication')
        release = self.remote.releases['finite-1.2.3']
        release['assets']['image.iso'] = self.remote.record('image.iso', state='starter')
        get_release = self.remote.get_release
        reads = []
        def changed(tag):
            if tag == 'finite-1.2.3':
                reads.append(tag)
                if len(reads) == 3:
                    release['draft'] = False
            return get_release(tag)
        self.remote.get_release = changed
        with self.assertRaisesRegex(ValueError, 'unsafe failed upload'):
            self.run_release()
        self.assertFalse(any(event[0] == 'delete' for event in self.remote.events))
        self.assertEqual(release['assets']['image.iso']['state'], 'starter')

    def test_unsafe_placeholders_are_preserved(self):
        for condition in ('published', 'nonempty', 'foreign', 'unexpected', 'conflicting'):
            with self.subTest(condition=condition):
                self.remote = Remote()
                self.run_release(phase='stage-publication')
                release = self.remote.releases['finite-1.2.3']
                name = 'foreign.iso' if condition == 'unexpected' else 'image.iso'
                record = self.remote.record(name, state='starter')
                release['assets'][name] = record
                if condition == 'published': release['draft'] = False
                if condition == 'nonempty': record['size'] = 1
                if condition == 'foreign': release['payloadDigest'] = 'b' * 64
                if condition == 'conflicting': record['digest'] = 'b' * 64
                before = copy.deepcopy(release)
                with self.assertRaises(ValueError): self.run_release()
                self.assertEqual(release, before)
                self.assertFalse(any(event[0] == 'delete' for event in self.remote.events))

    def test_three_failed_writes_are_bounded(self):
        calls = []
        def fail(*args):
            calls.append(args)
            raise RuntimeError('HTTP 502')
        self.remote.upload = fail
        with self.assertRaisesRegex(RuntimeError, 'three reconciled attempts'):
            self.run_release()
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.remote.journal['leaseUntil'], 0)

    def test_adapter_retains_placeholder_metadata_and_upload_disables_retries(self):
        client = release_set.GitHubClient('closure-labs/finite', token='scoped-token')
        record = {'id': 42, 'name': 'image.iso', 'state': 'starter', 'size': 0, 'digest': None}
        with patch.object(client, 'api', return_value=[record]):
            self.assertEqual(client.assets(1), {'image.iso': record})
        with patch.object(release_set.subprocess, 'run') as run:
            client.upload(1, self.roots['finite'] / 'image.iso')
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('--retry') + 1], '0')
            self.assertIn('--upload-file', args)
            self.assertEqual(run.call_args.kwargs['timeout'], 300)
            self.assertNotIn('scoped-token', ' '.join(args))

    def test_asset_path_traversal_and_missing_channel_rejected(self):
        self.doc['payload']['channels']['finite']['assets'] = {'../bad': 'b' * 64}
        with self.assertRaises(ValueError):
            payload_digest(self.doc)
        del self.doc['payload']['channels']['finite-dev']
        with self.assertRaises(ValueError):
            payload_digest(self.doc)


if __name__ == '__main__':
    unittest.main()
