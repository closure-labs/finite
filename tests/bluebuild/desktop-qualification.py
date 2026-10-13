#!/usr/bin/env python3
"""Offline evidence binding and negative VM observation fixtures."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('desktop_test', ROOT / 'scripts/bluebuild/desktop-qualification.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Desktop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = '{"schemaVersion":2,"manifests":[{"digest":"sha256:' + 'b' * 64 + '"}]}'
        self.image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(self.manifest.encode()).hexdigest()
        self.acceptance = dict(candidate=self.image, profile='bluefin-generic', sourceRevision='c'*40,
                               buildIdentity='v1:'+'d'*64, previousDigest='')
        self.observation = m.guest.observations('Enforcing', '1', '',
            'system_u:system_r:init_t:s0 1 systemd\nsystem_u:system_r:sshd_t:s0 22 sshd',
            'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=22,fd=3))', 'bluefin-generic')
        self.write_phase('fresh', 'first-boot', 'source')

    def write_phase(self, phase, boot, manifest):
        base = self.root / ('vm-' + phase)
        base.mkdir()
        (base / (manifest+'-manifest.json')).write_text(self.manifest)
        (base / (boot+'.json')).write_text(json.dumps({'status': {'booted': {'image': {'imageDigest': 'sha256:'+'b'*64}}}}))
        (base / (boot+'-desktop.json')).write_text(json.dumps(self.observation))

    def test_fresh_and_upgrade(self):
        for upgrade in (False, True):
            if upgrade:
                self.acceptance['previousDigest'] = 'sha256:'+'e'*64
                self.write_phase('upgrade', 'updated', 'target')
            m.assemble(self.root, self.acceptance)
            path = m.verify(self.root, self.acceptance)
            receipt = json.loads(path.read_text())
            self.assertEqual(len(receipt['phases']), 2 if upgrade else 1)
            self.assertEqual(receipt['phases']['fresh']['observations']['desktop']['hardware'], 'not-assessed')

    def test_missing_upgrade_fails(self):
        self.acceptance['previousDigest'] = 'sha256:'+'e'*64
        with self.assertRaises(ValueError): m.assemble(self.root, self.acceptance)

    def test_binding_mutations_fail(self):
        m.assemble(self.root, self.acceptance)
        for key in ('candidate', 'profile', 'sourceRevision', 'buildIdentity'):
            bad = {**self.acceptance, key: 'wrong'}
            with self.subTest(key=key), self.assertRaises(ValueError): m.verify(self.root, bad)

    def test_tampering_missing_symlink_and_oversize_fail(self):
        m.assemble(self.root, self.acceptance)
        path = m.verify(self.root, self.acceptance)
        original = path.read_bytes()
        path.write_bytes(original+b' ')
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        path.unlink()
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        target = self.root/'target'; target.write_bytes(original); path.symlink_to(target)
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)
        path.unlink(); path.write_bytes(b'x'*(m.LIMIT+1))
        with self.assertRaises(ValueError): m.verify(self.root, self.acceptance)

    def test_boot_manifest_checks_and_observation_truth(self):
        m.assemble(self.root, self.acceptance)
        receipt = json.loads(m.verify(self.root, self.acceptance).read_text())
        for mutate in (
            lambda r: r['phases']['fresh'].update(bootedDigest='sha256:'+'f'*64),
            lambda r: r['phases']['fresh'].update(manifest='{}'),
            lambda r: r['phases']['fresh']['observations']['checks'].update(selinuxEnforcing=False),
            lambda r: r['phases']['fresh']['observations']['selinux'].update(mode='Permissive'),
            lambda r: r['phases']['fresh']['observations'].update(listeners=[]),
            lambda r: r['phases']['fresh']['observations'].update(processes=[])):
            bad = copy.deepcopy(receipt); mutate(bad)
            with self.assertRaises(ValueError): m.validate(bad, self.acceptance)

    def test_permissive_inventory_not_blanket_waiver(self):
        args = ('Enforcing','1','unconfined_service_t',
                'system_u:system_r:init_t:s0 1 systemd\nsystem_u:system_r:sshd_t:s0 22 sshd',
                'tcp LISTEN 0 128 *:22 *:* owners', 'bluefin-generic')
        observed=m.guest.observations(*args)
        self.assertEqual(observed['selinux']['permissiveDomains'], ['unconfined_service_t'])
        with self.assertRaises(ValueError): m.guest.observations(*(*args[:2], 'sshd_t', *args[3:]))


if __name__ == '__main__': unittest.main()
