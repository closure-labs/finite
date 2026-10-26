#!/usr/bin/env python3
"""Early KVM failure, descriptor cleanup and retained host evidence."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vm_host', ROOT / 'scripts/ci/vm-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class KvmProbe(unittest.TestCase):
    def device(self):
        return patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFCHR))

    def test_usable_kvm_requires_api_and_empty_vm_and_releases_both_descriptors(self):
        with self.device(), patch.object(host.os, 'open', return_value=7) as opened, \
                patch.object(host.fcntl, 'ioctl', side_effect=[12, 9]) as ioctl, \
                patch.object(host.os, 'close') as close:
            result = host.probe()
        self.assertTrue(result['usable'])
        self.assertTrue(result['emptyVmCreated'])
        opened.assert_called_once_with(Path('/dev/kvm'), os.O_RDWR | os.O_CLOEXEC)
        self.assertEqual(ioctl.call_args_list, [call(7, 0xAE00, 0), call(7, 0xAE01, 0)])
        self.assertEqual(close.call_args_list, [call(9), call(7)])

    def test_missing_and_non_device_paths_never_open_kvm(self):
        for status in (FileNotFoundError(errno.ENOENT, 'missing'), SimpleNamespace(st_mode=stat.S_IFREG)):
            with patch.object(Path, 'stat', **({'side_effect': status} if isinstance(status, Exception)
                                              else {'return_value': status})), \
                    patch.object(host.os, 'open') as opened:
                result = host.probe()
            self.assertFalse(result['usable'])
            self.assertEqual(result['stage'], 'device')
            opened.assert_not_called()

    def test_permission_and_vm_creation_failures_remain_distinct(self):
        with self.device(), patch.object(host.os, 'open', side_effect=PermissionError(errno.EACCES, 'denied')):
            denied = host.probe()
        self.assertEqual((denied['stage'], denied['error']), ('open', 'EACCES'))
        for responses, stage, error in [([11], 'api-version', 'unsupported-api-version'),
                                         ([OSError(errno.ENOTTY, 'unsupported')], 'api-version', 'ENOTTY'),
                                         ([12, OSError(errno.ENODEV, 'unavailable')], 'create-empty-vm', 'ENODEV')]:
            with self.device(), patch.object(host.os, 'open', return_value=7), \
                    patch.object(host.fcntl, 'ioctl', side_effect=responses), patch.object(host.os, 'close') as close:
                result = host.probe()
            self.assertFalse(result['usable'])
            self.assertEqual((result['stage'], result['error']), (stage, error))
            close.assert_called_once_with(7)


class Evidence(unittest.TestCase):
    def test_capacity_reuses_cgroup_aware_budget_and_keeps_unknown_explicit(self):
        for detect, expected in [(lambda: (2, 7 * 1024 ** 3), (2, 7 * 1024 ** 3)),
                                 (unittest.mock.Mock(side_effect=OSError()), (None, None))]:
            with patch.object(host.runpy, 'run_path', return_value={'detect': detect}):
                result = host.capacity()
            self.assertEqual((result['effectiveCpuCount'], result['effectiveMemoryBytes']), expected)
            self.assertEqual(result['error'], None if expected[0] else 'OSError')

    def test_success_and_failure_write_origin_and_never_dump_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'evidence/host.json'
            for usable, status in [(True, 0), (False, 1)]:
                with patch.object(sys, 'argv', ['vm-host.py', '--output', str(output)]), \
                        patch.object(host, 'probe', return_value={'usable': usable}), \
                        patch.object(host, 'capacity', return_value={}), \
                        patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                                                'PROFILE': 'finite', 'PHASE': 'upgrade',
                                                'REGISTRY_TOKEN': 'do-not-export-this'}):
                    self.assertEqual(host.main(), status)
                record = json.loads(output.read_text())
                self.assertEqual((record['runId'], record['runAttempt'], record['phase']), ('123', '2', 'upgrade'))
                self.assertFalse(record['authorizesPublication'])
                self.assertNotIn('do-not-export-this', output.read_text())

    def test_workflow_checks_before_expensive_setup_and_keeps_failure_evidence(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())['jobs']
        steps = jobs['phase']['steps']
        probe = next(i for i, step in enumerate(steps) if step.get('name') == 'Verify KVM and record runner capacity')
        setup = next(i for i, step in enumerate(steps) if step.get('uses') == '$/.github/actions/setup-nix')
        self.assertLess(probe, setup)
        self.assertNotIn('continue-on-error', steps[probe])
        self.assertIn('timeout 20s', steps[probe]['run'])
        for job, name in [('phase', 'Save phase evidence'), ('aggregate', 'Save qualification evidence')]:
            upload = next(step for step in jobs[job]['steps'] if step.get('name') == name)
            self.assertEqual(upload['if'], 'always()')
            self.assertIn('.bluebuild/*-vm-host.json', upload['with']['path'].splitlines())
        guest = (ROOT / 'scripts/bluebuild/vm-acceptance.sh').read_text()
        self.assertIn("-enable-kvm -machine 'q35,smm=on' -cpu host -smp 2 -m 4096", guest)

    def test_probe_changes_require_vm_validation_and_invalidate_qualification_reuse(self):
        sys.path.insert(0, str(ROOT / 'scripts/ci'))
        import impact
        path = 'scripts/ci/vm-host.py'
        self.assertEqual(impact.classify([path]), {'checks': True, 'nix': False, 'profiles': []})
        vm_spec = importlib.util.spec_from_file_location('vm_selection', ROOT / 'scripts/ci/vm-selection.py')
        vm = importlib.util.module_from_spec(vm_spec)
        vm_spec.loader.exec_module(vm)
        self.assertTrue(vm.required([path]))
        context_spec = importlib.util.spec_from_file_location('qualification_context', ROOT / 'scripts/bluebuild/qualification-context.py')
        context = importlib.util.module_from_spec(context_spec)
        context_spec.loader.exec_module(context)
        inputs = context.source_inputs()
        self.assertIn(path, inputs)
        with patch.object(context, 'sha', side_effect=lambda p: 'changed' if p == ROOT / path else inputs[str(p.relative_to(ROOT))]['sha256']):
            self.assertNotEqual(context.source_inputs(), inputs)


if __name__ == '__main__':
    unittest.main()
