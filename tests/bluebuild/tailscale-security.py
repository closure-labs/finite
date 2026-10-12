#!/usr/bin/env python3
"""Vendor authentication and bounded transaction tests; no local RPM mutations."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tailscale_security', ROOT / 'files/scripts/tailscale-security.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
POLICY = mod.load_policy(ROOT / 'files/scripts/tailscale-security.json')
KEY = ROOT / 'files/scripts/tailscale-signing.pub'
OLD = 'tailscale\t0:1.102.5-1\tx86_64\nkernel-core\t0:7.2.5-200.fc44\tx86_64'
NEW = OLD.replace('1.102.5', '1.104.1')
METADATA = 'tailscale\t0:1.104.1-1\tx86_64'
SIGNATURE = ('Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: '
             + POLICY['keyFingerprint'].lower() + ': OK\nHeader SHA256 digest: OK\nPayload SHA256 digest: OK')


class TailscaleSecurity(unittest.TestCase):
    def exercise(self, before=OLD, after=NEW, fedora='44', signature=SIGNATURE,
                 metadata=METADATA, key=KEY, failure=None, payload=b'reviewed RPM', actual_payload=None):
        policy = copy.deepcopy(POLICY)
        policy['sha256'] = hashlib.sha256(payload).hexdigest()
        commands = []
        inventories = iter((before, after))
        def runner(args):
            commands.append(args)
            if failure and failure(args):
                raise subprocess.CalledProcessError(1, args)
            if args == ['rpm', '--eval', '%{fedora}']:
                return fedora
            if args[:2] == ['rpm', '-qa']:
                return next(inventories)
            if '--checksig' in args:
                return signature
            if args[:2] == ['rpm', '-qp']:
                return metadata
            return ''
        def downloader(url, destination, command_runner):
            commands.append(['download', url])
            destination.write_bytes(payload if actual_payload is None else actual_payload)
        mod.remediate(policy, key, runner, downloader, lambda a, b: (a > b) - (a < b))
        return commands

    def test_reviewed_key_digest(self):
        self.assertEqual(mod.digest(KEY), POLICY['keySHA256'])

    def test_authentication_precedes_system_key_and_transaction(self):
        commands = self.exercise()
        signature_index = next(i for i, c in enumerate(commands) if '--checksig' in c)
        metadata_index = next(i for i, c in enumerate(commands) if c[:2] == ['rpm', '-qp'])
        system_import = next(i for i, c in enumerate(commands) if c[:2] == ['rpmkeys', '--import'])
        transaction = next(i for i, c in enumerate(commands) if c[0] == 'dnf5')
        self.assertLess(signature_index, metadata_index)
        self.assertLess(metadata_index, system_import)
        self.assertLess(system_import, transaction)
        db_commands = [c for c in commands if '--dbpath' in c]
        self.assertEqual(len(db_commands), 3)
        self.assertEqual(len({c[c.index('--dbpath') + 1] for c in db_commands}), 1)
        self.assertIn('--initdb', db_commands[0])

    def test_transaction_preserves_source_and_stack_guards(self):
        command = next(c for c in self.exercise() if c[0] == 'dnf5')
        for arg in ('--disable-repo=*', '--enable-repo=fedora', '--enable-repo=updates',
                    '--setopt=gpgcheck=1', '--setopt=*.gpgcheck=1', '--setopt=localpkg_gpgcheck=1',
                    '--setopt=*.skip_if_unavailable=False', '--setopt=install_weak_deps=False',
                    '--exclude=kernel*,bootc*,rpm-ostree*,ostree*', '--no-allow-downgrade'):
            self.assertIn(arg, command)
        self.assertEqual(command[-1].split('/')[-1], 'tailscale.rpm')
        self.assertNotIn('--allowerasing', command)
        self.assertNotIn('--skip-unavailable', command)

    def test_absent_does_not_download_or_import(self):
        commands = self.exercise(before=OLD.split('\n')[1])
        self.assertEqual(len(commands), 2)

    def test_current_and_newer_do_not_download_or_import(self):
        for before in (NEW, NEW.replace('1.104.1', '1.104.2')):
            with self.subTest(before=before):
                self.assertEqual(len(self.exercise(before=before)), 2)

    def test_unreviewed_fedora(self):
        with self.assertRaisesRegex(ValueError, 'Fedora release'):
            self.exercise(fedora='45')

    def test_unreviewed_installed_architecture(self):
        for before in (OLD.replace('x86_64', 'aarch64'), OLD + '\ntailscale\t0:1.102.5-1\taarch64'):
            with self.subTest(before=before), self.assertRaisesRegex(ValueError, 'architecture is not reviewed'):
                self.exercise(before=before)

    def test_modified_key(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'key'
            key.write_bytes(b'unreviewed key')
            with self.assertRaisesRegex(ValueError, 'key digest mismatch'):
                self.exercise(key=key)

    def test_modified_package(self):
        with self.assertRaisesRegex(ValueError, 'RPM digest mismatch'):
            self.exercise(actual_payload=b'tampered RPM')

    def test_unsigned_bad_unknown_and_wrong_key_fail(self):
        for signature in ('Header SHA256 digest: OK', SIGNATURE.replace(': OK', ': BAD'),
                          SIGNATURE + '\nNOKEY', SIGNATURE.replace(POLICY['keyFingerprint'].lower(), 'f' * 40),
                          SIGNATURE + '\nPayload SHA256 digest: NOT OK'):
            with self.subTest(signature=signature), self.assertRaisesRegex(ValueError, 'signature was not authenticated'):
                self.exercise(signature=signature)

    def test_signed_metadata_mismatch(self):
        for metadata in (METADATA.replace('tailscale', 'other'), METADATA.replace('1.104.1', '1.104.0'),
                         METADATA.replace('x86_64', 'aarch64'), METADATA + '\n' + METADATA):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, 'metadata does not match'):
                self.exercise(metadata=metadata)

    def test_command_errors_propagate(self):
        for marker in ('--checksig', '--initdb', '--import', 'dnf5'):
            with self.subTest(marker=marker), self.assertRaises(subprocess.CalledProcessError):
                self.exercise(failure=lambda args: marker in args)

    def test_protected_stack_change(self):
        with self.assertRaisesRegex(ValueError, 'protected boot stack'):
            self.exercise(after=NEW.replace('7.2.5', '7.2.8'))

    def test_target_missing_or_old(self):
        for after in (OLD, NEW.split('\n')[1]):
            with self.subTest(after=after), self.assertRaisesRegex(ValueError, 'floor not satisfied'):
                self.exercise(after=after)

    def test_changed_installed_architecture(self):
        with self.assertRaisesRegex(ValueError, 'changed installed architectures'):
            self.exercise(after=NEW.replace('tailscale\t0:1.104.1-1\tx86_64', 'tailscale\t0:1.104.1-1\taarch64'))

    def test_strict_policy(self):
        mutations = [lambda p: p.update(schema=True), lambda p: p.update(fedora=45),
                     lambda p: p.update(package='kernel-core'), lambda p: p.update(arch='aarch64'),
                     lambda p: p.update(minimumEVR='1:1.104.1-1'), lambda p: p.update(minimumEVR='";evil'),
                     lambda p: p.update(sha256='f' * 63), lambda p: p.update(keyFingerprint='f' * 40),
                     lambda p: p.update(url=p['url'].replace('https:', 'http:')),
                     lambda p: p.update(url=p['url'].replace('/stable/', '/unstable/')),
                     lambda p: p.update(url=p['url'] + '?redirect=evil'), lambda p: p.update(keySource='https://evil.example/key'),
                     lambda p: p.update(extra='field')]
        for mutation in mutations:
            policy = copy.deepcopy(POLICY)
            mutation(policy)
            with self.subTest(policy=policy), patch.object(Path, 'read_text', return_value=json.dumps(policy)), self.assertRaises(ValueError):
                mod.load_policy('unused')

    def test_https_download_is_bounded(self):
        commands = []
        mod.download(POLICY['url'], Path('/tmp/not-written'), commands.append)
        command = commands[0]
        for arg in ('--fail', '--proto', '--proto-redir', '=https', '--connect-timeout',
                    '--max-time', '--retry', '--retry-max-time', '--max-filesize'):
            self.assertIn(arg, command)
        self.assertNotIn('--insecure', command)


unittest.main()
