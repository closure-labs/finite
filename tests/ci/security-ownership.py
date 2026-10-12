#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ownership', ROOT / 'scripts/ci/security-ownership.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
HASH = 'a' * 64
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64
EXTRACTION = {'sbomSha256': HASH, 'signedDigest': IMAGE.split('@')[1], 'method': 'umoci-rootless', 'sourcePath': '/tmp/scan/rootfs'}
LEDGER = {'image': IMAGE, 'findings': [
    {'component': 'pkg:golang/example@1', 'advisory': 'CVE-2026-1234'},
    {'component': 'pkg:pypi/unknown@1', 'advisory': 'CVE-2026-4567'},
]}
SBOM = {'source': {'type': 'directory', 'metadata': {'path': '/tmp/scan/rootfs'}}, 'artifacts': [
    {'id': 'go', 'name': 'example', 'version': '1', 'type': 'go-module', 'purl': 'pkg:golang/example@1',
     'locations': [{'path': '/usr/bin/example'}, {'accessPath': '/sysroot/ostree/repo/objects/ab/cd.file'}]},
    {'id': 'rpm', 'name': 'example-bin', 'version': '1-1.fc44', 'type': 'rpm', 'purl': 'pkg:rpm/example-bin@1-1.fc44',
     'metadata': {'sourceRpm': 'example-1-1.fc44.src.rpm', 'files': [{'path': '/usr/bin/example'}]}}
], 'artifactRelationships': [{'parent': 'rpm', 'child': 'go', 'type': 'contains'}]}


class Ownership(unittest.TestCase):
    def test_file_ownership_and_unresolved_objects(self):
        result = mod.report(SBOM, LEDGER, EXTRACTION, HASH)
        finding = result['findings'][0]
        self.assertEqual(result['findingCount'], 2)
        self.assertEqual(finding['owners'][0]['name'], 'example-bin')
        self.assertEqual(finding['remediationStatus'], 'pending-rescan')
        paths = {p['path']: p for p in finding['paths']}
        self.assertEqual(paths['/usr/bin/example']['ownership'], 'rpm-file-list')
        self.assertEqual(paths['/sysroot/ostree/repo/objects/ab/cd.file']['kind'], 'ostree-object')
        self.assertEqual(paths['/sysroot/ostree/repo/objects/ab/cd.file']['ownership'], 'unknown')
        self.assertEqual(result['findings'][1]['sbomMatch'], 'not-found')

    def test_relationship_alone_is_not_ownership(self):
        sbom = copy.deepcopy(SBOM)
        sbom['artifacts'][1]['metadata']['files'] = []
        finding = mod.report(sbom, LEDGER, EXTRACTION, HASH)['findings'][0]
        self.assertEqual(finding['owners'], [])
        self.assertEqual(finding['ownership'], 'unknown')
        self.assertEqual(finding['rpmRelationships'][0]['direction'], 'rpm-to-component')

    def test_integrity_failure(self):
        for key, value in [('sbomSha256', 'wrong'), ('signedDigest', 'wrong'), ('sourcePath', '/wrong'), ('method', 'unknown')]:
            extraction = {**EXTRACTION, key: value}
            with self.assertRaises(ValueError):
                mod.report(SBOM, LEDGER, extraction, HASH)

    def test_extraction_prefix_and_traversal(self):
        self.assertEqual(mod.path_value('/tmp/scan/rootfs/usr/bin/example', '/tmp/scan/rootfs'), '/usr/bin/example')
        self.assertIsNone(mod.path_value('/usr/../etc/passwd', '/tmp/scan/rootfs'))

    def test_rpm_is_its_own_owner(self):
        ledger = {'image': IMAGE, 'findings': [{'component': SBOM['artifacts'][1]['purl'], 'advisory': 'CVE-2026-1234'}]}
        self.assertEqual(mod.report(SBOM, ledger, EXTRACTION, HASH)['findings'][0]['owners'][0]['evidence'], 'rpm-artifact-itself')


unittest.main()
