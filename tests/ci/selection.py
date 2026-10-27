#!/usr/bin/env python3
"""Exercise change selection and failure propagation at CI boundaries."""
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import impact
import gate
import payloads
import image_identity


class Selection(unittest.TestCase):
    def test_reviewed_host_inputs_skip_images_but_unknown_inputs_remain_conservative(self):
        for path in image_identity.QUALIFICATION_ONLY:
            with self.subTest(path=path):
                self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        for path in ('scripts/bluebuild/new-host-helper.py', 'files/installer/new-hook',
                     '.github/workflows/new-qualification.yml'):
            self.assertEqual(impact.classify([path])['profiles'], sorted(impact.PROFILES))
        mixed = impact.classify(['scripts/bluebuild/unlock-vm.py', 'files/system/shipped-file'])
        self.assertEqual(mixed['profiles'], sorted(impact.PROFILES))
        self.assertTrue(mixed['checks'])

    def test_documentation_and_mixed_changes(self):
        self.assertEqual(impact.classify(['README.md', 'docs/installation.md']), {'checks': False, 'nix': False, 'profiles': []})
        for path in ['files/system/usr/share/finite/finite-logo.png',
                     '.github/workflows/image.yml',
                     'files/scripts/kernel-module-prune.py', 'new-image-input', 'docs-like/file',
                     'automation/security/vulnerability-policy.json', 'sources/bluefin.pub', 'sources/bluefin-trust.json']:
            with self.subTest(path=path):
                self.assertEqual(impact.classify(['README.md', path]), {'checks': True, 'nix': False, 'profiles': sorted(impact.PROFILES)})

    def test_decision_controls_keep_contracts_without_rebuilding_os_images(self):
        paths = ['.github/workflows/codeql.yml', '.github/workflows/decision-proposals.yml', 'scripts/ci/decision-controller.py',
                 'scripts/ci/decision-check.py', '.github/workflows/decision-authority.yml', 'scripts/ci/source_proof.py',
                 'scripts/ci/reconcile-decisions.py',
                 'scripts/ci/decision_controller.py', 'scripts/ci/security_admission.py',
                 'scripts/ci/release_artifact.py', 'scripts/ci/decision_packets.py',
                 'scripts/ci/archive_read.py', 'scripts/ci/publisher_health.py', 'scripts/ci/reconcile-delivery.py',
                 'scripts/ci/devenv_cache.py']
        self.assertEqual(impact.classify(paths), {'checks': True, 'nix': False, 'profiles': []})
        for payload in ('files/system/shipped-file', 'recipes/finite.yml', 'scripts/ci/new-controller.py'):
            with self.subTest(payload=payload):
                expected = ['finite'] if payload.startswith('recipes/') else sorted(impact.PROFILES)
                self.assertEqual(impact.classify([*paths, payload])['profiles'], expected)

    def test_nix_inputs_use_dependency_comparison(self):
        for path in ['VERSION', 'flake.lock', '.github/actions/setup-nix/action.yml',
                     'modules/outputs.nix', 'lib/image-payload.nix',
                     'templates/home-manager/customize.nix', 'lib/domain-catalog.nix']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': True, 'profiles': []})

    def test_read_only_cost_observation_keeps_checks_without_selecting_images(self):
        paths = ['scripts/ci/workflow-costs.py', 'scripts/ci/workflow_costs.py',
                 'scripts/ci/nix_observation.py',
                 'scripts/ci/cost_receipts.py', '.github/workflows/workflow-costs.yml',
                 'scripts/ci/report-release-transport.py', 'scripts/ci/release_transport_benchmark.py']
        for changed in ([path] for path in paths):
            self.assertEqual(impact.classify(changed), {'checks': True, 'nix': False, 'profiles': []})
        self.assertEqual(impact.classify([*paths, 'tests/ci/workflow-costs.py', 'docs/reports.md']),
                         {'checks': True, 'nix': False, 'profiles': []})
        for path, profiles in [('files/system/usr/libexec/finite/guest-check.py', sorted(impact.PROFILES)),
                               ('scripts/ci/new-cost-helper.py', sorted(impact.PROFILES)),
                               ('.github/workflows/new-cost-report.yml', sorted(impact.PROFILES)),
                               ('recipes/finite-dev.yml', ['finite-dev'])]:
            with self.subTest(path=path):
                self.assertEqual(impact.classify([*paths, path]),
                                 {'checks': True, 'nix': False, 'profiles': profiles})
        self.assertEqual(impact.classify([*paths, 'flake.lock']),
                         {'checks': True, 'nix': True, 'profiles': []})

    def test_ci_execution_admission_is_host_only_but_mixed_guest_changes_keep_images(self):
        paths = ['.github/workflows/ci-run-admission.yml', 'scripts/ci/ci-run-admission.py',
                 'automation/github/ci-execution.json', 'tests/ci/ci-run-admission.py']
        self.assertEqual(impact.classify(paths), {'checks': True, 'nix': False, 'profiles': []})
        self.assertEqual(impact.classify(paths + ['files/system/etc/changed.conf'])['profiles'], sorted(impact.PROFILES))

    def test_cost_report_mixed_with_vm_inputs_keeps_both_premerge_profiles(self):
        spec = importlib.util.spec_from_file_location('vm_selection', ROOT / 'scripts/ci/vm-selection.py')
        vm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vm)
        for changed in (['scripts/ci/cost_receipts.py'],
                        ['scripts/ci/cost_receipts.py', 'scripts/bluebuild/vm-acceptance.sh'],
                        ['scripts/ci/cost_receipts.py', 'files/system/usr/libexec/finite/guest-check.py']):
            with self.subTest(changed=changed):
                plan = impact.classify(changed)
                output = run_script('payloads.py', {}, GITHUB_EVENT_NAME='merge_group', GITHUB_SHA='a' * 40,
                                    IMPACT=json.dumps({key: json.dumps(plan[key]) for key in ('nix', 'profiles')}),
                                    VM_VALIDATION=str(vm.required(changed)).lower())
                expected = set(impact.PROFILES) if len(changed) > 1 else set()
                self.assertEqual({row['profile'] for row in json.loads(output['matrix'])['include']}, expected)


    def test_only_active_recipes_are_selected(self):
        for profile in impact.PROFILES:
            self.assertEqual(impact.classify(['recipes/' + profile + '.yml'])['profiles'], [profile])
        self.assertEqual(set(impact.PROFILES), {'finite', 'finite-dev'})
        self.assertEqual(impact.classify(['files/scripts/upstream-kernel.py'])['profiles'], sorted(impact.PROFILES))

    def test_check_only_inputs_and_full_rebuild_fallback(self):
        for path in impact.QUALIFICATION_ONLY:
            with self.subTest(path=path):
                self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        for path in ['tests/home/contracts.sh', 'automation/github/repository-security.json', '.github/workflows/release.yml', 'devenv.lock', 'scripts/ci/http-get.py',
                     '.github/workflows/update-bluefin.yml',
                     '.github/workflows/upstream-health.yml', '.github/workflows/repository-security.yml',
                     '.github/workflows/doppler-pilot.yml']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        for path in ['.github/workflows/desktop-security-evidence.yml',
                     'scripts/ci/go-binary-evidence.go', 'scripts/ci/go-binary-evidence_test.go',
                     'scripts/ci/go-desktop-evidence.py']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        self.assertEqual(impact.classify(['scripts/ci/local-candidate-evidence.py']),
                         {'checks': True, 'nix': False, 'profiles': []})
        self.assertEqual(impact.classify([])['profiles'], sorted(impact.PROFILES))
        for path in ['.github/workflows/iso.yml', '.github/workflows/vm-acceptance.yml']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        for event in ['schedule', 'workflow_dispatch', 'unknown']:
            self.assertIsNone(impact.changed_paths(event, {}))
        self.assertIsNone(impact.changed_paths('push', {'before': '0' * 40, 'after': 'a' * 40}))

    def test_complete_git_diff_for_pr_queue_push_and_renames(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            def git(*args):
                return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'user.name', 'CI Test')
            Path('README.md').write_text('Finite\n')
            Path('image-input').write_text('runtime\n')
            git('add', '.')
            git('commit', '-m', 'base')
            base = git('rev-parse', 'HEAD')
            Path('docs').mkdir()
            for index in range(350):
                Path(f'docs/{index}.md').write_text('Guide\n')
            git('mv', 'image-input', 'docs/renamed.md')
            git('add', '.')
            git('commit', '-m', 'change')
            head = git('rev-parse', 'HEAD')
            events = {
                'pull_request': {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}},
                'merge_group': {'merge_group': {'base_sha': base, 'head_sha': head}},
                'push': {'before': base, 'after': head},
            }
            for name, event in events.items():
                paths = impact.changed_paths(name, event)
                self.assertEqual(len(paths), 352)
                self.assertIn('image-input', paths)
                self.assertEqual(set(impact.classify(paths)['profiles']), set(impact.PROFILES))

    def test_detection_error_runs_full_checks(self):
        output = run_script('impact.py', {}, GITHUB_EVENT_NAME='push')
        self.assertEqual(output['checks'], 'true')
        self.assertEqual(json.loads(output['profiles']), sorted(impact.PROFILES))


def run_script(script, event, **environment):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'event').write_text(json.dumps(event))
        env = dict(os.environ, GITHUB_EVENT_PATH=str(root / 'event'),
                   GITHUB_OUTPUT=str(root / 'output'), GITHUB_STEP_SUMMARY=str(root / 'summary'), **environment)
        subprocess.run([sys.executable, str(ROOT / 'scripts/ci' / script)], env=env, check=True, stdout=subprocess.DEVNULL)
        return dict(line.split('=', 1) for line in (root / 'output').read_text().splitlines())


class Payloads(unittest.TestCase):

    def test_shared_payload_selects_both_active_variants(self):
        before = {'generic': 'generic-a'}
        self.assertEqual(payloads.select([], before, before), [])
        self.assertEqual(payloads.select([], before, {'generic': 'generic-b'}), sorted(impact.PROFILES))
        self.assertEqual(payloads.select(['finite'], before, before), ['finite'])
        for retired in ('bluefin-next', 'bluefin-dx-next'):
            with self.assertRaises(ValueError):
                payloads.select([retired], before, before)

    def test_uses_actual_merge_checkout_and_keeps_explicit_profiles(self):
        base, branch, merge = 'a' * 40, 'b' * 40, 'c' * 40
        seen = []
        def evaluate(revision):
            seen.append(revision)
            return {'generic': 'same'}
        event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': branch}}}
        selected, evidence = payloads.refine({'nix': True, 'profiles': ['finite']}, 'pull_request', event, merge, evaluate)
        self.assertEqual(seen, [base, merge])
        self.assertEqual(selected, ['finite'])
        self.assertEqual(evidence['head'], merge)

    def test_no_evaluation_for_explicit_full_builds(self):
        def unexpected(_):
            self.fail('Explicit full build must not evaluate payloads')
        all_profiles = sorted(impact.PROFILES)
        self.assertEqual(payloads.refine({'nix': True, 'profiles': all_profiles}, 'push', {}, '', unexpected)[0], all_profiles)

    def test_missing_comparison_selects_all_images(self):
        output = run_script('payloads.py', {}, GITHUB_EVENT_NAME='push', GITHUB_SHA='a' * 40,
                            IMPACT=json.dumps({'nix': 'true', 'profiles': '[]'}))
        self.assertEqual(output['images'], 'true')
        self.assertEqual({row['profile'] for row in json.loads(output['matrix'])['include']}, set(impact.PROFILES))

    def test_check_only_outputs_an_empty_matrix(self):
        output = run_script('payloads.py', {}, GITHUB_EVENT_NAME='push', GITHUB_SHA='a' * 40,
                            IMPACT=json.dumps({'nix': 'false', 'profiles': '[]'}))
        self.assertEqual(output['images'], 'false')
        self.assertEqual(json.loads(output['matrix']), {'include': []})


class Gate(unittest.TestCase):
    def needs(self, checks, selected, publish=False):
        matrix = {'include': [{'profile': profile, 'channel': impact.PROFILES[profile]} for profile in selected]}
        return {
            'impact': {'result': 'success', 'outputs': {'checks': str(checks).lower(), 'nix': 'false', 'profiles': json.dumps(selected)}},
            'docs': {'result': 'success'},
            'checks': {'result': 'success' if checks else 'skipped', 'outputs': {'images': str(bool(selected)).lower(), 'matrix': json.dumps(matrix)} if checks else {}},
            'images': {'result': 'success' if selected and not publish else 'skipped'},
            'publish': {'result': 'success' if selected and publish else 'skipped'},
        }

    def test_all_valid_routes(self):
        for checks, selected in [(False, []), (True, []), (True, ['finite']), (True, sorted(impact.PROFILES))]:
            for publish in (False, True):
                self.assertEqual(gate.failures(self.needs(checks, selected, publish), publish, 'push' if publish else 'merge_group'), [])

    def test_failed_cancelled_or_unexpectedly_skipped_jobs_block(self):
        for publish in (False, True):
            good = self.needs(True, sorted(impact.PROFILES), publish)
            for job in ('impact', 'docs', 'checks', 'publish' if publish else 'images'):
                for result in ('failure', 'cancelled', 'skipped'):
                    needs = copy.deepcopy(good)
                    needs[job]['result'] = result
                    self.assertTrue(gate.failures(needs, publish, 'push' if publish else 'merge_group'), (job, result))
        needs = self.needs(False, [])
        needs['impact']['outputs'] = {}
        self.assertTrue(gate.failures(needs, False, 'merge_group'))
        needs = self.needs(False, [])
        needs['publish']['result'] = 'success'
        self.assertTrue(gate.failures(needs, False, 'merge_group'))

    def test_prerequisite_failure_has_no_cascading_selection_errors(self):
        needs = self.needs(True, ['finite'])
        needs['docs']['result'] = 'failure'
        needs['checks'] = {'result': 'skipped', 'outputs': {}}
        self.assertEqual(gate.failures(needs, False, 'merge_group'), ['docs: expected success, got failure'])
        needs['docs']['result'] = 'success'
        needs['checks']['result'] = 'failure'
        self.assertEqual(gate.failures(needs, False, 'merge_group'), ['checks: expected success, got failure'])

    def test_pr_runs_source_checks_and_queue_requires_the_complete_os_jobs(self):
        for checks, selected in [(False, []), (True, []), (True, ['finite']), (True, sorted(impact.PROFILES))]:
            needs = self.needs(checks, selected)
            needs['images']['result'] = 'skipped'
            self.assertEqual(gate.failures(needs, False, 'pull_request'), [])
            if selected:
                self.assertTrue(gate.failures(needs, False, 'merge_group'))
                for status in ('failure', 'cancelled', 'skipped'):
                    failed = copy.deepcopy(needs)
                    failed['checks']['result'] = status
                    self.assertTrue(gate.failures(failed, False, 'pull_request'))
                malformed = copy.deepcopy(needs)
                malformed['checks']['outputs'] = {}
                self.assertTrue(gate.failures(malformed, False, 'pull_request'))
        needs = self.needs(True, sorted(impact.PROFILES))
        needs['images']['result'] = 'skipped'
        needs['impact']['outputs']['vm'] = 'true'
        needs['checks']['outputs']['matrix'] = json.dumps({'include': [{'profile': 'finite', 'channel': 'finite'}]})
        self.assertTrue(gate.failures(needs, False, 'pull_request'))

    def test_unknown_events_and_premerge_publication_fail_closed(self):
        for event in ('', 'pull_request_target', 'workflow_run', 'unknown'):
            self.assertTrue(gate.failures(self.needs(False, []), False, event))
        for event in ('pull_request', 'merge_group'):
            self.assertTrue(gate.failures(self.needs(True, sorted(impact.PROFILES), True), True, event))

    def test_updater_authentication_and_preflight(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/update-determinate-nix.yml').read_text())
        steps = workflow['jobs']['update']['steps']
        resolve = next(step for step in steps if step.get('id') == 'resolve')
        self.assertEqual(resolve['env']['GH_TOKEN'], '${{ github.token }}')
        for name in ['update-determinate-nix', 'update-flake-lock', 'update-foundation']:
            workflow = yaml.safe_load((ROOT / f'.github/workflows/{name}.yml').read_text())
            self.assertEqual(workflow['permissions'], {'contents': 'read'})
            steps = workflow['jobs']['update']['steps']
            names = [step.get('name') for step in steps]
            self.assertLess(names.index('Validate generated text'), names.index('Open or update pull request'))
            self.assertGreaterEqual(workflow['jobs']['update']['timeout-minutes'], 210)

    def lock_identity(self, user, *, slug='cl-decider', expected='cl-decider[bot]', fail=False):
        import yaml
        steps = yaml.safe_load((ROOT / '.github/workflows/update-flake-lock.yml').read_text())['jobs']['update']['steps']
        step = next(step for step in steps if step.get('id') == 'pr-identity')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / 'gh'
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$FIXTURE_ARGS"\nprintf "%s" "$FIXTURE_USER"\nexit "$FIXTURE_STATUS"\n')
            gh.chmod(0o755)
            output, args = root / 'output', root / 'args'
            result = subprocess.run(['bash', '-e', '-c', step['run']], capture_output=True, text=True,
                                    env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                                         'APP_SLUG': slug, 'EXPECTED_BOT': expected,
                                         'GH_TOKEN': 'fixture-app-token', 'GITHUB_OUTPUT': str(output),
                                         'FIXTURE_ARGS': str(args), 'FIXTURE_USER': json.dumps(user),
                                         'FIXTURE_STATUS': '1' if fail else '0'})
            return result, output.read_text() if output.exists() else '', args.read_text() if args.exists() else ''

    def test_lock_refresh_uses_scoped_app_for_creation_and_preserves_queue_auth(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/update-flake-lock.yml').read_text())
        steps = workflow['jobs']['update']['steps']
        token = next(step for step in steps if step.get('id') == 'lock-pr-token')
        self.assertEqual(token['if'], "steps.source.outputs.changed == 'true'")
        self.assertEqual(token['uses'], 'actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510')
        self.assertEqual({key: value for key, value in token['with'].items() if key.startswith('permission-')},
                         {'permission-contents': 'write', 'permission-pull-requests': 'write'})
        self.assertEqual(token['with']['owner'], '${{ github.repository_owner }}')
        self.assertEqual(token['with']['repositories'], '${{ github.event.repository.name }}')
        create = next(step for step in steps if step.get('id') == 'update')
        self.assertEqual(create['with']['token'], '${{ steps.lock-pr-token.outputs.token }}')
        self.assertEqual(create['with']['branch'], 'automation/decider-weekly-flake-input-refresh')
        self.assertEqual(create['with']['author'], '${{ steps.pr-identity.outputs.name }} <${{ steps.pr-identity.outputs.email }}>')
        self.assertEqual(create['with']['committer'], create['with']['author'])
        self.assertEqual(create['with']['add-paths'].splitlines(), ['flake.lock', 'devenv.lock'])
        validate = next(step for step in steps if step.get('name') == 'Validate and enable auto-merge')
        self.assertEqual(validate['env']['EXPECTED_AUTHOR'], '${{ steps.pr-identity.outputs.pr-author }}')
        self.assertEqual(validate['env']['EXPECTED_BRANCH'], create['with']['branch'])
        self.assertEqual(validate['env']['GH_TOKEN'], '${{ env.MERGE_QUEUE_TOKEN }}')
        names = [step.get('name') for step in steps]
        self.assertLess(names.index('Validate generated text'), names.index('Create short-lived Decider PR token'))
        self.assertLess(names.index('Clear Decider private credentials'), names.index('Open or update pull request'))
        clear = next(step for step in steps if step.get('name') == 'Clear Decider private credentials')
        self.assertEqual(clear['if'], "always() && steps.credentials.outcome == 'success'")

    def test_live_decider_identity_produces_bot_commit_and_app_pr_author(self):
        result, output, args = self.lock_identity({'id': 344936881, 'login': 'cl-decider[bot]', 'type': 'Bot'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'name=cl-decider[bot]\nemail=344936881+cl-decider[bot]@users.noreply.github.com\npr-author=app/cl-decider\n')
        self.assertEqual(args.splitlines(), ['api', 'users/cl-decider[bot]'])

    def test_personal_or_malformed_bot_metadata_cannot_create_pr_identity(self):
        for user in ({'id': 1, 'login': 'declarative-dale', 'type': 'User'},
                     {'id': 1, 'login': 'cl-decider[bot]', 'type': 'User'},
                     {'id': True, 'login': 'cl-decider[bot]', 'type': 'Bot'},
                     {'id': 0, 'login': 'cl-decider[bot]', 'type': 'Bot'}):
            with self.subTest(user=user):
                result, output, _ = self.lock_identity(user)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, '')

    def test_wrong_app_or_lookup_failure_never_falls_back_to_personal_auth(self):
        for options in ({'slug': 'other-app'}, {'slug': 'invalid/slug'}, {'expected': ''}):
            with self.subTest(options=options):
                result, output, args = self.lock_identity({}, **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((output, args), ('', ''))
        result, output, _ = self.lock_identity({}, fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, '')

    def test_missing_matrix_and_omitted_explicit_image_block(self):
        needs = self.needs(True, ['finite'])
        needs['checks']['outputs'] = {}
        self.assertTrue(gate.failures(needs, False, 'merge_group'))
        needs = self.needs(True, ['finite'])
        needs['checks']['outputs'] = {'images': 'false', 'matrix': '{"include":[]}'}
        self.assertTrue(gate.failures(needs, False, 'merge_group'))


class DopplerPilot(unittest.TestCase):
    def setUp(self):
        import yaml
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/doppler-pilot.yml').read_text())

    def probe(self, job, index, status=403, bad_claim=False):
        import base64
        import io
        import urllib.error
        from unittest.mock import patch
        steps = self.workflow['jobs'][job]['steps']
        source = steps[index]['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        claims = {
            'iss': 'https://token.actions.githubusercontent.com',
            'aud': 'https://github.com/closure-labs',
            'sub': 'repo:closure-labs@256683018/finite@1293375784:' + (
                'environment:doppler-pilot' if job == 'canary' else 'ref:refs/heads/main'),
            'repository_id': '1293375784', 'repository_owner_id': '256683018',
            'ref': 'refs/heads/main', 'event_name': 'workflow_dispatch',
            'workflow_ref': 'closure-labs/finite/.github/workflows/doppler-pilot.yml@refs/heads/main',
        }
        if bad_claim:
            claims['sub'] = 'unexpected'
        token = 'secret-header.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode() + '.secret-signature'
        calls = []
        def request(req, timeout):
            calls.append(req)
            self.assertEqual(timeout, 15)
            if len(calls) == 1:
                return io.BytesIO(json.dumps({'value': token}).encode())
            self.assertEqual(req.full_url, 'https://api.doppler.com/v3/auth/oidc')
            self.assertEqual(json.loads(req.data), {'identity': 'pilot-identity', 'token': token})
            if status == 'network':
                raise urllib.error.URLError(token)
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, token, {}, io.BytesIO(token.encode()))
            return io.BytesIO(token.encode())
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary'
            output = io.StringIO()
            error = None
            with patch.dict(os.environ, {
                'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://example.invalid/token?request=1',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'secret-request',
                'PILOT_IDENTITY': 'pilot-identity', 'GITHUB_STEP_SUMMARY': str(summary),
            }), patch('urllib.request.urlopen', side_effect=request), contextlib.redirect_stdout(output):
                try:
                    exec(compile(source, '<pilot>', 'exec'), {})
                except SystemExit as exc:
                    error = str(exc)
            retained = output.getvalue() + (summary.read_text() if summary.exists() else '') + (error or '')
            self.assertNotIn(token, retained)
            self.assertNotIn('secret-request', retained)
            return error, calls, retained

    def test_claims_only_and_bad_claims(self):
        error, calls, retained = self.probe('canary', 0)
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertIn('Public pilot OIDC claims', retained)
        self.assertIsNotNone(self.probe('canary', 0, bad_claim=True)[0])

    def test_negative_probes_require_actual_authentication_denial(self):
        for job, index in [('canary', 4), ('deny-without-environment', 0)]:
            for status in (401, 403):
                error, calls, _ = self.probe(job, index, status=status)
                self.assertIsNone(error)
                self.assertEqual(len(calls), 2)
                if job == 'canary':
                    self.assertIn('audience=finite-doppler-pilot-denied', calls[0].full_url)
            for status in (200, 400, 429, 500, 'network'):
                self.assertIsNotNone(self.probe(job, index, status=status)[0])
        error, calls, _ = self.probe('deny-without-environment', 0, bad_claim=True)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 1)

    def test_pilot_permissions_and_secret_scope(self):
        self.assertEqual(self.workflow['permissions'], {})
        jobs = self.workflow['jobs']
        self.assertEqual(jobs['canary']['environment'], 'doppler-pilot')
        self.assertNotIn('environment', jobs['deny-without-environment'])
        for job in jobs.values():
            self.assertEqual(job['permissions'], {'id-token': 'write'})
            self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        action = jobs['canary']['steps'][2]
        self.assertEqual(action['uses'], 'DopplerHQ/secrets-fetch-action@451892f16195f9ac360e1a5bcbf0b5fd0e957534')
        self.assertEqual(action['with']['inject-env-vars'], 'false')
        self.assertNotIn('doppler-token', action['with'])


if __name__ == '__main__':
    unittest.main()
