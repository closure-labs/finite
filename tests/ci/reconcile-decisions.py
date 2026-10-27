#!/usr/bin/env python3
"""Reconciliation reauthenticates humans and recovers ambiguous dispatches."""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
SPEC = importlib.util.spec_from_file_location('reconcile_decisions', ROOT / 'scripts/ci/reconcile-decisions.py')
reconcile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconcile)
SHA = 'a' * 40
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64


class Journal:
    def __init__(self):
        self.state = None
        self.version = None
        self.calls = 0
        self.fail_at = None

    def read_journal(self, identity):
        return deepcopy(self.state), self.version

    def write_journal(self, identity, state, version):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError('CAS or journal transport failure')
        if version != self.version:
            raise RuntimeError('CAS conflict')
        self.version = str(self.calls)
        self.state = deepcopy(state)
        return self.version


def observation_env():
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': reconcile.controller.REPOSITORY,
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_JOB': 'reconcile', 'GITHUB_SHA': SHA,
            'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_WORKFLOW_REF': reconcile.controller.REPOSITORY + '/.github/workflows/decision-proposals.yml@refs/heads/main'}


class PublicationBusy(unittest.TestCase):
    def publisher(self, **changes):
        return {'event': 'push', 'head_branch': 'main',
                'head_repository': {'full_name': reconcile.controller.REPOSITORY},
                'path': '.github/workflows/build.yml', 'status': 'in_progress', **changes}

    def test_every_incomplete_status_blocks_even_beyond_large_completed_history(self):
        statuses = ('in_progress', 'queued', 'requested', 'waiting', 'pending')
        for active in statuses:
            requested = []
            def api(path):
                query = parse_qs(urlsplit(path).query)
                self.assertEqual(query['branch'], ['main'])
                self.assertEqual(query['per_page'], ['100'])
                self.assertEqual(query['page'], ['1'])
                # An unfiltered listing would exhaust its pagination bound
                # before reaching this older active publisher.
                self.assertIn('status', query)
                status = query['status'][0]
                requested.append(status)
                return {'workflow_runs': [self.publisher(status=active)] if status == active else []}
            with self.subTest(status=active), patch.object(reconcile.controller, 'api', side_effect=api):
                self.assertTrue(reconcile.publication_busy())
                self.assertEqual(requested, list(statuses[:statuses.index(active) + 1]))

    def test_idle_checks_all_statuses_and_ignores_unrelated_or_completed_runs(self):
        unrelated = [self.publisher(status='completed'), self.publisher(event='pull_request'),
                     self.publisher(event='merge_group'), self.publisher(head_branch='other'),
                     self.publisher(head_repository={'full_name': 'fork/finite'}),
                     self.publisher(path='.github/workflows/other.yml')]
        with patch.object(reconcile.controller, 'collection', return_value=unrelated) as collection:
            self.assertFalse(reconcile.publication_busy())
        self.assertEqual([parse_qs(urlsplit(call.args[0]).query)['status'][0]
                          for call in collection.call_args_list],
                         ['in_progress', 'queued', 'requested', 'waiting', 'pending'])

    def test_matching_publisher_on_later_active_page_still_blocks(self):
        def api(path):
            query = parse_qs(urlsplit(path).query)
            if query['status'] != ['waiting']:
                return {'workflow_runs': []}
            if query['page'] == ['1']:
                return {'workflow_runs': [self.publisher(event='pull_request', status='waiting')] * 100}
            self.assertEqual(query['page'], ['2'])
            return {'workflow_runs': [self.publisher(event='workflow_dispatch', status='waiting')]}
        with patch.object(reconcile.controller, 'api', side_effect=api):
            self.assertTrue(reconcile.publication_busy())

    def test_transport_malformed_and_pagination_failures_never_mean_idle(self):
        for error in (ValueError('GitHub read failed'), TimeoutError('read timed out')):
            with self.subTest(error=error), patch.object(reconcile.controller, 'api', side_effect=error):
                with self.assertRaises(type(error)):
                    reconcile.publication_busy()
        for response in ({'workflow_runs': None}, {'workflow_runs': {}}):
            with self.subTest(response=response), patch.object(reconcile.controller, 'api', return_value=response):
                with self.assertRaisesRegex(ValueError, 'Invalid bounded API collection'):
                    reconcile.publication_busy()
        with patch.object(reconcile.controller, 'api', return_value={
                'workflow_runs': [self.publisher(event='pull_request')] * 100}) as api:
            with self.assertRaisesRegex(ValueError, 'exceeds bounded pagination'):
                reconcile.publication_busy()
            self.assertEqual(api.call_count, 10)


class Observations(unittest.TestCase):
    def make(self, root, clock=None, env=None):
        with patch.object(reconcile.subprocess, 'check_output', return_value='b' * 40):
            return reconcile.Observation(env=env or observation_env(),
                                         output=Path(root) / 'costs.json', clock=clock)

    def test_success_preserves_result_and_records_running_partial_without_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            observer = self.make(root, clock=iter([1, 3]).__next__)
            observer.profile = 'finite'
            result = object()
            def operation(secret):
                self.assertEqual(secret, 'private-token')
                partial = json.loads(observer.output.read_text())['stages'][0]
                self.assertEqual((partial['outcome'], partial['seconds']), ('running', None))
                return result
            self.assertIs(observer.call('packet-download', operation, 'private-token'), result)
            value = json.loads(observer.output.read_text())
            self.assertEqual(value['checkoutRevision'], 'b' * 40)
            self.assertEqual(value['stages'][0]['seconds'], 2)
            self.assertEqual(value['stages'][0]['profile'], 'finite')
            self.assertEqual(value['stages'][0]['outcome'], 'success')
            self.assertFalse(value['authorizesPublication'])
            self.assertNotIn('private-token', observer.output.read_text())

    def test_original_exception_and_partial_error_survive(self):
        with tempfile.TemporaryDirectory() as root:
            observer = self.make(root, clock=lambda: 2)
            failure = RuntimeError('sensitive error text')
            with self.assertRaises(RuntimeError) as raised:
                observer.call('authority-check', lambda: (_ for _ in ()).throw(failure))
            self.assertIs(raised.exception, failure)
            row = json.loads(observer.output.read_text())['stages'][0]
            self.assertEqual((row['outcome'], row['seconds']), ('error', 0))
            self.assertNotIn('sensitive error text', observer.output.read_text())

    def test_missing_reset_and_invalid_clocks_remain_unknown(self):
        for values in ([5, 4], [0, 86401], [float('nan'), 1], [True, 1], [None, 1], [OSError('clock'), 1]):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as root:
                clock = iter(values)
                def read():
                    value = next(clock)
                    if isinstance(value, BaseException):
                        raise value
                    return value
                observer = self.make(root, clock=read)
                self.assertEqual(observer.call('journal-read', lambda: 7), 7)
                self.assertIsNone(json.loads(observer.output.read_text())['stages'][0]['seconds'])

    def test_observation_write_failure_changes_neither_result_nor_exception(self):
        with tempfile.TemporaryDirectory() as root, patch('sys.stderr', new_callable=io.StringIO) as errors:
            blocked = Path(root) / 'not-a-directory'
            blocked.write_text('file')
            observer = self.make(root)
            observer.output = blocked / 'costs.json'
            self.assertEqual(observer.call('journal-read', lambda: 7), 7)
            with self.assertRaisesRegex(ValueError, 'original'):
                observer.call('dispatch', lambda: (_ for _ in ()).throw(ValueError('original')))
            self.assertEqual(errors.getvalue().count('timing unavailable'), 1)

    def test_phase_and_serialized_size_bounds_never_skip_operations(self):
        with tempfile.TemporaryDirectory() as root:
            observer = self.make(root, clock=lambda: 0)
            calls = []
            for index in range(65):
                observer.call('journal-read', calls.append, index)
            value = json.loads(observer.output.read_text())
            self.assertEqual(len(calls), 65)
            self.assertEqual(len(value['stages']), 64)
            self.assertTrue(value['truncated'])
            self.assertLessEqual(observer.output.stat().st_size, 65536)
            observer.document['oversized'] = 'x' * 65536
            with patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(observer.call('journal-read', lambda: 9), 9)
            self.assertLessEqual(observer.output.stat().st_size, 65536)

    def test_unhosted_or_unbound_context_does_not_create_receipts(self):
        for key, wrong in (('GITHUB_ACTIONS', 'false'), ('GITHUB_REF', 'refs/heads/branch'),
                           ('GITHUB_JOB', 'checks'), ('GITHUB_REPOSITORY', 'fork/repo'),
                           ('GITHUB_WORKFLOW_REF', 'other/workflow'), ('GITHUB_RUN_ID', ''), ('GITHUB_SHA', 'bad')):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                observer = self.make(root, env={**observation_env(), key: wrong})
                self.assertEqual(observer.call('journal-read', lambda: 9), 9)
                self.assertFalse(observer.output.exists())


class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        ledger = self.root / 'automation/decisions/security'
        ledger.mkdir(parents=True)
        policy = self.root / 'automation/security/image-policy.json'
        policy.parent.mkdir(parents=True)
        policy.write_text(json.dumps({'mode': 'maintainer-decision'}))
        self.origin = {'workflow': 'build.yml', 'runId': 123, 'runAttempt': 1, 'headSha': SHA}
        proposal = {'schema': 1, 'kind': 'security-findings',
                    'payload': {'profiles': ['finite'], 'supersedes': [],
                                'packet': {'reference': 'packet', 'sha256': 'c' * 64, 'producer': self.origin}}}
        self.identity = reconcile.canonical_hash(proposal)
        self.proposal = proposal
        (ledger / (self.identity + '.json')).write_text(json.dumps(proposal))
        self.run = {'id': 123, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                    'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'push',
                    'head_sha': SHA, 'run_attempt': 1, 'status': 'completed'}
        self.artifacts = [{'name': f'{kind}-finite-123-1', 'expired': False} for kind in ('image', 'security')]
        self.observed = []
        self.dispatched = []
        self.journal = Journal()
        self.current_sha = SHA
        self.ambiguous_dispatch = False
        self.verify_results = None
        self.verifications = 0
        self.native_scan = {'status': 'complete', 'scannerHealth': 'healthy', 'image': IMAGE}
        self.fetches = []
        self.patches = [patch.object(reconcile, 'completion', return_value=None),patch.object(reconcile.controller, 'ROOT', self.root),
                        patch.object(reconcile.controller, 'api', side_effect=self.api),
                        patch.object(reconcile.controller, 'collection', side_effect=self.collection),
                        patch.object(reconcile.decision_packets, 'fetch', side_effect=self.fetch),
                        patch.object(reconcile.controller, 'native_result', side_effect=lambda *a, **k: deepcopy(self.native_scan)),
                        patch.object(reconcile, 'GitHubClient', return_value=self.journal),
                        patch.object(reconcile, 'verify', side_effect=self.verify),
                        patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                                                'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA,
                                                'FINITE_REVIEW_BOT_LOGIN': 'finite-decisions[bot]'})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def fetch(self, reference, directory, digest, *, existing=False):
        self.fetches.append((reference, directory, digest, existing))
        if existing:
            self.assertTrue(directory.is_dir())
            return
        for profile in reconcile.controller.PROFILES:
            location = directory / profile
            location.mkdir(parents=True)
            (location / 'vulnerabilities.json').write_text(json.dumps({'descriptor': {'timestamp': '2026-01-01T00:00:00Z'}}))
            (location / 'security-result.json').write_text(json.dumps({'status': 'complete', 'scannerHealth': 'healthy', 'image': IMAGE}))

    def two_profile_proposal(self):
        ledger = self.root / 'automation/decisions/security'
        (ledger / (self.identity + '.json')).unlink()
        self.proposal['payload']['profiles'] = list(reconcile.controller.PROFILES)
        self.identity = reconcile.canonical_hash(self.proposal)
        (ledger / (self.identity + '.json')).write_text(json.dumps(self.proposal))

    def test_enabled_observations_preserve_two_profile_behavior_and_cleanup(self):
        self.two_profile_proposal()
        with patch.object(reconcile.subprocess, 'check_output', return_value=SHA):
            observer = reconcile.Observation(env=observation_env(), output=self.root / 'observations.json')
        with patch.object(reconcile, 'publication_busy', return_value=True):
            self.assertEqual([item['status'] for item in reconcile.reconcile(now=lambda: 1000, observer=observer)],
                             ['publisher-busy', 'publisher-busy'])
        rows = json.loads(observer.output.read_text())['stages']
        self.assertEqual([row['stage'] for row in rows if row['stage'].startswith('packet-')],
                         ['packet-download', 'packet-staged-verification'])
        self.assertEqual([row['profile'] for row in rows if row['stage'] == 'authority-check'],
                         ['finite', 'finite-dev'])
        self.assertEqual(rows[0]['stage'], 'reconciliation')
        self.assertEqual(rows[0]['outcome'], 'success')
        self.assertEqual(rows[-1]['stage'], 'staging-cleanup')
        self.assertTrue(all(not fetch[1].exists() for fetch in self.fetches))
        self.assertEqual(self.verifications, 2)
        self.assertEqual(self.dispatched, [])

    def test_enabled_observations_preserve_lost_response_and_partial_results(self):
        with patch.object(reconcile.subprocess, 'check_output', return_value=SHA):
            observer = reconcile.Observation(env=observation_env(), output=self.root / 'observations.json')
        self.ambiguous_dispatch = True
        with self.assertRaisesRegex(RuntimeError, 'Lost dispatch response'):
            reconcile.reconcile(now=lambda: 1000, observer=observer)
        rows = json.loads(observer.output.read_text())['stages']
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.assertEqual(rows[0]['outcome'], 'error')
        self.assertEqual(next(row['outcome'] for row in rows if row['stage'] == 'dispatch'), 'error')
        self.assertEqual(rows[-1]['stage'], 'staging-cleanup')
        self.assertEqual(rows[-1]['outcome'], 'success')
        self.assertTrue(all(not fetch[1].exists() for fetch in self.fetches))

    def test_shared_packet_downloads_once_but_rechecks_bytes_health_and_authority_for_each_profile(self):
        self.two_profile_proposal()
        with patch.object(reconcile, 'publication_busy', return_value=True):
            self.assertEqual([item['status'] for item in self.execute()], ['publisher-busy'] * 2)
        self.assertEqual([item[3] for item in self.fetches], [False, True])
        self.assertEqual(self.fetches[0][:3], self.fetches[1][:3])
        self.assertEqual(self.verifications, 2)
        self.assertEqual([call.kwargs['profile'] for call in reconcile.controller.native_result.call_args_list],
                         list(reconcile.controller.PROFILES))
        self.assertFalse(self.fetches[0][1].exists())
        self.assertEqual(self.dispatched, [])

    def observe_document_reads(self):
        calls = []
        def github(endpoint):
            self.assertIn('/contents/', endpoint)
            calls.append(endpoint)
            raw = json.dumps(self.proposal).encode()
            return {'type': 'file', 'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                    'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
        def verify(*args):
            document = reconcile.authority.document_at(github, 'closure-labs/finite',
                                                       'automation/decisions/security/proposal.json', SHA)
            self.assertEqual(document, self.proposal)
            return self.verify(*args)
        reconcile.verify.side_effect = verify
        return calls

    def test_document_bytes_are_shared_across_profiles_but_not_invocations(self):
        self.two_profile_proposal()
        calls = self.observe_document_reads()
        with patch.object(reconcile, 'publication_busy', return_value=True):
            self.assertEqual([item['status'] for item in self.execute()], ['publisher-busy'] * 2)
            self.assertEqual(len(calls), 1)
            self.assertEqual([item['status'] for item in self.execute()], ['publisher-busy'] * 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.verifications, 4)
        self.assertEqual(self.dispatched, [])

    def test_failed_dispatch_clears_document_scope_and_keeps_authority_recheck(self):
        calls = self.observe_document_reads()
        self.ambiguous_dispatch = True
        with self.assertRaisesRegex(RuntimeError, 'Lost dispatch response'):
            self.execute()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.verifications, 2)
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.ambiguous_dispatch = False
        self.assertEqual(self.execute()[0]['status'], 'already-dispatched')
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.dispatched), 1)

    def test_staging_is_not_reused_between_reconciliation_invocations(self):
        self.two_profile_proposal()
        with patch.object(reconcile, 'publication_busy', return_value=True):
            self.execute()
            self.execute()
        self.assertEqual([item[3] for item in self.fetches], [False, True, False, True])
        self.assertNotEqual(self.fetches[0][1], self.fetches[2][1])
        self.assertTrue(all(not item[1].exists() for item in self.fetches))
        self.assertEqual(self.verifications, 4)

    def test_first_dispatch_still_stops_before_second_profile_or_extra_transfer(self):
        self.two_profile_proposal()
        self.assertEqual([item['status'] for item in self.execute()], ['dispatched'])
        self.assertEqual([item[3] for item in self.fetches], [False])
        self.assertEqual(self.verifications, 2)
        self.assertEqual(len(self.dispatched), 1)
        self.assertFalse(self.fetches[0][1].exists())

    def test_second_profile_native_health_failure_is_not_covered_by_first_profile(self):
        self.two_profile_proposal()
        reconcile.controller.native_result.side_effect = [self.native_scan, ValueError('Invalid native evidence')]
        with patch.object(reconcile, 'publication_busy', return_value=True), \
                self.assertRaisesRegex(ValueError, 'Invalid native evidence'):
            self.execute()
        self.assertEqual([item[3] for item in self.fetches], [False, True])
        self.assertEqual(self.verifications, 1)
        self.assertEqual(self.dispatched, [])

    def test_different_immutable_packets_are_staged_separately(self):
        developer = deepcopy(self.proposal)
        developer['payload'].update(profiles=['finite-dev'])
        developer['payload']['packet'].update(reference='different-packet', sha256='d' * 64)
        identity = reconcile.canonical_hash(developer)
        (self.root / 'automation/decisions/security' / (identity + '.json')).write_text(json.dumps(developer))
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': item}}
                               for item in (self.identity, identity)]
        def fetch(*args, **kwargs):
            if self.fetches:
                self.assertFalse(self.fetches[0][1].exists())
            self.fetch(*args, **kwargs)
        with patch.object(reconcile, 'publication_busy', return_value=True), \
                patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch):
            self.execute()
        self.assertEqual([item[3] for item in self.fetches], [False, False])
        self.assertNotEqual(self.fetches[0][1], self.fetches[1][1])
        self.assertEqual(self.verifications, 2)

    def test_different_expected_packet_hash_does_not_use_staged_bytes(self):
        developer = deepcopy(self.proposal)
        developer['payload'].update(profiles=['finite-dev'])
        developer['payload']['packet']['sha256'] = 'd' * 64
        identity = reconcile.canonical_hash(developer)
        (self.root / 'automation/decisions/security' / (identity + '.json')).write_text(json.dumps(developer))
        def fetch(reference, directory, digest, **kwargs):
            if digest == 'd' * 64:
                self.assertFalse(kwargs.get('existing', False))
                raise ValueError('Packet contents differ from approved manifest')
            self.fetch(reference, directory, digest, **kwargs)
        with patch.object(reconcile, 'publication_busy', return_value=True), \
                patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch), \
                self.assertRaisesRegex(ValueError, 'approved manifest'):
            self.execute()
        self.assertEqual(self.verifications, 1)
        self.assertEqual(self.dispatched, [])

    def test_corrupt_staged_packet_stops_before_second_health_authority_or_dispatch(self):
        self.two_profile_proposal()
        def fetch(reference, directory, digest, *, existing=False):
            if existing:
                raise ValueError('Packet member integrity failure')
            self.fetch(reference, directory, digest)
        with patch.object(reconcile, 'publication_busy', return_value=True), \
                patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch), \
                self.assertRaisesRegex(ValueError, 'integrity failure'):
            self.execute()
        self.assertEqual(reconcile.controller.native_result.call_count, 1)
        self.assertEqual(self.verifications, 1)
        self.assertFalse(self.fetches[0][1].exists())
        self.assertEqual(self.dispatched, [])

    def test_failed_initial_transfer_is_cleaned_and_never_retained_for_retry(self):
        self.two_profile_proposal()
        def fetch(*args, **kwargs):
            self.fetch(*args, **kwargs)
            raise OSError('Interrupted transfer')
        with patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch), \
                self.assertRaisesRegex(OSError, 'Interrupted'):
            self.execute()
        self.assertEqual(self.verifications, 0)
        self.assertFalse(self.fetches[0][1].exists())
        with patch.object(reconcile, 'publication_busy', return_value=True):
            self.execute()
        self.assertEqual([item[3] for item in self.fetches], [False, False, True])

    def test_cached_packet_does_not_carry_approval_across_profiles_or_past_revocation(self):
        self.two_profile_proposal()
        self.verify_results = [
            {'status': 'review-required'},
            {'status': 'covered', 'decision': {'proposalHash': self.identity}},
            {'status': 'revoked'}]
        with self.assertRaisesRegex(ValueError, 'authority changed'):
            self.execute()
        self.assertEqual([item[3] for item in self.fetches], [False, True])
        self.assertEqual(self.verifications, 3)
        self.assertEqual(self.dispatched, [])

    def verify(self, *args, **kwargs):
        self.verifications += 1
        if self.verify_results:
            return self.verify_results.pop(0)
        return {'status': 'covered', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}

    def collection(self, path, key):
        if path.endswith('/artifacts'): return deepcopy(self.artifacts)
        if '/actions/workflows/build.yml/runs?' in path: return deepcopy(self.observed)
        raise AssertionError(path)

    def api(self, path, method='GET', payload=None):
        if path.endswith('/actions/runs/123'):
            return deepcopy(self.run)
        if path.endswith('/git/ref/heads/main'):
            return {'object': {'sha': self.current_sha}}
        if path.endswith('/dispatches'):
            self.assertEqual(method, 'POST')
            self.assertEqual(self.journal.state['status'], 'claimed')
            self.dispatched.append(deepcopy(payload))
            self.observed = [{'id': 999, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                              'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'workflow_dispatch',
                              'display_title': 'Build Finite [decision:' + payload['inputs']['decision_request'] + ']',
                              'status': 'in_progress'}]
            if self.ambiguous_dispatch: raise RuntimeError('Lost dispatch response')
            return None
        raise AssertionError(path)

    def execute(self, clock=1000):
        return reconcile.reconcile(now=lambda: clock)

    def test_parallel_initial_history_keeps_final_authority_recheck_serial(self):
        with patch.object(reconcile, 'verify', side_effect=self.verify) as verify:
            result = reconcile.reconcile(now=lambda: 1000, historical_workers=4)
        self.assertEqual(result[0]['status'], 'dispatched')
        self.assertEqual(verify.call_args_list[0].kwargs, {'historical_workers': 4})
        self.assertEqual(verify.call_args_list[1].kwargs, {})

    def test_parallel_initial_history_does_not_bypass_revocation_before_dispatch(self):
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': self.identity}},
                               {'status': 'revoked'}]
        with self.assertRaisesRegex(ValueError, 'authority changed'):
            reconcile.reconcile(now=lambda: 1000, historical_workers=4)
        self.assertEqual(self.dispatched, [])

    def test_worker_mode_is_observed_and_invalid_limits_fail_before_reconciliation(self):
        with patch.object(reconcile.subprocess, 'check_output', return_value=SHA):
            observer = reconcile.Observation(env=observation_env(), output=self.root / 'observations.json')
        reconcile.reconcile(now=lambda: 1000, observer=observer, historical_workers=4)
        self.assertEqual(json.loads(observer.output.read_text())['historicalReadWorkers'], 4)
        for value in (True, 0, 2, '4'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'one or four'):
                reconcile.reconcile(historical_workers=value)

    def test_independent_publisher_satisfies_without_claim_or_dispatch(self):
        proof = {'runId': 456, 'artifacts': {'promotion': {'sha256': 'd' * 64}}}
        with patch.object(reconcile, 'completion', return_value=proof):
            self.assertEqual(self.execute()[0]['status'], 'satisfied')
        self.assertEqual(self.journal.state['schema'], 2)
        self.assertEqual(self.journal.state['publisherProof'], proof)
        self.assertNotIn('inputs', self.journal.state)
        self.assertEqual(self.dispatched, [])

    def test_completion_after_claim_prevents_post(self):
        with patch.object(reconcile, 'completion', side_effect=[None, {'runId': 456}]):
            self.assertEqual(self.execute()[0]['status'], 'satisfied')
        self.assertEqual(self.journal.calls, 2)
        self.assertEqual(self.dispatched, [])

    def test_satisfied_receipt_requires_live_reauthentication(self):
        with patch.object(reconcile, 'completion', return_value={'runId': 456}):
            self.execute()
        self.assertEqual(self.execute()[0]['status'], 'dispatched')
        self.assertEqual(len(self.dispatched), 1)

    def test_satisfaction_cas_conflict_does_not_dispatch(self):
        self.journal.fail_at = 1
        with patch.object(reconcile, 'completion', return_value={'runId': 456}), self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.dispatched, [])

    def test_claim_before_dispatch_and_live_authority_rechecked(self):
        result = self.execute()
        self.assertEqual(result[0]['status'], 'dispatched')
        self.assertEqual(self.verifications, 2)
        self.assertEqual(self.dispatched[0]['inputs']['resume_run'], '123')
        self.assertEqual(self.dispatched[0]['inputs']['resume_digest'], IMAGE.split('@')[1])
        self.assertRegex(self.dispatched[0]['inputs']['decision_request'], r'^[0-9a-f]{64}$')
        self.assertEqual(self.journal.state['status'], 'dispatched')

    def test_legacy_packet_reconstructs_cvss_and_uses_real_admission_identity(self):
        from security_decisions import evaluate, normalize_findings, TechnicalError
        finding = {'component': 'pkg:rpm/fedora/openssl@3.0?arch=x86_64',
                   'advisory': 'CVE-2026-12345', 'aliases': [], 'severity': 'High',
                   'cvss': 8.1, 'knownExploited': False, 'locations': ['/usr/bin/openssl'],
                   'locationCoverage': 'complete', 'fixVersions': []}
        self.native_scan['observations'] = [finding]
        accepted = normalize_findings(self.native_scan, 'finite')
        legacy = deepcopy(self.native_scan)
        del legacy['observations'][0]['cvss']
        with self.assertRaisesRegex(TechnicalError, 'CVSS evidence disappeared'):
            evaluate(legacy, 'finite', accepted)

        def admission(scan, profile, *args):
            result = evaluate(scan, profile, accepted)
            return {**result, 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}
        with patch.object(reconcile, 'verify', side_effect=admission):
            self.assertEqual(self.execute()[0]['status'], 'dispatched')
        snapshot = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reconcile.controller.native_result.assert_called_once()
        call = reconcile.controller.native_result.call_args
        self.assertEqual(call.args[1:], (snapshot, snapshot))
        self.assertEqual(call.kwargs, {'profile': 'finite'})
        self.assertEqual(len(self.dispatched), 1)

    def test_native_evidence_failure_stops_before_authority_or_dispatch(self):
        reconcile.controller.native_result.side_effect = ValueError('Invalid native evidence')
        with self.assertRaisesRegex(ValueError, 'Invalid native evidence'):
            self.execute()
        self.assertEqual(self.verifications, 0)
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_wrong_decision_identity_never_dispatches(self):
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': 'f' * 64}}]
        with self.assertRaisesRegex(ValueError, 'differs from authenticated'):
            self.execute()
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_changed_decision_identity_after_claim_never_dispatches(self):
        self.verify_results = [self.verify(), {'status': 'covered', 'decision': {'proposalHash': 'f' * 64}}]
        with self.assertRaisesRegex(ValueError, 'authority changed'):
            self.execute()
        self.assertEqual(self.dispatched, [])

    def test_genuinely_missing_native_cvss_remains_a_technical_failure(self):
        from security_decisions import evaluate, normalize_findings, TechnicalError
        finding = {'component': 'pkg:rpm/fedora/openssl@3.0?arch=x86_64',
                   'advisory': 'CVE-2026-12345', 'aliases': [], 'severity': 'High',
                   'cvss': 8.1, 'knownExploited': False, 'locations': ['/usr/bin/openssl'],
                   'locationCoverage': 'complete', 'fixVersions': []}
        self.native_scan['observations'] = [finding]
        accepted = normalize_findings(self.native_scan, 'finite')
        del finding['cvss']
        with patch.object(reconcile, 'verify', side_effect=lambda scan, profile, *a: evaluate(scan, profile, accepted)):
            with self.assertRaisesRegex(TechnicalError, 'CVSS evidence disappeared'):
                self.execute()
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_future_or_unzoned_snapshot_never_dispatches(self):
        original = self.fetch
        for timestamp in ('2999-01-01T00:00:00Z', '2026-01-01T00:00:00', None):
            def fetch(reference, directory, digest):
                original(reference, directory, digest)
                (directory / 'finite/vulnerabilities.json').write_text(json.dumps({'descriptor': {'timestamp': timestamp}}))
            with self.subTest(timestamp=timestamp), patch.object(reconcile.decision_packets, 'fetch', side_effect=fetch):
                with self.assertRaisesRegex(ValueError, 'scan time'):
                    self.execute()
            self.assertEqual(self.journal.calls, 0)
            self.assertEqual(self.dispatched, [])

    def test_shadow_bootstrap_never_dispatches_before_explicit_policy_cutover(self):
        (self.root / 'automation/security/image-policy.json').write_text(json.dumps({'mode': 'desktop-critical-only'}))
        self.assertEqual(self.execute()[0]['status'], 'awaiting-policy-cutover')
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.verifications, 0)

    def test_ambiguous_post_is_observed_without_duplicate_dispatch(self):
        self.ambiguous_dispatch = True
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.ambiguous_dispatch = False
        self.assertEqual(self.execute()[0]['status'], 'already-dispatched')
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.journal.state['observedRun'], 999)

    def test_crash_writing_success_receipt_is_recovered_by_run_marker(self):
        self.journal.fail_at = 2
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.journal.fail_at = None
        self.execute()
        self.assertEqual(len(self.dispatched), 1)

    def test_unobserved_claim_waits_for_lease_before_bounded_retry(self):
        self.ambiguous_dispatch = True
        with self.assertRaises(RuntimeError): self.execute()
        self.ambiguous_dispatch = False
        self.observed = []
        self.assertEqual(self.execute(clock=1001)[0]['status'], 'dispatch-pending')
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.execute(clock=2000)[0]['status'], 'dispatched')
        self.assertEqual(len(self.dispatched), 2)

    def test_observed_success_is_idempotent_without_journal_churn(self):
        self.execute()
        self.execute()
        writes = self.journal.calls
        self.execute()
        self.assertEqual(self.journal.calls, writes)
        self.assertEqual(len(self.dispatched), 1)

    def test_claim_conflict_stops_before_any_dispatch(self):
        self.journal.fail_at = 1
        with self.assertRaises(RuntimeError): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_busy_publisher_defers_without_consuming_pending_slot(self):
        self.observed = [{'id': 456, 'path': '.github/workflows/build.yml', 'head_branch': 'main',
                          'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'schedule', 'status': 'queued'}]
        self.assertEqual(self.execute()[0]['status'], 'publisher-busy')
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.journal.calls, 0)

    def test_later_status_lookup_failure_never_claims_or_dispatches(self):
        def collection(path, key):
            if '&status=waiting' in path:
                raise ValueError('Publisher status lookup unavailable')
            return self.collection(path, key)
        with patch.object(reconcile.controller, 'collection', side_effect=collection):
            with self.assertRaisesRegex(ValueError, 'status lookup unavailable'):
                self.execute()
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.journal.calls, 0)

    def test_expired_missing_or_rerun_origin_uses_full_build(self):
        for mutation in ('expired', 'missing', 'attempt', 'source'):
            self.journal = Journal()
            reconcile.GitHubClient.return_value = self.journal
            self.artifacts = [{'name': f'{kind}-finite-123-1', 'expired': False} for kind in ('image', 'security')]
            self.run.update(head_sha=SHA, run_attempt=1)
            if mutation == 'expired': self.artifacts[0]['expired'] = True
            if mutation == 'missing': self.artifacts.pop()
            if mutation == 'attempt': self.run['run_attempt'] = 2
            if mutation == 'source': self.run['head_sha'] = 'd' * 40
            with self.subTest(mutation=mutation):
                self.execute()
                inputs = self.dispatched[-1]['inputs']
                self.assertNotIn('resume_run', inputs)
                self.assertNotIn('resume_digest', inputs)

    def test_failed_resume_with_expired_artifacts_retries_full_build_once(self):
        self.execute()
        first = self.dispatched[0]['inputs']['decision_request']
        self.observed[0].update(status='completed', conclusion='failure')
        self.artifacts[0]['expired'] = True
        self.execute()
        self.assertEqual(len(self.dispatched), 2)
        self.assertNotIn('resume_run', self.dispatched[-1]['inputs'])
        self.assertNotEqual(first, self.dispatched[-1]['inputs']['decision_request'])
        self.execute()
        self.assertEqual(len(self.dispatched), 2)

    def test_completed_success_does_not_rebuild_when_artifacts_expire(self):
        self.execute()
        self.observed[0].update(status='completed', conclusion='success')
        self.artifacts[0]['expired'] = True
        self.execute()
        self.assertEqual(len(self.dispatched), 1)

    def test_publication_starting_after_claim_defers_dispatch(self):
        with patch.object(reconcile, 'publication_busy', side_effect=[False, True]):
            self.assertEqual(self.execute()[0]['status'], 'publisher-busy')
        self.assertEqual(self.journal.state['status'], 'claimed')
        self.assertEqual(self.dispatched, [])

    def test_revocation_between_claim_and_dispatch_stops_publication(self):
        self.verify_results = [{'status': 'covered', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}, {'status': 'revoked', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}]
        with self.assertRaisesRegex(ValueError, 'authority changed'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_main_advancement_stops_stale_reconciliation(self):
        self.current_sha = 'e' * 40
        with self.assertRaisesRegex(ValueError, 'Main changed'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_review_required_never_dispatches_or_writes_journal(self):
        self.verify_results = [{'status': 'review-required', 'decision': {'proposalHash': self.identity, 'disposition': 'accepted'}}]
        self.assertEqual(self.execute()[0]['status'], 'review-required')
        self.assertEqual(self.journal.calls, 0)
        self.assertEqual(self.dispatched, [])

    def test_untrusted_context_stops_before_api_or_packet_fetch(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/branch'}), self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.verifications, 0)

    def test_foreign_origin_does_not_fall_back_under_false_identity(self):
        self.run['head_repository']['full_name'] = 'fork/finite'
        with self.assertRaisesRegex(ValueError, 'trusted main build'): self.execute()
        self.assertEqual(self.dispatched, [])

    def test_build_workflow_exposes_request_marker_and_validates_it(self):
        import yaml
        document = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        events = document.get('on', document.get(True))
        self.assertIn('decision_request', events['workflow_dispatch']['inputs'])
        self.assertIn('[decision:', document['run-name'])
        validation = next(step for step in document['jobs']['impact']['steps'] if step.get('name') == 'Validate decision reconciliation request')
        self.assertIn('DECISION_REQUEST', validation['env'])
        self.assertIn('^[0-9a-f]{64}$', validation['run'])
        self.assertNotIn('${{', validation['run'])


if __name__ == '__main__':
    unittest.main()
