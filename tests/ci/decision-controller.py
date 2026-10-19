#!/usr/bin/env python3
"""Controller trust boundaries: authoritative archives, current rules and inert summaries."""
import copy
import importlib.util
import contextlib
import io
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import decision_controller as mod

HEAD = 'a' * 40
RUN = {'id': 7, 'path': '.github/workflows/build.yml', 'event': 'push', 'head_branch': 'main',
       'status': 'completed', 'conclusion': 'failure', 'head_repository': {'full_name': mod.REPOSITORY},
       'head_sha': HEAD, 'run_attempt': 2, 'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T02:00:00Z'}
ORIGIN = {'repository': mod.REPOSITORY, 'workflow': 'build.yml', 'runId': 7,
          'runAttempt': 2, 'headSha': HEAD, 'artifacts': []}


def artifacts():
    return [{'id': i, 'name': f'security-{profile}-7-2', 'expired': False,
             'workflow_run': {'id': 7, 'head_sha': HEAD}, 'digest': 'sha256:' + str(i) * 64,
             'size_in_bytes': 100, 'created_at': '2026-01-01T01:00:00Z'}
            for i, profile in enumerate(mod.PROFILES, 1)]


def rules(app_id=123):
    return [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [
        {'context': 'Maintainer decision authority', 'integration_id': app_id}]}},
        {'type': 'merge_queue', 'parameters': {'max_entries_to_build': 1, 'max_entries_to_merge': 1}}]


def proposal():
    origin = copy.deepcopy(ORIGIN)
    origin['artifacts'] = [{k: a[k] for k in ('id', 'name', 'digest')} for a in artifacts()]
    return {'schema': 1, 'kind': 'security-findings', 'payload': {
        'profiles': list(mod.PROFILES), 'findings': [], 'disposition': 'accepted', 'supersedes': [],
        'rationale': 'Human review required', 'packet': {'reference': 'ghcr.io/closure-labs/finite-decisions@sha256:' + 'f' * 64, 'sha256': 'a' * 64, 'producer': origin}}}


class Controller(unittest.TestCase):
    def test_interrupted_proposal_creation_reuses_only_identical_branch(self):
        import release_set
        document = proposal()
        path = mod.authority.proposal_path(document)
        with mock.patch.object(release_set.GitHubClient, 'api', return_value={'object': {'sha': HEAD}}), \
                mock.patch.object(mod.authority, 'document_at', return_value=document), \
                mock.patch.object(mod, 'api') as mutation:
            mod.proposal_branch(document, path, 'automation/decision-fixture')
            mutation.assert_not_called()
        with mock.patch.object(release_set.GitHubClient, 'api', return_value={'object': {'sha': HEAD}}), \
                mock.patch.object(mod.authority, 'document_at', return_value={'forged': True}), \
                mock.patch.object(mod, 'api') as mutation:
            with self.assertRaisesRegex(ValueError, 'differs'):
                mod.proposal_branch(document, path, 'automation/decision-fixture')
            mutation.assert_not_called()

    def test_release_pr_includes_scan_counts_and_vulnerability_links(self):
        from security_decisions import normalize_findings
        scan = {'status': 'pass', 'observations': [{
            'component': 'pkg:rpm/fedora/example@1', 'advisory': 'CVE-2026-12345',
            'aliases': [], 'severity': 'Unknown', 'knownExploited': False,
            'locations': ['/usr/bin/example'], 'locationCoverage': 'complete', 'fixVersions': []}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'findings.json').write_text(json.dumps(normalize_findings(scan, 'finite')))
            rendered = mod.release_scan_summary(directory)
            self.assertIn('Unknown: 1', rendered)
            self.assertIn('https://nvd.nist.gov/vuln/detail/CVE-2026-12345', rendered)
            self.assertIn('finite-dev | 0', rendered)
            self.assertIn('risk acceptance is verified separately', rendered)

    def test_completed_failed_build_can_supply_scans_but_forks_and_prs_cannot(self):
        with mock.patch.object(mod, 'api', return_value=RUN):
            self.assertEqual(mod.producer(7), ORIGIN)
        for field, value in (('event', 'pull_request'), ('head_branch', 'feature'),
                             ('head_repository', {'full_name': 'attacker/finite'}), ('run_attempt', 0), ('id', 8)):
            run = {**RUN, field: value}
            with mock.patch.object(mod, 'api', return_value=run), self.assertRaises(ValueError):
                mod.producer(7)

    def test_exact_complete_unexpired_same_attempt_artifacts(self):
        self.assertEqual(set(mod.artifacts_for(ORIGIN, artifacts())), set(mod.PROFILES))
        for change in ({'expired': True}, {'name': 'security-finite-7-1'},
                       {'workflow_run': {'id': 9, 'head_sha': HEAD}}, {'digest': 'bad'}, {'size_in_bytes': 0}):
            values = artifacts()
            values[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                mod.artifacts_for(ORIGIN, values)
        with self.assertRaises(ValueError):
            mod.artifacts_for(ORIGIN, artifacts()[:1])
        with self.assertRaises(ValueError):
            mod.artifacts_for(ORIGIN, artifacts() + artifacts()[:1])

    def test_live_app_bound_rule_and_single_pr_queue_are_mandatory(self):
        with mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_APP_ID': '123'}), mock.patch.object(mod, 'api', return_value=rules()):
            self.assertEqual(mod.require_live_authority_rule(), 123)
        for value in (rules(999), [], rules()[:1], [rules()[0], {'type': 'merge_queue', 'parameters': {'max_entries_to_build': 2, 'max_entries_to_merge': 1}}]):
            with mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_APP_ID': '123'}), mock.patch.object(mod, 'api', return_value=value), self.assertRaises(ValueError):
                mod.require_live_authority_rule()
        with mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_APP_ID': ''}), self.assertRaises(ValueError):
            mod.require_live_authority_rule()

    def test_unconfigured_rules_prevent_all_proposal_mutation(self):
        with mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'api') as api, mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_APP_ID': ''}):
            with self.assertRaises(ValueError):
                mod.propose(proposal())
            api.assert_not_called()

    def test_historical_scan_clock_binds_to_github_upload(self):
        with mock.patch.object(mod, 'api', return_value=RUN):
            window = mod.producer_window(ORIGIN)
        value = mod.artifact_clock(artifacts()[0], window)
        self.assertEqual(value.isoformat(), '2026-01-01T01:00:00+00:00')
        for when in ('2025-12-31T23:00:00Z', '2026-01-01T03:00:00Z', '2026-01-01T01:00:00'):
            with self.assertRaises(ValueError):
                mod.artifact_clock({**artifacts()[0], 'created_at': when}, window)

    def test_native_evaluation_asof_authenticated_upload_and_future_timestamp_rejected(self):
        evaluate = mock.Mock(return_value={'status': 'complete'})
        policy = SimpleNamespace(load_policy=lambda path: {}, read_manifests=lambda path: {},
                                 production_baseline=lambda *args: {}, read_baseline=lambda path: {},
                                 evaluate=evaluate, timestamp=lambda v: datetime.fromisoformat(v.replace('Z', '+00:00')))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        upload = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(mod, 'module', return_value=policy):
            directory = Path(temporary)
            for name, value in {'security-result.json': {'image': 'immutable', 'status': 'complete', 'scannerHealth': 'healthy'}, 'sbom.syft.json': {},
                                'database-coverage.json': {}, 'vulnerabilities.json': {'descriptor': {'timestamp': '2026-01-01T00:30:00Z'}}}.items():
                (directory / name).write_text(json.dumps(value))
            mod.native_result(directory, upload, start)
            self.assertEqual(evaluate.call_args.kwargs['now'], upload)
            (directory / 'vulnerabilities.json').write_text(json.dumps({'descriptor': {'timestamp': '2026-01-01T01:30:00Z'}}))
            with self.assertRaises(ValueError):
                mod.native_result(directory, upload, start)

    def packet_validation(self, forged=False, extra=False):
        document = proposal()
        def extract(artifact, directory):
            directory.mkdir()
            (directory / 'native.json').write_text('authentic GitHub archive bytes')
        def fetch(reference, directory, expected):
            directory.mkdir()
            for profile in mod.PROFILES:
                target = directory / profile
                target.mkdir()
                (target / 'native.json').write_text('forged bytes' if forged else 'authentic GitHub archive bytes')
            files = {f'{p}/native.json': values for p in mod.PROFILES
                     for _, values in mod.decision_packets.inventory(directory / p).items()}
            if extra:
                (directory / 'injected.json').write_text('{}')
                files['injected.json'] = {'size': 2, 'sha256': 'b' * 64}
            return {'producer': document['payload']['packet']['producer'], 'files': files}
        window = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
        with mock.patch.object(mod, 'producer', return_value=ORIGIN), mock.patch.object(mod, 'collection', return_value=artifacts()), \
                mock.patch.object(mod, 'producer_window', return_value=window), \
                mock.patch.object(mod, 'extract_artifact', side_effect=extract), \
                mock.patch.object(mod, 'native_result', return_value={'status': 'complete', 'scannerHealth': 'healthy', 'observations': []}), \
                mock.patch.object(mod.decision_packets, 'fetch', side_effect=fetch):
            return mod.validate_proposal_packet(document)

    def test_packet_bytes_must_match_actual_archives_not_just_metadata(self):
        self.packet_validation()
        with self.assertRaises(ValueError):
            self.packet_validation(forged=True)
        with self.assertRaises(ValueError):
            self.packet_validation(extra=True)

    def test_single_profile_consolidation_dispatches_both_once(self):
        jobs = [{**{'run_id': 7, 'run_attempt': 2, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success'},
                 'name': f'Publish (finite) / {name}'} for name in ('build / build', 'security')]
        window = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
        with mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'require_live_authority_rule'), \
                mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                mock.patch.object(mod, 'collection', side_effect=[jobs, artifacts()[:1]]), \
                mock.patch.object(mod, 'producer_window', return_value=window), \
                mock.patch.object(mod, 'extract_artifact'), \
                mock.patch.object(mod, 'native_result', return_value={'status': 'complete', 'scannerHealth': 'healthy', 'observations': []}), \
                mock.patch('security_admission.verify', return_value={'status': 'review-required'}), \
                mock.patch.object(mod, 'api') as api:
            result = mod.request_consolidation(ORIGIN)
            self.assertEqual(result['status'], 'consolidation-required')
            self.assertEqual(api.call_args.args[1], 'POST')
            self.assertEqual(api.call_args.args[2]['inputs'], {'target': 'automatic', 'reconcile': 'false'})
            api.assert_called_once()
        jobs.append({**jobs[0], 'name': 'Publish (finite-dev) / build / build', 'conclusion': 'failure'})
        with mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'require_live_authority_rule'), \
                mock.patch.object(mod, 'producer', return_value=ORIGIN), mock.patch.object(mod, 'collection', return_value=jobs), \
                mock.patch.object(mod, 'api') as api, self.assertRaises(ValueError):
            mod.request_consolidation(ORIGIN)
        api.assert_not_called()

    def test_covered_single_profile_reuse_does_not_dispatch_another_build(self):
        jobs = [{'run_id': 7, 'run_attempt': 2, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success',
                 'name': f'Publish (finite) / {name}'} for name in ('build / build', 'security')]
        window = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 2, tzinfo=timezone.utc))
        with mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'require_live_authority_rule'), \
                mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                mock.patch.object(mod, 'collection', side_effect=[jobs, artifacts()[:1]]), \
                mock.patch.object(mod, 'producer_window', return_value=window), mock.patch.object(mod, 'extract_artifact'), \
                mock.patch.object(mod, 'has_reused_evidence', return_value=True), \
                mock.patch.object(mod, 'native_result', return_value={'status': 'complete', 'scannerHealth': 'healthy', 'observations': []}) as native, \
                mock.patch('security_admission.verify', return_value={'status': 'covered'}), mock.patch.object(mod, 'api') as api:
            result = mod.request_consolidation(ORIGIN)
            self.assertEqual(result['status'], 'covered')
            self.assertFalse(result['proposalRequired'])
            self.assertEqual(native.call_args.kwargs['profile'], 'finite')
            self.assertEqual(len(native.call_args.args), 1)
            api.assert_not_called()

    def test_collect_does_not_mistake_full_build_missing_scan_for_valid_partial_packet(self):
        with mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                mock.patch.object(mod, 'collection', return_value=artifacts()[:1]), self.assertRaises(mod.ConsolidationRequired):
            mod.collect(7, Path('/unused'))

    def test_covered_and_pending_skip_registry_upload_and_new_pr(self):
        spec = importlib.util.spec_from_file_location('controller_cli_test', ROOT / 'scripts/ci/decision-controller.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        for statuses, pending in (({'finite': {'status': 'covered'}, 'finite-dev': {'status': 'covered'}}, None),
                                  ({'finite': {'status': 'review-required'}, 'finite-dev': {'status': 'covered'}}, {'status': 'pending-review'})):
            with mock.patch.object(sys, 'argv', ['decision-controller.py', 'collect', '--run', '7', '--packet-directory', '/unused']), \
                    mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'collect', return_value=(ORIGIN, [])), \
                    mock.patch.object(mod, 'current_admission', return_value=statuses), mock.patch.object(mod, 'decision_ids', return_value=[]), \
                    mock.patch.object(mod, 'pending_proposal', return_value=pending), mock.patch.object(cli.decision_packets, 'push') as push, \
                    mock.patch.object(mod, 'propose') as propose, contextlib.redirect_stdout(io.StringIO()) as output:
                cli.main()
                push.assert_not_called()
                propose.assert_not_called()
                self.assertIn('covered' if pending is None else 'pending-review', output.getvalue())

    def test_pending_snapshot_deduplicates_without_authorizing_publication(self):
        document = proposal()
        path = mod.authority.proposal_path(document)
        pull = {'number': 12, 'user': {'type': 'Bot', 'login': 'finite-review[bot]'}, 'state': 'open',
                'base': {'ref': 'main'}, 'head': {'sha': HEAD, 'repo': {'full_name': mod.REPOSITORY}},
                'html_url': 'https://github.com/closure-labs/finite/pull/12'}
        files = [{'filename': path, 'status': 'added'}]
        with mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_BOT_LOGIN': 'finite-review[bot]'}), \
                mock.patch.object(mod, 'collection', side_effect=[[pull], files]), \
                mock.patch.object(mod.authority, 'document_at', return_value=document):
            pending = mod.pending_proposal([], [])
            self.assertEqual(pending['status'], 'pending-review')
            self.assertFalse(pending['authorizesPublication'])
        with mock.patch.dict(mod.os.environ, {'FINITE_REVIEW_BOT_LOGIN': 'finite-review[bot]'}), \
                mock.patch.object(mod, 'collection', side_effect=[[pull], files]), \
                mock.patch.object(mod.authority, 'document_at', return_value=document):
            self.assertIsNone(mod.pending_proposal([], ['b' * 64]))

    def test_uncovered_reused_scan_requests_fresh_full_build_without_resume(self):
        with mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'require_live_authority_rule'), \
                mock.patch.object(mod, 'producer', return_value=ORIGIN), mock.patch.object(mod, 'api') as api:
            result = mod.request_fresh_scans(ORIGIN)
            self.assertEqual(result['status'], 'fresh-scans-required')
            self.assertFalse(result['authorizesPublication'])
            self.assertEqual(api.call_args.args[2]['inputs'], {'target': 'automatic', 'reconcile': 'false'})
            self.assertNotIn('resume_run', api.call_args.args[2]['inputs'])
            api.assert_called_once()

    def test_reused_presence_only_signals_refresh_and_cannot_grant_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertFalse(mod.has_reused_evidence(directory))
            (directory / 'reuse-provenance.json').write_text('{"approved":true,"reviewer":"forged"}')
            self.assertTrue(mod.has_reused_evidence(directory))

    def test_uncovered_reused_cli_refreshes_before_packet_upload_or_proposal(self):
        spec = importlib.util.spec_from_file_location('reused_controller_cli_test', ROOT / 'scripts/ci/decision-controller.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(sys, 'argv', ['decision-controller.py', 'collect', '--run', '7', '--packet-directory', '/unused']), \
                mock.patch.object(mod, 'trusted_context'), mock.patch.object(mod, 'collect', return_value=(ORIGIN, [])), \
                mock.patch.object(mod, 'current_admission', return_value={'finite': {'status': 'review-required'}, 'finite-dev': {'status': 'covered'}}), \
                mock.patch.object(mod, 'has_reused_evidence', return_value=True), \
                mock.patch.object(mod, 'request_fresh_scans', return_value={'status': 'fresh-scans-required'}) as fresh, \
                mock.patch.object(cli.decision_packets, 'push') as push, mock.patch.object(mod, 'propose') as propose, \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main()
            fresh.assert_called_once_with(ORIGIN)
            push.assert_not_called()
            propose.assert_not_called()

    def test_scan_summary_cannot_introduce_markdown_commands_or_mentions(self):
        document = proposal()
        document['payload']['rationale'] = '<script>\n/approve\n@maintainer [link](https://attacker) `code` | table'
        text = mod.summary(document)
        self.assertNotIn('<script>', text)
        self.assertNotIn('\n/approve', text)
        self.assertNotIn('@maintainer', text)
        self.assertNotIn('[link]', text)


if __name__ == '__main__':
    unittest.main()
