#!/usr/bin/env python3
"""Reject UKI arguments that weaken or ambiguously select the verified root."""
import importlib.util
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('verify_native', ROOT / 'scripts/bluebuild/verify-native-oci.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
DIGEST = 'a' * 128
ARG = 'composefs.digest=v1-sha512-12:' + DIGEST


class NativeDigest(unittest.TestCase):
    def test_strict_native_root(self):
        self.assertEqual(native.digest_arguments('quiet rw ' + ARG + '\0'), DIGEST)

    def test_optional_or_ambiguous_root_is_rejected(self):
        for args in ['rw composefs=?' + DIGEST, 'rw composefs=' + DIGEST,
                     'rw ' + ARG.replace('=v1', '=?v1'), 'rw ' + ARG + ' ' + ARG,
                     'rw ' + ARG + ' composefs=' + DIGEST,
                     'ro ' + ARG, 'rw ro ' + ARG,
                     'rw ostree=/ostree/boot.0/default ' + ARG,
                     'rw composefs.digest=v1-sha512-12:' + 'a' * 127]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                native.digest_arguments(args)


class CompletedArchive(unittest.TestCase):
    def verify(self, cmdline='rw ' + ARG, bad_signature=False, bad_importer=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'sources').mkdir()
        bootc = root / 'bootc'
        bootc.write_bytes(b'fixture importer')
        (root / 'sources/native-composefs-verifier.json').write_text(json.dumps({
            'architecture': native.platform.machine(), 'bootcVersion': 'bootc fixture',
            'bootcSha256': hashlib.sha256(bootc.read_bytes()).hexdigest()}))
        archive, cert, output = root / 'final.oci.tar', root / 'production.pem', root / 'verified.json'
        archive.write_bytes(b'completed fixture OCI')
        cert.write_bytes(b'public certificate fixture')
        args = argparse.Namespace(archive=archive, certificate=cert, output=output,
                                  certificate_sha256=hashlib.sha256(b'DER certificate').hexdigest())
        calls = []

        def capture(command):
            if '--version' in command:
                return 'bootc wrong' if bad_importer else 'bootc fixture'
            self.assertIn('compute-id', command)
            return DIGEST

        def run(command):
            command = list(map(str, command))
            calls.append(command)
            if command[0] == str(bootc) and 'init' in command:
                Path(command[command.index('--repo') + 1]).mkdir()
            elif command[0] == 'umoci':
                uki = Path(command[-1]) / 'rootfs/boot/EFI/Linux/fixture.efi'
                self.assertFalse((Path(command[-1]).parent / 'repo').exists())
                uki.parent.mkdir(parents=True)
                uki.write_bytes(b'signed UKI fixture')
            elif command[0] == 'objcopy':
                Path(command[-1]).write_text(cmdline)
            elif command[0] == 'sbverify' and bad_signature:
                raise subprocess.CalledProcessError(1, command)

        patches = [patch.object(native, 'ROOT', root), patch.object(native.shutil, 'which', return_value=str(bootc)),
                   patch.object(native, 'capture', side_effect=capture), patch.object(native, 'run', side_effect=run),
                   patch.object(native.oci, 'extract_layout', return_value='oci:fixture:candidate'),
                   patch.object(native.subprocess, 'check_output', return_value=b'DER certificate')]
        import contextlib
        with contextlib.ExitStack() as stack:
            for replacement in patches:
                stack.enter_context(replacement)
            try:
                native.verify(args)
            except (ValueError, subprocess.CalledProcessError):
                self.assertFalse(output.exists())
                raise
        return json.loads(output.read_text()), calls

    def test_independent_final_import_and_signature_bind_evidence(self):
        result, calls = self.verify()
        self.assertEqual(result['bootableRootDigest'], DIGEST)
        self.assertEqual(len(result['ukis']), 1)
        self.assertTrue(any('oci' in call and 'pull' in call for call in calls))
        self.assertTrue(any(call[0] == 'sbverify' for call in calls))

    def test_different_signed_root_cannot_create_evidence(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.verify(cmdline='rw ' + ARG.replace('a' * 128, 'b' * 128))

    def test_invalid_signature_cannot_create_evidence(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify(bad_signature=True)

    def test_runner_digest_is_limited_to_disposable_branch(self):
        actual = 'a' * 64
        bootc = Path('/nix/store/fixture-importer/bin/bootc')
        pin = {'bootcVersion': 'bootc 1.17.1', 'architecture': native.platform.machine(),
               'bootcSha256': 'b' * 64}
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
               'GITHUB_REF': 'refs/heads/qualification/native-iso'}
        with patch.object(native, 'capture', return_value=pin['bootcVersion']) as invoke, \
                patch.object(native, 'sha256', return_value=actual), patch.dict(native.os.environ, env):
            self.assertEqual(native.check_importer(bootc, pin, actual), actual)
            with self.assertRaisesRegex(ValueError, 'reviewed pin'):
                native.check_importer(bootc, pin)
            with self.assertRaisesRegex(ValueError, 'reviewed pin'):
                native.check_importer(bootc, pin, 'f' * 64)
            with patch.dict(native.os.environ, GITHUB_REF='refs/heads/main'), \
                    self.assertRaisesRegex(ValueError, 'disposable'):
                native.check_importer(bootc, pin, actual)
            invoke.assert_called_once_with([bootc, '--version'])

    def test_unpinned_importer_cannot_create_evidence(self):
        with self.assertRaisesRegex(ValueError, 'reviewed version'):
            self.verify(bad_importer=True)


if __name__ == '__main__':
    unittest.main()
