#!/usr/bin/env python3
"""Security integration boundaries: identity, privileges and supported coverage."""
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github/workflows'


def document(name):
    return yaml.safe_load((WORKFLOWS / (name + '.yml')).read_text())


def uses(step, action):
    return step.get('uses', '').split('@')[0] == action


class Integrations(unittest.TestCase):
    def test_codeql_has_one_nonduplicated_actions_python_matrix(self):
        entries = []
        for path in WORKFLOWS.glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            for name, job in workflow.get('jobs', {}).items():
                if any(uses(step, 'github/codeql-action/init') for step in job.get('steps', [])):
                    entries.append((path.name, name, job))
        self.assertEqual(len(entries), 1, 'Use one CodeQL workflow, disable duplicate default setup at rollout')
        job = entries[0][2]
        self.assertEqual(job['strategy']['matrix']['language'], ['actions', 'python'])
        self.assertEqual(job['permissions'], {'contents': 'read', 'security-events': 'write'})
        init = next(s for s in job['steps'] if uses(s, 'github/codeql-action/init'))
        self.assertEqual(init['with']['languages'], '${{ matrix.language }}')
        self.assertEqual(init['with']['build-mode'], 'none')
        analyze = next(s for s in job['steps'] if uses(s, 'github/codeql-action/analyze'))
        self.assertIn('matrix.language', analyze['with']['category'])

    def test_harden_runner_is_pinned_first_hosted_audit_without_paid_features(self):
        count = 0
        for path in WORKFLOWS.glob('*.yml'):
            workflow = yaml.safe_load(path.read_text())
            for job in workflow.get('jobs', {}).values():
                steps = job.get('steps', [])
                monitors = [i for i, step in enumerate(steps) if uses(step, 'step-security/harden-runner')]
                if not monitors:
                    continue
                count += 1
                self.assertEqual(monitors, [0], path.name)
                monitor = steps[0]
                self.assertRegex(monitor['uses'], r'@[0-9a-f]{40}$')
                self.assertEqual(monitor['with'].get('egress-policy'), 'audit', path.name)
                self.assertNotIn('self-hosted', str(job.get('runs-on', '')))
                self.assertNotIn('api-key', monitor['with'])
                self.assertNotIn('policy', monitor['with'])
        self.assertGreaterEqual(count, 3)

    def test_attestation_is_digest_bound_with_sbom_and_scoped_privileges(self):
        workflow = document('attest-image')
        job = workflow['jobs']['attest']
        permissions = job['permissions']
        for capability in ('id-token', 'attestations', 'packages'):
            self.assertEqual(permissions[capability], 'write')
        self.assertEqual(permissions['contents'], 'read')
        self.assertEqual(permissions['actions'], 'read')
        steps = [s for s in job['steps'] if uses(s, 'actions/attest')]
        self.assertEqual(len(steps), 2)
        for step in steps:
            self.assertRegex(step['uses'], r'@[0-9a-f]{40}$')
            self.assertIn('digest', str(step['with'].get('subject-digest', '')))
            self.assertTrue(step['with'].get('push-to-registry'))
        references = [s for s in steps if s['with'].get('predicate-type') ==
                      'https://github.com/closure-labs/finite/blob/main/docs/automation/sbom-reference-v1.md']
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]['with']['predicate-path'], '.bluebuild/sbom-attestation/sbom-reference.json')
        self.assertTrue(any('--publish-reference' in s.get('run', '') for s in job['steps']))
        self.assertNotIn('COSIGN_PRIVATE_KEY', (WORKFLOWS / 'attest-image.yml').read_text())
        publication = document('publication')
        self.assertIn('attest', publication['jobs']['sign']['needs'])
        self.assertIn('security', publication['jobs']['sign']['needs'])

    def test_review_app_profile_resolution_and_small_token_scope(self):
        job = document('release-set')['jobs']['prepare']
        steps = job['steps']
        token_index = next(i for i, s in enumerate(steps) if uses(s, 'actions/create-github-app-token'))
        token = steps[token_index]['with']
        self.assertEqual(token['repositories'], '${{ github.event.repository.name }}')
        self.assertEqual({k: v for k, v in token.items() if k.startswith('permission-')},
                         {'permission-administration': 'read', 'permission-actions': 'read',
                          'permission-contents': 'write', 'permission-pull-requests': 'write',
                          'permission-members': 'read'})
        self.assertTrue(any('--profile review-app' in s.get('run', '') and '--scope review-app' in s['run']
                            for s in steps[:token_index]))
        self.assertIn('FINITE_REVIEW_PRIVATE_KEY=\\n', steps[token_index + 1]['run'])
        proposal = steps[-1]
        self.assertEqual(proposal['env']['REGISTRY_TOKEN'], '${{ github.token }}')
        self.assertEqual(proposal['env']['GH_TOKEN'], '${{ steps.decision-app.outputs.token }}')
        self.assertIn('propose --kind release-set', proposal['run'])

    def test_official_bundle_has_one_isolated_signer_and_distinct_publisher_credentials(self):
        workflow = document('publish-release-set')
        self.assertEqual(workflow['concurrency']['group'], 'finite-official-release')
        jobs = workflow['jobs']
        self.assertEqual(jobs['sign']['environment'], 'release')
        self.assertEqual(jobs['sign']['needs'], 'prepare')
        self.assertEqual(jobs['publish']['needs'], ['prepare', 'sign'])
        self.assertEqual(jobs['prepare']['permissions']['contents'], 'read')
        self.assertEqual(jobs['sign']['permissions']['contents'], 'read')
        self.assertEqual(jobs['publish']['permissions']['contents'], 'read')
        sign_steps = jobs['sign']['steps']
        key_step = next(i for i, step in enumerate(sign_steps) if 'COSIGN_PRIVATE_KEY' in step.get('env', {}))
        self.assertTrue(any('execute-release-set.py check' in step.get('run', '') for step in sign_steps[:key_step]))
        self.assertNotIn('nix develop', sign_steps[key_step]['run'])
        self.assertIn('finite-ci-secrets-run release-signing', sign_steps[key_step]['run'])
        for job in ('prepare', 'publish'):
            self.assertFalse(any('COSIGN_PRIVATE_KEY' in step.get('env', {}) for step in jobs[job]['steps']))
        publisher = jobs['publish']['steps'][-1]
        self.assertNotEqual(publisher['env']['GH_TOKEN'], publisher['env']['RELEASE_PUBLISH_TOKEN'])
        self.assertTrue(any('execute-release-set.py download' in step.get('run', '') for step in jobs['publish']['steps']))
        self.assertEqual(publisher['env']['RELEASE_PUBLISH_TOKEN'], '${{ secrets.MERGE_QUEUE_PAT }}')
        self.assertIn('finite-ci-secrets-run release-set-publishing', publisher['run'])
        self.assertNotIn('nix develop', publisher['run'])
        for name in ('prepare', 'sign'):
            self.assertNotIn('MERGE_QUEUE_PAT', str(jobs[name]))

    def test_app_manifest_limits_organization_access_to_members_read(self):
        manifest = json.loads((ROOT / 'automation/github/apps/maintainer-decisions.json').read_text())
        self.assertFalse(manifest['hook_attributes']['active'])
        self.assertEqual(manifest['default_events'], [])
        self.assertEqual(manifest['default_permissions'], {
            'administration': 'read', 'actions': 'write', 'checks': 'write',
            'contents': 'write', 'issues': 'write', 'pull_requests': 'write', 'members': 'read'})
        docs = (ROOT / 'docs/maintainer-decision-app.md').read_text()
        self.assertIn('select **only finite**', docs)
        self.assertIn('No Workflows write', docs)
        self.assertIn('Keep cl-sec-audit read-only', docs)

    def test_long_release_transfers_precede_fresh_authority_credentials(self):
        jobs = document('publish-release-set')['jobs']
        for name in ('prepare', 'sign', 'publish'):
            steps = jobs[name]['steps']
            transfer = next(i for i, step in enumerate(steps) if
                            ('execute-release-set.py stage' if name == 'prepare' else 'execute-release-set.py download')
                            in step.get('run', ''))
            fresh = next(i for i, step in enumerate(steps) if step.get('id') == 'authority-token')
            self.assertLess(transfer, fresh, name)
            self.assertIn('FINITE_REVIEW_PRIVATE_KEY=\\n', steps[fresh + 1]['run'])
            authority_steps = [step for step in steps[fresh + 1:] if step.get('env', {}).get('GH_TOKEN') ==
                               '${{ steps.authority-token.outputs.token }}']
            self.assertTrue(authority_steps, name)
        stage = next(step for step in jobs['prepare']['steps'] if 'execute-release-set.py stage' in step.get('run', ''))
        self.assertEqual(stage['env']['ARTIFACT_READ_TOKEN'], '${{ github.token }}')
        rescan = next(step for step in jobs['prepare']['steps'] if step.get('id') == 'prepare')
        self.assertIn('prepare --staged', rescan['run'])
        self.assertNotIn('ARTIFACT_READ_TOKEN', rescan['env'])

    def test_publication_stages_then_renews_before_commit_and_downloads_use_job_token(self):
        jobs = document('publish-release-set')['jobs']
        self.assertEqual([jobs[name]['timeout-minutes'] for name in ('prepare', 'sign', 'publish')], [240, 180, 240])
        for name in ('sign', 'publish'):
            transfer = next(step for step in jobs[name]['steps'] if 'execute-release-set.py download' in step.get('run', ''))
            self.assertEqual(transfer['env']['ARTIFACT_READ_TOKEN'], '${{ github.token }}')
        steps = jobs['publish']['steps']
        stage = next(i for i, step in enumerate(steps) if 'execute-release-set.py stage-publication' in step.get('run', ''))
        fresh = next(i for i, step in enumerate(steps) if step.get('id') == 'commit-authority-token')
        commit = next(i for i, step in enumerate(steps) if 'execute-release-set.py commit-publication' in step.get('run', ''))
        self.assertLess(stage, fresh)
        self.assertLess(fresh, commit)
        self.assertIn('FINITE_REVIEW_PRIVATE_KEY=\\n', steps[fresh + 1]['run'])
        self.assertEqual(steps[commit]['env']['GH_TOKEN'], '${{ steps.commit-authority-token.outputs.token }}')
        self.assertTrue(all(value == 'read' for key, value in steps[fresh]['with'].items() if key.startswith('permission-')))

    def test_all_decision_and_release_tokens_can_verify_the_pinned_team(self):
        for name in ('decision-authority', 'decision-proposals', 'release-set', 'publish-release-set'):
            for job in document(name)['jobs'].values():
                for step in job.get('steps', []):
                    if uses(step, 'actions/create-github-app-token'):
                        self.assertEqual(step['with']['permission-members'], 'read', name)
                        self.assertEqual(step['with']['repositories'], '${{ github.event.repository.name }}')
        rules = json.loads((ROOT / 'automation/github/repository-security.json').read_text())
        for name in ('release', 'package-cleanup'):
            reviewers = next(rule['reviewers'] for rule in rules['environments'][name]['protection_rules']
                             if rule['type'] == 'required_reviewers')
            self.assertEqual(reviewers, [{'type': 'Team', 'id': 20196962}])


if __name__ == '__main__':
    unittest.main()
