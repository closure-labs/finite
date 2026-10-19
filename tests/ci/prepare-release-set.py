#!/usr/bin/env python3
"""Release preparation validates both profiles and excludes refreshed evidence."""
import copy
import hashlib
import importlib.util
import json
import os
import types
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('prepare_release_set', ROOT / 'scripts/ci/prepare-release-set.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.revision = 'a' * 40
        for channel in module.CHANNELS:
            directory = self.output / ('release-' + channel)
            directory.mkdir()
            iso = channel + '.iso'
            (directory / iso).write_bytes(channel.encode())
            digest = hashlib.sha256(channel.encode()).hexdigest()
            image = 'ghcr.io/closure-labs/finite@sha256:' + digest
            provenance = {'revision': self.revision, 'isoMatchesQualification': True,
                          'qualification': {'qualifiedIso': {'name': iso, 'sha256': digest}},
                          'image': image, 'buildRun': 'https://github.com/closure-labs/finite/actions/runs/1',
                          'isoRun': 'https://github.com/closure-labs/finite/actions/runs/1'}
            (directory / 'provenance.json').write_text(json.dumps(provenance))
            (directory / 'SHA256SUMS').write_text('derived and refreshed')
            (directory / 'SHA256SUMS.bundle.json').write_text('{}')
            security = self.output / ('security-' + channel)
            security.mkdir()
            scan = {'status': 'pass', 'image': image, 'observations': []}
            (security / 'security-result.json').write_text(json.dumps(scan))

    def test_both_channels_immutable_assets_and_review_envelope(self):
        document = module.assemble(self.output, '1.2.3', self.revision)
        self.assertEqual(set(document['payload']['channels']), set(module.CHANNELS))
        self.assertEqual(document['payload']['channels']['finite']['assets'].keys(), {'finite.iso'})
        proposal = json.loads((self.output / 'release-set-proposal.json').read_text())
        self.assertEqual(proposal, {'schema': 1, 'kind': 'release-set', 'payload': document['payload']})
        self.assertIn('Both images', (self.output / 'summary.md').read_text())

    def test_refreshed_scan_and_derived_files_do_not_change_identity(self):
        original = module.assemble(self.output, '1.2.3', self.revision)
        (self.output / 'release-finite' / 'SHA256SUMS').write_text('new derived checksums')
        scan_path = self.output / 'security-finite' / 'security-result.json'
        scan = json.loads(scan_path.read_text())
        scan['scannedAt'] = 'fresh'
        scan_path.write_text(json.dumps(scan))
        updated = module.assemble(self.output, '1.2.3', self.revision)
        self.assertEqual(module.payload_digest(original), module.payload_digest(updated))
        self.assertNotEqual(original['evidence'], updated['evidence'])

    def test_old_qualified_source_or_regenerated_iso_is_rejected(self):
        path = self.output / 'release-finite' / 'provenance.json'
        original = json.loads(path.read_text())
        for field, value in [('revision', 'b' * 40), ('isoMatchesQualification', False)]:
            changed = copy.deepcopy(original)
            changed[field] = value
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                module.assemble(self.output, '1.2.3', self.revision)

    def test_low_severity_review_findings_are_retained_with_cve_links(self):
        path = self.output / 'security-finite' / 'security-result.json'
        scan = json.loads(path.read_text())
        scan['status'] = 'blocked'
        scan['observations'] = [{'component': 'pkg:rpm/fedora/demo@1',
                                 'advisory': 'CVE-2026-12345', 'aliases': [],
                                 'locations': ['/usr/bin/demo'], 'locationCoverage': 'complete',
                                 'severity': 'Low', 'knownExploited': False, 'fixVersions': []}]
        path.write_text(json.dumps(scan))
        module.assemble(self.output, '1.2.3', self.revision)
        summary = (self.output / 'summary.md').read_text()
        self.assertIn('Low:', summary)
        self.assertIn('https://www.cve.org/CVERecord?id=CVE-2026-12345', summary)
        self.assertEqual(len(json.loads((self.output / 'findings.json').read_text())), 1)

    def test_large_iso_parts_are_frozen_before_approval(self):
        iso = self.output / 'release-finite' / 'finite.iso'
        iso.write_bytes(b'0123456789')
        assets = module.product_assets(iso, split_threshold=8, part_size=4)
        self.assertEqual(list(assets), ['finite.iso.part-000', 'finite.iso.part-001', 'finite.iso.part-002'])
        self.assertEqual(b''.join((iso.parent / name).read_bytes() for name in assets), iso.read_bytes())
        self.assertEqual(assets['finite.iso.part-002'], hashlib.sha256(b'89').hexdigest())
        with self.assertRaises(FileExistsError):
            module.product_assets(iso, split_threshold=8, part_size=4)

    def test_main_consumes_native_healthy_complete_and_legacy_blocked_but_rejects_technical_failure(self):
        document = module.assemble(self.output, '1.2.3', self.revision)
        real_validate = module.helper_module().validate_run
        run = {'conclusion': 'success', 'status': 'completed', 'head_branch': 'main',
               'head_sha': self.revision, 'path': '.github/workflows/build.yml',
               'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'schedule'}
        helper = types.SimpleNamespace(github=lambda _: run, validate_run=real_validate)
        (self.output / 'VERSION').write_text('1.2.3')
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.output)
        cases = [(0, 'complete', 'healthy', True), (2, 'blocked', None, False),
                 (0, 'complete', None, False), (1, 'blocked', None, True),
                 (0, 'covered', None, False)]
        for index, (code, status, health, allowed) in enumerate(cases):
            with self.subTest(code=code, status=status, health=health):
                packet = self.output / ('packet-' + str(index))
                def subprocess_run(argv, **kwargs):
                    if argv[0] == 'python3':
                        channel = argv[2]
                        workspace = self.output / '.bluebuild/release'
                        workspace.mkdir(parents=True)
                        image = 'ghcr.io/closure-labs/finite@sha256:' + ('a' if channel == 'finite' else 'b') * 64
                        (workspace / 'provenance.json').write_text(json.dumps({'isoMatchesQualification': True, 'image': image}))
                        return types.SimpleNamespace(returncode=0)
                    scan_directory = Path(argv[3])
                    scan_directory.mkdir()
                    scan = {'status': status, 'image': argv[2], 'observations': []}
                    if health is not None:
                        scan['scannerHealth'] = health
                    (scan_directory / 'security-result.json').write_text(json.dumps(scan))
                    return types.SimpleNamespace(returncode=code)
                with patch.object(module, 'ROOT', self.output), patch.object(module, 'helper_module', return_value=helper), \
                        patch.object(module, 'assemble', return_value=document) as assemble, \
                        patch.object(module.subprocess, 'run', side_effect=subprocess_run), \
                        patch.object(sys, 'argv', ['prepare-release-set.py', '--build-run', '5', '--output-directory', str(packet)]), \
                        patch.dict(os.environ, GITHUB_REPOSITORY='closure-labs/finite', GITHUB_REF='refs/heads/main',
                                   GITHUB_SHA=self.revision, GITHUB_OUTPUT=''):
                    if allowed:
                        module.main()
                        assemble.assert_called_once()
                        self.assertTrue((packet / 'security-finite-dev/security-result.json').is_file())
                    else:
                        with self.assertRaises(ValueError):
                            module.main()
                        assemble.assert_not_called()

    def test_other_image_scan_and_technical_failure_rejected(self):
        path = self.output / 'security-finite' / 'security-result.json'
        scan = json.loads(path.read_text())
        scan['image'] = 'ghcr.io/closure-labs/finite@sha256:' + 'b' * 64
        path.write_text(json.dumps(scan))
        with self.assertRaises(ValueError):
            module.assemble(self.output, '1.2.3', self.revision)
        scan['image'] = json.loads((self.output / 'release-finite' / 'provenance.json').read_text())['image']
        scan['status'] = 'scanner-error'
        path.write_text(json.dumps(scan))
        with self.assertRaises(ValueError):
            module.assemble(self.output, '1.2.3', self.revision)

    def test_authenticate_build_requires_same_main_revision_and_completed_trusted_event(self):
        run = {'conclusion': 'success', 'status': 'completed', 'head_branch': 'main',
               'head_sha': self.revision, 'path': '.github/workflows/build.yml',
               'head_repository': {'full_name': 'closure-labs/finite'}, 'event': 'schedule'}
        self.assertEqual(module.authenticate_build(run, self.revision), self.revision)
        for field, value in [('event', 'pull_request'), ('status', 'in_progress'), ('head_sha', 'b' * 40)]:
            changed = copy.deepcopy(run)
            changed[field] = value
            with self.assertRaises(ValueError):
                module.authenticate_build(changed, self.revision)


if __name__ == '__main__':
    unittest.main()
