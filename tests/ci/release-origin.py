#!/usr/bin/env python3
"""Native origin receipts fail closed and never grant approval."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import archive_read
import decision_packets
import release_origin as origin
from security_decisions import canonical_hash


class Origin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'packet'
        self.root.mkdir()
        (self.root / 'release-set.json').write_text(json.dumps({'payload': {'sourceRevision': 'a' * 40}}))
        for lane in ('finite', 'finite-dev'):
            (self.root / (lane + '.iso')).write_bytes(lane.encode())
        self.artifact = {'id': 10, 'name': 'release-set-packet-5-1', 'digest': 'sha256:' + 'b' * 64, 'size_in_bytes': 400}
        self.producer = {'repository': origin.REPOSITORY, 'workflow': 'release-set.yml', 'runId': 5,
                         'runAttempt': 1, 'headSha': 'a' * 40,
                         'artifacts': [{k: self.artifact[k] for k in ('id', 'name', 'digest')}]}
        self.manifest = {'schema': 1, 'producer': self.producer, 'files': decision_packets.inventory(self.root)}
        self.reference = decision_packets.REGISTRY + '@sha256:' + 'c' * 64
        packet = {'reference': self.reference, 'sha256': canonical_hash(self.manifest), 'producer': self.producer}
        self.value = origin.receipt(self.root, self.producer, self.artifact, packet, 50)
        self.run = {'id': 5, 'run_attempt': 1, 'head_sha': 'a' * 40, 'head_branch': 'main',
                    'head_repository': {'full_name': origin.REPOSITORY}, 'status': 'completed',
                    'conclusion': 'success', 'event': 'workflow_dispatch', 'path': '.github/workflows/release-set.yml'}
        self.job = {'id': 50, 'name': 'prepare', 'run_id': 5, 'run_attempt': 1, 'head_sha': 'a' * 40,
                    'status': 'completed', 'conclusion': 'success', 'steps': [
                        {'name': 'Propose the single official release approval', 'conclusion': 'success'},
                        {'name': 'Retain native release product origin', 'conclusion': 'success'}]}
        self.present = True
        self.native_changes = {}
        self.downloads = 0

    def collection(self, endpoint, key):
        if key == 'jobs': return [deepcopy(self.job)]
        if not self.present: return []
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('release-set-origin.json', json.dumps(self.value))
        self.raw = stream.getvalue()
        return [{'id': 11, 'name': origin.artifact_name(self.producer), 'expired': False,
                 'size_in_bytes': len(self.raw), 'digest': 'sha256:' + hashlib.sha256(self.raw).hexdigest(),
                 'workflow_run': {'id': 5, 'head_sha': 'a' * 40}, **self.native_changes}]

    def download(self, command, **kwargs):
        self.assertEqual(command[-1], 'repos/closure-labs/finite/actions/artifacts/11/zip')
        self.downloads += 1
        kwargs['stdout'].write(self.raw)

    def verify(self, **kwargs):
        with patch.object(archive_read.subprocess, 'run', side_effect=self.download):
            return origin.verify(self.root, self.manifest, self.reference, self.artifact,
                                 self.collection, lambda _: self.run, **kwargs)

    def test_authenticates_two_profile_inventory_and_reuses_staged_receipt(self):
        cached = Path(self.tmp.name) / 'origin.zip'
        self.assertTrue(self.verify(cached_archive=cached))
        self.assertTrue(self.verify(cached_archive=cached))
        self.assertEqual(self.downloads, 1)
        self.assertFalse(self.value['authorizesPublication'])

    def test_only_absent_receipt_allows_legacy_fallback(self):
        self.present = False
        self.assertFalse(self.verify())
        self.assertEqual(self.downloads, 0)
        self.present = True
        self.native_changes['expired'] = True
        with self.assertRaisesRegex(ValueError, 'native origin'): self.verify()

    def test_forged_receipt_bindings_fail_closed(self):
        original = deepcopy(self.value)
        for field, value in [('schema', True), ('producer', {}), ('jobId', 99),
                             ('sourceRevision', 'd' * 40), ('artifact', {}), ('packet', {}),
                             ('files', {}), ('authorizesPublication', True)]:
            with self.subTest(field=field):
                self.value = {**original, field: value}
                with self.assertRaises(ValueError): self.verify()

    def test_altered_products_and_extra_members_are_rejected(self):
        (self.root / 'finite.iso').write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError, 'products changed'): self.verify()
        (self.root / 'finite.iso').write_bytes(b'finite')
        (self.root / 'extra.iso').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'products changed'): self.verify()

    def test_failed_foreign_or_incomplete_producer_is_rejected(self):
        original = deepcopy(self.run)
        for field, value in [('conclusion', 'failure'), ('status', 'in_progress'),
                             ('head_sha', 'd' * 40), ('run_attempt', 2), ('head_branch', 'other'),
                             ('head_repository', {'full_name': 'attacker/repo'})]:
            self.run = {**original, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'trusted workflow'): self.verify()
        self.run = original
        self.job['conclusion'] = 'failure'
        with self.assertRaises(ValueError): self.verify()

    def test_diagnostic_native_receipt_cannot_satisfy_production_provenance(self):
        self.producer['workflow'] = 'benchmark-release-transport.yml'
        self.producer['sourcePacket'] = self.reference
        self.run.update(path='.github/workflows/benchmark-release-transport.yml', head_branch='audit/transport')
        self.job.update(name='producer', steps=[{'name': name, 'conclusion': 'success'} for name in
            ('Persist authenticated diagnostic packet', 'Retain native diagnostic origin')])
        (self.root / 'release-set.json').write_text(json.dumps({'payload': {'sourceRevision': 'd' * 40}}))
        self.manifest['files'] = decision_packets.inventory(self.root)
        packet = {'reference': self.reference, 'sha256': canonical_hash(self.manifest), 'producer': self.producer}
        self.value = origin.receipt(self.root, self.producer, self.artifact, packet, 50)
        with self.assertRaisesRegex(ValueError, 'Invalid origin producer'): self.verify()
        self.assertTrue(self.verify(diagnostic=True))
        self.job['status'] = 'in_progress'
        with self.assertRaises(ValueError): self.verify(diagnostic=True)

    def test_receipt_writer_requires_the_current_native_producer_job(self):
        self.job['status'] = 'in_progress'
        packet = {'reference': self.reference, 'sha256': canonical_hash(self.manifest), 'producer': self.producer}
        output = Path(self.tmp.name) / 'release-set-origin.json'
        origin.write(self.root, self.producer, self.artifact, packet, self.collection, output)
        self.assertEqual(json.loads(output.read_text()), self.value)
        self.job['status'] = 'completed'
        with self.assertRaisesRegex(ValueError, 'native preparing job'):
            origin.write(self.root, self.producer, self.artifact, packet, self.collection, output)

    def test_interrupted_receipt_transfer_discards_partial_cache(self):
        cached = Path(self.tmp.name) / 'origin.zip'
        def interrupted(command, **kwargs):
            kwargs['stdout'].write(b'partial')
            raise subprocess.TimeoutExpired(command, 1800)
        with patch.object(archive_read.subprocess, 'run', side_effect=interrupted), patch.object(archive_read.time, 'sleep'):
            with self.assertRaises(subprocess.TimeoutExpired):
                origin.verify(self.root, self.manifest, self.reference, self.artifact,
                              self.collection, lambda _: self.run, cached_archive=cached)
        self.assertFalse(cached.exists())


if __name__ == '__main__':
    unittest.main()
