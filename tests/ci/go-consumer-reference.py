#!/usr/bin/env python3
"""Authentication and actual collector integration regressions without downloads."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

app = load('consumer_reference_test', 'scripts/ci/go-consumer-reference.py')
fixtures = load('consumer_go_fixtures', 'tests/ci/applicability-evidence.py')


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.key = self.root / 'key.pub'
        self.key.write_bytes(b'fixture public key')
        self.payload = fixtures.fixture(settings='build\tGOOS=linux\nbuild\tGOARCH=amd64\nbuild\tCGO_ENABLED=0\nbuild\tvcs.revision=' + 'a' * 40 + '\nbuild\tvcs.modified=false\n')
        self.archive = b'fixture archive'
        self.specs = {name: {**spec, 'bytes': len(self.archive)} for name, spec in app.RPMS.items()}
        self.signature = ('Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: '
            + app.utilities.FINGERPRINT + ': OK\nPayload SHA256 digest: OK\n')
        self.error = None
        self.executed = []

    def runner(self, argv):
        self.executed.append(argv)
        if '--import' in argv:
            return ''
        if '--checksig' in argv:
            return self.signature
        name = Path(argv[-1]).stem
        spec = self.specs[name]
        if '%{FILESIZES}' in argv[-2]:
            sha = hashlib.sha256(self.payload).hexdigest()
            if self.error == 'payload': sha = 'f' * 64
            entry = '/usr/bin/' + name + '\t' + str(len(self.payload)) + '\t' + sha + '\t' + str(0o100755) + '\n'
            return entry * (2 if self.error == 'duplicate' else 1)
        epoch = '9' if self.error == 'epoch' else spec['epoch']
        return '\t'.join([name, epoch, spec['version'], '1.fc44', 'x86_64',
            name + '-' + spec['version'] + '-1.fc44.src.rpm', '8', 'Fedora Project']) + '\n'

    def downloader(self, name, target):
        target.write_bytes(self.archive)
        result = {'url': app.rpm_url(name), 'bytes': len(self.archive), 'sha256': hashlib.sha256(self.archive).hexdigest()}
        if self.error == 'download': result['url'] = 'https://unapproved.example/package.rpm'
        return result

    def extractor(self, name, archive, directory):
        target = directory / 'usr/bin' / name
        target.parent.mkdir(parents=True)
        target.write_bytes(self.payload)
        target.chmod(0o755)
        if self.error == 'symlink':
            target.rename(target.with_suffix('.real'))
            target.symlink_to(target.name + '.real')

    def collect(self, name='result'):
        with patch.dict(app.RPMS, self.specs, clear=True), patch.object(app.utilities, 'KEY_SHA256', hashlib.sha256(self.key.read_bytes()).hexdigest()):
            return app.collect(self.key, self.root / name, self.runner, self.downloader, self.extractor)

    def test_complete_collection_authenticates_bytes_and_records_metadata_without_payload_execution(self):
        result = self.collect()
        self.assertEqual(result['status'], 'signed-reference-bytes-proven')
        self.assertFalse(result['releaseEligible'])
        self.assertTrue(result['candidateBindingUnproven'])
        self.assertEqual(result['dispositionsGranted'], [])
        self.assertEqual(len(result['packages']), 2)
        for p in result['packages']:
            self.assertTrue(p['signatureVerified'])
            self.assertTrue(p['referenceBytes']['actualFileIntegrityVerified'])
            self.assertEqual(p['goBuildInfo']['sha256'], hashlib.sha256(self.payload).hexdigest())
            self.assertIn('build\tCGO_ENABLED=0', p['goBuildInfo']['goBuildSettingsRecords'])
            self.assertIn('dep\tgolang.org/x/mod\tv0.37.0\th1:fixture', p['goBuildInfo']['goDependencyModuleRecords'])
        self.assertTrue(all(cmd[0] in ('rpmkeys', 'rpm') for cmd in self.executed))

    def test_invalid_signature_fails_before_extracting_payload(self):
        for value in ('NOKEY', 'Payload SHA256 digest: OK', self.signature.replace('SHA256', 'SHA1')):
            self.signature = value
            with self.assertRaises(ValueError): self.collect('signature-' + str(len(value)))

    def test_download_binding_epoch_duplicate_manifest_and_payload_hash_are_fail_closed(self):
        for error in ('download', 'epoch', 'duplicate', 'payload'):
            self.error = error
            with self.assertRaises(ValueError): self.collect(error)

    def test_symlink_payload_is_unknown_and_cannot_authenticate_reference(self):
        self.error = 'symlink'
        with self.assertRaises(ValueError): self.collect()

    def test_existing_or_symlinked_output_parent_cannot_be_reused(self):
        self.collect()
        with self.assertRaises(FileExistsError): self.collect()
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with patch.object(app.utilities, 'KEY_SHA256', hashlib.sha256(self.key.read_bytes()).hexdigest()), self.assertRaises(OSError):
            app.collect(self.key, alias / 'out')

    def test_unreviewed_key_rejected_before_fetch(self):
        with self.assertRaises(ValueError): app.collect(self.key, self.root / 'out')
        self.assertEqual(self.executed, [])

    def test_main_requires_hosted_canonical_repository(self):
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(SystemExit) as error:
            app.main(['--key', str(self.key), '--directory', str(self.root / 'out')])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
