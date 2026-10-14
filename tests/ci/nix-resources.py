#!/usr/bin/env python3
"""Resource sizing, applied configuration and workflow setup coverage."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('resources', ROOT / 'scripts/ci/nix-resources.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class Resources(unittest.TestCase):
    def test_runner_sizes_use_cpu_without_multiplying_threads(self):
        for cpus, gib, expected in [(4, 16, (4, 1, 4)), (2, 8, (2, 1, 2)),
                                    (16, 64, (16, 1, 16)), (16, 16, (5, 3, 7)),
                                    (2, 4, (1, 2, 1)), (1, 1, (1, 1, 1))]:
            with self.subTest(cpus=cpus, gib=gib):
                value = resources.budget(cpus, gib * resources.GIB)
                self.assertEqual(tuple(value.values()), expected)
                self.assertLessEqual(value['max-jobs'] * value['cores'], cpus)

    def test_nested_cgroup_and_ancestor_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, group = root / 'proc', root / 'cgroup'
            (proc / 'self').mkdir(parents=True)
            (group / 'job').mkdir(parents=True)
            (proc / 'meminfo').write_text('MemTotal: 67108864 kB\n')
            (proc / 'self/cgroup').write_text('0::/job\n')
            (group / 'cpu.max').write_text('400000 100000\n')
            (group / 'memory.max').write_text(str(8 * resources.GIB))
            (group / 'job/cpu.max').write_text('200000 100000\n')
            (group / 'job/memory.max').write_text('max\n')
            with patch.object(resources.os, 'sched_getaffinity', return_value=set(range(16))):
                self.assertEqual(resources.detect(proc, group), (2, 8 * resources.GIB))

    def test_verify_rejects_ignored_settings_and_wrong_client(self):
        value = resources.budget(4, 16 * resources.GIB)
        config = {name: {'value': setting} for name, setting in value.items()}
        config['experimental-features'] = {'value': ['parallel-eval']}
        with patch.object(resources.subprocess, 'check_output', side_effect=['nix (Determinate Nix 3.22.2)', json.dumps(config)]):
            resources.verify(value, 'nix')
        config['cores']['value'] = 0
        with patch.object(resources.subprocess, 'check_output', side_effect=['nix (Determinate Nix 3.22.2)', json.dumps(config)]):
            with self.assertRaisesRegex(ValueError, 'cores'):
                resources.verify(value, 'nix')
        with patch.object(resources.subprocess, 'check_output', return_value='nix 2.35'):
            with self.assertRaisesRegex(ValueError, 'Determinate'):
                resources.verify(value, 'nix')

    def test_all_host_nix_jobs_install_before_use(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            document = yaml.safe_load(path.read_text())
            for name, job in document.get('jobs', {}).items():
                installed = False
                for step in job.get('steps', []):
                    uses = step.get('uses', '')
                    if uses == './.github/actions/setup-nix' or uses.startswith('DeterminateSystems/determinate-nix-action@'):
                        installed = True
                    command = step.get('run', '')
                    if re.search(r'\bnix\s+(shell|develop|build|eval|run)\b', command) or 'scripts/ci/nix-checks.py' in command or 'scripts/ci/benchmark-image-tools.py' in command:
                        with self.subTest(workflow=path.name, job=name):
                            self.assertTrue(installed)
                # The setup condition must cover the conditional reconcile step.
                if path.name == 'build.yml' and name == 'impact':
                    setup = next(s for s in job['steps'] if s.get('uses') == './.github/actions/setup-nix')
                    self.assertIn('inputs.reconcile', setup['if'])
                    self.assertIn("github.event_name == 'push'", setup['if'])

    def test_benchmark_and_shared_setup_use_identical_budget(self):
        action = yaml.safe_load((ROOT / '.github/actions/setup-nix/action.yml').read_text())['runs']['steps']
        benchmark = yaml.safe_load((ROOT / '.github/workflows/benchmark-image-tools.yml').read_text())['jobs']['benchmark']['steps']
        for steps in (action, benchmark):
            detect = next(i for i, step in enumerate(steps) if step.get('run') == 'python3 scripts/ci/nix-resources.py')
            install = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('DeterminateSystems/determinate-nix-action@'))
            verify = next(i for i, step in enumerate(steps) if step.get('run') == 'python3 scripts/ci/nix-resources.py --verify')
            self.assertLess(detect, install)
            self.assertLess(install, verify)
            for setting in ('max-jobs', 'cores', 'eval-cores'):
                self.assertIn('${{ steps.resources.outputs.' + setting + ' }}', steps[install]['with']['extra-conf'])


if __name__ == '__main__':
    unittest.main()
