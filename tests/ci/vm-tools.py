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


benchmark = load('vm_benchmark_test', 'scripts/ci/benchmark-vm-tools.py')
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

    def test_workflows_share_tools_and_benchmark_is_read_only(self):
        for name in ('image', 'qualification', 'vm-acceptance'):
            value = yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())
            uses = [step.get('uses') for job in value['jobs'].values() for step in job.get('steps', [])]
            self.assertIn('./.github/actions/setup-vm-tools', uses)
            self.assertIn('./.github/actions/setup-nix', uses)
            self.assertNotIn('apt-get install', (ROOT / '.github/workflows' / (name + '.yml')).read_text())
        value = yaml.safe_load((ROOT / '.github/workflows/benchmark-vm-tools.yml').read_text())
        self.assertEqual(value['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(len(value['jobs']['benchmark']['strategy']['matrix']['include']), 9)
        self.assertNotIn('secrets.', (ROOT / '.github/workflows/benchmark-vm-tools.yml').read_text())
        self.assertNotIn('ready_for_review', (ROOT / '.github/workflows/benchmark-vm-tools.yml').read_text())
        for job in value['jobs'].values():
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/upload-artifact@'):
                    self.assertTrue(step['with']['include-hidden-files'], 'Reports under .bluebuild must remain visible to uploads')


class Measurements(unittest.TestCase):
    def fixture(self, directory):
        reports, jobs = [], []
        for provider in benchmark.PROVIDERS:
            for repetition in (1, 2, 3):
                cold = {'apt': 100, 'apt-minimal': 90, 'nix': 40}[provider]
                report = {'schema': 1, 'provider': provider, 'repetition': repetition, 'revision': 'a' * 40,
                          'proposalRevision': 'b' * 40, 'runId': '123', 'runAttempt': '2', 'lockSha256': 'c' * 64,
                          'nixVersion': 'Nix fixture', 'status': 'success',
                          'runner': {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageVersion': 'image-1'},
                          'setup': {'seconds': 40}, 'passes': [
                              {'phase': phase, 'seconds': cold if phase == 'cold' else 2,
                               'identity': {'provider': provider}, 'transport': {'receivedBytes': 1000}}
                              for phase in ('cold', 'warm')]}
                reports.append(report)
                jobs.append({'name': f'vm-tools-{provider}-{repetition}', 'status': 'completed', 'conclusion': 'success',
                             'run_id': 123, 'run_attempt': 2, 'head_sha': 'b' * 40,
                             'started_at': '2026-10-22T00:00:00Z',
                             'completed_at': '2026-10-22T00:03:00Z' if provider == 'nix' else '2026-10-22T00:04:00Z'})
        return reports, jobs

    def summarize(self, mutate=lambda reports, jobs: None):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reports, jobs = self.fixture(directory)
            mutate(reports, jobs)
            for index, report in enumerate(reports):
                path = directory / str(index) / 'benchmark.json'
                path.parent.mkdir()
                path.write_text(json.dumps(report))
            metadata = directory / 'jobs'
            metadata.write_text(json.dumps([{'jobs': jobs}]))
            with patch.dict(os.environ, {}, clear=True):
                return benchmark.summarize(directory, metadata, directory / 'summary.md')

    def test_complete_material_improvement_is_eligible(self):
        self.assertTrue(self.summarize()['faster'])

    def test_slow_or_marginal_nix_stays_draft(self):
        def slow(reports, jobs):
            for report in reports:
                if report['provider'] == 'nix': report['passes'][0]['seconds'] = 89
        self.assertFalse(self.summarize(slow)['faster'])
        def longer(reports, jobs):
            for job in jobs:
                if 'nix' in job['name']: job['completed_at'] = '2026-10-22T00:05:00Z'
        self.assertFalse(self.summarize(longer)['faster'])

    def test_different_runner_images_cannot_authorize_rollout(self):
        self.assertFalse(self.summarize(lambda reports, jobs: reports[-1]['runner'].update(ImageVersion='image-2'))['faster'])

    def test_incomplete_failed_foreign_or_inconsistent_reports_are_terminal(self):
        cases = [lambda reports, jobs: reports.pop(),
                 lambda reports, jobs: reports.append(copy.deepcopy(reports[0])),
                 lambda reports, jobs: reports[0].update(status='error'),
                 lambda reports, jobs: reports[0].update(runAttempt='1'),
                 lambda reports, jobs: jobs[0].update(conclusion='failure'),
                 lambda reports, jobs: jobs[0].update(head_sha='d' * 40),
                 lambda reports, jobs: reports[0]['passes'][0].update(seconds=float('nan')),
                 lambda reports, jobs: reports[0]['passes'][0].update(seconds=10000),
                 lambda reports, jobs: reports[0]['passes'][1].update(identity={'changed': True})]
        for mutate in cases:
            with self.subTest(case=cases.index(mutate)), self.assertRaises(ValueError):
                self.summarize(mutate)


if __name__ == '__main__':
    unittest.main()
