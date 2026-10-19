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

    def create_draft(self, tag, revision, identity):
        self.releases[tag] = {'id': tag, 'payloadDigest': identity, 'draft': True, 'assets': {}}
        self.events.append(('draft', tag))

    def assets(self, release_id):
        return dict(self.releases[release_id]['assets'])

    def upload(self, release_id, path):
        if self.fail_upload:
            self.fail_upload = False
            raise RuntimeError('network upload failed')
        self.releases[release_id]['assets'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.events.append(('upload', release_id))

    def publish(self, release_id):
        if self.fail_publish == release_id:
            self.fail_publish = None
            raise RuntimeError('publish failed')
        assert len(self.releases) == 2
        assert all(v['assets'] for v in self.releases.values())
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

    def run_release(self, owner='run-1'):
        return execute(self.doc, self.remote, self.roots, payload_digest(self.doc), owner, now=lambda: 100,
                       derived_assets=self.derived, evidence_validator=lambda *args: None)

    def test_github_gets_have_no_body_and_mutations_keep_structured_json(self):
        result = types.SimpleNamespace(returncode=0, stdout='{}', stderr='')
        with patch.object(release_set.subprocess, 'run', return_value=result) as run:
            client = release_set.GitHubClient('closure-labs/finite', token='fixture-publish')
            client.api('git/ref/heads/main')
            self.assertNotIn('--input', run.call_args.args[0])
            self.assertIsNone(run.call_args.kwargs['input'])
            client.api('git/refs', 'POST', {'ref': 'refs/tags/finite-1.2.3', 'sha': 'a' * 40})
            self.assertIn('--input', run.call_args.args[0])
            self.assertEqual(json.loads(run.call_args.kwargs['input'])['ref'], 'refs/tags/finite-1.2.3')
            self.assertEqual(run.call_args.kwargs['env']['GH_TOKEN'], 'fixture-publish')

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

    def test_evidence_refresh_does_not_change_approval_identity(self):
        other = copy.deepcopy(self.doc)
        other['evidence']['finite']['scanRun'] = 'fresh-run'
        self.assertEqual(payload_digest(other), payload_digest(self.doc))
        other['payload']['channels']['finite']['imageDigest'] = 'sha256:' + 'b' * 64
        self.assertNotEqual(payload_digest(other), payload_digest(self.doc))

    def test_partial_upload_resumes_without_duplicate_or_clobber(self):
        self.remote.fail_upload = True
        with self.assertRaises(RuntimeError):
            self.run_release()
        self.assertEqual(self.remote.journal['state'], 'interrupted')
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
        self.remote.releases['finite-1.2.3']['assets']['image.iso'] = 'b' * 64
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

    def test_asset_path_traversal_and_missing_channel_rejected(self):
        self.doc['payload']['channels']['finite']['assets'] = {'../bad': 'b' * 64}
        with self.assertRaises(ValueError):
            payload_digest(self.doc)
        del self.doc['payload']['channels']['finite-dev']
        with self.assertRaises(ValueError):
            payload_digest(self.doc)


if __name__ == '__main__':
    unittest.main()
