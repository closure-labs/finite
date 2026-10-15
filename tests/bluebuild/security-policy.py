#!/usr/bin/env python3
"""Negative tests for the independent vulnerability/signing publication boundary."""
from datetime import datetime, timezone
from contextlib import chdir
import importlib.util
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('security_policy', ROOT / 'scripts/bluebuild/security-policy.py')
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)
NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
STAMP = '2026-10-12T10:00:00Z'
DIGEST = 'sha256:' + 'a' * 64
IMAGE = 'ghcr.io/closure-labs/finite@' + DIGEST
DATABASE_COVERAGE = [{'vulnerability': {'provider': 'fedora'},
                      'packages': [{'os': {'name': 'fedora', 'version': '44'},
                                    'package': {'name': 'openssl', 'ecosystem': 'rpm'}}]}]


def evidence():
    policy = security.load_policy(ROOT / 'automation/security/image-policy.json')
    # Historical gate fixtures remain independent of the live reviewed mode.
    policy.pop('blockingBasis', None)
    policy.pop('confirmedDesktopRisks', None)
    policy.update(mode='fixable-severity', blockKnownExploited=True,
                  blockedFixableSeverities=['High', 'Critical'])
    sbom = {'source': {'type': 'image', 'metadata': {'manifestDigest': DIGEST}},
            'distro': {'id': 'bluefin', 'versionID': '44'},
            'artifacts': [{'id': str(i), 'type': 'rpm', 'foundBy': 'rpm-db-cataloger', 'name': 'package-' + str(i), 'version': '1'}
                          for i in range(100)]}
    sbom['artifacts'][0].update(name='fedora-release-common', version='44-18')
    scan = {'source': {'type': 'image', 'target': {'manifestDigest': DIGEST}},
            'distro': {'name': 'fedora', 'version': '44'}, 'matches': [],
            'descriptor': {'name': 'grype', 'version': '0.112.0', 'timestamp': STAMP,
                           'db': {'status': {'valid': True, 'built': STAMP},
                                  'providers': {'fedora': {'captured': STAMP}, 'kev': {'captured': STAMP}}}}}
    return policy, sbom, scan


def finding(severity='High', fixed=True, known=False):
    return {'vulnerability': {'id': 'CVE-2026-1234', 'severity': severity,
                             'fix': {'state': 'fixed' if fixed else 'not-fixed', 'versions': ['2'] if fixed else []},
                             'knownExploited': [{'cve': 'CVE-2026-1234'}] if known else []},
            'artifact': {'id': 'pkg1', 'purl': 'pkg:rpm/fedora/example@1'}}


def scanner_command(image, directory, policy):
    # Exercise scanner failures under an explicit historical fixture policy,
    # independently of the currently reviewed production policy mode.
    # Keep the policy in a temporary file: reviewed proof rows can exceed the
    # operating system's per-argument limit even though the policy is valid.
    fixture = Path(directory).parent / 'scanner-fixture-policy.json'
    fixture.write_text(json.dumps(policy))
    bootstrap = ('import importlib.util,json,sys; '
                 'fixture=json.load(open(sys.argv.pop(1))); '
                 'spec=importlib.util.spec_from_file_location("scanner",sys.argv[1]); '
                 'scanner=importlib.util.module_from_spec(spec); spec.loader.exec_module(scanner); '
                 'scanner.policy_module.load_policy=lambda path:fixture; '
                 'sys.argv=sys.argv[1:]; scanner.main()')
    return [sys.executable, '-c', bootstrap, str(fixture), str(ROOT / 'scripts/bluebuild/security-scan.py'), image, str(directory)]


class Policy(unittest.TestCase):
    def setUp(self):
        self.policy, self.sbom, self.scan = evidence()

    def evaluate(self):
        return security.evaluate(self.sbom, self.scan, IMAGE, self.policy, NOW, database_coverage=DATABASE_COVERAGE)

    def test_diagnostic_candidate_cannot_qualify_release_before_catalog_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('extraction.json', 'source-provenance.json', 'security-result.json'):
                for marker in ({'releaseEligible': False}, {'sourceType': 'locally-built-unpublished'}):
                    with self.subTest(name=name, marker=marker):
                        path = directory / name
                        path.write_text(json.dumps(marker))
                        with patch.object(security, 'evaluate') as evaluate:
                            with self.assertRaisesRegex(ValueError, 'cannot qualify a release'):
                                security.verify(directory, IMAGE)
                            evaluate.assert_not_called()
                        path.unlink()

    def test_clean_supported_inventory_passes_without_rpm_vulnerabilities(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['coverage']['effective'], 'fedora:44')
        self.assertEqual(result['coverage']['original']['id'], 'bluefin')
        self.assertEqual(result['coverage']['rpmPackages'], 100)

    def test_missing_or_inconsistent_distribution_proof_fails(self):
        for change in ('distro', 'version', 'rpm', 'release', 'scan_distro'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'distro': self.sbom['distro']['id'] = 'unknown'
                if change == 'version': self.sbom['distro']['versionID'] = '45'
                if change == 'rpm': self.sbom['artifacts'] = []
                if change == 'release': self.sbom['artifacts'][0]['name'] = 'other'
                if change == 'scan_distro': self.scan['distro']['name'] = 'bluefin'
                with self.assertRaises(ValueError): self.evaluate()

    def test_wrong_digest_or_mutable_reference_fails(self):
        with self.assertRaises(ValueError):
            security.evaluate(self.sbom, self.scan, IMAGE.replace('a' * 64, 'b' * 64), self.policy, NOW, database_coverage=DATABASE_COVERAGE)
        self.scan['source']['target']['manifestDigest'] = 'sha256:' + 'b' * 64
        with self.assertRaises(ValueError): self.evaluate()
        with self.assertRaises(ValueError): security.inventory(self.sbom, 'ghcr.io/closure-labs/finite:finite', self.policy)

    def test_stale_database_provider_or_scan_fail(self):
        for target, field in [(self.scan['descriptor']['db']['status'], 'built'),
                              (self.scan['descriptor']['db']['providers']['kev'], 'captured'),
                              (self.scan['descriptor']['db']['providers']['fedora'], 'captured'),
                              (self.scan['descriptor'], 'timestamp')]:
            old = target[field]
            for stamp in ['2026-10-01T00:00:00Z', '2026-11-01T00:00:00Z']:
                target[field] = stamp
                with self.assertRaises(ValueError): self.evaluate()
            target[field] = old
        self.scan['descriptor']['db']['status']['valid'] = False
        with self.assertRaises(ValueError): self.evaluate()

    def test_fixable_high_critical_and_any_known_exploited_block(self):
        for severity, fixed, known in [('High', True, False), ('Critical', True, False), ('Low', False, True)]:
            self.scan['matches'] = [finding(severity, fixed, known)]
            self.assertEqual(self.evaluate()['status'], 'blocked')
        self.scan['matches'] = [finding('High', False, False), finding('Medium', True, False)]
        self.assertEqual(self.evaluate()['status'], 'pass')

    def test_known_exploited_alias_is_not_lost(self):
        match = finding('Low', False)
        match['relatedVulnerabilities'] = [{'knownExploited': [{'cve': 'CVE-2026-1234'}]}]
        self.scan['matches'] = [match]
        self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_scanner_ignored_match_cannot_bypass_policy(self):
        self.scan['ignoredMatches'] = [{**finding(), 'appliedIgnoreRules': [{}]}]
        self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_exception_requires_exact_component_advisory_digest_and_expiry(self):
        self.scan['matches'] = [finding()]
        exception = {'digest': DIGEST, 'component': 'pkg:rpm/fedora/example@1', 'advisory': 'CVE-2026-1234',
                     'approvedAt': STAMP, 'expiresAt': '2026-10-20T00:00:00Z',
                     'reviewedBy': 'maintainer', 'reason': 'Fixture with vendor backport evidence'}
        self.policy['exceptions'] = [exception]
        self.assertEqual(self.evaluate()['status'], 'pass')
        for field, value in [('component', 'pkg:rpm/fedora/example@2'), ('advisory', 'CVE-2026-9999'),
                             ('digest', 'sha256:' + 'b' * 64), ('expiresAt', '2026-10-12T11:00:00Z')]:
            with self.subTest(field=field):
                self.policy['exceptions'] = [{**exception, field: value}]
                self.assertEqual(self.evaluate()['status'], 'blocked')
        self.policy['exceptions'] = [{**exception, 'expiresAt': '2027-01-01T00:00:00Z'}]
        with self.assertRaises(ValueError): self.evaluate()

    def exact_exception(self):
        return {'digest': DIGEST, 'component': 'pkg:rpm/fedora/example@1', 'advisory': 'CVE-2026-1234',
                'approvedAt': STAMP, 'expiresAt': '2026-10-20T00:00:00Z',
                'reviewedBy': 'maintainer', 'reason': 'Fixture exact ordinary exception'}

    def test_known_exploitation_cannot_be_waived_by_exact_ordinary_exception(self):
        self.scan['matches'] = [finding('Low', False, True)]
        self.policy['exceptions'] = [self.exact_exception()]
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(len(result['blocked']), 1)
        self.assertTrue(result['blocked'][0]['knownExploited'])
        self.assertEqual(result['exceptionsApplied'], [])

    def test_related_known_exploitation_and_ignored_matches_cannot_be_waived(self):
        for group in ('matches', 'ignoredMatches'):
            with self.subTest(group=group):
                self.scan['matches'] = []
                self.scan['ignoredMatches'] = []
                match = finding('Low', False)
                match['relatedVulnerabilities'] = [{'id': 'CVE-2026-ALIAS',
                                                   'knownExploited': [{'cve': 'CVE-2026-ALIAS'}]}]
                self.scan[group] = [match]
                self.policy['exceptions'] = [self.exact_exception()]
                result = self.evaluate()
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['matches'], 1)
                self.assertEqual(len(result['blocked']), 1)
                self.assertTrue(result['blocked'][0]['knownExploited'])
                self.assertEqual(result['exceptionsApplied'], [])

    def test_known_exploitation_switch_disabled_preserves_ordinary_exception_behavior(self):
        self.policy['blockKnownExploited'] = False
        self.policy['exceptions'] = [self.exact_exception()]
        self.scan['matches'] = [finding('High', True, True)]
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['blocked'], [])
        self.assertEqual(len(result['exceptionsApplied']), 1)
        self.assertTrue(result['exceptionsApplied'][0]['knownExploited'])
        # Without the KEV gate, a low/unfixed finding is outside the ordinary
        # fixable-severity gate and does not falsely consume an exception.
        self.scan['matches'] = [finding('Low', False, True)]
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['blocked'], [])
        self.assertEqual(result['exceptionsApplied'], [])

    def test_missing_database_distribution_coverage_fails(self):
        for proof in (None, [], [{'vulnerability': {'provider': 'other'}, 'packages': []}]):
            with self.assertRaises(ValueError):
                security.evaluate(self.sbom, self.scan, IMAGE, self.policy, NOW, database_coverage=proof)

    def test_scanner_failure_is_distinct_from_vulnerability_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/security-policy.py'),
                                     str(directory), IMAGE], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads((directory / 'security-result.json').read_text())['status'], 'scanner-error')

    def test_failed_scanner_cannot_emit_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = '{}'
            config_digest = 'sha256:' + hashlib.sha256(config.encode()).hexdigest()
            manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                   'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                                              'size': len(config.encode()), 'digest': config_digest}})
            image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(manifest.encode()).hexdigest()
            (directory / 'umoci').write_text('#!/bin/sh\necho \'umoci version 0.6.0\'\n')
            (directory / 'umoci').chmod(0o755)
            (directory / 'syft').write_text('#!/bin/sh\nexit 42\n')
            (directory / 'syft').chmod(0o755)
            (directory / 'skopeo').write_text('#!' + sys.executable + '\n' + r"""
import os, pathlib, sys
raw = os.environ['MOCK_MANIFEST']
digest = sys.argv[-2].split('@')[1]
pathlib.Path(sys.argv[sys.argv.index('--digestfile') + 1]).write_text(digest)
blobs = pathlib.Path(sys.argv[-1].removeprefix('oci:').removesuffix(':audit')) / 'blobs/sha256'
blobs.mkdir(parents=True)
(blobs / digest.removeprefix('sha256:')).write_text(raw)
(blobs / os.environ['MOCK_CONFIG_DIGEST'].removeprefix('sha256:')).write_text(os.environ['MOCK_CONFIG'])
""")
            (directory / 'skopeo').chmod(0o755)
            result = subprocess.run(scanner_command(image, directory / 'evidence', self.policy),
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'],
                                         'MOCK_MANIFEST': manifest, 'MOCK_CONFIG': config,
                                         'MOCK_CONFIG_DIGEST': config_digest}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            status = json.loads((directory / 'evidence/security-result.json').read_text())
            self.assertEqual(status['status'], 'scanner-error')
            self.assertIn("['syft',", status['error'])
            self.assertIn('exit status 42', status['error'])
            self.assertIn("'--base-path'", status['error'])
            self.assertIn("'--override-default-catalogers', 'image'", status['error'])
            self.assertFalse((directory / 'evidence/vulnerabilities.json').exists())

    def test_disk_copy_must_preserve_digest_before_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tool = directory / 'skopeo'
            tool.write_text('#!' + sys.executable + '\n' + r"""
import json, os, pathlib, sys
pathlib.Path(os.environ['CALLS']).write_text(json.dumps(sys.argv[1:]))
pathlib.Path(sys.argv[sys.argv.index('--digestfile') + 1]).write_text('sha256:' + 'b' * 64)
""")
            tool.chmod(0o755)
            (directory / 'syft').write_text('#!/bin/sh\ntouch "${UNEXPECTED}"\nexit 42\n')
            (directory / 'syft').chmod(0o755)
            result = subprocess.run(scanner_command(IMAGE, directory / 'scan', self.policy),
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'],
                                         'CALLS': str(directory / 'calls'), 'UNEXPECTED': str(directory / 'unexpected')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('changed the requested image digest', result.stderr)
            self.assertFalse((directory / 'unexpected').exists())
            args = json.loads((directory / 'calls').read_text())
            self.assertIn('--preserve-digests', args)
            self.assertIn('--src-no-creds', args)
            self.assertIn('--all', args)
            self.assertEqual(args[args.index('--image-parallel-copies') + 1], '1')
            self.assertIn('docker://' + IMAGE, args)
            copied_image = Path(args[-1].removeprefix('oci:').removesuffix(':audit'))
            self.assertFalse(copied_image.parent.exists())


class ManifestBinding(unittest.TestCase):
    def setUp(self):
        self.config = '{}'
        self.config_digest = 'sha256:' + hashlib.sha256(self.config.encode()).hexdigest()
        self.child = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                 'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                                            'size': len(self.config.encode()), 'digest': self.config_digest},
                                 'layers': []})
        self.digest = 'sha256:' + hashlib.sha256(self.child.encode()).hexdigest()
        self.descriptor = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': self.digest,
                           'size': len(self.child.encode()), 'platform': {'os': 'linux', 'architecture': 'amd64'}}
        self.parent = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                       'manifests': [self.descriptor]}

    def binding(self, parent=None, child=None):
        raw = json.dumps(self.parent if parent is None else parent)
        image = 'ghcr.io/closure-labs/finite@sha256:' + hashlib.sha256(raw.encode()).hexdigest()
        return image, {'parent': raw, 'child': self.child if child is None else child}

    def test_raw_parent_and_child_authenticate_platform_inventory(self):
        image, manifests = self.binding()
        self.assertEqual(security.manifest_binding(image, manifests), self.digest)
        policy, sbom, scan = evidence()
        sbom['source']['metadata']['manifestDigest'] = self.digest
        scan['source']['target']['manifestDigest'] = self.digest
        result = security.evaluate(sbom, scan, image, policy, NOW, DATABASE_COVERAGE, manifests)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['coverage']['scannedManifestDigest'], self.digest)
        sbom['source']['metadata']['manifestDigest'] = DIGEST
        with self.assertRaises(ValueError):
            security.evaluate(sbom, scan, image, policy, NOW, DATABASE_COVERAGE, manifests)

    def test_tampered_missing_or_unsupported_metadata_fails(self):
        image, manifests = self.binding()
        for invalid in ({**manifests, 'parent': manifests['parent'] + ' '},
                        {**manifests, 'child': self.child + ' '}, {**manifests, 'child': None},
                        {**manifests, 'parent': ' ' * (security.MANIFEST_LIMIT + 1)}):
            with self.assertRaises(ValueError): security.manifest_binding(image, invalid)
        for parent in ({**self.parent, 'mediaType': 'unexpected'},
                       {**self.parent, 'manifests': [self.descriptor, self.descriptor]},
                       {**self.parent, 'manifests': [self.descriptor, {**self.descriptor, 'platform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v3'}}]},
                       {**self.parent, 'manifests': [{**self.descriptor, 'platform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v3'}}]},
                       {**self.parent, 'manifests': [{**self.descriptor, 'platform': {'os': 'linux', 'architecture': 'arm64'}}]},
                       {**self.parent, 'manifests': [{**self.descriptor, 'mediaType': 'unexpected'}]}):
            modified_image, modified = self.binding(parent)
            with self.assertRaises(ValueError): security.manifest_binding(modified_image, modified)

    def test_direct_manifest_retains_exact_digest_binding(self):
        image = 'ghcr.io/closure-labs/finite@' + self.digest
        self.assertEqual(security.manifest_binding(image, {'parent': self.child, 'child': None}), self.digest)
        with self.assertRaises(ValueError):
            security.manifest_binding(image, {'parent': self.child, 'child': self.child})

    def test_layout_selection_preserves_original_signed_blobs(self):
        spec = importlib.util.spec_from_file_location('security_scan', ROOT / 'scripts/bluebuild/security-scan.py')
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)
        image, manifests = self.binding()
        manifests['config'] = self.config
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            blobs = directory / 'image/blobs/sha256'
            blobs.mkdir(parents=True)
            output = directory / 'evidence'
            output.mkdir()
            (blobs / image.split(':')[-1]).write_text(manifests['parent'])
            (blobs / self.digest.split(':')[-1]).write_text(self.child)
            (blobs / self.config_digest.split(':')[-1]).write_text(self.config)
            self.assertEqual(scanner.prepare_layout(directory / 'image', image, output), manifests)
            self.assertEqual(json.loads((directory / 'image/index.json').read_text())['manifests'],
                             [{**self.descriptor, 'annotations': {'org.opencontainers.image.ref.name': 'audit'}}])
            self.assertEqual((blobs / image.split(':')[-1]).read_text(), manifests['parent'])
            self.assertEqual(security.read_manifests(output), manifests)
            (output / 'platform-manifest.json').unlink()
            with self.assertRaises(ValueError):
                security.manifest_binding(image, security.read_manifests(output))
            (output / 'image-manifest.json').unlink()
            with self.assertRaises(ValueError): security.read_manifests(output)
            (output / 'image-manifest.json').write_text(self.child)
            direct = 'ghcr.io/closure-labs/finite@' + self.digest
            self.assertEqual(security.manifest_binding(direct, security.read_manifests(output)), self.digest)
            (output / 'image-manifest.json').unlink()
            with self.assertRaises(ValueError): security.read_manifests(output)


    def test_directory_inventory_requires_exact_authenticated_extraction(self):
        image, manifests = self.binding()
        policy, sbom, scan = evidence()
        source = '/tmp/finite-security-image-test/bundle/rootfs'
        sbom['source'] = {'type': 'directory', 'metadata': {'path': source}}
        scan['source'] = {'type': 'directory', 'target': source}
        extraction = {'schema': 1, 'method': 'umoci-rootless', 'toolVersion': 'umoci version 0.6.0\nimage spec: 1.1.1\nruntime spec: 1.2.1\ngo: go1.26.7',
                      'signedDigest': image.split('@')[1], 'scannedManifestDigest': self.digest,
                      'sourcePath': source, 'basePath': source, 'catalogers': 'image'}
        manifests['extraction'] = extraction
        result = security.evaluate(sbom, scan, image, policy, NOW, DATABASE_COVERAGE, manifests)
        self.assertEqual(result['status'], 'pass')
        for key, value in [('signedDigest', DIGEST), ('scannedManifestDigest', DIGEST),
                           ('sourcePath', '/tmp/other'), ('basePath', '/'), ('method', 'unverified'),
                           ('toolVersion', ''), ('catalogers', 'directory')]:
            with self.subTest(key=key):
                original = extraction[key]
                extraction[key] = value
                with self.assertRaises(ValueError): security.inventory(sbom, image, policy, manifests)
                extraction[key] = original
        for path in ('relative', '/tmp/../rootfs'):
            original = dict(extraction)
            extraction.update(sourcePath=path, basePath=path)
            sbom['source']['metadata']['path'] = path
            with self.assertRaises(ValueError): security.inventory(sbom, image, policy, manifests)
            extraction.update(original)
        sbom['source']['metadata']['path'] = source
        scan['source']['target'] = '/tmp/other'
        with self.assertRaises(ValueError):
            security.evaluate(sbom, scan, image, policy, NOW, DATABASE_COVERAGE, manifests)
        del manifests['extraction']
        with self.assertRaises(ValueError): security.inventory(sbom, image, policy, manifests)

    def test_extraction_provenance_revalidates_native_sbom_bytes(self):
        image, manifests = self.binding()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'image-manifest.json').write_text(manifests['parent'])
            (directory / 'platform-manifest.json').write_text(manifests['child'])
            sbom = directory / 'sbom.syft.json'
            sbom.write_text('{}')
            (directory / 'extraction.json').write_text(json.dumps({'sbomSha256': security.file_sha256(sbom)}))
            self.assertIn('extraction', security.read_manifests(directory))
            sbom.write_text('{"modified":true}')
            with self.assertRaises(ValueError): security.read_manifests(directory)


class ScannerOutputPaths(unittest.TestCase):
    def setUp(self):
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, ROOT / path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        self.scanner = load('scanner_paths', 'scripts/bluebuild/security-scan.py')
        self.collector = load('collector_paths', 'scripts/ci/rpm-file-evidence.py')

    def invoke_production_relative_output(self, temporary, symlink_sbom=False):
        scanner = self.scanner
        directory = temporary / '.bluebuild/security-bluefin-generic'
        observed = []
        class CollectorReached(RuntimeError):
            pass
        def run(command, output=None):
            if command[0] == 'skopeo':
                Path(command[command.index('--digestfile') + 1]).write_text(DIGEST)
            elif command[0] == 'syft':
                path = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('syft-json=')))
                if symlink_sbom:
                    target = temporary / 'outside-sbom.json'
                    target.write_text('{}')
                    path.symlink_to(target)
                else:
                    path.write_text('{}')
            elif command[0] == 'python3' and command[1].endswith('/rpm-file-evidence.py'):
                sbom = command[command.index('--sbom') + 1]
                output = command[command.index('--output') + 1]
                self.assertEqual(sbom, str(directory / 'sbom.syft.json'))
                self.assertEqual(output, str(directory / 'rpm-file-evidence.json'))
                self.assertTrue(self.collector.canonical(sbom))
                self.assertTrue(self.collector.canonical(output))
                # Invoke the real no-follow reader rather than merely matching
                # command strings. Production relative paths failed here.
                self.assertEqual(self.collector.read_sbom(Path(sbom))[0], {})
                observed.append((sbom, output))
                raise CollectorReached()
        inspected = json.dumps({'Digest': DIGEST, 'Labels': {}})
        with chdir(temporary), patch.object(sys, 'argv', ['security-scan.py', IMAGE, '.bluebuild/security-bluefin-generic']), \
                patch.object(scanner.policy_module, 'load_policy', return_value={'mode': 'upstream-maintained-risk'}), \
                patch.object(scanner.baseline_module, 'authenticate', return_value={}), \
                patch.object(scanner.baseline_module, 'context', return_value={}), \
                patch.object(scanner, 'prepare_layout', return_value={'config': '{}'}), \
                patch.object(scanner.subprocess, 'check_output', side_effect=[inspected, 'umoci fixture']), \
                patch.object(scanner, 'run', side_effect=run):
            if symlink_sbom:
                with self.assertRaises(SystemExit) as exit_status:
                    scanner.main()
                self.assertEqual(exit_status.exception.code, 2)
                result = json.loads((directory / 'security-result.json').read_text())
                self.assertEqual(result['status'], 'scanner-error')
                self.assertEqual(observed, [])
            else:
                with self.assertRaises(CollectorReached):
                    scanner.main()
                self.assertEqual(len(observed), 1)

    def test_relative_scan_output_reaches_actual_canonical_sbom_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.invoke_production_relative_output(Path(temporary))

    def test_relative_output_does_not_hide_symlinked_sbom(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.invoke_production_relative_output(Path(temporary), symlink_sbom=True)

    def test_output_parent_symlinks_and_parent_traversal_fail_before_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            outside = temporary / 'outside'
            outside.mkdir()
            (temporary / 'alias').symlink_to(outside, target_is_directory=True)
            for relative in ('alias/evidence', 'alias/../evidence', '../evidence'):
                with self.subTest(relative=relative), chdir(temporary), \
                        patch.object(sys, 'argv', ['security-scan.py', IMAGE, relative]), \
                        patch.object(self.scanner, 'run') as run:
                    with self.assertRaises(SystemExit) as exit_status:
                        self.scanner.main()
                    self.assertEqual(exit_status.exception.code, 2)
                    run.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])


class BoundedScanner(unittest.TestCase):
    def test_local_invocation_is_rejected_before_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), IMAGE,
                                     str(Path(temporary) / 'scan')],
                                    env={**os.environ, 'GITHUB_ACTIONS': 'false'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('hosted-only', result.stderr)
            self.assertFalse((Path(temporary) / 'scan').exists())

    def test_existing_passing_evidence_is_rejected_before_service_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'scan'
            directory.mkdir()
            record = {'status': 'pass', 'image': IMAGE}
            (directory / 'security-result.json').write_text(json.dumps(record))
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), IMAGE, str(directory)],
                                    env={**os.environ, 'GITHUB_ACTIONS': 'true'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(json.loads((directory / 'security-result.json').read_text()), record)
            self.assertFalse((directory / 'runner-resources.log').exists())

    def test_killed_service_preserves_failure_and_enforces_memory_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            memory = directory / 'awk'
            memory.write_text('#!/bin/sh\nprintf \'16777216\\n\'\n')
            memory.chmod(0o755)
            sudo = directory / 'sudo'
            sudo.write_text('#!' + sys.executable + '\n' + r"""
import json, os, sys
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\n')
if sys.argv[1] == 'systemd-run':
    print('Memory cap fixture: scanner killed')
    sys.exit(137)
print('Result=oom-kill')
""")
            sudo.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), IMAGE,
                                     str(directory / 'scan')],
                                    env={**os.environ, 'GITHUB_ACTIONS': 'true', 'CALLS': str(directory / 'calls'),
                                         'PATH': str(directory) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 137, result.stderr)
            record = json.loads((directory / 'scan/security-result.json').read_text())
            self.assertEqual(record['status'], 'scanner-error')
            self.assertEqual(record['exitCode'], 137)
            self.assertIn('oom-kill', (directory / 'scan/runner-resources.log').read_text())
            calls = [json.loads(line) for line in (directory / 'calls').read_text().splitlines()]
            self.assertIn('--property=MemoryMax=10240M', calls[0])
            self.assertIn('--property=MemorySwapMax=0', calls[0])
            self.assertIn('--property=NoNewPrivileges=yes', calls[0])
            self.assertIn('--property=CapabilityBoundingSet=', calls[0])
            self.assertIn('--property=ProtectControlGroups=yes', calls[0])
            self.assertTrue(any(call[:2] == ['systemctl', 'stop'] for call in calls))
            self.assertIn('--setenv=GOMEMLIMIT=8192MiB', calls[0])
            self.assertIn('--setenv=SYFT_PARALLELISM=1', calls[0])

    def test_service_success_and_policy_block_preserve_exact_result(self):
        for status, outcome in ((0, 'pass'), (1, 'blocked'), (0, 'missing')):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                memory = directory / 'awk'
                memory.write_text('#!/bin/sh\nprintf \'8388608\\n\'\n')
                memory.chmod(0o755)
                sudo = directory / 'sudo'
                sudo.write_text('#!' + sys.executable + '\n' + r"""
import json, os, pathlib, sys
if sys.argv[1] == 'systemd-run':
    destination = pathlib.Path(sys.argv[-1])
    destination.mkdir()
    if os.environ['OUTCOME'] != 'missing':
        (destination / 'security-result.json').write_text(json.dumps({'status': os.environ['OUTCOME'], 'image': sys.argv[-2]}))
    sys.exit(int(os.environ['SERVICE_STATUS']))
""")
                sudo.chmod(0o755)
                result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), IMAGE,
                                         str(directory / 'scan')],
                                        env={**os.environ, 'GITHUB_ACTIONS': 'true', 'SERVICE_STATUS': str(status),
                                             'OUTCOME': outcome, 'PATH': str(directory) + ':' + os.environ['PATH']},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2 if outcome == 'missing' else status, result.stderr)
                record = json.loads((directory / 'scan/security-result.json').read_text())
                self.assertEqual(record['status'], 'scanner-error' if outcome == 'missing' else outcome)
                self.assertEqual(record['image'], IMAGE)
                self.assertIn('Scanner memory limit: 4096 MiB', (directory / 'scan/runner-resources.log').read_text())

    def test_insufficient_memory_stops_before_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            memory = directory / 'awk'
            memory.write_text('#!/bin/sh\nprintf \'4194304\\n\'\n')
            memory.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), IMAGE, str(directory / 'scan')],
                                    env={**os.environ, 'GITHUB_ACTIONS': 'true', 'PATH': str(directory) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Insufficient available memory', result.stderr)
            self.assertFalse((directory / 'scan').exists())


class PublicationBoundary(unittest.TestCase):
    def test_only_the_isolated_signer_receives_the_key(self):
        publication = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())['jobs']
        image = (ROOT / '.github/workflows/image.yml').read_text()
        self.assertNotIn('COSIGN_PRIVATE_KEY', image)
        self.assertNotIn('cosign_private_key', image)
        self.assertNotIn('secrets', publication['build'])
        workflow = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())
        caller = yaml.safe_load((ROOT / '.github/workflows/build.yml').read_text())['jobs']['publish']
        self.assertEqual(workflow[True]['workflow_call']['secrets'], {'COSIGN_PRIVATE_KEY': {'required': True}, 'COSIGN_PASSWORD': {'required': False}})
        self.assertEqual(caller['secrets'], {'COSIGN_PRIVATE_KEY': '${{ secrets.COSIGN_PRIVATE_KEY }}', 'COSIGN_PASSWORD': '${{ secrets.COSIGN_PASSWORD }}'})
        self.assertNotIn('secrets: inherit', (ROOT / '.github/workflows/build.yml').read_text())
        self.assertNotIn('secrets: inherit', (ROOT / '.github/workflows/publication.yml').read_text())
        self.assertEqual(publication['sign']['needs'], 'security')
        self.assertEqual(publication['sign']['environment'], 'image-signing')
        self.assertIn('sign', publication['qualification']['needs'])
        signer = publication['sign']
        self.assertIn("github.ref == 'refs/heads/main'", signer['if'])
        setup = next(step for step in signer['steps'] if step.get('uses') == './.github/actions/setup-nix')
        self.assertEqual(setup['with']['cache-mode'], 'none')
        self.assertNotIn('env', setup)
        sparse = set(signer['steps'][0]['with']['sparse-checkout'].splitlines())
        self.assertIn('cosign.pub', sparse)
        self.assertIn('secretspec.toml', sparse)
        self.assertNotIn('files/', sparse)
        self.assertNotIn('recipes/', sparse)
        sign = next(step for step in signer['steps'] if 'COSIGN_PRIVATE_KEY' in step.get('env', {}))
        self.assertEqual(sign['env']['CANDIDATE_DIGEST'], '${{ needs.security.outputs.digest }}')
        self.assertEqual(sign['env']['COSIGN_PRIVATE_KEY'], '${{ secrets.COSIGN_PRIVATE_KEY }}')
        self.assertIn('finite-ci-secrets-run image-signing', sign['run'])
        self.assertIn('--new-bundle-format=false --use-signing-config=false', sign['run'])
        self.assertNotIn('--tlog-upload=false', sign['run'])
        self.assertNotIn('--insecure-ignore', sign['run'])
        installer = next(step for step in signer['steps'] if step.get('uses', '').startswith('sigstore/cosign-installer@'))
        runtime = json.loads((ROOT / 'sources/cosign-runtime.json').read_text())
        self.assertEqual(installer['with']['cosign-release'], 'v' + runtime['version'])
        self.assertNotIn('scripts/', sign['run'])
        self.assertNotIn('run download', sign['run'])
        for dependency in ('security', 'sign', 'qualification'):
            self.assertIn("needs." + dependency + ".result == 'success'", publication['promote']['if'])
        download = next(step for step in publication['promote']['steps'] if 'SECURITY_ARTIFACT' in step.get('env', {}))
        self.assertEqual(download['env']['SECURITY_ARTIFACT'], '${{ needs.security.outputs.evidence }}')

    def test_signer_preflight_rejects_missing_invalid_or_wrong_key_before_registry_access(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/publication.yml').read_text())['jobs']
        step = next(step for step in jobs['sign']['steps'] if 'COSIGN_PRIVATE_KEY' in step.get('env', {}))
        self.assertIn('timeout 30s cosign public-key --key env://COSIGN_PRIVATE_KEY', step['run'])
        step = dict(step, run=step['run'].split("<<'SIGN_IMAGE'\n", 1)[1].rsplit('SIGN_IMAGE', 1)[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'bin'
            tools.mkdir()
            (root / 'cosign.pub').write_text('fixture-public-key\n')
            bash = shutil.which('bash')
            self.assertIsNotNone(bash)
            programs = {
                'cosign': '#!/bin/bash\nprintf "%s\\n" "cosign:$1" >>"$CALLS"\n'
                          'if [[ $1 == public-key ]]; then\n'
                          '  if [[ $KEY_MODE == invalid ]]; then printf "%s" "$COSIGN_PRIVATE_KEY" >&2; exit 1; fi\n'
                          '  printf "%s\\n" "$DERIVED_PUBLIC_KEY"\nfi\n',
                'gh': '#!/bin/bash\nprintf "gh\\n" >>"$CALLS"\nprintf "%s\\n" "$GITHUB_SHA"\n',
                'docker': '#!/bin/bash\nprintf "docker:%s\\n" "$1" >>"$CALLS"\n'
                          'if [[ $1 == login ]]; then cat >/dev/null; fi\n'}
            for name, code in programs.items():
                path = tools / name
                path.write_text(code.replace('#!/bin/bash', '#!' + bash, 1))
                path.chmod(0o755)
            for label, key, derived, expected in [('missing', '', 'fixture-public-key', False),
                    ('invalid', 'sensitive-fixture-key', 'fixture-public-key', False),
                    ('mismatch', 'sensitive-fixture-key', 'wrong-public-key', False),
                    ('matching', 'sensitive-fixture-key', 'fixture-public-key', True)]:
                calls = root / (label + '.calls')
                env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'], 'CALLS': str(calls),
                       'KEY_MODE': label, 'COSIGN_PRIVATE_KEY': key, 'DERIVED_PUBLIC_KEY': derived,
                       'CANDIDATE_DIGEST': DIGEST, 'GITHUB_SHA': 'b' * 40,
                       'REGISTRY_TOKEN': 'fixture-token', 'REGISTRY_USER': 'fixture-user'}
                completed = subprocess.run(['bash', '-c', step['run']], cwd=root, env=env,
                                           capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode == 0, expected, completed.stderr)
                observed = calls.read_text() if calls.exists() else ''
                self.assertNotIn('sensitive-fixture-key', completed.stdout + completed.stderr)
                self.assertNotIn('fixture-token', completed.stdout + completed.stderr)
                if expected:
                    self.assertLess(observed.index('cosign:public-key'), observed.index('docker:login'))
                    self.assertIn('cosign:sign', observed)
                    self.assertIn('cosign:verify', observed)
                else:
                    self.assertNotIn('gh', observed)
                    self.assertNotIn('docker:', observed)
                    self.assertNotIn('cosign:sign', observed)
            self.assertEqual({path.name for path in root.iterdir()},
                             {'bin', 'cosign.pub', 'invalid.calls', 'mismatch.calls', 'matching.calls'})

    def test_release_scan_cannot_share_signing_credentials(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())['jobs']
        self.assertEqual(jobs['sign-release']['needs'], 'release')
        self.assertEqual(jobs['sign-release']['environment'], 'release')
        self.assertNotIn('COSIGN_PRIVATE_KEY', json.dumps(jobs['release']))
        self.assertNotIn('continue-on-error', json.dumps(jobs['release']))

    def test_policy_or_signature_failure_leaves_public_tags_untouched(self):
        spec = importlib.util.spec_from_file_location('publication_security', ROOT / 'scripts/bluebuild/publication.py')
        publication = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publication)
        manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json'})
        digest = 'sha256:' + hashlib.sha256(manifest.encode()).hexdigest()
        image = 'ghcr.io/closure-labs/finite@' + digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / '.bluebuild'
            output.mkdir()
            profile = 'bluefin-generic'
            record = {'publish': True, 'profile': profile, 'tags': ['finite', 'latest'],
                      'revision': 'revision', 'publishedDigest': '', 'previousDigest': '',
                      'recoveryReason': '', 'buildIdentity': 'identity', 'qualificationMode': 'enforce'}
            acceptance = {'accepted': True, 'candidate': image, 'previousDigest': '',
                          'profile': profile, 'revision': 'revision', 'buildIdentity': 'identity',
                          'secureBoot': True, 'encryptedRoot': True}
            (output / (profile + '-publication.json')).write_text(json.dumps(record))
            (output / (profile + '-image-ref.txt')).write_text(image)
            (output / (profile + '-acceptance.json')).write_text(json.dumps(acceptance))
            policy, sbom, scan = evidence()
            sbom['source']['metadata']['manifestDigest'] = digest
            scan['source']['target']['manifestDigest'] = digest
            security_dir = output / ('security-' + profile)
            security_dir.mkdir()
            (security_dir / 'image-manifest.json').write_text(manifest)
            (root / 'automation/security').mkdir(parents=True)
            (root / 'automation/security/image-policy.json').write_text(json.dumps(policy))
            # Use real current timestamps, so only the intended mutation fails.
            stamp = datetime.now(timezone.utc).isoformat()
            scan['descriptor']['timestamp'] = stamp
            scan['descriptor']['db']['status']['built'] = stamp
            for provider in scan['descriptor']['db']['providers'].values():
                provider['captured'] = stamp
            (security_dir / 'sbom.syft.json').write_text(json.dumps(sbom))
            (security_dir / 'database-coverage.json').write_text(json.dumps(DATABASE_COVERAGE))
            # Isolate the native-security gate; desktop receipt validation has
            # dedicated coverage and must not mask these security mutations.
            with patch.dict(os.environ, GITHUB_SHA='revision', FINITE_QUALIFICATION_MODE='enforce'), \
                    patch.object(publication.desktop, 'verify') as desktop:

                for failure in ('missing', 'stale', 'vulnerable', 'missing-binding'):
                    with self.subTest(failure=failure):
                        current = json.loads(json.dumps(scan))
                        if failure == 'stale': current['descriptor']['db']['status']['built'] = '2000-01-01T00:00:00Z'
                        if failure == 'vulnerable': current['matches'] = [finding()]
                        if failure == 'missing-binding': (security_dir / 'image-manifest.json').unlink()
                        if failure != 'missing':
                            (security_dir / 'vulnerabilities.json').write_text(json.dumps(current))
                        with patch.object(publication.subprocess, 'run') as registry:
                            with self.assertRaises((ValueError, FileNotFoundError)):
                                publication.promote(profile, root)
                            registry.assert_not_called()
                        (security_dir / 'image-manifest.json').write_text(manifest)
                (security_dir / 'vulnerabilities.json').write_text(json.dumps(scan))
                with patch.object(publication.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cosign')) as registry:
                    with self.assertRaises(subprocess.CalledProcessError):
                        publication.promote(profile, root)
                    desktop.assert_called()
                    self.assertEqual(registry.call_count, 1)
                    self.assertEqual(registry.call_args.args[0][:2], ['cosign', 'verify'])


class UpstreamRiskPolicy(unittest.TestCase):
    def setUp(self):
        self.policy, self.sbom, self.scan = evidence()
        self.policy.update(mode='upstream-maintained-risk', seriousAdvisories=[], reviewedDispositions=[])
        self.policy.pop('releaseBlockers', None)
        self.baseline = {'schema': 1, 'status': 'verified', 'image': IMAGE, 'profile': 'bluefin-generic',
                         'sourceRevision': '1' * 40, 'buildIdentity': 'v1:' + 'b' * 64,
                         'baseImage': 'ghcr.io/ublue-os/bluefin@sha256:' + 'c' * 64,
                         'trustPolicySha256': 'd' * 64}
        self.config = {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
            'org.opencontainers.image.revision': self.baseline['sourceRevision'],
            'io.finite.profile': self.baseline['profile'], 'io.finite.build-inputs': self.baseline['buildIdentity'],
            'org.opencontainers.image.base.name': self.baseline['baseImage'].replace('@', ':stable@'),
            'org.opencontainers.image.base.digest': self.baseline['baseImage'].split('@')[1]}}}
        self.bind_config()

    def bind_config(self):
        raw = json.dumps(self.config)
        self.manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                         'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                                    'digest': 'sha256:' + hashlib.sha256(raw.encode()).hexdigest(),
                                    'size': len(raw.encode())}}
        self.manifests = {'parent': json.dumps(self.manifest), 'child': None, 'config': raw}
        self.bind_manifest()

    def bind_manifest(self):
        self.manifests['parent'] = json.dumps(self.manifest)
        self.digest = 'sha256:' + hashlib.sha256(self.manifests['parent'].encode()).hexdigest()
        self.image = 'ghcr.io/closure-labs/finite@' + self.digest
        self.baseline['image'] = self.image
        self.sbom['source']['metadata']['manifestDigest'] = self.digest
        self.scan['source']['target']['manifestDigest'] = self.digest

    def evaluate(self, baseline=True):
        return security.evaluate(self.sbom, self.scan, self.image, self.policy, NOW,
                                 database_coverage=DATABASE_COVERAGE, manifests=self.manifests,
                                 approved_baseline=self.baseline if baseline else None)

    def serious(self):
        rule = {'id': 'fixture-serious', 'advisories': ['CVE-2026-1234', 'GO-2026-6604'],
                'riskClass': 'authentication-bypass', 'reason': 'Fixture serious authentication risk',
                'officialSources': ['https://go.dev/vuln/GO-2026-6604'],
                'reviewedBy': 'fixture-reviewer', 'reviewedAt': STAMP}
        self.policy['seriousAdvisories'] = [rule]
        return rule

    def disposition(self, kind='routine'):
        rule = {'id': 'fixture-proof', 'advisories': ['CVE-2026-1234', 'GO-2026-6604'],
                'digest': self.digest, 'component': 'pkg:rpm/fedora/example@1', 'platform': 'linux/amd64',
                'locations': ['/usr/bin/example'], 'disposition': kind,
                'reason': 'Fixture proof covering exact component, aliases and all locations',
                'officialSources': ['https://go.dev/vuln/GO-2026-6604'],
                'evidence': ['sha256:' + 'e' * 64 + ':/usr/bin/example'],
                'reviewedBy': 'fixture-reviewer', 'reviewedAt': STAMP,
                'expiresAt': '2026-10-20T00:00:00Z'}
        self.policy['reviewedDispositions'] = [rule]
        return rule

    def located(self, severity='Critical', fixed=False):
        match = finding(severity, fixed)
        match['artifact']['locations'] = [{'path': '/usr/bin/example'}]
        self.scan['matches'] = [match]
        return match

    def ordinary_exception(self):
        return {**Policy.exact_exception(self), 'digest': self.digest}

    def test_historical_output_omits_new_mode_metadata(self):
        self.located()
        result = self.evaluate()
        self.assertNotIn('trackedReleaseConcerns', result)
        self.assertNotIn('criticalSeverityAdvisories', result['blocked'][0])
        policy, sbom, scan = evidence()
        scan['matches'] = [finding()]
        result = security.evaluate(sbom, scan, IMAGE, policy, NOW,
                                   database_coverage=DATABASE_COVERAGE)
        self.assertNotIn('trackedReleaseConcerns', result)
        self.assertNotIn('criticalSeverityAdvisories', result['blocked'][0])

    def test_routine_findings_are_visible_not_cleared_or_erased(self):
        self.scan['matches'] = [finding('High'), finding('High', False), finding('Medium'), finding('Low')]
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['blocked'], [])
        self.assertEqual(len(result['advisories']), 4)
        self.assertEqual(result['observations'], result['advisories'])
        self.assertTrue(all(v['reason'] == 'maintained-upstream-advisory' for v in result['advisories']))
        self.assertEqual(result['approvedBaseline'], self.baseline)

    def test_missing_or_wrong_baseline_does_not_relax_severity_gate(self):
        with self.assertRaisesRegex(ValueError, 'approved baseline context'):
            self.evaluate(False)
        for field, value in [('image', IMAGE.replace('a' * 64, 'e' * 64)), ('profile', 'bluefin-dx-generic'),
                             ('sourceRevision', 'head'), ('buildIdentity', 'b' * 64),
                             ('baseImage', 'ghcr.io/attacker/base@sha256:' + 'c' * 64),
                             ('trustPolicySha256', ''), ('status', 'unverified'), ('schema', True),
                             ('profile', []), ('unknown', True)]:
            with self.subTest(field=field, value=value):
                original = dict(self.baseline)
                self.baseline[field] = value
                with self.assertRaises(ValueError):
                    self.evaluate()
                self.baseline = original

    def test_known_exploited_direct_related_ignored_and_exception_never_waive(self):
        self.policy['exceptions'] = [self.ordinary_exception()]
        for group in ('matches', 'ignoredMatches'):
            for direct in (True, False):
                with self.subTest(group=group, direct=direct):
                    self.scan['matches'], self.scan['ignoredMatches'] = [], []
                    match = self.located('Low', False)
                    if direct:
                        match['vulnerability']['knownExploited'] = [{'cve': 'CVE-2026-1234'}]
                    else:
                        match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604', 'knownExploited': [{}]}]
                    self.scan['matches'] = []
                    self.scan[group] = [match]
                    self.disposition('nonapplicable')
                    result = self.evaluate()
                    self.assertEqual(result['status'], 'blocked')
                    self.assertEqual(result['blocked'][0]['reason'], 'known-exploited')
                    self.assertEqual(result['exceptionsApplied'], [])

    def test_serious_aliases_block_unfixed_medium_and_survive_version_changes(self):
        self.serious()
        self.policy['exceptions'] = [self.ordinary_exception()]
        for severity in ('Medium', 'High'):
            for version in ('1', '2'):
                for primary in ('CVE-2026-1234', 'GO-2026-6604'):
                    with self.subTest(severity=severity, version=version, primary=primary):
                        match = finding(severity, False)
                        match['vulnerability']['id'] = primary
                        match['artifact']['purl'] = 'pkg:rpm/fedora/example@' + version
                        self.scan['matches'] = [match]
                        result = self.evaluate()
                        self.assertEqual(result['status'], 'blocked')
                        self.assertEqual(result['blocked'][0]['reason'], 'reviewed-serious-risk')
                        self.assertEqual(result['blocked'][0]['reviewRules'], ['fixture-serious'])

    def test_related_serious_alias_and_scanner_ignored_matches_block(self):
        self.serious()
        match = finding('Low', False)
        match['vulnerability']['id'] = 'CVE-2026-9999'
        match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604'}]
        self.scan['ignoredMatches'] = [match]
        result = self.evaluate()
        self.assertEqual(result['blocked'][0]['aliases'], ['CVE-2026-9999', 'GO-2026-6604'])
        self.assertEqual(result['status'], 'blocked')

    def test_untriaged_critical_blocks_even_without_fix_or_with_ordinary_exception(self):
        self.policy['exceptions'] = [self.ordinary_exception()]
        self.located()
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['blocked'][0]['reason'], 'untriaged-critical')
        self.assertEqual(result['exceptionsApplied'], [])

    def test_related_critical_cannot_be_hidden_behind_high_primary(self):
        match = self.located('High')
        match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604', 'severity': 'Critical'}]
        self.assertEqual(self.evaluate()['blocked'][0]['reason'], 'untriaged-critical')

    def test_malformed_scanner_metadata_is_probe_error_not_routine_advisory(self):
        for change in ('match', 'artifact', 'vulnerability', 'fix', 'severity', 'related'):
            with self.subTest(change=change):
                self.setUp()
                match = self.located('High')
                if change == 'match': self.scan['matches'] = [None]
                if change == 'artifact': match['artifact'] = None
                if change == 'vulnerability': match['vulnerability'] = None
                if change == 'fix': match['vulnerability']['fix'] = None
                if change == 'severity': match['vulnerability']['severity'] = 'critical'
                if change == 'related': match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604', 'severity': 'critical'}]
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_related_identifiers_and_typed_severity_cannot_silently_become_advisory(self):
        malformed = [{}, {'id': None}, {'id': []}, {'id': ''}, {'id': 'CVE-2026-ALIAS'},
                     {'id': 'GO-2026-6604 '}, {'id': 'other/advisory'},
                     {'id': 'GO-2026-6604', 'severity': 'critical'},
                     {'id': 'GO-2026-6604', 'severity': {}},
                     {'id': 'GO-2026-6604', 'severity': []},
                     {'id': 'GO-2026-6604', 'severity': None}]
        for related in malformed:
            with self.subTest(related=related):
                match = self.located('High')
                match['relatedVulnerabilities'] = [related]
                with self.assertRaises(ValueError):
                    self.evaluate()
        for related in ({}, '', [None]):
            self.scan['matches'][0]['relatedVulnerabilities'] = related
            with self.assertRaises(ValueError):
                self.evaluate()

    def test_known_related_identifier_families_allow_missing_severity(self):
        for advisory in ('CVE-2026-1234', 'GHSA-2345-cfgh-jmpq', 'GO-2026-6604',
                         'FEDORA-2026-012345abcd', 'FEDORA-EPEL-2026-012345abcd',
                         'PYSEC-2026-1', 'RUSTSEC-2026-0001', 'OSV-2026-1'):
            with self.subTest(advisory=advisory):
                match = self.located('High')
                match['relatedVulnerabilities'] = [{'id': advisory}]
                self.assertEqual(self.evaluate()['status'], 'pass')

    def test_grype_unspecified_fix_state_is_unknown_without_changing_raw_evidence(self):
        match = self.located('High')
        match['vulnerability']['fix'] = {'versions': [], 'state': ''}
        raw_before = json.dumps(self.scan, sort_keys=True)
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['advisories'][0]['fixState'], 'unknown')
        self.assertEqual(result['advisories'][0]['fixVersions'], [])
        self.assertEqual(json.dumps(self.scan, sort_keys=True), raw_before)

    def test_unspecified_fix_data_does_not_clear_serious_critical_or_kev(self):
        for gate in ('serious', 'critical', 'kev', 'related-kev', 'ignored-serious'):
            with self.subTest(gate=gate):
                self.setUp()
                match = self.located('Critical' if gate == 'critical' else 'High')
                match['vulnerability']['fix'] = {'versions': [], 'state': ''}
                if gate in ('serious', 'ignored-serious'):
                    self.serious()
                if gate == 'kev': match['vulnerability']['knownExploited'] = [{}]
                if gate == 'related-kev':
                    match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604', 'knownExploited': [{}]}]
                if gate == 'ignored-serious':
                    self.scan['matches'] = []
                    self.scan['ignoredMatches'] = [match]
                result = self.evaluate()
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['blocked'][0]['fixState'], 'unknown')
                self.assertEqual(result['blocked'][0]['fixVersions'], [])

    def test_only_exact_unspecified_fix_shape_is_accepted(self):
        malformed = [{'versions': []}, {'state': None, 'versions': []}, {'state': {}, 'versions': []},
                     {'state': '', 'versions': ['2']}, {'state': '', 'versions': None},
                     {'state': '', 'versions': {}}, {'state': '', 'versions': [None]},
                     {'state': '', 'versions': ['']}, {'state': '', 'versions': [' 2 ']},
                     {'state': ' ', 'versions': []}, {'state': 'malformed', 'versions': []}]
        for fix in malformed:
            with self.subTest(fix=fix):
                self.located('High')['vulnerability']['fix'] = fix
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_exact_reviewed_critical_disposition_is_visible_advisory(self):
        self.located()
        self.disposition()
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['advisories'][0]['reason'], 'reviewed-routine')
        self.assertEqual(result['advisories'][0]['reviewedDisposition'], 'fixture-proof')
        self.assertEqual(result['observations'], result['advisories'])

    def test_scoped_review_does_not_follow_package_version_digest_or_uncovered_path(self):
        for change in ('version', 'digest', 'missing', 'new-location', 'accessPath', 'realPath', 'alias', 'traversal'):
            with self.subTest(change=change):
                self.setUp()
                match = self.located()
                rule = self.disposition()
                if change == 'version': match['artifact']['purl'] = 'pkg:rpm/fedora/example@2'
                if change == 'digest': rule['digest'] = 'sha256:' + 'e' * 64
                if change == 'missing': match['artifact']['locations'] = []
                if change == 'new-location': match['artifact']['locations'].append({'path': '/ostree/repo/example'})
                if change in ('accessPath', 'realPath'): match['artifact']['locations'][0][change] = '/usr/bin/other'
                if change == 'alias': match['relatedVulnerabilities'] = [{'id': 'GO-2026-9999'}]
                if change == 'traversal': match['artifact']['locations'] = [{'path': '/usr/bin/../example'}]
                self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_serious_nonapplicability_requires_proof_and_cannot_be_routine(self):
        self.serious()
        self.located('High')
        self.disposition('nonapplicable')
        self.assertEqual(self.evaluate()['advisories'][0]['reason'], 'reviewed-nonapplicable')
        self.policy['reviewedDispositions'][0]['disposition'] = 'backported'
        self.assertEqual(self.evaluate()['advisories'][0]['reason'], 'reviewed-backported')
        self.policy['reviewedDispositions'][0]['disposition'] = 'routine'
        with self.assertRaisesRegex(ValueError, 'routine waiver'):
            self.evaluate()

    def test_expired_review_returns_to_untriaged_critical(self):
        self.located()
        rule = self.disposition()
        rule['expiresAt'] = '2026-10-12T11:00:00Z'
        self.assertEqual(self.evaluate()['blocked'][0]['reason'], 'untriaged-critical')
        rule['expiresAt'] = '2026-12-20T00:00:00Z'
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_malformed_unused_review_rules_fail_closed(self):
        changes = [('id', ''), ('advisories', ['CVE-*']), ('advisories', ['CVE-2026-1234'] * 2),
                   ('advisories', []), ('riskClass', 'ordinary'), ('riskClass', []),
                   ('officialSources', ['http://example.com']), ('officialSources', ['https://user:secret@example.com']),
                   ('reviewedBy', ''), ('reviewedAt', '2026-10-13T00:00:00Z'), ('unknown', True)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.setUp()
                self.serious()[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_overlapping_and_duplicate_rules_fail_closed(self):
        rule = self.serious()
        for duplicate in (dict(rule), {**rule, 'id': 'another-serious'}):
            self.policy['seriousAdvisories'] = [rule, duplicate]
            with self.assertRaises(ValueError):
                self.evaluate()
        self.policy['seriousAdvisories'] = []
        proof = self.disposition()
        self.policy['reviewedDispositions'].append({**proof, 'id': 'conflicting-proof', 'disposition': 'backported'})
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_risk_policy_rejects_disabled_kev_unknown_mode_or_misspelled_fields(self):
        for key, value in [('blockKnownExploited', False), ('mode', 'critical-only'),
                           ('maxExceptionDays', 31), ('seriousAdvisories', None), ('typo', True)]:
            with self.subTest(key=key):
                self.setUp()
                self.policy[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_review_scope_rejects_wrong_platform_mutable_component_and_traversal(self):
        for key, value in [('platform', 'windows/amd64'), ('component', 'pkg:rpm/fedora/example'),
                           ('component', 'pkg:rpm/fedora/example@*'), ('locations', []),
                           ('locations', ['/usr/../bin/example']), ('locations', ['relative']),
                           ('locations', ['/usr/bin/example', '/usr/bin/example']), ('evidence', [])]:
            with self.subTest(key=key):
                self.setUp()
                self.disposition()[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_purl_qualifiers_are_exact_components_not_wildcards(self):
        match = self.located()
        proof = self.disposition()
        match['artifact']['purl'] = proof['component'] = 'pkg:rpm/fedora/example@1?arch=x86_64&distro=fedora-44'
        self.assertEqual(self.evaluate()['status'], 'pass')

    def test_native_paths_normalize_without_host_symlink_resolution(self):
        source = '/tmp/scan/rootfs'
        sbom = {'source': {'type': 'directory', 'metadata': {'path': source}}}
        artifact = {'locations': [{'path': source + '/usr/bin/example', 'accessPath': '/usr/bin/example',
                                   'realPath': source + '/usr/libexec/example'}]}
        with patch.object(Path, 'resolve', side_effect=AssertionError('Must not resolve host paths')):
            self.assertEqual(security.component_locations(artifact, sbom),
                             (['/usr/bin/example', '/usr/libexec/example'], True))
        for locations in ([], [{}], [{'path': None}], [{'path': '../example'}]):
            artifact['locations'] = locations
            self.assertFalse(security.component_locations(artifact, sbom)[1])

    def test_baseline_receipt_default_path_and_size_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertIsNone(security.read_baseline(directory))
            path = directory / 'approved-baseline.json'
            path.write_text(json.dumps(self.baseline))
            self.assertEqual(security.read_baseline(directory), self.baseline)
            path.write_bytes(b' ' * (security.MANIFEST_LIMIT + 1))
            with self.assertRaises(ValueError):
                security.read_baseline(directory)

    def test_risk_mode_requires_configuration_not_just_a_verified_context_string(self):
        for manifests in (None, {'parent': self.manifests['parent'], 'child': None},
                          {**self.manifests, 'config': '{}'}):
            with self.subTest(manifests=manifests):
                with self.assertRaises(ValueError):
                    security.evaluate(self.sbom, self.scan, self.image, self.policy, NOW,
                                      database_coverage=DATABASE_COVERAGE, manifests=manifests,
                                      approved_baseline=self.baseline)

    def test_immutable_config_digest_size_type_and_platform_are_verified(self):
        for key, value in [('digest', 'sha256:' + 'f' * 64), ('size', 1),
                           ('size', True), ('mediaType', 'text/plain')]:
            with self.subTest(key=key, value=value):
                self.setUp()
                self.manifest['config'][key] = value
                self.bind_manifest()
                with self.assertRaisesRegex(ValueError, 'configuration does not match'):
                    self.evaluate()
        for key, value in [('os', 'windows'), ('architecture', 'arm64'), ('variant', 'v2')]:
            with self.subTest(key=key, value=value):
                self.setUp()
                self.config[key] = value
                self.bind_config()
                with self.assertRaisesRegex(ValueError, 'linux/amd64'):
                    self.evaluate()

    def test_context_fields_must_match_immutable_config_labels(self):
        for key in ('org.opencontainers.image.source', 'org.opencontainers.image.revision',
                    'io.finite.profile', 'io.finite.build-inputs',
                    'org.opencontainers.image.base.name', 'org.opencontainers.image.base.digest'):
            with self.subTest(key=key):
                self.setUp()
                self.config['config']['Labels'][key] = 'wrong'
                self.bind_config()
                with self.assertRaisesRegex(ValueError, 'configuration labels'):
                    self.evaluate()

    def test_read_manifests_retains_exact_config_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'image-manifest.json').write_text(self.manifests['parent'])
            (directory / 'image-config.json').write_text(self.manifests['config'])
            self.assertEqual(security.read_manifests(directory), self.manifests)

    def test_selected_platform_config_is_bound_through_index(self):
        child = self.manifests['parent']
        self.manifests['child'] = child
        self.manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                         'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                        'digest': self.digest, 'size': len(child.encode()),
                                        'platform': {'os': 'linux', 'architecture': 'amd64'}}]}
        self.bind_manifest()
        self.sbom['source']['metadata']['manifestDigest'] = self.manifest['manifests'][0]['digest']
        self.scan['source']['target']['manifestDigest'] = self.manifest['manifests'][0]['digest']
        self.assertEqual(self.evaluate()['status'], 'pass')
        self.manifests['child'] += ' '
        with self.assertRaises(ValueError):
            self.evaluate()

    def write_metadata(self, directory):
        (directory / 'image-manifest.json').write_text(self.manifests['parent'])
        (directory / 'image-config.json').write_text(self.manifests['config'])
        (directory / 'approved-baseline.json').write_text(json.dumps(self.baseline))

    def publisher_receipt(self):
        policy_path = ROOT / 'sources/bluefin-trust.json'
        policy = json.loads(policy_path.read_text())
        self.baseline['trustPolicySha256'] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
        return {'schema': 1, 'repository': 'closure-labs/finite',
                'sourceRevision': self.baseline['sourceRevision'],
                'trustPolicySha256': self.baseline['trustPolicySha256'],
                'verified': [{'image': self.baseline['baseImage'], 'keySha256': policy['keySha256'],
                              'signatureFormat': 'legacy'}]}

    def test_production_verify_rejects_naked_context_before_catalog_or_evaluate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.write_metadata(directory)
            policy_path = directory / 'policy.json'
            policy_path.write_text(json.dumps(self.policy))
            with patch.object(security, 'evaluate') as evaluate:
                with self.assertRaisesRegex(ValueError, 'bounded regular file'):
                    security.verify(directory, self.image, policy_path)
                evaluate.assert_not_called()
            self.assertFalse((directory / 'sbom.syft.json').exists())

    def test_production_main_rejects_naked_context_as_probe_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.write_metadata(directory)
            policy_path = directory / 'policy.json'
            policy_path.write_text(json.dumps(self.policy))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/security-policy.py'),
                                     str(directory), self.image, '--policy', str(policy_path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            record = json.loads((directory / 'security-result.json').read_text())
            self.assertEqual(record['status'], 'scanner-error')
            self.assertIn('bounded regular file', record['error'])
            self.assertNotIn('sbom.syft.json', record['error'])

    def test_production_receipt_rechecks_current_trust_and_exact_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = self.publisher_receipt()
            path = directory / 'upstream-verification.json'
            path.write_text(json.dumps(receipt))
            self.assertEqual(security.production_baseline(directory, self.image, self.policy,
                                                          self.manifests, self.baseline), self.baseline)
            self.baseline['trustPolicySha256'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'differs'):
                security.production_baseline(directory, self.image, self.policy, self.manifests, self.baseline)
            self.publisher_receipt()
            for key, value in [('schema', True), ('repository', 'attacker/repo'), ('verified', []),
                               ('trustPolicySha256', 'f' * 64)]:
                with self.subTest(key=key):
                    path.write_text(json.dumps({**receipt, key: value}))
                    with self.assertRaises(ValueError):
                        security.production_baseline(directory, self.image, self.policy,
                                                     self.manifests, self.baseline)

    def kernel_hold(self):
        hold = {'id': 'fixture-source-security-gap', 'profiles': ['bluefin-dx-generic'],
                'riskClass': 'major-data-loss', 'reason': 'Fixture unresolved XFS corruption risk',
                'officialSources': ['https://bodhi.fedoraproject.org/updates/FEDORA-2026-012345abcd'],
                'reviewedBy': 'fixture-reviewer', 'reviewedAt': STAMP,
                'unblockEvidence': 'Reviewed signed stable kernel source and matching module/boot evidence'}
        self.policy['releaseBlockers'] = [hold]
        return hold

    def profile(self, value):
        self.baseline['profile'] = value
        foundation = 'bluefin-dx' if '-dx-' in value else 'bluefin'
        self.baseline['baseImage'] = 'ghcr.io/ublue-os/' + foundation + '@sha256:' + 'c' * 64
        labels = self.config['config']['Labels']
        labels['io.finite.profile'] = value
        labels['org.opencontainers.image.base.name'] = self.baseline['baseImage'].replace('@', ':stable@')
        self.bind_config()

    def test_profile_source_hold_blocks_without_inventing_vulnerability_findings(self):
        hold = self.kernel_hold()
        for profile in ('bluefin-generic', 'bluefin-dx-generic'):
            with self.subTest(profile=profile):
                self.profile(profile)
                result = self.evaluate()
                held = profile in hold['profiles']
                self.assertEqual(result['status'], 'blocked' if held else 'pass')
                self.assertEqual(result['releaseBlockers'], [hold] if held else [])
                self.assertEqual(result['matches'], 0)
                self.assertEqual(result['blocked'], [])
                self.assertEqual(result['advisories'], [])
                self.assertEqual(result['observations'], [])

    def test_ordinary_and_reviewed_exceptions_cannot_waive_profile_source_hold(self):
        self.kernel_hold()
        self.profile('bluefin-dx-generic')
        self.located()
        self.policy['exceptions'] = [self.ordinary_exception()]
        self.disposition('nonapplicable')
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(len(result['releaseBlockers']), 1)
        self.assertEqual(result['blocked'], [])
        self.assertEqual(result['advisories'][0]['reason'], 'reviewed-nonapplicable')

    def test_malformed_unused_source_holds_fail_closed(self):
        for key, value in [('profiles', ['unknown']), ('profiles', []), ('profiles', ['bluefin-dx-generic'] * 2),
                           ('riskClass', 'ordinary'), ('unblockEvidence', ''), ('reviewedBy', ''),
                           ('reviewedAt', '2026-10-13T00:00:00Z'), ('officialSources', ['http://example.com']),
                           ('unknown', True)]:
            with self.subTest(key=key):
                self.setUp()
                self.kernel_hold()[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()
        self.setUp()
        hold = self.kernel_hold()
        self.policy['releaseBlockers'].append(dict(hold))
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_source_hold_does_not_expire_until_reviewed_policy_change(self):
        self.kernel_hold()['reviewedAt'] = '2025-01-01T00:00:00Z'
        self.profile('bluefin-dx-generic')
        self.assertEqual(self.evaluate()['status'], 'blocked')
        self.policy['releaseBlockers'] = []
        self.assertEqual(self.evaluate()['status'], 'pass')


class DesktopCriticalPolicy(unittest.TestCase):
    # Reuse evidence builders, not the old mode's deliberately different verdicts.
    bind_config = UpstreamRiskPolicy.bind_config
    bind_manifest = UpstreamRiskPolicy.bind_manifest
    evaluate = UpstreamRiskPolicy.evaluate
    located = UpstreamRiskPolicy.located
    disposition = UpstreamRiskPolicy.disposition
    serious = UpstreamRiskPolicy.serious
    profile = UpstreamRiskPolicy.profile
    ordinary_exception = UpstreamRiskPolicy.ordinary_exception
    write_metadata = UpstreamRiskPolicy.write_metadata

    def setUp(self):
        UpstreamRiskPolicy.setUp(self)
        self.policy.update(mode='desktop-critical-only', blockKnownExploited=False,
                           blockedFixableSeverities=['Critical'])

    def test_noncritical_serious_and_exploited_findings_remain_visible(self):
        self.serious()
        for severity in ('Unknown', 'Negligible', 'Low', 'Medium', 'High'):
            for ignored in (False, True):
                with self.subTest(severity=severity, ignored=ignored):
                    match = self.located(severity)
                    match['vulnerability']['knownExploited'] = [{}]
                    self.scan['matches'] = [] if ignored else [match]
                    self.scan['ignoredMatches'] = [match] if ignored else []
                    result = self.evaluate()
                    self.assertEqual(result['status'], 'pass')
                    self.assertEqual(result['observations'], result['advisories'])
                    self.assertTrue(result['advisories'][0]['knownExploited'])
                    self.assertEqual(result['advisories'][0]['reviewRules'], ['fixture-serious'])
                    self.assertEqual(result['advisories'][0]['reason'], 'below-critical-release-threshold')

    def test_critical_aliases_block_even_without_cve_primary_or_fix(self):
        for primary in ('CVE-2026-1234', 'GHSA-aaaa-bbbb-cccc', 'GO-2026-6604'):
            for related in (False, True):
                for ignored in (False, True):
                    with self.subTest(primary=primary, related=related, ignored=ignored):
                        match = self.located('High' if related else 'Critical')
                        match['vulnerability']['id'] = primary
                        if related:
                            match['relatedVulnerabilities'] = [{'id': 'CVE-2026-1234', 'severity': 'Critical'}]
                        self.scan['matches'] = [] if ignored else [match]
                        self.scan['ignoredMatches'] = [match] if ignored else []
                        result = self.evaluate()
                        self.assertEqual(result['status'], 'blocked')
                        self.assertEqual(result['blocked'][0]['reason'], 'critical-applicability-pending-review')
                        self.assertEqual(result['blocked'][0]['criticalSeverityAdvisories'],
                                         ['CVE-2026-1234' if related else primary])

    def test_critical_cannot_be_cleared_by_routine_or_ordinary_exception(self):
        self.located()
        self.policy['exceptions'] = [self.ordinary_exception()]
        self.disposition('routine')
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['exceptionsApplied'], [])
        self.assertNotIn('reviewedDisposition', result['blocked'][0])

    def test_exact_nonapplicable_or_backport_proof_clears_even_critical_kev(self):
        match = self.located()
        match['vulnerability']['knownExploited'] = [{}]
        for disposition in ('nonapplicable', 'backported'):
            with self.subTest(disposition=disposition):
                self.disposition(disposition)
                result = self.evaluate()
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(result['advisories'][0]['reason'], 'reviewed-' + disposition)
                self.assertTrue(result['advisories'][0]['knownExploited'])

    def test_critical_proof_cannot_follow_different_digest_path_alias_or_version(self):
        for mutation in ('digest', 'version', 'path', 'alias', 'expired', 'missing-locations'):
            with self.subTest(mutation=mutation):
                self.setUp()
                match = self.located()
                proof = self.disposition('nonapplicable')
                if mutation == 'digest': proof['digest'] = DIGEST
                if mutation == 'version': match['artifact']['purl'] += '2'
                if mutation == 'path': match['artifact']['locations'].append({'path': '/usr/bin/other'})
                if mutation == 'alias': match['relatedVulnerabilities'] = [{'id': 'CVE-2026-9876'}]
                if mutation == 'expired': proof['expiresAt'] = '2026-10-12T11:00:00Z'
                if mutation == 'missing-locations': match['artifact']['locations'] = []
                self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_missing_baseline_and_malformed_scanner_still_fail_closed(self):
        with self.assertRaises(ValueError):
            self.evaluate(False)
        for mutation in ('stale', 'invalid-db', 'missing-coverage', 'malformed-severity'):
            with self.subTest(mutation=mutation):
                self.setUp()
                match = self.located('High')
                if mutation == 'stale': self.scan['descriptor']['timestamp'] = '2026-01-01T00:00:00Z'
                if mutation == 'invalid-db': self.scan['descriptor']['db']['status']['valid'] = False
                if mutation == 'missing-coverage': self.sbom['artifacts'] = []
                if mutation == 'malformed-severity': match['vulnerability']['severity'] = 'critical'
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_source_holds_only_block_explicit_critical_advisories(self):
        self.profile('bluefin-dx-generic')
        hold = UpstreamRiskPolicy.kernel_hold(self)
        hold.update(severity='Unknown', advisories=[])
        for severity in ('Unknown', 'High', 'Critical'):
            with self.subTest(severity=severity):
                hold.update(severity=severity, advisories=['CVE-2026-1234'] if severity == 'Critical' else [])
                result = self.evaluate()
                self.assertEqual(result['status'], 'blocked' if severity == 'Critical' else 'pass')
                self.assertEqual(result['releaseBlockers'], [hold] if severity == 'Critical' else [])
                self.assertEqual(result['trackedReleaseConcerns'], [] if severity == 'Critical' else [hold])
                self.assertEqual(result['matches'], 0)

    def test_source_hold_classification_requires_explicit_valid_evidence(self):
        for change in ('missing', 'severity', 'empty-critical', 'wildcard'):
            with self.subTest(change=change):
                self.setUp()
                hold = UpstreamRiskPolicy.kernel_hold(self)
                hold.update(severity='Critical', advisories=['CVE-2026-1234'])
                if change == 'missing': del hold['severity']
                if change == 'severity': hold['severity'] = 'critical'
                if change == 'empty-critical': hold['advisories'] = []
                if change == 'wildcard': hold['advisories'] = ['CVE-*']
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_production_still_requires_protected_publisher_receipt(self):
        UpstreamRiskPolicy.test_production_verify_rejects_naked_context_before_catalog_or_evaluate(self)

    def test_mode_rejects_misleading_threshold_or_kev_configuration(self):
        for key, value in [('blockKnownExploited', True), ('blockedFixableSeverities', ['High', 'Critical'])]:
            with self.subTest(key=key):
                self.setUp()
                self.policy[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()


class ReviewedDesktopExploitability(unittest.TestCase):
    bind_config = UpstreamRiskPolicy.bind_config
    bind_manifest = UpstreamRiskPolicy.bind_manifest
    evaluate = UpstreamRiskPolicy.evaluate
    located = UpstreamRiskPolicy.located
    disposition = UpstreamRiskPolicy.disposition
    serious = UpstreamRiskPolicy.serious
    profile = UpstreamRiskPolicy.profile

    def setUp(self):
        DesktopCriticalPolicy.setUp(self)
        self.policy.update(blockingBasis='reviewed-desktop-exploitability', confirmedDesktopRisks=[])

    def confirmed(self):
        receipt = {
            'id': 'confirmed-fixture', 'digest': self.digest, 'profile': self.baseline['profile'],
            'platform': 'linux/amd64', 'component': 'pkg:rpm/fedora/example@1', 'severity': 'Critical',
            'advisories': ['CVE-2026-1234'], 'locations': ['/usr/bin/example'],
            'officialSources': ['https://example.org/security/CVE-2026-1234'],
            'severityEvidence': ['Official advisory rates unauthenticated remote takeover Critical'],
            'affectedCodeEvidence': ['sha256:' + 'a' * 64 + ':exact-file-function-review'],
            'impact': 'Unauthenticated hostile input executes code with desktop user authority',
            'attackerPath': 'Supported desktop application opens attacker-controlled file',
            'preconditions': ['Default supported file handler installed and reachable'],
            'selinuxAssessment': 'Verified application domain permits the affected user-file access',
            'selinuxEvidence': ['sha256:' + 'b' * 64 + ':guest-domain-and-policy-review'],
            'reason': 'Exact image evidence establishes the supported exploit path',
            'reviewedBy': 'fixture-reviewer', 'reviewedAt': STAMP}
        self.policy['confirmedDesktopRisks'] = [receipt]
        return receipt

    def test_critical_advisory_pairs_are_unresolved_not_automatic_blockers(self):
        self.serious()
        for primary in ('High', 'Critical'):
            with self.subTest(primary=primary):
                match = self.located(primary)
                match['relatedVulnerabilities'] = [{'id': 'GO-2026-6604', 'severity': 'Critical'}]
                match['vulnerability']['knownExploited'] = [{}]
                self.scan['matches'], self.scan['ignoredMatches'] = [], [match]
                result = self.evaluate()
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(result['blocked'], [])
                self.assertEqual(result['advisories'][0]['reason'], 'critical-applicability-unresolved')
                self.assertTrue(result['advisories'][0]['knownExploited'])
                self.assertEqual(result['observations'], result['advisories'])
                self.assertEqual(result['blockingBasis'], 'reviewed-desktop-exploitability')

    def test_old_critical_source_concern_alone_is_only_tracked(self):
        self.profile('bluefin-dx-generic')
        concern = UpstreamRiskPolicy.kernel_hold(self)
        concern.update(severity='Critical', advisories=['CVE-2026-1234'])
        result = self.evaluate()
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['releaseBlockers'], [])
        self.assertEqual(result['trackedReleaseConcerns'], [concern])

    def test_confirmed_exact_source_risk_blocks_even_without_scanner_match(self):
        receipt = self.confirmed()
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['releaseBlockers'], [receipt])
        self.assertEqual(result['matches'], 0)
        self.assertEqual(result['observations'], [])

    def test_confirmed_risk_cannot_follow_different_image_or_profile(self):
        for key, value in [('digest', DIGEST), ('profile', 'bluefin-dx-generic')]:
            with self.subTest(key=key):
                self.confirmed()[key] = value
                self.assertEqual(self.evaluate()['status'], 'pass')
                self.assertEqual(self.evaluate()['releaseBlockers'], [])

    def test_nonapplicable_review_does_not_silently_remove_confirmed_source_hold(self):
        self.confirmed()
        self.located()
        self.disposition('nonapplicable')
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['blocked'][0]['reason'], 'confirmed-desktop-exploitability')
        self.assertEqual(result['blocked'][0]['confirmedRiskReviews'], ['confirmed-fixture'])
        self.assertEqual(len(result['releaseBlockers']), 1)

    def test_confirmed_holds_require_full_exact_evidence(self):
        mutations = [('severity', 'High'), ('digest', 'latest'), ('profile', 'all'),
                     ('platform', 'windows/amd64'), ('component', 'pkg:rpm/fedora/example'),
                     ('component', '*'), ('advisories', []), ('advisories', ['CVE-*']),
                     ('locations', ['/usr/../bin/example']), ('locations', []),
                     ('officialSources', ['http://example.org']), ('affectedCodeEvidence', []),
                     ('severityEvidence', []), ('attackerPath', ''), ('preconditions', []),
                     ('selinuxAssessment', ''), ('selinuxEvidence', []), ('impact', ''),
                     ('reviewedBy', ''), ('reviewedAt', '2026-10-13T00:00:00Z'),
                     ('affectedCodeEvidence', ['x' * 8193]), ('unknown', True)]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                self.confirmed()[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()
        self.confirmed().pop('selinuxEvidence')
        with self.assertRaises(ValueError):
            self.evaluate()
        record = self.confirmed()
        self.policy['confirmedDesktopRisks'].append(dict(record))
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_basis_requires_explicit_valid_mode_and_list(self):
        for key, value in [('mode', 'upstream-maintained-risk'), ('blockingBasis', 'scanner-count'),
                           ('confirmedDesktopRisks', None)]:
            with self.subTest(key=key):
                self.setUp()
                self.policy[key] = value
                with self.assertRaises(ValueError):
                    self.evaluate()
        self.setUp()
        del self.policy['confirmedDesktopRisks']
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_old_critical_mode_output_and_verdict_preserved_without_opt_in(self):
        self.policy.pop('blockingBasis')
        self.policy.pop('confirmedDesktopRisks')
        self.located()
        result = self.evaluate()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['blocked'][0]['reason'], 'critical-applicability-pending-review')
        self.assertNotIn('blockingBasis', result)

    def test_confirmed_blocked_observation_references_are_independently_checked(self):
        self.confirmed()
        self.located('High')
        result = self.evaluate()
        self.assertEqual(result['blocked'][0]['severity'], 'High')
        security.validate_confirmed_findings(result['blocked'], result['releaseBlockers'])
        original = result['blocked'][0]
        for key, value in [('confirmedRiskReviews', ['wrong-review']), ('component', 'other-component'),
                           ('locations', ['/usr/bin/other']), ('aliases', ['CVE-2026-9999']),
                           ('reason', 'critical-applicability-unresolved'), ('locationCoverage', 'unknown')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    security.validate_confirmed_findings([{**original, key: value}], result['releaseBlockers'])

    def test_probes_remain_errors_when_scanner_match_does_not_block(self):
        self.located()
        self.scan['descriptor']['db']['status']['valid'] = False
        with self.assertRaises(ValueError):
            self.evaluate()


if __name__ == '__main__':
    unittest.main()
