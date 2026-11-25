#!/usr/bin/env python3
"""Validate VM provenance and the measured, read-only rollout decision."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import vm_tools


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qualification = load('vm_qualification_test', 'scripts/bluebuild/qualification-context.py')


class Tools(unittest.TestCase):
    def test_nix_profile_requires_one_named_output_and_preserves_host_tools(self):
        root = '/nix/store/' + 'a' * 32 + '-finite-ci-vm-tools'
        with patch.object(vm_tools.subprocess, 'check_output', return_value=root + '\n') as command:
            env = vm_tools.provision('nix')
        self.assertEqual(env['PATH'].split(os.pathsep)[0], root + '/bin')
        self.assertEqual(env['FINITE_VM_FIRMWARE_DIR'], root + '/share/finite-vm/firmware')
        self.assertIn('--file', command.call_args.args[0])
        for bad in ('/tmp/other', root + '\n' + root, root + '\nINJECT=value', ''):
            with patch.object(vm_tools.subprocess, 'check_output', return_value=bad), self.assertRaises(ValueError):
                vm_tools.provision('nix')

    def test_apt_lanes_differ_only_in_recommended_packages(self):
        for provider in ('apt', 'apt-minimal'):
            with patch.object(vm_tools.subprocess, 'run') as run:
                env = vm_tools.provision(provider)
            self.assertEqual(run.call_args_list[0].args[0], ['sudo', 'apt-get', 'update'])
            self.assertEqual('--no-install-recommends' in run.call_args_list[1].args[0], provider == 'apt-minimal')
            self.assertEqual(env['FINITE_VM_FIRMWARE_DIR'], '/usr/share/OVMF')
            self.assertNotIn('FINITE_VM_TOOLS_MANIFEST', env)

    def test_identity_checks_actual_executables_and_firmware(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('code', 'variables'):
                (directory / name).write_text(name)
            (directory / 'OVMF_CODE_4M.secboot.fd').symlink_to(directory / 'code')
            (directory / 'OVMF_VARS_4M.ms.fd').symlink_to(directory / 'variables')
            expected = {name: '/nix/store/' + 'a' * 32 + '-fixture/bin/' + name for name in vm_tools.TOOLS}
            value = {'schema': 1, 'provider': 'nix', 'executables': {
                name: {'path': path, 'version': '1.0'} for name, path in expected.items()},
                'firmware': {'secureBoot': True, 'code': str(directory / 'code'), 'variables': str(directory / 'variables')}}
            manifest = directory / 'manifest'
            manifest.write_text(json.dumps(value))
            env = {'PATH': '/fixture', 'FINITE_VM_TOOLS_MANIFEST': str(manifest), 'FINITE_VM_FIRMWARE_DIR': temporary}
            with patch.object(vm_tools.shutil, 'which', side_effect=lambda name, **_: expected[name]), \
                    patch.object(vm_tools, 'digest', return_value='hash'):
                identity = vm_tools.identity(env)
                self.assertTrue(all(record['sha256'] == 'hash' for record in identity['executables'].values()))
                (directory / 'OVMF_CODE_4M.secboot.fd').unlink()
                (directory / 'OVMF_CODE_4M.secboot.fd').symlink_to(directory / 'variables')
                with self.assertRaisesRegex(ValueError, 'firmware'):
                    vm_tools.identity(env)
            with patch.object(vm_tools.shutil, 'which', return_value='/tmp/foreign-tool'), \
                    self.assertRaisesRegex(ValueError, 'executable'):
                vm_tools.identity(env)
            manifest.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                vm_tools.identity(env)

    def test_nix_context_records_native_identity_without_dpkg(self):
        value = {'provider': 'nix', 'executables': {'qemu': 'pinned'}}
        with patch.dict(os.environ, {'FINITE_VM_TOOLS_MANIFEST': '/fixture/manifest', 'FINITE_VM_FIRMWARE_DIR': '/fixture/fw'}), \
                patch.object(qualification, 'validate_certificate'), patch.object(qualification, 'source_inputs', return_value={}), \
                patch.object(qualification, 'sha', return_value='hash') as sha, \
                patch.object(vm_tools, 'identity', return_value=value), \
                patch.object(qualification.subprocess, 'check_output', side_effect=AssertionError('No dpkg for Nix')):
            context = qualification.context()
        self.assertEqual(json.loads(context['packages']), value)
        self.assertEqual(str(sha.call_args_list[0].args[0]), '/fixture/fw/OVMF_CODE_4M.secboot.fd')

    def test_workflows_share_tools(self):
        for name in ('image', 'qualification', 'vm-acceptance'):
            value = yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())
            uses = [step.get('uses') for job in value['jobs'].values() for step in job.get('steps', [])]
            self.assertIn('$/.github/actions/setup-vm-tools', uses)
            self.assertIn('$/.github/actions/setup-nix', uses)
            self.assertNotIn('apt-get install', (ROOT / '.github/workflows' / (name + '.yml')).read_text())


if __name__ == '__main__':
    unittest.main()
