#!/usr/bin/env python3
"""No package manager mutations: mock the bounded transaction boundary."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('remediate', ROOT / 'files/scripts/security-remediate.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
POLICY = mod.load_policy(ROOT / 'files/scripts/security-remediation.json')


class Remediation(unittest.TestCase):
    def test_inventory_preserves_signing_key_pseudo_package(self):
        output = 'gpg-pubkey\t0:38ab71f4-60242b08\t(none)\npython3\t0:3.14.8-1.fc44\tx86_64'
        calls = []
        def runner(command):
            calls.append(command)
            return output
        inventory = mod.inventory(runner)
        self.assertEqual(inventory['gpg-pubkey'], [('0:38ab71f4-60242b08', '(none)')])
        self.assertEqual(inventory['python3'], [('0:3.14.8-1.fc44', 'x86_64')])
        self.assertEqual(calls[0][:2], ['rpm', '-qa'])

    def test_inventory_rejects_other_missing_arch_and_malformed_fields(self):
        for output in ('python3\t0:3.14.8-1.fc44\t(none)', 'gpg-pubkey\tinvalid\t(none)',
                       'python3\t0:3.14.8-1.fc44', 'python3\t0:3.14.8-1.fc44\tx86_64\textra'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'Malformed RPM inventory record:'):
                mod.inventory(lambda command: output)

    def test_native_signing_key_inventory_if_available(self):
        import shutil
        if not shutil.which('rpm'):
            self.skipTest('RPM not present')
        result = subprocess.run(['rpm', '-q', 'gpg-pubkey', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n'],
                                text=True, capture_output=True)
        if result.returncode:
            self.skipTest('No installed signing-key pseudo-package')
        inventory = mod.inventory(lambda command: result.stdout.strip())
        self.assertTrue(inventory['gpg-pubkey'])

    def test_reviewed_targets(self):
        self.assertEqual(set(POLICY['packages']), {
            'hplip', 'hplip-common', 'hplip-libs', 'libsane-hpaio',
            'python-unversioned-command', 'python3', 'python3-libs',
            'libX11', 'libX11-common', 'libX11-xcb',
            'tesseract-common', 'tesseract-libs', 'freerdp-libs', 'libwinpr',
            'sudo', 'sudo-python-plugin', 'curl', 'libcurl', 'libcurl-minimal',
        })

    def exercise(self, after=None, current='0:3.14.7-1.fc44', failure=False):
        before = {'python3': [(current, 'x86_64')], 'kernel-core': [('0:7.2.5-200.fc44', 'x86_64')]}
        if after is None:
            after = copy.deepcopy(before)
            after['python3'] = [('0:3.14.8-1.fc44', 'x86_64')]
        commands = []
        def run(args):
            commands.append(args)
            if args[:2] == ['dnf5', '-y']:
                if failure:
                    raise subprocess.CalledProcessError(1, args)
                return ''
            self.assertEqual(args, ['rpm', '--eval', '%{fedora}'])
            return '44'
        # These fixture versions differ only at one numeric component. Real RPM
        # comparator is independently exercised below when RPM is available.
        with patch.object(mod, 'run', run), patch.object(mod, 'inventory', side_effect=[before, after]), patch.object(mod, 'compare', lambda a, b: (a > b) - (a < b)):
            mod.remediate(POLICY)
        return commands

    def test_installed_only_bounded_transaction(self):
        command = self.exercise()[-1]
        self.assertIn('python3 >= 0:3.14.8-1.fc44', command)
        self.assertFalse(any(arg.startswith('hplip ') for arg in command))
        for arg in ('--disable-repo=*', '--enable-repo=fedora', '--enable-repo=updates', '--setopt=*.gpgcheck=1', '--setopt=*.skip_if_unavailable=False', '--no-allow-downgrade', '--exclude=kernel*,bootc*,rpm-ostree*,ostree*'):
            self.assertIn(arg, command)
        self.assertNotIn('--allowerasing', command)
        self.assertNotIn('--skip-unavailable', command)

    def test_curl_floor_preserves_the_installed_library_variant(self):
        before = {'curl': [('0:8.18.0-10.fc44', 'x86_64')],
                  'libcurl-minimal': [('0:8.18.0-10.fc44', 'x86_64')],
                  'kernel-core': [('0:7.2.9-201.fc44', 'x86_64')]}
        after = copy.deepcopy(before)
        for name in ('curl', 'libcurl-minimal'):
            after[name] = [('0:8.18.0-12.fc44', 'x86_64')]
        commands = []
        def run(args):
            commands.append(args)
            return '44' if args == ['rpm', '--eval', '%{fedora}'] else ''
        with patch.object(mod, 'run', run), patch.object(mod, 'inventory', side_effect=[before, after]), \
                patch.object(mod, 'compare', lambda a,b: (a>b)-(a<b)):
            mod.remediate(POLICY)
        self.assertIn('curl >= 0:8.18.0-12.fc44', commands[-1])
        self.assertIn('libcurl-minimal >= 0:8.18.0-12.fc44', commands[-1])
        self.assertFalse(any(arg.startswith('libcurl ') for arg in commands[-1]))
        replaced = {key:value for key,value in after.items() if key != 'libcurl-minimal'}
        replaced['libcurl'] = [('0:8.18.0-12.fc44', 'x86_64')]
        with patch.object(mod, 'run', run), patch.object(mod, 'inventory', side_effect=[before, replaced]), \
                patch.object(mod, 'compare', lambda a,b: (a>b)-(a<b)), self.assertRaisesRegex(ValueError, 'floor not satisfied'):
            mod.remediate(POLICY)

    def test_no_network_if_current(self):
        self.assertEqual(len(self.exercise(current='0:3.14.8-1.fc44')), 1)

    def test_missing_package_fails(self):
        with self.assertRaisesRegex(ValueError, 'floor not satisfied'):
            self.exercise(after={'kernel-core': [('0:7.2.5-200.fc44', 'x86_64')]})

    def test_old_package_fails(self):
        with self.assertRaisesRegex(ValueError, 'floor not satisfied'):
            self.exercise(after={'python3': [('0:3.14.7-1.fc44', 'x86_64')], 'kernel-core': [('0:7.2.5-200.fc44', 'x86_64')]})

    def test_boot_stack_changed_fails(self):
        with self.assertRaisesRegex(ValueError, 'protected boot stack'):
            self.exercise(after={'python3': [('0:3.14.8-1.fc44', 'x86_64')]})

    def test_new_vulnerable_family_dependency_fails(self):
        with self.assertRaisesRegex(ValueError, 'floor not satisfied for dependency'):
            self.exercise(after={
                'python3': [('0:3.14.8-1.fc44', 'x86_64')],
                'kernel-core': [('0:7.2.5-200.fc44', 'x86_64')],
                'python3-libs': [('0:3.14.7-1.fc44', 'x86_64')],
            })

    def test_transaction_failure_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise(failure=True)

    def test_invalid_policy(self):
        import json
        for mutate in (lambda p: p.update(schema=True), lambda p: p.update(packages={}), lambda p: p['packages']['python3'].update(minimumEVR='0:1-1.fc45'), lambda p: p['packages'].update({'kernel-core': p['packages']['python3']}), lambda p: p['packages']['python3'].update(minimumEVR='";evil')):
            p = copy.deepcopy(POLICY)
            mutate(p)
            with patch.object(Path, 'read_text', return_value=json.dumps(p)), self.assertRaises(ValueError):
                mod.load_policy('unused')

    def test_lua_injection_rejected(self):
        with self.assertRaises(ValueError):
            mod.compare('";evil', '0:1-1.fc44')

    def test_comparator_fail_closed(self):
        with patch.object(mod, 'run', return_value='unexpected'), self.assertRaises(ValueError):
            mod.compare('0:1-1.fc44', '0:2-1.fc44')

    def test_fedora_drift_fails(self):
        with patch.object(mod, 'run', return_value='45'), self.assertRaises(ValueError):
            mod.remediate(POLICY)

    def test_native_rpm_comparison_if_available(self):
        import shutil
        if not shutil.which('rpm'):
            self.skipTest('RPM not in test environment; command boundary covered by mocks')
        self.assertEqual(mod.compare('2:3.31.1-1.fc44', '2:3.32.1-1.fc44'), -1)
        self.assertEqual(mod.compare('1:1.0-1.fc44', '0:99.0-1.fc44'), 1)
        self.assertEqual(mod.compare('0:1.9.17-8.p2.fc44', '0:1.9.17-10.p2.fc44'), -1)
        self.assertEqual(mod.compare('10:1-1.fc44', '2:99-1.fc44'), 1)
        self.assertEqual(mod.compare('0:1.0~rc1-1.fc44', '0:1.0-1.fc44'), -1)


unittest.main()
