#!/usr/bin/env python3
"""Negative tests for the independent vulnerability/signing publication boundary."""
from datetime import datetime, timezone
import importlib.util
import hashlib
import json
import os
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


class Policy(unittest.TestCase):
    def setUp(self):
        self.policy, self.sbom, self.scan = evidence()

    def evaluate(self):
        return security.evaluate(self.sbom, self.scan, IMAGE, self.policy, NOW, database_coverage=DATABASE_COVERAGE)

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
            manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json'})
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
""")
            (directory / 'skopeo').chmod(0o755)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/security-scan.py'),
                                     image, str(directory / 'evidence')],
                                    env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'],
                                         'MOCK_MANIFEST': manifest}, capture_output=True, text=True)
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
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/bluebuild/security-scan.py'),
                                     IMAGE, str(directory / 'scan')],
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
        self.child = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                 'config': {}, 'layers': []})
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
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            blobs = directory / 'image/blobs/sha256'
            blobs.mkdir(parents=True)
            output = directory / 'evidence'
            output.mkdir()
            (blobs / image.split(':')[-1]).write_text(manifests['parent'])
            (blobs / self.digest.split(':')[-1]).write_text(self.child)
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
        self.assertEqual(publication['sign']['needs'], 'security')
        self.assertEqual(publication['sign']['environment'], 'image-signing')
        self.assertIn('sign', publication['qualification']['needs'])
        signer = publication['sign']
        self.assertIn("github.ref == 'refs/heads/main'", signer['if'])
        self.assertFalse(any(step.get('uses') == './.github/actions/setup-nix' for step in signer['steps']))
        self.assertEqual(signer['steps'][0]['with']['sparse-checkout'], 'cosign.pub')
        sign = next(step for step in signer['steps'] if 'COSIGN_PRIVATE_KEY' in step.get('env', {}))
        self.assertEqual(sign['env']['CANDIDATE_DIGEST'], '${{ needs.security.outputs.digest }}')
        self.assertEqual(sign['env']['COSIGN_PRIVATE_KEY'], '${{ secrets.COSIGN_PRIVATE_KEY }}')
        self.assertIn('--new-bundle-format=false', sign['run'])
        self.assertNotIn('scripts/', sign['run'])
        self.assertNotIn('run download', sign['run'])
        for dependency in ('security', 'sign', 'qualification'):
            self.assertIn("needs." + dependency + ".result == 'success'", publication['promote']['if'])
        download = next(step for step in publication['promote']['steps'] if 'SECURITY_ARTIFACT' in step.get('env', {}))
        self.assertEqual(download['env']['SECURITY_ARTIFACT'], '${{ needs.security.outputs.evidence }}')

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
            with patch.dict(os.environ, GITHUB_SHA='revision', FINITE_QUALIFICATION_MODE='enforce'):
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
                    self.assertEqual(registry.call_count, 1)
                    self.assertEqual(registry.call_args.args[0][:2], ['cosign', 'verify'])


if __name__ == '__main__':
    unittest.main()
