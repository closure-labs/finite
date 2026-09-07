#!/usr/bin/env python3
"""Exercise change selection and failure propagation at CI boundaries."""
import contextlib
import copy
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


class Selection(unittest.TestCase):
    def test_documentation_and_mixed_changes(self):
        self.assertEqual(impact.classify(['README.md', 'docs/installation.md']), {'checks': False, 'nix': False, 'profiles': []})
        for path in ['files/system/usr/share/finite/finite-logo.png', '.github/workflows/build.yml',
                     '.github/workflows/image.yml', '.github/actions/setup-nix/action.yml', 'scripts/ci/impact.py',
                     'scripts/bluebuild/publication.py', 'scripts/ci/bluefin-upstream.py', 'new-image-input', 'docs-like/file']:
            with self.subTest(path=path):
                self.assertEqual(impact.classify(['README.md', path]), {'checks': True, 'nix': False, 'profiles': sorted(impact.PROFILES)})

    def test_nix_inputs_use_dependency_comparison(self):
        for path in ['VERSION', 'flake.lock', 'modules/outputs.nix', 'lib/image-payload.nix',
                     'templates/home-manager/customize.nix', 'sources/kernel-next.json']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': True, 'profiles': []})

    def test_recipe_and_next_only_inputs(self):
        self.assertEqual(impact.classify(['recipes/bluefin-next.yml'])['profiles'], ['bluefin-next'])
        for path in ['recipes/shared/next.yml', 'files/scripts/kernel-next.sh']:
            self.assertEqual(impact.classify([path])['profiles'], sorted(impact.NEXT))

    def test_check_only_inputs_and_full_rebuild_fallback(self):
        for path in ['tests/home/contracts.sh', 'automation/github/repository-security.json', '.github/workflows/iso.yml', 'devenv.lock', 'scripts/ci/http-get.py',
                     '.github/workflows/update-bluefin.yml',
                     '.github/workflows/upstream-health.yml']:
            self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        self.assertEqual(impact.classify([])['profiles'], sorted(impact.PROFILES))
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
    def test_unchanged_generic_next_and_shared_payloads(self):
        before = {'generic': 'generic-a', 'next': 'next-a'}
        self.assertEqual(payloads.select([], before, before), [])
        self.assertEqual(payloads.select([], before, dict(before, next='next-b')), sorted(impact.NEXT))
        self.assertEqual(payloads.select([], before, dict(before, generic='generic-b')), sorted(set(impact.PROFILES) - impact.NEXT))
        self.assertEqual(payloads.select([], before, {'generic': 'b', 'next': 'b'}), sorted(impact.PROFILES))
        self.assertEqual(payloads.select(['bluefin-next'], before, before), ['bluefin-next'])

    def test_uses_actual_merge_checkout_and_keeps_explicit_profiles(self):
        base, branch, merge = 'a' * 40, 'b' * 40, 'c' * 40
        seen = []
        def evaluate(revision):
            seen.append(revision)
            return {'generic': 'same', 'next': 'same'}
        event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': branch}}}
        selected, evidence = payloads.refine({'nix': True, 'profiles': ['bluefin-next']}, 'pull_request', event, merge, evaluate)
        self.assertEqual(seen, [base, merge])
        self.assertEqual(selected, ['bluefin-next'])
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
        for checks, selected in [(False, []), (True, []), (True, ['bluefin-next']), (True, sorted(impact.NEXT)), (True, sorted(impact.PROFILES))]:
            for publish in (False, True):
                self.assertEqual(gate.failures(self.needs(checks, selected, publish), publish), [])

    def test_failed_cancelled_or_unexpectedly_skipped_jobs_block(self):
        for publish in (False, True):
            good = self.needs(True, sorted(impact.PROFILES), publish)
            for job in ('impact', 'docs', 'checks', 'publish' if publish else 'images'):
                for result in ('failure', 'cancelled', 'skipped'):
                    needs = copy.deepcopy(good)
                    needs[job]['result'] = result
                    self.assertTrue(gate.failures(needs, publish), (job, result))
        needs = self.needs(False, [])
        needs['impact']['outputs'] = {}
        self.assertTrue(gate.failures(needs, False))
        needs = self.needs(False, [])
        needs['publish']['result'] = 'success'
        self.assertTrue(gate.failures(needs, False))

    def test_prerequisite_failure_has_no_cascading_selection_errors(self):
        needs = self.needs(True, ['bluefin-next'])
        needs['docs']['result'] = 'failure'
        needs['checks'] = {'result': 'skipped', 'outputs': {}}
        self.assertEqual(gate.failures(needs, False), ['docs: expected success, got failure'])
        needs['docs']['result'] = 'success'
        needs['checks']['result'] = 'failure'
        self.assertEqual(gate.failures(needs, False), ['checks: expected success, got failure'])

    def test_updater_authentication_and_preflight(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/update-determinate-nix.yml').read_text())
        steps = workflow['jobs']['update']['steps']
        resolve = next(step for step in steps if step.get('id') == 'resolve')
        self.assertEqual(resolve['env']['GH_TOKEN'], '${{ github.token }}')
        for name in ['update-determinate-nix', 'update-flake-lock', 'update-home-release']:
            workflow = yaml.safe_load((ROOT / f'.github/workflows/{name}.yml').read_text())
            self.assertEqual(workflow['permissions'], {'contents': 'read'})
            steps = workflow['jobs']['update']['steps']
            names = [step.get('name') for step in steps]
            self.assertLess(names.index('Validate generated text'), names.index('Open or update pull request'))
            self.assertGreaterEqual(workflow['jobs']['update']['timeout-minutes'], 210)

    def test_missing_matrix_and_omitted_explicit_image_block(self):
        needs = self.needs(True, ['bluefin-next'])
        needs['checks']['outputs'] = {}
        self.assertTrue(gate.failures(needs, False))
        needs = self.needs(True, ['bluefin-next'])
        needs['checks']['outputs'] = {'images': 'false', 'matrix': '{"include":[]}'}
        self.assertTrue(gate.failures(needs, False))


if __name__ == '__main__':
    unittest.main()
