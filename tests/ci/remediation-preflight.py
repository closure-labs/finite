#!/usr/bin/env python3
"""Metadata-only preflight boundary; no repository access or package mutation."""
import importlib.util
import json
import tempfile
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('preflight', ROOT / 'scripts/ci/remediation-preflight.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class Preflight(unittest.TestCase):
    def test_command_is_read_only_and_restricts_repositories(self):
        command = mod.command({'python3', 'sudo'})
        self.assertIn('repoquery', command)
        for forbidden in ('install', 'upgrade', 'download', '--nogpgcheck', '--skip-unavailable'):
            self.assertNotIn(forbidden, command)
        for required in ('--disable-repo=*', '--enable-repo=fedora', '--enable-repo=updates',
                         '--setopt=*.gpgcheck=1', '--setopt=*.skip_if_unavailable=False'):
            self.assertIn(required, command)
        self.assertEqual(command[-2:], ['python3', 'sudo'])

    def test_native_zero_epoch_is_normalized_and_exact_nevra_checked(self):
        result = mod.parse('python3\t3.14.8-1.fc44\tx86_64\tupdates\tpython3-0:3.14.8-1.fc44.x86_64', {'python3'})
        self.assertEqual(result['python3'][0]['evr'], '0:3.14.8-1.fc44')
        for line in ('python3\t3.14.8-1.fc44\tx86_64\tterra\tpython3-0:3.14.8-1.fc44.x86_64',
                     'python3\t3.14.8-1.fc44\tx86_64\tupdates\tother', 'garbled'):
            with self.assertRaises(ValueError): mod.parse(line, {'python3'})

    def test_missing_outdated_and_available_are_distinct(self):
        policy = {'fedora': 44, 'sourceImage': 'fixture', 'packages': {
            'python3': {'minimumEVR': '0:3.14.8-1.fc44'}, 'sudo': {'minimumEVR': '0:1.9.17-10.p2.fc44'}}}
        fixtures = [('', 'missing'),
                    ('python3\t3.14.7-1.fc44\tx86_64\tupdates\tpython3-0:3.14.7-1.fc44.x86_64', 'outdated'),
                    ('python3\t3.14.8-1.fc44\tx86_64\tupdates\tpython3-0:3.14.8-1.fc44.x86_64', 'available')]
        for output, expected in fixtures:
            with patch.object(mod, 'run', return_value=output), patch.object(mod, 'compare', side_effect=lambda a,b,r: (a>b)-(a<b)):
                result = mod.probe(policy, {'packages': {}})
            self.assertEqual(next(x for x in result['findings'] if x['name'] == 'python3')['status'], expected)
            self.assertEqual(result['status'], 'blocked')  # sudo is absent in every fixture
            self.assertEqual(result['scannerResolution'], 'unknown')

    def test_failed_metadata_query_does_not_become_missing_packages(self):
        with patch.object(mod, 'run', side_effect=subprocess.CalledProcessError(1, ['dnf5'])), self.assertRaises(subprocess.CalledProcessError):
            mod.probe({'packages': {}}, {'packages': {}})

    def test_hosted_container_boundary_and_metadata_only_execution(self):
        policy = {'fedora': 44, 'sourceImage': 'fixture', 'packages': {'python3': {'minimumEVR': '0:3.14.8-1.fc44'}}}
        for image in (mod.FEDORA_IMAGE, 'fedora:44'):
            calls = []
            def run(args):
                calls.append(args)
                if args[:2] == ['docker', 'inspect']:
                    return json.dumps([{'Config': {'Image': image}, 'State': {'Running': True}}])
                self.assertEqual(args[:3], ['docker', 'exec', 'finite-fedora-probe'])
                command = args[3:]
                if command == ['cat', '/etc/os-release']: return 'ID=fedora\nVERSION_ID="44"'
                if command[0] == 'dnf5' and 'repoquery' in command:
                    return 'python3\t3.14.8-1.fc44\tx86_64\tupdates\tpython3-0:3.14.8-1.fc44.x86_64'
                if command[:2] == ['rpm', '-qa']: return 'gpg-pubkey\t0:38ab71f4-60242b08\t(none)'
                if command[:2] == ['rpm', '--eval']: return '0'
                if '--version' in command: return 'native version'
                self.fail('Unexpected command: ' + repr(command))
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'result.json'
                with patch.dict(mod.os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(mod, 'run', run), \
                     patch.object(mod.remediation, 'load_policy', return_value=policy), \
                     patch.object(mod, 'load_prerequisites', return_value={**policy, 'packages': {}}), patch('builtins.print'):
                    code = mod.main(['--container', 'finite-fedora-probe', '--output', str(output)])
                report = json.loads(output.read_text())
                self.assertEqual(code, 0 if image == mod.FEDORA_IMAGE else 2)
                self.assertEqual(report['scannerResolution'], 'unknown')
                if image != mod.FEDORA_IMAGE:
                    self.assertEqual(len(calls), 1)
                else:
                    self.assertEqual(report['status'], 'available')  # Missing observational extras do not claim failure/clearance.

    def test_prerequisites_block_even_when_all_package_floors_are_available(self):
        policy = {'fedora': 44, 'sourceImage': 'fixture', 'packages': {'sudo': {'minimumEVR': '0:1.9.17-10.p2.fc44'}}}
        prerequisites = {'packages': {'python3-anyio': {'minimumUpstreamVersion': '4.14.2',
                         'component': 'pkg:pypi/anyio@4.13.0', 'advisories': ['GHSA-82r6-8w77-94w6']}}}
        for available, expected in [('4.13.0', False), ('4.14.2', True)]:
            output = ('sudo\t1.9.17-10.p2.fc44\tx86_64\tupdates\tsudo-0:1.9.17-10.p2.fc44.x86_64\n' +
                      f'python3-anyio\t{available}-1.fc44\tnoarch\tupdates\tpython3-anyio-0:{available}-1.fc44.noarch')
            with patch.object(mod, 'run', return_value=output), patch.object(mod, 'compare', side_effect=lambda a,b,r: (a>b)-(a<b)):
                result = mod.probe(policy, prerequisites)
            self.assertTrue(result['packageFloorsAvailable'])
            self.assertEqual(result['prerequisiteReady'], expected)
            self.assertEqual(result['status'], 'available' if expected else 'blocked')
            self.assertEqual(result['scannerResolution'], 'unknown')

    def test_ordinary_unavailable_fix_does_not_block_reviewed_risk_readiness(self):
        risk = mod.security.load_policy(ROOT / 'automation/security/image-policy.json')
        policy = {'fedora': 44, 'sourceImage': 'fixture', 'packages': {}}
        prerequisites = mod.load_prerequisites(ROOT / 'scripts/ci/remediation-prerequisites.json')
        output = ('python3-anyio\t4.14.2-1.fc44\tnoarch\tupdates\tpython3-anyio-0:4.14.2-1.fc44.noarch\n'
                  'rclone\t1.75.1-1.fc44\tx86_64\tupdates\trclone-0:1.75.1-1.fc44.x86_64\n'
                  'python3-msgpack\t1.1.2-2.fc44\tnoarch\tupdates\tpython3-msgpack-0:1.1.2-2.fc44.noarch')
        with patch.object(mod, 'run', return_value=output), patch.object(mod, 'compare', side_effect=lambda a,b,r: (a>b)-(a<b)):
            current = mod.probe(policy, prerequisites, risk_policy=risk)
            legacy = mod.probe(policy, prerequisites)
        self.assertTrue(current['prerequisiteReady'])
        self.assertFalse(current['allRequestedFixesAvailable'])
        self.assertEqual(current['status'], 'available')
        msgpack = next(row for row in current['prerequisites'] if row['name'] == 'python3-msgpack')
        self.assertEqual(msgpack['status'], 'outdated')
        self.assertFalse(msgpack['blockingUnderCurrentPolicy'])
        self.assertEqual(current['scannerResolution'], 'unknown')
        self.assertEqual(legacy['status'], 'blocked')
        with patch.object(mod, 'run', return_value=output.replace('4.14.2', '4.13.0')), \
                patch.object(mod, 'compare', side_effect=lambda a,b,r: (a>b)-(a<b)):
            serious = mod.probe(policy, prerequisites, risk_policy=risk)
        self.assertFalse(serious['prerequisiteReady'])
        self.assertEqual(serious['status'], 'blocked')

    def test_upstream_comparison_discards_epoch_and_release(self):
        with patch.object(mod, 'compare', return_value=-1) as compare:
            self.assertFalse(mod.upstream_meets('99:4.13.0-999.fc44', '4.14.2', mod.run))
        self.assertEqual(compare.call_args.args[:2], ('0:4.13.0-0', '0:4.14.2-0'))
        with self.assertRaises(ValueError): mod.upstream_meets('0:4.13.0-1.fc44', '";bad', mod.run)

    def test_reviewed_prerequisite_schema_and_advisories(self):
        policy = mod.load_prerequisites(ROOT / 'scripts/ci/remediation-prerequisites.json')
        self.assertEqual(set(policy['packages']), {'python3-anyio', 'python3-msgpack', 'rclone'})
        self.assertEqual(policy['packages']['python3-msgpack']['minimumUpstreamVersion'], '1.2.1')
        with patch.object(Path, 'read_text', return_value='{}'), self.assertRaises(ValueError):
            mod.load_prerequisites(Path('unused'))

    def test_native_rpm_epoch_comparison_when_present(self):
        if not shutil.which('rpm'):
            self.skipTest('No native RPM in this lightweight test environment')
        self.assertGreater(mod.compare('2:1-1.fc44', '0:99-1.fc44', mod.run), 0)
        self.assertLess(mod.compare('0:1~rc1-1.fc44', '0:1-1.fc44', mod.run), 0)


unittest.main()
