#!/usr/bin/env python3
"""Publication authority uses checked policy and separates registry credentials."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())
JOBS = WORKFLOW['jobs']
TOKEN = '${{ steps.review-token.outputs.token || github.token }}'


def step(job, name):
    return next(item for item in JOBS[job]['steps'] if item.get('name') == name)


class PublicationAuthority(unittest.TestCase):
    def test_checked_policy_controls_all_three_authority_consumers(self):
        for job in ('security', 'sign', 'promote'):
            script = step(job, 'Read checked publication admission policy')['run']
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'scripts/bluebuild').mkdir(parents=True)
                (root / 'scripts/bluebuild/security-policy.py').symlink_to(ROOT / 'scripts/bluebuild/security-policy.py')
                target = root / 'automation/security/image-policy.json'
                target.parent.mkdir(parents=True)
                original = json.loads((ROOT / 'tests/fixtures/legacy-image-security-policy.json').read_text())
                for decision in (False, True):
                    policy = deepcopy(original)
                    if decision:
                        import runpy
                        fields = runpy.run_path(str(ROOT / 'scripts/bluebuild/security-policy.py'))['DECISION_FIELDS']
                        policy = {k: v for k, v in policy.items() if k in fields}
                        policy['mode'] = 'maintainer-decision'
                    target.write_text(json.dumps(policy))
                    output = root / 'output'
                    output.unlink(missing_ok=True)
                    # Repository variables cannot switch authority mode.
                    env = dict(os.environ, GITHUB_OUTPUT=str(output), FINITE_MAINTAINER_DECISION=str(not decision).lower())
                    subprocess.run(['bash', '-e', '-c', script], cwd=root, env=env, check=True, capture_output=True)
                    self.assertEqual(output.read_text(), 'maintainer=' + str(decision).lower() + '\n')
                target.write_text('{"mode":"maintainer-decision"}')
                result = subprocess.run(['bash', '-e', '-c', script], cwd=root, env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    def test_tokens_are_readonly_scoped_and_private_key_is_cleared_even_on_failure(self):
        for job in ('security', 'sign', 'promote'):
            steps = JOBS[job]['steps']
            mint = step(job, 'Generate short-lived read-only authority token')
            self.assertIn("steps.admission-policy.outputs.maintainer == 'true'", mint['if'])
            if job == 'security':
                self.assertIn("inputs.resume_run != ''", mint['if'])
            permissions = {k: v for k, v in mint['with'].items() if k.startswith('permission-')}
            self.assertEqual(permissions, {f'permission-{p}': 'read' for p in ('contents', 'actions', 'pull-requests', 'administration', 'members')})
            self.assertEqual(mint['with']['repositories'], '${{ github.event.repository.name }}')
            resolve = step(job, 'Resolve declared read-only authority App credentials')
            self.assertIn('--profile review-app', resolve['run'])
            self.assertIn('--scope review-app', resolve['run'])
            clear = step(job, 'Clear App private credentials')
            self.assertIn('always()', clear['if'])
            self.assertIn('FINITE_REVIEW_PRIVATE_KEY=\\n', clear['run'])
            self.assertLess(steps.index(mint), steps.index(clear))

    def test_authority_tokens_reach_verifiers_while_registry_and_scan_keep_workflow_token(self):
        for job, name in [('security', 'Revalidate fresh security evidence for a resumed candidate'),
                          ('sign', 'Authenticate native evidence and human admission before signing credentials'),
                          ('promote', 'Promote verified digest to public channels')]:
            self.assertEqual(step(job, name)['env']['GH_TOKEN'], TOKEN)
        for job, name in [('security', 'Revalidate fresh security evidence for a resumed candidate'),
                          ('sign', 'Sign the independently scanned immutable digest'),
                          ('promote', 'Promote verified digest to public channels')]:
            self.assertEqual(step(job, name)['env']['REGISTRY_TOKEN'], '${{ github.token }}')
        scan = step('security', 'Scan exact candidate and enforce image security policy')
        self.assertEqual(scan['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertNotIn('review-token', json.dumps(scan))
        self.assertNotIn('DECIDER_KEY', json.dumps(scan))
        signer = JOBS['sign']['steps']
        self.assertLess(signer.index(step('sign', 'Clear App private credentials')),
                        signer.index(step('sign', 'Sign the independently scanned immutable digest')))

    def test_reusable_secrets_are_optional_for_legacy_and_forwarded_from_build(self):
        # YAML 1.1 parses GitHub's `on` key as True.
        secrets = WORKFLOW.get('on', WORKFLOW.get(True))['workflow_call']['secrets']
        build = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())
        for name in ('DECIDER_KEY', 'DECIDER_CLIENT'):
            self.assertFalse(secrets[name]['required'])
            self.assertEqual(build['jobs']['publish']['secrets'][name], '${{ secrets.' + name + ' }}')


if __name__ == '__main__':
    unittest.main()
