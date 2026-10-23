#!/usr/bin/env python3
"""Premerge VM selection and local receipts cannot replace production evidence."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
from local_vm import validate_context
import gate
spec = importlib.util.spec_from_file_location('vm_selection', ROOT / 'scripts/ci/vm-selection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())


class Premerge(unittest.TestCase):
    def lock(self):
        return {'version': 7, 'root': 'root', 'nodes': {
            'root': {'inputs': {'nixpkgs': 'nixpkgs'}},
            'nixpkgs': {'original': {'type': 'github', 'owner': 'NixOS', 'repo': 'nixpkgs', 'ref': 'stable'},
                        'locked': {'type': 'github', 'owner': 'NixOS', 'repo': 'nixpkgs',
                                   'rev': 'a' * 40, 'narHash': 'sha256-fixture'},
                        'inputs': {'self': ['nixpkgs']}}}}

    def test_only_original_reference_metadata_is_ignored(self):
        before = self.lock()
        after = copy.deepcopy(before)
        del after['nodes']['nixpkgs']['original']['ref']
        self.assertEqual(selection.resolved_lock(before), selection.resolved_lock(after))
        self.assertFalse(selection.required(['flake.lock'], lock_metadata_only=True))
        self.assertTrue(selection.required(['flake.lock', 'files/installer/install_finite_fstab'], lock_metadata_only=True))
        for field, value in [('rev', 'b' * 40), ('narHash', 'sha256-changed'), ('repo', 'other')]:
            changed = copy.deepcopy(after)
            changed['nodes']['nixpkgs']['locked'][field] = value
            self.assertNotEqual(selection.resolved_lock(before), selection.resolved_lock(changed))
        self.assertNotEqual(selection.resolved_lock(before),
                            selection.resolved_lock({**after, 'extra': 'future-significant-field'}))
        renamed = copy.deepcopy(after)
        renamed['nodes']['new-root'] = renamed['nodes'].pop('root')
        renamed['root'] = 'new-root'
        self.assertNotEqual(selection.resolved_lock(before), selection.resolved_lock(renamed))
        changed = copy.deepcopy(after)
        changed['nodes']['nixpkgs']['inputs']['self'] = ['root']
        self.assertNotEqual(selection.resolved_lock(before), selection.resolved_lock(changed))
        for broken in ({}, {**before, 'version': 8}, {**before, 'version': True},
                       {**before, 'nodes': {'root': {}, 'unresolved': {}}}):
            with self.assertRaises(ValueError):
                selection.resolved_lock(broken)

    def test_lock_comparison_uses_actual_checkout_and_fails_conservatively(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=directory, stderr=subprocess.DEVNULL, text=True).strip()
            git('init')
            git('config', 'user.name', 'CI fixture')
            git('config', 'user.email', 'ci@example.invalid')
            def commit(value):
                (directory / 'flake.lock').write_text(value if isinstance(value, str) else json.dumps(value))
                git('add', 'flake.lock')
                git('commit', '-m', 'fixture')
                return git('rev-parse', 'HEAD')
            before = self.lock()
            base = commit(before)
            after = copy.deepcopy(before)
            del after['nodes']['nixpkgs']['original']['ref']
            proposal = commit(after)
            event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': proposal}}}
            (directory / 'event').write_text(json.dumps(event))
            def run(head, event_name='pull_request', metadata=event):
                (directory / 'event').write_text(json.dumps(metadata))
                output = directory / 'output'
                output.write_text('')
                env = {**os.environ, 'GITHUB_EVENT_NAME': event_name, 'GITHUB_SHA': head,
                       'GITHUB_EVENT_PATH': str(directory / 'event'), 'GITHUB_OUTPUT': str(output),
                       'GITHUB_STEP_SUMMARY': str(directory / 'summary')}
                subprocess.run([sys.executable, str(ROOT / 'scripts/ci/vm-selection.py')],
                               cwd=directory, env=env, check=True, capture_output=True)
                return output.read_text().strip()
            self.assertEqual(run(proposal), 'vm=false')
            self.assertEqual(run(proposal, 'merge_group', {'merge_group': {'base_sha': base, 'head_sha': proposal}}), 'vm=false')
            # The assembled checkout can contain a newer resolved input than
            # the proposal head. Never compare only the proposal metadata.
            after['nodes']['nixpkgs']['locked']['rev'] = 'b' * 40
            assembled = commit(after)
            self.assertEqual(run(assembled), 'vm=true')
            for broken in ('broken', '{"version":7,"version":7}', '{}'):
                self.assertEqual(run(commit(broken)), 'vm=true')
            self.assertEqual(run('0' * 40), 'vm=true')

    def test_boot_installer_selinux_and_harness_changes_require_vm(self):
        for path in ('files/system/usr/lib/systemd/system/example.service', 'files/installer/install_finite_fstab',
                     'files/system/usr/lib/tmpfiles.d/finite-gdm.conf', 'scripts/bluebuild/check-vm-gdm-labels.sh',
                     'scripts/bluebuild/vm-acceptance.sh', 'tests/nix/nix-systemd.sh', '.github/workflows/image.yml',
                     'lib/vm-tools.nix', 'scripts/ci/vm_tools.py', '.github/actions/setup-vm-tools/action.yml',
                     'sources/bluefin.json', 'files/system/usr/share/selinux/finite.te', 'flake.lock'):
            self.assertTrue(selection.required([path]), path)
        self.assertTrue(selection.required(None))
        self.assertFalse(selection.required(['docs/installation.md', 'README.md']))
        self.assertFalse(selection.required(['scripts/ci/decision-health.py']))

    def test_local_receipts_require_premerge_context_and_exact_checkout(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
               'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/pull/5/merge',
               'GITHUB_SHA': 'a' * 40, 'FINITE_LOCAL_VM_VALIDATION': 'true'}
        receipt = {'localValidation': True, 'sourceRevision': 'a' * 40, 'profile': 'finite',
                   'image': 'local-image@sha256:' + 'b' * 64, 'installationTag': 'localhost/finite-validation:v1-1'}
        self.assertEqual(validate_context(receipt, env), receipt)
        for changes in ({'GITHUB_REF': 'refs/heads/main'}, {'GITHUB_EVENT_NAME': 'push'},
                        {'FINITE_LOCAL_VM_VALIDATION': 'false'}, {'GITHUB_REPOSITORY': 'fork/finite'}):
            with self.assertRaises(ValueError): validate_context(receipt, {**env, **changes})
        for changes in ({'sourceRevision': 'c' * 40}, {'localValidation': False},
                        {'image': 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64}):
            with self.assertRaises(ValueError): validate_context({**receipt, **changes}, env)

    def test_vm_is_in_required_build_path_with_read_only_permissions(self):
        build = workflow('build')
        images = build['jobs']['images']
        self.assertIn("github.event_name != 'pull_request'", images['if'])
        self.assertNotIn("github.event_name != 'merge_group'", images['if'])
        self.assertEqual(images['with']['vm_validation'], "${{ needs.impact.outputs.vm == 'true' }}")
        self.assertFalse(images['with']['publish'])
        self.assertNotIn('secrets', images)
        self.assertEqual(images['permissions'], {'contents': 'read', 'pull-requests': 'read', 'packages': 'read'})
        steps = workflow('image')['jobs']['build']['steps']
        vm = next(step for step in steps if step.get('name', '').startswith('Boot the exact local'))
        self.assertEqual(vm['if'], 'inputs.vm_validation && !inputs.publish')
        self.assertNotIn('env', vm)
        self.assertLess(steps.index(vm), next(i for i, step in enumerate(steps) if step.get('name') == 'Save build evidence'))

    def test_gate_rejects_a_dropped_vm_profile(self):
        needs = {'impact': {'result': 'success', 'outputs': {'checks': 'true', 'nix': 'false', 'profiles': '[]', 'vm': 'true'}},
                 'docs': {'result': 'success'}, 'checks': {'result': 'success', 'outputs': {'images': 'true',
                    'matrix': json.dumps({'include': [{'profile': 'finite', 'channel': 'finite'}]})}},
                 'images': {'result': 'success'}, 'publish': {'result': 'skipped'}}
        self.assertTrue(gate.failures(needs, False, 'merge_group'))
        matrix = {'include': [{'profile': profile, 'channel': profile} for profile in ('finite', 'finite-dev')]}
        needs['checks']['outputs']['matrix'] = json.dumps(matrix)
        self.assertEqual(gate.failures(needs, False, 'merge_group'), [])

    def test_release_and_health_keep_human_boundaries(self):
        prep = workflow('release-set')['jobs']['prepare']['steps']
        readiness = next(i for i, step in enumerate(prep) if step.get('id') == 'readiness')
        self.assertTrue(all('steps.readiness.outputs.ready' in step.get('if', '') for step in prep[readiness + 1:]))
        self.assertIn('environment: release', (ROOT / '.github/workflows/publish-release-set.yml').read_text())
        jobs = workflow('delivery-health')['jobs']
        health = jobs['reconcile']['steps']
        observer = next(step for step in jobs['health']['steps'] if step.get('id') == 'review-token')['with']
        self.assertEqual(observer['permission-actions'], 'read')
        self.assertNotIn('permission-issues', observer)
        self.assertTrue(any('reconcile-delivery.py' in step.get('run', '') for step in health))
        monitor = next(step for step in health if step.get('name', '').startswith('Report audit'))
        self.assertIn('always()', monitor['if'])
        dispatch_token = next(step for step in health if step.get('id') == 'review-token')['with']
        self.assertEqual(dispatch_token['permission-actions'], 'write')
        self.assertEqual(dispatch_token['permission-contents'], 'read')
        self.assertNotIn('permission-packages', dispatch_token)


if __name__ == '__main__':
    unittest.main()
