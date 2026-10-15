#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('baseline', ROOT / 'scripts/ci/approved-baseline.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + '2' * 64
BASE = 'ghcr.io/ublue-os/bluefin'
DIGEST = 'sha256:' + '3' * 64


class BaselineTests(unittest.TestCase):
    def setUp(self):
        policy, policy_hash = baseline.read(ROOT / 'sources/bluefin-trust.json')
        self.config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.revision': '1' * 40,
            'io.finite.profile': 'finite', 'io.finite.build-inputs': 'v1:' + '4' * 64,
            'org.opencontainers.image.base.digest': DIGEST,
            'org.opencontainers.image.base.name': BASE + ':stable@' + DIGEST}}}
        self.receipt = {'schema': 1, 'repository': 'closure-labs/finite', 'sourceRevision': '5' * 40,
            'trustPolicySha256': policy_hash, 'verified': [{'image': BASE + '@' + DIGEST,
                'keySha256': policy['keySha256'], 'signatureFormat': 'legacy'}]}

    def test_reuses_exact_authenticated_base_across_builds(self):
        result = baseline.context(self.config, IMAGE, self.receipt)
        self.assertEqual(result['image'], IMAGE)
        self.assertEqual(result['sourceRevision'], '1' * 40)
        self.assertEqual(result['baseImage'], BASE + '@' + DIGEST)
        self.assertEqual(result['buildIdentity'], 'v1:' + '4' * 64)

    def test_profile_cannot_claim_another_foundation(self):
        self.config['config']['Labels']['io.finite.profile'] = 'finite-dev'
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, self.receipt)

    def test_retired_profile_labels_cannot_authenticate_as_an_active_variant(self):
        for profile in ('bluefin-next', 'bluefin-dx-next'):
            self.config['config']['Labels']['io.finite.profile'] = profile
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                baseline.context(self.config, IMAGE, self.receipt)

    def test_exact_signature_scope_required(self):
        for field, value in [('image', BASE + '@sha256:' + '6' * 64), ('keySha256', '7' * 64),
                             ('signatureFormat', 'unchecked')]:
            with self.subTest(field=field):
                receipt = copy.deepcopy(self.receipt)
                receipt['verified'][0][field] = value
                with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, receipt)

    def test_status_string_cannot_supply_publisher_authority(self):
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, {'status': 'verified'})

    def test_boolean_receipt_schema_cannot_be_normalized_into_authority(self):
        self.receipt['schema'] = True
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, self.receipt)

    def test_source_and_build_identity_required(self):
        for field in ('org.opencontainers.image.source', 'org.opencontainers.image.revision', 'io.finite.build-inputs'):
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                config['config']['Labels'][field] = 'unverified'
                with self.assertRaises(ValueError): baseline.context(config, IMAGE, self.receipt)

    def test_mutable_or_foreign_image_rejected(self):
        for image in ('ghcr.io/closure-labs/finite:latest', 'ghcr.io/another/finite@sha256:' + '2' * 64):
            with self.subTest(image=image):
                with self.assertRaises(ValueError): baseline.context(self.config, image, self.receipt)

    def test_platform_and_base_labels_cannot_be_substituted(self):
        for config in ({**self.config, 'architecture': 'arm64'}, {**self.config, 'os': 'windows'}):
            with self.assertRaises(ValueError): baseline.context(config, IMAGE, self.receipt)
        self.config['config']['Labels']['org.opencontainers.image.base.name'] = BASE + ':latest'
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, self.receipt)

    def test_receipt_tracks_current_trust_policy_and_rejects_duplicates(self):
        receipt = {**self.receipt, 'trustPolicySha256': '0' * 64}
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, receipt)
        self.receipt['verified'] *= 2
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, self.receipt)

    def test_unapproved_extra_publisher_record_rejected(self):
        self.receipt['verified'].append({**self.receipt['verified'][0], 'image': 'https://attacker.invalid/key'})
        with self.assertRaises(ValueError): baseline.context(self.config, IMAGE, self.receipt)

    def test_metadata_read_bounds_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'receipt.json'
            path.write_bytes(b'x' * (1024 * 1024 + 1))
            with self.assertRaises(ValueError): baseline.read(path)
            path.write_text('{"verified":[],"verified":["fake"]}')
            with self.assertRaises(ValueError): baseline.read(path)
            target = Path(tmp) / 'link.json'
            target.symlink_to(path)
            with self.assertRaises(ValueError): baseline.read(target)


if __name__ == '__main__': unittest.main()
