#!/usr/bin/env python3
"""Protect raw-to-sealed provenance and reject disposable signing evidence."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/bluebuild'))
spec = importlib.util.spec_from_file_location('native_handoff', ROOT / 'scripts/bluebuild/native-handoff.py')
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)
fixture = runpy.run_path(str(ROOT / 'tests/bluebuild/native-oci-layer.py'))['fixture']


class Handoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        archive = self.work / 'image.tar'
        fixture(archive)
        image = handoff.oci.Image(archive)
        digest = image.index['manifests'][0]['digest']
        image.close()
        self.args = argparse.Namespace(directory=self.work, profile='finite', digest=digest,
            revision='a' * 40, identity='v1:' + 'b' * 64, info=self.work / 'info.json',
            archive=archive, receipt=self.work / 'receipt.json')
        self.record = dict(profile='finite', publish=True, revision=self.args.revision,
            sourceRevision=self.args.revision, buildIdentity=self.args.identity,
            candidate='candidate-finite', qualificationMode='enforce', digest='sha256:' + 'c' * 64)
        self.record_path = self.work / 'finite-publication.json'
        self.save(self.record_path, self.record)
        self.reference = self.work / 'finite-image-ref.txt'
        self.reference.write_text(handoff.REPOSITORY + '@' + digest + '\n')
        self.info = dict(Digest=digest, Architecture='amd64', Os='linux', Labels={
            'io.finite.profile': 'finite', 'io.finite.build-inputs': self.args.identity,
            'io.finite.boot-architecture': 'native-composefs',
            'org.opencontainers.image.revision': self.args.revision,
            'org.opencontainers.image.base.digest': self.record['digest'],
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'})
        self.save(self.args.info, self.info)
        signer = handoff.read(ROOT / 'sources/boot-signing.json')
        importer = handoff.read(ROOT / 'sources/native-composefs-verifier.json')
        sha = handoff.oci.sha256(archive)
        self.receipt = dict(schema=1, validationOnly=False, profile='finite',
            sourceRevision=self.args.revision, sourceArchiveSha256=sha, archiveSha256=sha,
            certificateDerSha256=signer['certificateDerSha256'],
            importerSha256=importer['bootcSha256'], bootableRootDigest='d' * 128,
            integrity=dict(strictVerity=True, ukis=[dict(path='boot/EFI/Linux/test.efi', sha256='e' * 64)],
                certificateDerSha256=signer['certificateDerSha256'], archiveSha256=sha,
                importerBinarySha256=importer['bootcSha256'], bootableRootDigest='d' * 128))
        self.save(self.args.receipt, self.receipt)

    def save(self, path, value):
        path.write_text(json.dumps(value))

    def test_final_digest_receipt_and_original_root_are_preserved(self):
        handoff.prepare(self.args)
        handoff.finalize(self.args)
        record = handoff.read(self.record_path)
        self.assertEqual(record['digest'], self.record['digest'])
        self.assertEqual(record['bootSeal']['sourceDigest'], self.args.digest)
        self.assertEqual(record['bootSeal']['imageDigest'], self.args.digest)
        self.assertEqual((self.work / 'finite-native-seal.json').read_bytes(), self.args.receipt.read_bytes())

    def test_wrong_source_profile_build_and_resume_are_rejected_before_signing(self):
        for field, value in [('publish', False), ('sourceRevision', 'f' * 40),
                             ('buildIdentity', 'v1:' + 'f' * 64), ('resumeOrigin', {}), ('bootSeal', {})]:
            with self.subTest(field=field):
                record = {**self.record, field: value}
                self.save(self.record_path, record)
                with self.assertRaises(ValueError):
                    handoff.prepare(self.args)
                self.assertFalse((self.work / 'finite-native-source.json').exists())

    def test_disposable_or_changed_receipt_cannot_become_production_evidence(self):
        handoff.prepare(self.args)
        cases = [('validationOnly', True), ('validationOnly', 0),
                 ('sourceRevision', 'f' * 40), ('sourceArchiveSha256', 'f' * 64),
                 ('certificateDerSha256', 'f' * 64), ('importerSha256', 'f' * 64),
                 ('archiveSha256', 'f' * 64), ('bootableRootDigest', 'f' * 128)]
        for field, value in cases:
            with self.subTest(field=field):
                self.save(self.args.receipt, {**self.receipt, field: value})
                with self.assertRaises(ValueError):
                    handoff.finalize(self.args)
                self.assertNotIn('bootSeal', handoff.read(self.record_path))
        for field, value in [('strictVerity', False), ('ukis', []), ('importerBinarySha256', 'f' * 64)]:
            receipt = copy.deepcopy(self.receipt)
            receipt['integrity'][field] = value
            self.save(self.args.receipt, receipt)
            with self.subTest(field=field), self.assertRaises(ValueError):
                handoff.finalize(self.args)

    def test_registry_conversion_and_wrong_labels_cannot_rebind_archive(self):
        handoff.prepare(self.args)
        self.args.digest = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(ValueError, 'manifest digest'):
            handoff.finalize(self.args)
        self.args.digest = self.info['Digest']
        self.info['Labels']['io.finite.boot-architecture'] = 'ostree'
        self.save(self.args.info, self.info)
        with self.assertRaisesRegex(ValueError, 'build identity'):
            handoff.finalize(self.args)

    def test_resume_rechecks_proof_bindings_and_strict_root(self):
        publication = runpy.run_path(str(ROOT / 'scripts/bluebuild/publication.py'))
        handoff.prepare(self.args)
        handoff.finalize(self.args)
        record = handoff.read(self.record_path)
        validate = publication['validate_boot_seal']
        validate(record, self.args.receipt.read_bytes(), self.args.digest, self.args.revision, ROOT)
        for field, value in [('buildIdentity', 'v1:' + 'f' * 64), ('sourceDigest', ''),
                             ('bootableRootDigest', 'optional'), ('validationOnly', True)]:
            changed = copy.deepcopy(record)
            changed['bootSeal'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(changed, self.args.receipt.read_bytes(), self.args.digest, self.args.revision, ROOT)

    def test_native_publication_cannot_promote_a_raw_image(self):
        publication = runpy.run_path(str(ROOT / 'scripts/bluebuild/publication.py'))
        recipes = self.work / 'recipes'
        recipes.mkdir()
        (recipes / 'finite.yml').write_text('labels:\n  io.finite.boot-architecture: native-composefs\n')
        evidence = self.work / '.bluebuild'
        evidence.mkdir()
        record = {**self.record, 'tags': ['finite', 'latest'], 'publishedDigest': '',
                  'previousDigest': '', 'recoveryReason': ''}
        self.save(evidence / 'finite-publication.json', record)
        (evidence / 'finite-image-ref.txt').write_bytes(self.reference.read_bytes())
        with patch.dict('os.environ', GITHUB_SHA=self.args.revision), patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'production sealing proof'):
                publication['promote']('finite', self.work)
            run.assert_not_called()


class HistoricalSignatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.publication = runpy.run_path(str(ROOT / 'scripts/bluebuild/publication.py'))

    def test_only_exact_historical_profile_and_digest_use_reviewed_keyless_identity(self):
        policy = handoff.read(ROOT / 'sources/legacy-registry-signatures.json')
        authenticate = self.publication['authenticate_predecessor']
        for profile, digest in policy['profiles'].items():
            with patch('subprocess.run') as run:
                authenticate(profile, digest, ROOT)
                command = run.call_args.args[0]
                self.assertIn(policy['certificateIdentity'], command)
                self.assertIn(policy['certificateOidcIssuer'], command)
                self.assertNotIn('--key', command)
            with patch('subprocess.run') as run:
                authenticate(profile, 'sha256:' + 'f' * 64, ROOT)
                self.assertIn('--key', run.call_args.args[0])
                self.assertNotIn('--certificate-identity', run.call_args.args[0])
        with patch('subprocess.run') as run:
            authenticate('finite', policy['profiles']['finite-dev'], ROOT)
            self.assertIn('--key', run.call_args.args[0])

    def test_failed_verification_has_no_fallback(self):
        import subprocess
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'cosign')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                self.publication['authenticate_predecessor']('finite', 'sha256:' + 'f' * 64, ROOT)
            run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
