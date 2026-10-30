"""Small Git-graph, native job wiring and optional cached-engine fixtures."""
import json
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/build.yml'

import yaml
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import gate


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def scan_script():
    return next(step['run'] for step in workflow()['jobs']['repository-secrets']['steps']
                if step.get('name') == 'Scan complete introduced commit range')


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'candidate'
        self.repo.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        self.git('init', '-q', '-b', 'main')
        self.commit('base.txt', 'pre-existing-marker\n')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '-b', 'side')
        self.commit('side.txt', 'side-introduced-then-deleted-marker\n')
        self.side = self.git('rev-parse', 'HEAD')
        self.git('rm', '-q', 'side.txt')
        self.git('commit', '-qm', 'remove side fixture')
        self.git('checkout', '-q', 'main')
        self.commit('main.txt', 'main-introduced-marker\n')
        self.git('merge', '--no-ff', '--no-commit', 'side')
        self.commit('merge-only.txt', 'merge-only-resolution-marker\n')
        self.head = self.git('rev-parse', 'HEAD')
        self.runtime = self.root / 'runtime'
        (self.runtime / 'gitleaks').mkdir(parents=True)
        binary = self.runtime / 'gitleaks/gitleaks'
        binary.write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["ARG_LOG"]).write_text(json.dumps(sys.argv[1:]))\nprint("DO-NOT-EXPOSE-FIXTURE-PAYLOAD")\nsys.exit(int(os.environ.get("SCANNER_EXIT","0")))\n')
        binary.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args], cwd=self.repo, env=self.env, stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        self.git('add', name)
        self.git('commit', '-qm', 'synthetic fixture')

    def run_scan(self, **values):
        env = dict(self.env, EVENT_NAME='pull_request', BASE_SHA=self.base, HEAD_SHA=self.head,
                   RUNNER_TEMP=str(self.runtime), GITHUB_WORKSPACE=str(self.root), ARG_LOG=str(self.root / 'args.json'))
        env.update(values)
        return subprocess.run(['bash', '-c', scan_script()], cwd=self.repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_complete_graph_and_merge_only_content(self):
        result = self.run_scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.root / 'args.json').read_text())
        opts = next(a.split('=', 1)[1] for a in args if a.startswith('--log-opts='))
        self.assertNotIn('--first-parent ', opts)
        self.assertNotIn('--no-merges', opts)
        patch = self.git('log', '-p', '-U0', *opts.split())
        for marker in ['side-introduced-then-deleted-marker', 'merge-only-resolution-marker', 'main-introduced-marker']:
            self.assertIn('+' + marker, patch)
        self.assertNotIn('+pre-existing-marker', patch)
        self.assertIn(self.side, patch)
        self.assertNotIn('DO-NOT-EXPOSE', result.stdout + result.stderr)
        self.assertIn('--redact=100', args)
        self.assertFalse(any(a.startswith('--report') or a.startswith('--baseline') for a in args))
        self.assertEqual(self.run_scan(EVENT_NAME='merge_group').returncode, 0)
        for author in ('dependabot[bot]', 'ordinary-contributor'):
            self.assertEqual(self.run_scan(GITHUB_ACTOR=author).returncode, 0)

    def test_missing_bad_equal_and_wrong_checkout_fail_before_scanner(self):
        for values in [{'BASE_SHA': ''}, {'BASE_SHA': '1' * 40}, {'HEAD_SHA': 'not-a-sha'},
                       {'BASE_SHA': self.head}, {'HEAD_SHA': self.base}, {'HEAD_SHA': ''},
                       *({'EVENT_NAME': event} for event in ('workflow_run', 'pull_request_target', 'push', 'schedule', 'workflow_dispatch'))]:
            with self.subTest(values=values):
                result = self.run_scan(**values)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / 'args.json').exists())

    def test_diverged_pr_base_is_valid_but_queue_base_must_be_ancestor(self):
        self.git('checkout', '-q', '-b', 'new-base', self.base)
        self.commit('new-base.txt', 'new base data\n')
        diverged = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        self.assertEqual(self.run_scan(BASE_SHA=diverged).returncode, 0)
        self.assertNotEqual(self.run_scan(BASE_SHA=diverged, EVENT_NAME='merge_group').returncode, 0)

    def test_shallow_checkout_fails(self):
        (self.repo / '.git/shallow').write_text(self.base + '\n')
        self.assertNotEqual(self.run_scan().returncode, 0)
        self.assertFalse((self.root / 'args.json').exists())

    def test_actual_shallow_clone_fails_before_scanner(self):
        clone = self.root / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--depth=1', self.repo.as_uri(), str(clone)],
                       env=self.env, check=True, capture_output=True)
        self.repo = clone
        self.assertEqual(self.git('rev-parse', '--is-shallow-repository'), 'true')
        self.assertNotEqual(self.run_scan().returncode, 0)
        self.assertFalse((self.root / 'args.json').exists())

    def test_existing_but_unrelated_base_fails_before_scanner(self):
        self.git('checkout', '-q', '--orphan', 'unrelated')
        self.commit('unrelated.txt', 'unrelated root\n')
        unrelated = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        for event in ('pull_request', 'merge_group'):
            self.assertNotEqual(self.run_scan(BASE_SHA=unrelated, EVENT_NAME=event).returncode, 0)
            self.assertFalse((self.root / 'args.json').exists())

    def test_findings_errors_and_timeouts_never_pass_or_leak(self):
        for status in [1, 2, 124, 137]:
            result = self.run_scan(SCANNER_EXIT=str(status))
            self.assertEqual(result.returncode, status)
            self.assertNotIn('DO-NOT-EXPOSE', result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gitleaks'), 'Optional cached Gitleaks binary unavailable')
    def test_real_default_engine_blocks_new_findings_but_not_old_history(self):
        binary = self.runtime / 'gitleaks/gitleaks'
        binary.unlink()
        binary.symlink_to(shutil.which('gitleaks'))
        self.assertEqual(subprocess.check_output([str(binary), 'version'], text=True).strip(), '8.30.1')
        # Synthetic recognizable token, assembled only within this temporary Git graph.
        token = 'ghp_' + '9F0r2JtQ6Lw8aD3sG7hK1mN5pR4vXyZcBeTu'
        self.commit('old-token.txt', 'token = "' + token + '"\n')
        historical = self.git('rev-parse', 'HEAD')
        self.commit('clean.txt', 'new harmless content\n')
        clean = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=clean).returncode, 0)
        self.commit('.gitleaks.toml', '[extend]\nuseDefault = true\n[allowlist]\nregexes = [".+"]\n')
        self.commit('.gitleaksignore', '*\n')
        self.commit('new-token.txt', 'token = "' + token + '" # gitleaks:allow\n')
        introduced = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=introduced).returncode, 2)
        self.git('rm', '-q', 'new-token.txt')
        self.git('commit', '-qm', 'remove synthetic token')
        deleted = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.run_scan(BASE_SHA=historical, HEAD_SHA=deleted).returncode, 2)
        self.git('remote', 'add', 'origin', str(self.repo))
        history = yaml.safe_load((ROOT / '.github/workflows/repository-secret-history.yml').read_text())
        script = next(s['run'] for s in history['jobs']['history']['steps']
                      if s.get('name') == 'Audit all fetched branch tag and pull-request history')
        result = subprocess.run(['bash', '-c', script], cwd=self.repo,
                                env=dict(self.env, RUNNER_TEMP=str(self.runtime)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(token, result.stdout + result.stderr)


class NativeGateTests(unittest.TestCase):
    def needs(self):
        return {'repository-secrets': {'result': 'success'},
                'impact': {'result': 'success', 'outputs': {'checks': 'false', 'nix': 'false', 'profiles': '[]'}},
                'docs': {'result': 'success'}, 'checks': {'result': 'skipped'},
                'images': {'result': 'skipped'}, 'publish': {'result': 'skipped'}}

    def test_scan_required_even_for_docs_and_no_images(self):
        for event in ('pull_request', 'merge_group'):
            self.assertEqual(gate.failures(self.needs(), False, event), [])
            for state in ('failure', 'cancelled', 'skipped', 'pending', None):
                needs = self.needs(); needs['repository-secrets']['result'] = state
                errors = gate.failures(needs, False, event)
                self.assertEqual(errors, ['Repository scan did not produce the required native job result'])
            needs = self.needs(); del needs['repository-secrets']
            needs['history'] = {'result': 'success'}
            needs['savedScan'] = {'result': 'success', 'head': 'old'}
            self.assertTrue(gate.failures(needs, False, event))

    def test_history_is_not_a_premerge_or_publication_scan_receipt(self):
        for event in ('push', 'schedule', 'workflow_dispatch'):
            needs = self.needs(); needs['repository-secrets']['result'] = 'skipped'
            self.assertEqual(gate.failures(needs, False, event), [])
            needs['repository-secrets']['result'] = 'success'
            self.assertTrue(gate.failures(needs, False, event))
        for event in ('workflow_run', 'pull_request_target', '', 'forged'):
            self.assertTrue(gate.failures(self.needs(), False, event))

    def test_native_same_run_dependency_and_real_job_name(self):
        jobs = workflow()['jobs']
        self.assertEqual(jobs['repository-secrets']['name'], 'Repository security audit')
        self.assertEqual(jobs['repository-secrets']['if'],
                         "github.event_name == 'pull_request' || github.event_name == 'merge_group'")
        self.assertEqual(jobs['repository-secrets'].get('permissions', workflow()['permissions']), {'contents': 'read'})
        self.assertIn('repository-secrets', jobs['gate']['needs'])
        self.assertEqual(jobs['gate']['name'], 'CI gate')
        self.assertEqual(jobs['gate']['if'], 'always()')
        self.assertEqual(jobs['gate']['env']['NEEDS'], '${{ toJSON(needs) }}')
        self.assertNotIn('uses', jobs['repository-secrets'])
        steps = jobs['repository-secrets']['steps']
        checkout = steps[0]['with']
        self.assertEqual(checkout['ref'], '${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}')
        self.assertIs(checkout['persist-credentials'], False)
        self.assertEqual(checkout['fetch-depth'], 0)
        self.assertEqual(checkout['path'], 'candidate')
        env = next(s['env'] for s in steps if s.get('name') == 'Scan complete introduced commit range')
        self.assertEqual(env['BASE_SHA'], '${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}')
        self.assertEqual(env['HEAD_SHA'], checkout['ref'])

    def test_supported_triggers_and_history_main_guard(self):
        build = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(build['on']), {'pull_request', 'merge_group', 'push', 'schedule', 'workflow_dispatch'})
        self.assertEqual(build['on']['merge_group']['types'], ['checks_requested'])
        history = yaml.load((ROOT / '.github/workflows/repository-secret-history.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(history['on']), {'schedule', 'workflow_dispatch'})
        guard = history['jobs']['history']['steps'][0]['run']
        for ref, wanted in [('refs/heads/main', 0), ('refs/heads/topic', 1), ('refs/pull/7/merge', 1), ('', 1)]:
            result = subprocess.run(['bash', '-c', guard], env=dict(os.environ, GITHUB_REF=ref))
            self.assertEqual(result.returncode, wanted)

    def test_scanner_has_no_candidate_execution_credentials_or_exclusions(self):
        job = workflow()['jobs']['repository-secrets']
        history = yaml.safe_load((ROOT / '.github/workflows/repository-secret-history.yml').read_text())
        self.assertEqual(history['permissions'], {'contents': 'read'})
        self.assertEqual(history['jobs']['history']['name'], 'Repository historical audit (nonblocking debt)')
        self.assertEqual(history['jobs']['history']['steps'][0]['run'], 'test "$GITHUB_REF" = refs/heads/main')
        for jobs in (job, history['jobs']['history']):
            text = yaml.safe_dump(jobs)
            for forbidden in ('secrets.', 'token:', 'continue-on-error:', 'upload-artifact', 'checks: write',
                              'id-token:', '--baseline', '--max-target-megabytes', 'uses: $/', 'uses: ./'):
                self.assertNotIn(forbidden, text)
            self.assertIn('551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb', text)
            run = next(s['run'] for s in jobs['steps'] if 'log_opts=' in s.get('run', ''))
            self.assertIn('useDefault = true', run)
            self.assertNotIn('allowlists', run)
            self.assertIn('--ignore-gitleaks-allow', run)
            self.assertIn('--gitleaks-ignore-path "$RUNNER_TEMP/empty.gitleaksignore"', run)
            self.assertIn('>/dev/null 2>&1', run)


class NativeOriginTests(unittest.TestCase):
    def test_existing_build_origin_covers_dependabot_and_ordinary_prs(self):
        spec = importlib.util.spec_from_file_location('scanner_admission', ROOT / 'scripts/ci/ci-run-admission.py')
        admission = importlib.util.module_from_spec(spec); spec.loader.exec_module(admission)
        rules = json.loads((ROOT / 'automation/github/ci-execution.json').read_text())
        repo = {'id': rules['repositoryId'], 'full_name': rules['repository']}
        for author in ('dependabot[bot]', 'ordinary-contributor'):
            pr = {'user': {'login': author}, 'head': {'sha': 'a' * 40, 'ref': 'topic', 'repo': repo}}
            run = {'id': 10, 'run_attempt': 1, 'workflow_id': 50, 'repository': repo, 'head_repository': repo,
                   'head_branch': 'topic', 'head_sha': 'a' * 40, 'event': 'pull_request',
                   'path': '.github/workflows/build.yml'}
            self.assertTrue(admission.bound_run(run, pr, rules))
            for change in ({'head_sha': 'b' * 40}, {'head_branch': 'other'},
                           {'repository': {'id': 1}}, {'head_repository': {'id': 1}},
                           {'run_attempt': 0}, {'workflow_id': None}, {'event': 'workflow_run'}, {'event': 'workflow_dispatch'},
                           {'path': '.github/workflows/repository-secret-history.yml'},
                           {'path': '.github/workflows/forged.yml'}):
                with self.subTest(author=author, change=change):
                    self.assertFalse(admission.bound_run({**copy.deepcopy(run), **change}, pr, rules))
        # This is origin matching only; existing live author/reviewer eligibility still applies.
        self.assertNotIn('.github/workflows/repository-secret-history.yml', rules['workflows'])


if __name__ == '__main__': unittest.main()
