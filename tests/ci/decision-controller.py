#!/usr/bin/env python3
"""Controller trust boundaries: authoritative archives, current rules and inert summaries."""
import copy
import importlib.util
import contextlib
import io
import hashlib
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
    def test_security_summary_exposes_both_profiles_and_prioritizes_review_risks(self):
        from security_decisions import normalize_findings
        def observation(advisory, severity, known=False):
            return {'component': 'pkg:rpm/fedora/example@1', 'advisory': advisory,
                    'aliases': [], 'severity': severity, 'cvss': 9.8 if severity == 'Critical' else None,
                    'knownExploited': known, 'locations': ['/usr/bin/example'],
                    'locationCoverage': 'complete', 'fixVersions': []}
        low = [observation(f'CVE-2026-{10000 + i}', 'Low') for i in range(155)]
        known = observation('GHSA-abcd-1234-efgh', 'Medium', True)
        critical = observation('CVE-2026-99999', 'Critical')
        document = proposal()
        document['payload']['findings'] = normalize_findings(
            {'status': 'pass', 'observations': low + [known]}, 'finite') + normalize_findings(
            {'status': 'pass', 'observations': [critical]}, 'finite-dev')
        rendered = mod.summary(document)
        self.assertIn('| finite | Medium: 1, Low: 155 |', rendered)
        self.assertIn('| finite-dev | Critical: 1 |', rendered)
        self.assertIn('Critical | 9.8 | No', rendered)
        advisory = 'https://github.com/advisories/GHSA-abcd-1234-efgh'
        cve = 'https://nvd.nist.gov/vuln/detail/CVE-2026-99999'
        self.assertLess(rendered.index(advisory), rendered.index(cve))
        self.assertNotIn('CVE-2026-10154', rendered)
        self.assertIn('Showing 150 of 157 findings', rendered)
        self.assertIn('Files changed tab and immutable scan packet', rendered)

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
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(mod, 'module', return_value=policy), \
                mock.patch.object(mod, 'native_observation_policy', return_value={}):
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

    def no_image_jobs(self):
        return [{'name': name, 'run_id': 7, 'run_attempt': 2, 'head_sha': HEAD,
                 'status': 'completed', 'conclusion': conclusion} for name, conclusion in (
            ('Select checks', 'success'), ('Documentation checks', 'success'),
            ('Nix and runtime contracts', 'success'), ('CI gate', 'success'),
            ('Validate (${{ matrix.profile }})', 'skipped'),
            ('Publish (${{ matrix.profile }})', 'skipped'))]

    def test_collect_skips_only_authenticated_no_image_build(self):
        with mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                mock.patch.object(mod, 'collection', side_effect=[[], self.no_image_jobs()]) as inventory, \
                mock.patch.object(mod, 'extract_artifact') as extract, \
                self.assertRaises(mod.NoImageWork):
            mod.collect(7, Path('/unused'))
        self.assertIn('/attempts/2/jobs', inventory.call_args.args[0])
        extract.assert_not_called()

    def test_no_image_detection_rejects_incomplete_failed_or_mismatched_jobs(self):
        mutations = (
            lambda jobs: jobs.clear(),
            lambda jobs: jobs.pop(),
            lambda jobs: jobs[0].update(run_id=8),
            lambda jobs: jobs[0].update(run_attempt=1),
            lambda jobs: jobs[0].update(head_sha='b' * 40),
            lambda jobs: jobs[0].update(status='in_progress'),
            lambda jobs: jobs[3].update(conclusion='failure'),
            lambda jobs: jobs[-1].update(conclusion='success'),
            lambda jobs: jobs.append(copy.deepcopy(jobs[0])),
            lambda jobs: jobs.append({**jobs[0], 'name': 'Publish (finite) / security'}),
        )
        for mutation in mutations:
            jobs = self.no_image_jobs()
            mutation(jobs)
            with self.subTest(mutation=mutation), mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                    mock.patch.object(mod, 'collection', side_effect=[[], jobs]):
                try:
                    mod.collect(7, Path('/unused'))
                except mod.NoImageWork:
                    self.fail('Incomplete or image-producing build was incorrectly ignored')
                except ValueError:
                    pass
                else:
                    self.fail('Missing native scans must fail closed')

    def test_no_image_detection_never_hides_wrong_attempt_or_partial_scan_archives(self):
        for values in ([{**artifacts()[0], 'name': 'security-finite-7-1'}], artifacts()[:1]):
            with self.subTest(values=values), mock.patch.object(mod, 'producer', return_value=ORIGIN), \
                    mock.patch.object(mod, 'collection', return_value=values), \
                    mock.patch.object(mod, 'skipped_image_work') as skipped, self.assertRaises(ValueError):
                mod.collect(7, Path('/unused'))
            skipped.assert_not_called()
        published = {**ORIGIN, 'workflow': 'image-security.yml'}
        with mock.patch.object(mod, 'producer', return_value=published), \
                mock.patch.object(mod, 'collection', return_value=[]), \
                mock.patch.object(mod, 'skipped_image_work') as skipped, self.assertRaises(ValueError):
            mod.collect(7, Path('/unused'))
        skipped.assert_not_called()

    def test_no_image_cli_returns_success_without_proposal_or_dispatch(self):
        spec = importlib.util.spec_from_file_location('controller_cli_no_image', ROOT / 'scripts/ci/decision-controller.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch.object(sys, 'argv', ['decision-controller.py', 'collect', '--run', '7']), \
                mock.patch.object(mod, 'trusted_context'), \
                mock.patch.object(mod, 'collect', side_effect=mod.NoImageWork(ORIGIN)), \
                mock.patch.object(mod, 'current_admission') as admission, \
                mock.patch.object(mod, 'request_consolidation') as dispatch, \
                mock.patch.object(mod, 'propose') as propose, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'no-image-work')
        self.assertFalse(result['authorizesPublication'])
        self.assertFalse(result['proposalRequired'])
        admission.assert_not_called()
        dispatch.assert_not_called()
        propose.assert_not_called()
        workflow = (ROOT / '.github/workflows/decision-proposals.yml').read_text()
        self.assertLess(workflow.index('decision-controller.py collect'), workflow.index('reconcile-decisions.py'))

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


class BootstrapNativeObservations(unittest.TestCase):
    """Exercise the real native evaluator and publisher receipt before mode cutover."""
    def setUp(self):
        self.policy = mod.module('bootstrap_real_security_policy', ROOT / 'scripts/bluebuild/security-policy.py')
        self.source = mod.load_json(ROOT / 'automation/security/image-policy.json')
        self.now = datetime.now(timezone.utc)
        self.stamp = self.now.isoformat()

    def bundle(self, directory, profile):
        foundation = 'bluefin' if profile == 'finite' else 'bluefin-dx'
        base = 'ghcr.io/ublue-os/' + foundation + '@sha256:' + 'c' * 64
        trust_path = ROOT / 'sources/bluefin-trust.json'
        trust = json.loads(trust_path.read_text())
        trust_hash = hashlib.sha256(trust_path.read_bytes()).hexdigest()
        baseline = {'schema': 1, 'status': 'verified', 'profile': profile, 'sourceRevision': HEAD,
                    'buildIdentity': 'v1:' + 'b' * 64, 'baseImage': base, 'trustPolicySha256': trust_hash}
        config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.revision': HEAD, 'io.finite.profile': profile,
            'io.finite.build-inputs': baseline['buildIdentity'],
            'org.opencontainers.image.base.name': base.replace('@', ':stable@'),
            'org.opencontainers.image.base.digest': 'sha256:' + 'c' * 64}}}
        raw_config = json.dumps(config)
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                               'digest': 'sha256:' + hashlib.sha256(raw_config.encode()).hexdigest(),
                               'size': len(raw_config.encode())}}
        raw_manifest = json.dumps(manifest)
        digest = 'sha256:' + hashlib.sha256(raw_manifest.encode()).hexdigest()
        image = baseline['image'] = 'ghcr.io/closure-labs/finite@' + digest
        sbom = {'source': {'type': 'image', 'metadata': {'manifestDigest': digest}},
                'distro': {'id': 'bluefin', 'versionID': '44'},
                'artifacts': [{'id': str(i), 'type': 'rpm', 'foundBy': 'rpm-db-cataloger',
                               'name': 'package-' + str(i), 'version': '1'} for i in range(100)]}
        sbom['artifacts'][0].update(name='fedora-release-common', version='44-18')
        scan = {'source': {'type': 'image', 'target': {'manifestDigest': digest}},
                'distro': {'name': 'fedora', 'version': '44'},
                'descriptor': {'name': 'grype', 'version': '0.112.0', 'timestamp': self.stamp,
                               'db': {'status': {'valid': True, 'built': self.stamp},
                                      'providers': {'fedora': {'captured': self.stamp}, 'kev': {'captured': self.stamp}}}},
                'matches': [{'vulnerability': {'id': 'CVE-2026-1234', 'severity': 'Low',
                                              'fix': {'state': 'fixed', 'versions': ['2']},
                                              'knownExploited': [], 'cvss': [{'metrics': {'baseScore': 3.1}}]},
                             'relatedVulnerabilities': [{'id': 'GO-2026-6604', 'severity': 'Critical',
                                                         'cvss': [{'metrics': {'baseScore': 9.8}}]}],
                             'artifact': {'id': 'example', 'purl': 'pkg:rpm/fedora/example@1',
                                          'locations': [{'path': '/usr/bin/example'}]}}]}
        coverage = [{'vulnerability': {'provider': 'fedora'}, 'packages': [
            {'os': {'name': 'fedora', 'version': '44'}, 'package': {'name': 'openssl', 'ecosystem': 'rpm'}}]}]
        publisher = {'schema': 1, 'repository': 'closure-labs/finite', 'sourceRevision': HEAD,
                     'trustPolicySha256': trust_hash,
                     'verified': [{'image': base, 'keySha256': trust['keySha256'], 'signatureFormat': 'legacy'}]}
        manifests = {'parent': raw_manifest, 'child': None, 'config': raw_config}
        legacy = copy.deepcopy(self.source)
        if legacy.get('mode') == 'maintainer-decision':
            legacy.update(mode='desktop-critical-only', maxExceptionDays=30,
                          blockedFixableSeverities=['Critical'], blockKnownExploited=False,
                          exceptions=[], seriousAdvisories=[], reviewedDispositions=[], releaseBlockers=[])
        original = self.policy.evaluate(sbom, scan, image, legacy, now=self.now,
                                        database_coverage=coverage, manifests=manifests, approved_baseline=baseline)
        self.assertNotIn('cvss', original['observations'][0])
        for name, value in {'image-manifest.json': manifest, 'image-config.json': config,
                            'approved-baseline.json': baseline, 'upstream-verification.json': publisher,
                            'security-result.json': original, 'sbom.syft.json': sbom,
                            'vulnerabilities.json': scan, 'database-coverage.json': coverage}.items():
            (directory / name).write_text(json.dumps(value))
        return image, sbom, scan, coverage, baseline, manifests

    def test_legacy_baseline_has_identical_full_risk_ceilings_after_cutover_for_both_profiles(self):
        checked = (ROOT / 'automation/security/image-policy.json').read_bytes()
        from security_decisions import normalize_findings
        for profile in ('finite', 'finite-dev'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                image, sbom, scan, coverage, baseline, manifests = self.bundle(directory, profile)
                initial = mod.native_result(directory, self.now, self.now, profile)
                health = {key: self.source[key] for key in self.policy.DECISION_FIELDS - {'mode'}}
                health['mode'] = self.policy.DECISION_MODE
                eventual = self.policy.evaluate(sbom, scan, image, health, now=self.now,
                                                database_coverage=coverage, manifests=manifests, approved_baseline=baseline)
                normalized = normalize_findings(initial, profile)
                self.assertEqual(normalized, normalize_findings(eventual, profile))
                self.assertEqual(normalized[0]['severity'], 'Critical')
                self.assertEqual(normalized[0]['cvss'], 9.8)
                self.assertEqual(initial['status'], 'complete')
                self.assertNotIn('admission', initial)
        self.assertEqual((ROOT / 'automation/security/image-policy.json').read_bytes(), checked)

    def test_legacy_ai_fields_cannot_block_or_approve_fresh_native_assessment(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'policy.json'
            legacy = copy.deepcopy(self.source)
            legacy['mode'] = 'desktop-critical-only'
            legacy.update(reviewedDispositions=[{'expiresAt': '2000-01-01T00:00:00Z'}],
                          confirmedDesktopRisks=[{'reviewedBy': 'AI', 'broken': True}],
                          releaseBlockers=[{'reason': 'unvalidated legacy claim'}])
            path.write_text(json.dumps(legacy))
            projected = mod.native_observation_policy(self.policy, path)
            self.assertEqual(set(projected), self.policy.DECISION_FIELDS)
            self.assertEqual(projected['mode'], self.policy.DECISION_MODE)
            self.assertNotIn('reviewedDispositions', projected)
            self.assertEqual(projected['requiredProviders'], self.source['requiredProviders'])

    def test_health_config_projection_fails_closed_for_missing_invalid_or_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'policy.json'
            for change in ({'maxDatabaseAgeHours': 0}, {'requiredProviders': ['fedora']}, {'schema': True},
                           {'minimumRpmPackages': False}, {'mode': 'unknown'}, {'unknownHealthControl': True}):
                path.write_text(json.dumps({**self.source, **change}))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    mod.native_observation_policy(self.policy, path)
            missing = copy.deepcopy(self.source)
            del missing['coverageProbePackage']
            path.write_text(json.dumps(missing))
            with self.assertRaises(ValueError):
                mod.native_observation_policy(self.policy, path)

    def test_native_health_original_status_provenance_and_cvss_errors_cannot_be_accepted(self):
        changes = [('vulnerabilities.json', lambda value: value['descriptor']['db']['status'].update(valid=False)),
                   ('vulnerabilities.json', lambda value: value['descriptor']['db']['providers'].pop('kev')),
                   ('vulnerabilities.json', lambda value: value['matches'][0]['relatedVulnerabilities'][0].update(cvss=[{'metrics': {'baseScore': 11}}])),
                   ('security-result.json', lambda value: value.update(status='scanner-error')),
                   ('security-result.json', lambda value: value.update(status='complete', scannerHealth='unknown')),
                   ('upstream-verification.json', lambda value: value.update(trustPolicySha256='f' * 64)),
                   ('image-config.json', lambda value: value.update(architecture='arm64'))]
        for name, mutate in changes:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.bundle(directory, 'finite')
                path = directory / name
                value = json.loads(path.read_text())
                mutate(value)
                path.write_text(json.dumps(value))
                with self.assertRaises((ValueError, KeyError)):
                    mod.native_result(directory, self.now, self.now, 'finite')


class PolicyCutover(unittest.TestCase):
    PATH = 'automation/security/image-policy.json'
    BOT = 'cl-decider[bot]'
    MAIN = 'b' * 40

    def setUp(self):
        import release_set
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict('os.environ', FINITE_REVIEW_BOT_LOGIN=self.BOT))
        policy = mod.module('fixture_cutover_policy', ROOT / 'scripts/bluebuild/security-policy.py')
        self.config = mod.native_observation_policy(policy, ROOT / self.PATH)
        # Exercise the historical bootstrap even after production activates it.
        # The active-mode no-op has its own explicit fixture below.
        self.source = policy.load_policy(ROOT / 'tests/fixtures/legacy-image-security-policy.json')
        self.trust = self.stack.enter_context(mock.patch.object(mod, 'trusted_context'))
        self.binding = self.stack.enter_context(mock.patch.object(mod, 'require_live_authority_rule'))
        self.stack.enter_context(mock.patch.object(mod.authority, 'validate_context'))
        self.load = self.stack.enter_context(mock.patch.object(mod, 'load_json', return_value=self.source))
        self.collect = self.stack.enter_context(mock.patch.object(mod, 'collect', return_value=(ORIGIN, [])))
        self.admit = self.stack.enter_context(mock.patch.object(mod, 'current_admission', return_value={p: {'status': 'covered'} for p in mod.PROFILES}))
        self.document = self.stack.enter_context(mock.patch.object(mod.authority, 'document_at', side_effect=lambda api, repo, path, sha: self.source if sha == self.MAIN else self.config))
        self.branch = self.stack.enter_context(mock.patch.object(release_set.GitHubClient, 'api', return_value=None))
        self.collections = self.stack.enter_context(mock.patch.object(mod, 'collection', return_value=[]))
        self.commands = self.stack.enter_context(mock.patch.object(mod.subprocess, 'run'))
        self.calls = []
        self.pull = {'number': 12, 'state': 'open', 'draft': True, 'changed_files': 1,
                     'html_url': 'https://github.com/closure-labs/finite/pull/12',
                     'user': {'type': 'Bot', 'login': self.BOT},
                     'base': {'ref': 'main', 'repo': {'full_name': mod.REPOSITORY}},
                     'head': {'sha': HEAD, 'repo': {'full_name': mod.REPOSITORY}}}
        self.files = [{'filename': self.PATH, 'status': 'modified'}]
        self.comparison = {'total_commits': 1, 'commits': [{'sha': HEAD}], 'files': self.files}
        def github(path, method='GET', body=None):
            self.calls.append((path, method, body))
            if path.endswith('git/ref/heads/main'): return {'object': {'sha': self.MAIN}}
            if '/compare/' in path: return self.comparison
            if path.endswith('?recursive=1'): return {'truncated': False, 'tree': [{'path': self.PATH, 'type': 'blob', 'mode': '100644'}]}
            if path.endswith('git/commits/' + self.MAIN): return {'tree': {'sha': 'base-tree'}}
            if path.endswith('/git/trees') and method == 'POST': return {'sha': 'new-tree'}
            if path.endswith('/git/commits') and method == 'POST': return {'sha': HEAD}
            if path.endswith('/git/refs') and method == 'POST': return {}
            if path.endswith('/pulls') and method == 'POST': return self.pull
            if path.endswith('/pulls/12'): return self.pull
            raise AssertionError((path, method, body))
        self.api = self.stack.enter_context(mock.patch.object(mod, 'api', side_effect=github))

    def mutations(self):
        return [call for call in self.calls if call[1] != 'GET']

    def existing(self):
        self.branch.return_value = {'object': {'sha': HEAD}}
        self.collections.side_effect = lambda path: self.files if path.endswith('/files') else [self.pull]

    def test_creates_only_fixed_health_policy_and_queues_without_granting_approval(self):
        result = mod.propose_cutover(7, '/tmp/native')
        self.assertEqual(result['status'], 'pending-review')
        self.assertFalse(result['authorizesPublication'])
        self.assertFalse(result['policyChanged'])
        tree = next(body for path, method, body in self.mutations() if path.endswith('/git/trees'))
        self.assertEqual(len(tree['tree']), 1)
        entry = tree['tree'][0]
        self.assertEqual(entry['path'], self.PATH)
        self.assertEqual(json.loads(entry['content']), self.config)
        self.assertEqual(set(json.loads(entry['content'])), set(self.config))
        self.assertEqual(self.config['mode'], 'maintainer-decision')
        pr = next(body for path, method, body in self.mutations() if path.endswith('/pulls'))
        self.assertTrue(pr['draft'])
        self.assertIn('grants no approval', pr['body'])
        self.assertIn('must approve this exact PR head', pr['body'])
        self.assertIn('--match-head-commit', self.commands.call_args.args[0])
        self.assertIn(HEAD, self.commands.call_args.args[0])

    def test_missing_baseline_or_technical_failure_prevents_every_mutation(self):
        for profile in mod.PROFILES:
            with self.subTest(profile=profile):
                self.admit.return_value = {p: {'status': 'review-required' if p == profile else 'covered'} for p in mod.PROFILES}
                with self.assertRaisesRegex(ValueError, 'both profiles'):
                    mod.propose_cutover(7, '/tmp/native')
                self.assertEqual(self.mutations(), [])
                self.commands.assert_not_called()
        self.collect.side_effect = ValueError('native database stale')
        with self.assertRaisesRegex(ValueError, 'database stale'):
            mod.propose_cutover(7, '/tmp/native')
        self.assertEqual(self.mutations(), [])

    def test_incomplete_profile_admission_and_changed_main_policy_cannot_create_pr(self):
        self.admit.return_value = {'finite': {'status': 'covered'}}
        with self.assertRaisesRegex(ValueError, 'both profiles'):
            mod.propose_cutover(7, '/tmp/native')
        self.assertEqual(self.mutations(), [])
        self.admit.return_value = {p: {'status': 'covered'} for p in mod.PROFILES}
        self.document.side_effect = None
        self.document.return_value = self.config
        with self.assertRaisesRegex(ValueError, 'main policy changed'):
            mod.propose_cutover(7, '/tmp/native')
        self.assertEqual(self.mutations(), [])
        self.commands.assert_not_called()

    def test_cutover_rechecks_live_admission_before_any_mutation_or_queue(self):
        covered = {p: {'status': 'covered'} for p in mod.PROFILES}
        revoked = {p: {'status': 'revoked'} for p in mod.PROFILES}
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.existing()
                self.admit.side_effect = [covered, revoked]
                self.calls.clear()
                with self.assertRaisesRegex(ValueError, 'both profiles'):
                    mod.propose_cutover(7, '/tmp/native')
                self.assertEqual(self.mutations(), [])
                self.commands.assert_not_called()

    def test_context_and_bound_check_are_required_before_collect(self):
        for guard in (self.trust, self.binding):
            guard.side_effect = ValueError('untrusted or unbound')
            with self.assertRaisesRegex(ValueError, 'untrusted'):
                mod.propose_cutover(7, '/tmp/native')
            self.collect.assert_not_called()
            self.assertEqual(self.mutations(), [])
            guard.side_effect = None

    def test_active_mode_is_noop(self):
        self.load.return_value = self.config
        with mock.patch.object(mod, 'native_observation_policy', return_value=self.config):
            self.assertEqual(mod.propose_cutover(7, '/tmp/native')['status'], 'already-active')
        self.collect.assert_not_called()
        self.api.assert_not_called()
        self.commands.assert_not_called()

    def test_existing_equivalent_bot_pr_is_reused_without_branch_writes(self):
        self.existing()
        result = mod.propose_cutover(7, '/tmp/native')
        self.assertEqual(result['pullRequest'], self.pull['html_url'])
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.commands.call_count, 2)

    def test_branch_or_pr_divergence_is_rejected_before_ready_or_queue(self):
        cases = ('extra-branch-file', 'incomplete-comparison', 'extra-pr-file', 'wrong-author', 'wrong-base', 'wrong-head', 'wrong-policy')
        for case in cases:
            with self.subTest(case=case):
                self.existing()
                self.calls.clear()
                self.commands.reset_mock()
                with contextlib.ExitStack() as local:
                    if case == 'extra-branch-file':
                        local.enter_context(mock.patch.dict(self.comparison, files=self.files + [{'filename': 'evil.py', 'status': 'added'}]))
                    elif case == 'incomplete-comparison':
                        local.enter_context(mock.patch.dict(self.comparison, total_commits=2))
                    elif case == 'extra-pr-file':
                        local.enter_context(mock.patch.dict(self.pull, changed_files=2))
                    elif case == 'wrong-author':
                        local.enter_context(mock.patch.dict(self.pull, user={'login': 'human', 'type': 'User'}))
                    elif case == 'wrong-base':
                        local.enter_context(mock.patch.dict(self.pull, base={'ref': 'feature'}))
                    elif case == 'wrong-head':
                        local.enter_context(mock.patch.dict(self.pull, head={'sha': 'c' * 40}))
                    elif case == 'wrong-policy':
                        local.enter_context(mock.patch.object(mod.authority, 'document_at', side_effect=lambda api, repo, path, sha: self.source))
                    with self.assertRaises(ValueError):
                        mod.propose_cutover(7, '/tmp/native')
                self.assertEqual(self.mutations(), [])
                self.commands.assert_not_called()

    def test_cli_rejects_incompatible_inputs(self):
        cli = mod.module('fixture_cutover_cli', ROOT / 'scripts/ci/decision-controller.py')
        for extra in ([], ['--kind', 'security-findings'], ['--rationale', 'accept'], ['--disposition', 'rejected'], ['--decision-hash', 'a'*64], ['--proposal', '/tmp/proposal.json']):
            args = ['decision-controller.py', 'propose-cutover'] + ([] if not extra else ['--run', '7']) + extra
            with self.subTest(extra=extra), mock.patch.object(sys, 'argv', args), mock.patch.object(mod, 'propose_cutover') as create:
                with self.assertRaises(ValueError):
                    cli.main()
                create.assert_not_called()

    def test_workflow_requires_explicit_dispatch_and_keeps_default_reconcile(self):
        workflow = (ROOT / '.github/workflows/decision-proposals.yml').read_text()
        self.assertIn('options: [reconcile, propose-cutover]', workflow)
        self.assertIn('default: reconcile', workflow)
        operation = workflow.index('if [[ $DECISION_OPERATION == propose-cutover ]]')
        login = workflow.index('oras login ghcr.io')
        self.assertLess(operation, login)
        block = workflow[operation:login]
        self.assertIn('$GITHUB_EVENT_NAME == workflow_dispatch', block)
        self.assertIn('$PRODUCER_RUN =~ ^[1-9][0-9]*$', block)
        self.assertIn('-z $DECISION_RATIONALE && -z $DECISION_HASH', block)
        self.assertIn('exit 0', block)


if __name__ == '__main__':
    unittest.main()
