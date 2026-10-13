#!/usr/bin/env python3
"""Small native metadata fixtures preserve binding, ownership and unknowns."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_summary', ROOT / 'scripts/ci/native-evidence-summary.py')
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
IMAGE = 'ghcr.io/closure-labs/finite@sha256:' + 'a' * 64
COMPONENT = 'pkg:golang/stdlib@1.26.4'
ROOTFS = '/tmp/hosted/rootfs'
OBJECT = '/sysroot/ostree/repo/objects/ab/example.file'


class NativeSummary(unittest.TestCase):
    def setUp(self):
        self.go = {'id': 'go1', 'type': 'go-module', 'name': 'stdlib', 'version': '1.26.4',
            'purl': COMPONENT, 'foundBy': 'go-module-binary-cataloger',
            'locations': [{'path': ROOTFS + '/usr/bin/cosign', 'realPath': ROOTFS + OBJECT}],
            'metadata': {'goCompiledVersion': 'go1.26.4', 'architecture': 'amd64',
                         'goBuildSettings': [{'key': 'GOOS', 'value': 'linux'}], 'symbols': {'os': ['Root.Mkdir']}}}
        self.rpm = {'id': 'rpm1', 'type': 'rpm', 'name': 'cosign', 'version': '3.1.3-1.fc44',
            'purl': 'pkg:rpm/fedora/cosign@3.1.3-1.fc44', 'foundBy': 'rpm-db-cataloger',
            'metadata': {'sourceRpm': 'cosign-3.1.3-1.fc44.src.rpm', 'files': [
                {'path': '/usr/bin/cosign', 'digest': {'algorithm': 'sha256', 'value': 'b' * 64}, 'mode': 33188}]}}
        self.sbom = {'source': {'type': 'directory', 'metadata': {'path': ROOTFS}},
                     'artifacts': [self.go, self.rpm],
                     'files': [{'id': 'file1', 'location': {'path': ROOTFS + '/usr/bin/cosign'},
                                'digests': [{'algorithm': 'sha256', 'value': 'c' * 64}],
                                'executable': {'format': 'elf'}, 'metadata': {'size': 1234}}],
                     'artifactRelationships': [{'parent': 'go1', 'child': 'rpm1', 'type': 'contains'}]}
        self.result = {'schema': 1, 'image': IMAGE, 'status': 'blocked', 'scannedAt': '2026-10-13T12:00:00Z',
                       'policySha256': 'd' * 64, 'releaseBlockers': [], 'blocked': [{
                           'component': COMPONENT, 'advisory': 'GO-2026-6604',
                           'aliases': ['GO-2026-6604', 'CVE-2026-56857'], 'locations': ['/usr/bin/cosign', OBJECT],
                           'knownExploited': False, 'severity': 'Critical', 'reason': 'untriaged-critical',
                           'locationCoverage': 'complete'}]}
        self.extraction = {'schema': 1, 'sbomSha256': 'e' * 64, 'signedDigest': IMAGE.split('@')[1],
                           'method': 'umoci-rootless', 'catalogers': 'image', 'sourcePath': ROOTFS, 'basePath': ROOTFS}

    def report(self):
        return native.report(self.sbom, self.result, self.extraction, IMAGE, 'e' * 64)

    def test_exact_current_aliases_paths_metadata_and_owner_are_retained(self):
        result = self.report()
        self.assertEqual(result['blockingPairs'], 1)
        finding = result['findings'][0]
        self.assertEqual(finding['aliases'], ['CVE-2026-56857', 'GO-2026-6604'])
        self.assertEqual(set(finding['locations']), {'/usr/bin/cosign', OBJECT})
        self.assertEqual(finding['nativeComponentMatch'], 'exact')
        self.assertEqual(finding['artifacts'][0]['metadata']['goCompiledVersion'], 'go1.26.4')
        self.assertNotIn('symbols', finding['artifacts'][0]['metadata'])
        live = next(path for path in finding['paths'] if path['path'] == '/usr/bin/cosign')
        self.assertEqual(live['rpmFileOwners'][0]['rpm']['sourceRpm'], 'cosign-3.1.3-1.fc44.src.rpm')
        self.assertFalse(live['rpmFileOwners'][0]['actualFileIntegrityVerified'])
        self.assertEqual(live['catalogedFileMetadata'][0]['executable']['format'], 'elf')
        self.assertFalse(live['independentFileBytesObserved'])
        self.assertEqual(live['independentPlatformProof'], 'unknown')
        self.assertFalse(result['releaseEligible'])
        self.assertFalse(result['releaseFreshnessReevaluated'])

    def test_relationships_do_not_invent_ownership_of_retained_objects(self):
        result = self.report()
        historical = next(path for path in result['findings'][0]['paths'] if path['path'] == OBJECT)
        self.assertEqual(historical['kind'], 'ostree-object')
        self.assertEqual(historical['ownership'], 'unknown')
        self.assertEqual(historical['rpmFileOwners'], [])

    def test_duplicate_occurrences_union_every_alias_and_path(self):
        second = deepcopy(self.result['blocked'][0])
        second['aliases'].append('GHSA-aaaa-bbbb-cccc')
        second['locations'] = ['/unmatched-location']
        second['locationCoverage'] = 'unknown'
        self.result['blocked'].append(second)
        finding = self.report()['findings'][0]
        self.assertEqual(finding['occurrences'], 2)
        self.assertIn('GHSA-aaaa-bbbb-cccc', finding['aliases'])
        self.assertEqual(finding['findingPathsMissingFromArtifactLocations'], ['/unmatched-location'])
        self.assertEqual(finding['locationCoverage'], 'unknown')

    def test_unmatched_component_and_malformed_path_remain_unknown_or_error(self):
        self.go['purl'] = COMPONENT + '-other'
        finding = self.report()['findings'][0]
        self.assertEqual(finding['nativeComponentMatch'], 'unknown')
        self.assertEqual(finding['artifacts'], [])
        self.result['blocked'][0]['locations'] = ['/usr/../secret']
        with self.assertRaises(ValueError): self.report()

    def test_hash_image_schema_source_and_status_binding_fail_closed(self):
        mutations = [lambda: self.result.update(image=IMAGE.replace('a' * 64, 'b' * 64)),
                     lambda: self.result.update(schema=True), lambda: self.result.update(status='pass'),
                     lambda: self.extraction.update(schema=True), lambda: self.extraction.update(sbomSha256='f' * 64),
                     lambda: self.extraction.update(signedDigest='sha256:' + 'f' * 64),
                     lambda: self.extraction.update(sourcePath='/different'),
                     lambda: self.sbom['source'].update(type='image')]
        for change in mutations:
            self.setUp()
            change()
            with self.assertRaises(ValueError): self.report()

    def test_malformed_aliases_exploitation_flag_and_duplicate_artifacts_reject(self):
        for field, value in [('aliases', []), ('aliases', [1]), ('aliases', ['missing-primary']),
                             ('knownExploited', 1), ('severity', 'critical'), ('reason', '')]:
            self.setUp()
            self.result['blocked'][0][field] = value
            with self.assertRaises(ValueError): self.report()
        self.setUp()
        self.sbom['artifacts'].append(deepcopy(self.go))
        with self.assertRaises(ValueError): self.report()

    def test_httpd_and_freerdp_expected_digests_are_not_integrity_verification(self):
        for name in ('httpd-tools', 'freerdp-libs'):
            rpm = deepcopy(self.rpm)
            rpm.update(id=name, name=name)
            self.sbom['artifacts'].append(rpm)
        packages = self.report()['focusedRpmPackages']
        self.assertEqual({p['rpm']['name'] for p in packages}, {'httpd-tools', 'freerdp-libs'})
        self.assertTrue(all(not p['actualFileIntegrityVerified'] for p in packages))
        self.assertEqual(packages[0]['declaredFiles'][0]['digest']['algorithm'], 'sha256')

    def test_artifact_id_fallback_is_exactly_supported(self):
        self.go.pop('purl')
        self.result['blocked'][0]['component'] = 'go1'
        self.assertEqual(self.report()['findings'][0]['nativeComponentMatch'], 'exact')

    def test_unknown_native_locations_and_missing_file_catalog_remain_visible(self):
        self.go['locations'].append({'accessPath': 'relative'})
        self.sbom.pop('files')
        result = self.report()
        self.assertEqual(result['findings'][0]['artifacts'][0]['locationCoverage'], 'unknown')
        self.assertTrue(all(path['catalogedFileMetadata'] == [] for path in result['findings'][0]['paths']))

    def test_full_cli_hashes_manifest_sbom_and_result_without_overwriting_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {'io.finite.profile': 'bluefin-generic'}}}
            config_raw = json.dumps(config).encode()
            manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'config': {'digest': 'sha256:' + hashlib.sha256(config_raw).hexdigest(), 'size': len(config_raw)}}
            parent = json.dumps(manifest).encode()
            image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(parent).hexdigest()
            self.result['image'] = image
            self.extraction.update(signedDigest=image.split('@')[1], scannedManifestDigest=image.split('@')[1])
            sbom_raw = json.dumps(self.sbom).encode()
            self.extraction['sbomSha256'] = hashlib.sha256(sbom_raw).hexdigest()
            for name, raw in [('sbom.syft.json', sbom_raw), ('image-config.json', config_raw), ('image-manifest.json', parent),
                              ('security-result.json', json.dumps(self.result).encode()), ('extraction.json', json.dumps(self.extraction).encode())]:
                (directory / name).write_bytes(raw)
            output = directory / 'summary.json'
            arguments = ['--directory', str(directory), '--image', image, '--output', str(output)]
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit): native.main(arguments)
            environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite'}
            with patch.dict(os.environ, environment, clear=True): self.assertEqual(native.main(arguments), 0)
            result = json.loads(output.read_text())
            self.assertEqual(result['sourceResultSha256'], hashlib.sha256((directory / 'security-result.json').read_bytes()).hexdigest())
            self.assertEqual(result['sbomSha256'], hashlib.sha256(sbom_raw).hexdigest())
            with patch.dict(os.environ, environment, clear=True), self.assertRaises(SystemExit): native.main(arguments)
            output.unlink()
            (directory / 'sbom.syft.json').write_bytes(sbom_raw + b' ')
            with patch.dict(os.environ, environment, clear=True), self.assertRaises(SystemExit): native.main(arguments)


if __name__ == '__main__':
    unittest.main()
