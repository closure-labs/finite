#!/usr/bin/env python3
"""Premerge VM selection and local receipts cannot replace production evidence."""
import importlib.util
import json
from pathlib import Path
import sys
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
    def test_boot_installer_selinux_and_harness_changes_require_vm(self):
        for path in ('files/system/usr/lib/systemd/system/example.service', 'files/installer/install_finite_fstab',
                     'files/system/usr/lib/tmpfiles.d/finite-gdm.conf', 'scripts/bluebuild/check-vm-gdm-labels.sh',
                     'scripts/bluebuild/vm-acceptance.sh', 'tests/nix/nix-systemd.sh', '.github/workflows/image.yml',
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
        self.assertEqual(images['with']['vm_validation'], "${{ needs.impact.outputs.vm == 'true' }}")
        self.assertFalse(images['with']['publish'])
        self.assertNotIn('secrets', images)
        self.assertEqual(images['permissions'], {'contents': 'read', 'packages': 'read'})
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
        self.assertTrue(gate.failures(needs, False))
        matrix = {'include': [{'profile': profile, 'channel': profile} for profile in ('finite', 'finite-dev')]}
        needs['checks']['outputs']['matrix'] = json.dumps(matrix)
        self.assertEqual(gate.failures(needs, False), [])

    def test_release_and_health_keep_human_boundaries(self):
        prep = workflow('release-set')['jobs']['prepare']['steps']
        readiness = next(i for i, step in enumerate(prep) if step.get('id') == 'readiness')
        self.assertTrue(all('steps.readiness.outputs.ready' in step.get('if', '') for step in prep[readiness + 1:]))
        self.assertIn('environment: release', (ROOT / '.github/workflows/publish-release-set.yml').read_text())
        health = workflow('delivery-health')['jobs']['health']['steps']
        monitor = next(step for step in health if step.get('name', '').startswith('Report audit'))
        self.assertIn('always()', monitor['if'])
        dispatch_token = next(step for step in health if step.get('id') == 'review-token')['with']
        self.assertEqual(dispatch_token['permission-actions'], 'write')
        self.assertEqual(dispatch_token['permission-contents'], 'read')
        self.assertNotIn('permission-packages', dispatch_token)


if __name__ == '__main__':
    unittest.main()
