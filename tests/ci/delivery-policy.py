#!/usr/bin/env python3
"""Keep delivery deadlines and privileged audit boundaries internally consistent."""
import json
import fnmatch
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())


def action_allowed(action, selected):
    if not re.fullmatch(r'[^@\s]+@[0-9a-f]{40}', action):
        return False
    # GitHub's owned-actions setting covers both exact organization names.
    github_owned = action.partition('/')[0] in {'actions', 'github'}
    return (selected['github_owned_allowed'] and github_owned
            or any(fnmatch.fnmatchcase(action, pattern) for pattern in selected['patterns_allowed']))


class DeliveryPolicy(unittest.TestCase):
    def test_all_external_actions_are_allowed_without_verified_publisher_bypass(self):
        policy = json.loads((ROOT / 'automation/github/repository-security.json').read_text())['actions']
        selected = policy['selected_actions']
        self.assertFalse(selected['verified_allowed'])
        for path in (ROOT / '.github').rglob('*.yml'):
            for action in re.findall(r'\buses:\s*([^\s#]+)', path.read_text()):
                if action.startswith('$/'):
                    continue
                with self.subTest(path=path, action=action):
                    self.assertRegex(action, r'@[0-9a-f]{40}$')
                    self.assertTrue(action_allowed(action, selected), action)

    def test_github_owned_actions_require_exact_owner(self):
        selected = {'github_owned_allowed': True, 'patterns_allowed': []}
        sha = '9b3254085494b55a0f7c4c2b3d2d52cc712ce370'
        for action in ('github/codeql-action/init@' + sha,
                       'github/codeql-action/analyze@' + sha,
                       'actions/checkout@' + 'a' * 40):
            with self.subTest(action=action):
                self.assertTrue(action_allowed(action, selected))
        for owner in ('github-evil', 'actions-evil', 'unrelated'):
            with self.subTest(owner=owner):
                self.assertFalse(action_allowed(owner + '/checkout@' + sha, selected))

    def test_allowed_actions_still_require_full_sha(self):
        selected = {'github_owned_allowed': True, 'patterns_allowed': ['unrelated/action@*']}
        for action in ('github/codeql-action/init', 'actions/checkout', 'unrelated/action'):
            for ref in ('v1', 'a' * 39, 'a' * 41, 'g' * 40):
                with self.subTest(action=action, ref=ref):
                    self.assertFalse(action_allowed(action + '@' + ref, selected))

    def test_disabled_owned_actions_require_explicit_allowlist(self):
        selected = {'github_owned_allowed': False, 'verified_allowed': True, 'patterns_allowed': []}
        for action in ('github/codeql-action/init', 'actions/checkout', 'unrelated/action'):
            action += '@' + 'a' * 40
            with self.subTest(action=action):
                self.assertFalse(action_allowed(action, selected))
                self.assertTrue(action_allowed(action, {**selected, 'patterns_allowed': [action]}))

    def test_validation_fits_native_queue_deadline(self):
        jobs = workflow('build')['jobs']
        # Docs run alongside impact; images start after both and Nix checks.
        critical = max(jobs['impact']['timeout-minutes'], jobs['docs']['timeout-minutes'])
        critical += jobs['checks']['timeout-minutes']
        critical += workflow('image')['jobs']['build']['timeout-minutes']
        critical += jobs['gate']['timeout-minutes']
        policy = json.loads((ROOT / 'automation/github/policies/main-merge-queue.json').read_text())
        queue = next(rule['parameters']['check_response_timeout_minutes']
                     for rule in policy['rules'] if rule['type'] == 'merge_queue')
        self.assertGreaterEqual(queue, critical + 20)

    def test_updater_continuation_is_bounded_and_never_substitutes_for_native_checks(self):
        operations = (ROOT / 'lib/ci-applications/dependency-operations.nix').read_text()
        helper = operations.split('queueDependabot =', 1)[0]
        self.assertIn('timeout 60s gh pr view', helper)
        self.assertIn('timeout 60s gh pr merge', helper)
        self.assertIn('--match-head-commit "$head_sha"', helper)
        for forbidden in ('gh run ', 'gh workflow run', 'gh pr update-branch', '/approve', '--admin', 'sleep '):
            with self.subTest(operation=forbidden):
                self.assertNotIn(forbidden, helper)

    def test_reconciliation_is_added_only_at_trusted_push_boundary(self):
        steps = workflow('build')['jobs']['impact']['steps']
        reconcile = next(step for step in steps if step.get('id') == 'reconcile')
        self.assertEqual(reconcile['if'], "inputs.reconcile || (github.repository == 'closure-labs/finite' && github.ref == 'refs/heads/main' && github.event_name == 'push')")
        self.assertEqual(reconcile['env']['IMPACT'], '${{ toJSON(steps.impact.outputs) }}')
        impact = next(step for step in steps if step.get('id') == 'impact')
        self.assertEqual(impact['if'], "${{ !inputs.reconcile && steps.target.outputs.selected != 'true' }}")

    def test_audit_is_read_only_and_never_uses_update_credential(self):
        audit = workflow('repository-security')
        self.assertEqual(audit['permissions'], {'contents': 'read'})
        job = audit['jobs']['audit']
        self.assertEqual(job['if'], "github.repository == 'closure-labs/finite' && github.ref == 'refs/heads/main'")
        text = (ROOT / '.github/workflows/repository-security.yml').read_text()
        self.assertIn('vars.SECAUDIT_CLIENTID', text)
        self.assertIn('secrets.SECAUDIT_PEM', text)
        token = next(step for step in job['steps'] if step.get('id') == 'audit-token')
        self.assertEqual(token['with']['permission-administration'], 'read')
        self.assertEqual(token['with']['owner'], '${{ github.repository_owner }}')
        self.assertEqual(token['with']['repositories'], '${{ github.event.repository.name }}')
        self.assertNotIn('skip-token-revoke', token['with'])
        audit_step = next(step for step in job['steps'] if step.get('name') == 'Compare live settings with reviewed policy')
        self.assertEqual(audit_step['env']['GH_TOKEN'], '${{ steps.audit-token.outputs.token }}')
        self.assertNotIn('REPOSITORY_AUDIT_TOKEN', text)
        self.assertNotIn('MERGE_QUEUE_TOKEN', text)
        self.assertNotIn('pull_request', text)
        self.assertIn('nix shell --file lib/ci-tools.nix ci-secrets-run ci-repository-security-audit', text)
        self.assertIn('finite-ci-secrets-run repository-read', audit_step['run'])
        self.assertEqual(token['with']['client-id'], '${{ env.SECAUDIT_CLIENTID }}')
        self.assertEqual(token['with']['private-key'], '${{ env.SECAUDIT_PEM }}')
        self.assertNotIn('nix run', text)
        self.assertIn('ci-repository-security-audit = import', (ROOT / 'lib/ci-tools.nix').read_text())


if __name__ == '__main__':
    unittest.main()
