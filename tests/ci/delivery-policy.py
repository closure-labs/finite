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


class DeliveryPolicy(unittest.TestCase):
    def test_all_external_actions_are_allowed_without_verified_publisher_bypass(self):
        policy = json.loads((ROOT / 'automation/github/repository-security.json').read_text())['actions']
        selected = policy['selected_actions']
        self.assertFalse(selected['verified_allowed'])
        for path in (ROOT / '.github').rglob('*.yml'):
            for action in re.findall(r'\buses:\s*([^\s#]+)', path.read_text()):
                if action.startswith('./'):
                    continue
                with self.subTest(path=path, action=action):
                    self.assertRegex(action, r'@[0-9a-f]{40}$')
                    permitted = selected['github_owned_allowed'] and action.startswith('actions/')
                    self.assertTrue(permitted or any(fnmatch.fnmatchcase(action, pattern)
                                                    for pattern in selected['patterns_allowed']), action)

    def test_validation_fits_queue_and_updater_deadlines(self):
        jobs = workflow('build')['jobs']
        # Docs run alongside impact; images start after both and Nix checks.
        critical = max(jobs['impact']['timeout-minutes'], jobs['docs']['timeout-minutes'])
        critical += jobs['checks']['timeout-minutes']
        critical += workflow('image')['jobs']['build']['timeout-minutes']
        critical += jobs['gate']['timeout-minutes']
        policy = json.loads((ROOT / 'automation/github/policies/main-merge-queue.json').read_text())
        queue = next(rule['parameters']['check_response_timeout_minutes']
                     for rule in policy['rules'] if rule['type'] == 'merge_queue')
        operations = (ROOT / 'lib/ci-applications/dependency-operations.nix').read_text()
        watcher = int(re.search(r'timeout (\d+)m gh run watch', operations)[1])
        self.assertGreaterEqual(queue, critical + 20)
        self.assertGreaterEqual(watcher, critical + 20)
        for name in ('bluefin', 'flake-lock', 'determinate-nix', 'home-release'):
            with self.subTest(updater=name):
                self.assertGreaterEqual(workflow('update-' + name)['jobs']['update']['timeout-minutes'], watcher + 30)

    def test_reconciliation_is_added_only_at_trusted_push_boundary(self):
        steps = workflow('build')['jobs']['impact']['steps']
        reconcile = next(step for step in steps if step.get('id') == 'reconcile')
        self.assertEqual(reconcile['if'], "inputs.reconcile || (github.repository == 'closure-labs/finite' && github.ref == 'refs/heads/main' && github.event_name == 'push')")
        self.assertEqual(reconcile['env']['IMPACT'], '${{ toJSON(steps.impact.outputs) }}')
        impact = next(step for step in steps if step.get('id') == 'impact')
        self.assertEqual(impact['if'], '${{ !inputs.reconcile }}')

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
        self.assertIn('nix shell --file lib/ci-tools.nix ci-repository-security-audit', text)
        self.assertNotIn('nix run', text)
        self.assertIn('ci-repository-security-audit = import', (ROOT / 'lib/ci-tools.nix').read_text())


if __name__ == '__main__':
    unittest.main()
