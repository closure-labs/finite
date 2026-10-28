#!/usr/bin/env python3
"""Small offline transport fixtures: bounds, integrity, failures and matched cohorts."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('image_transfer', ROOT / 'scripts/ci/benchmark-image-transfer.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Transfer(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.image = M.METADATA.REPOSITORY + '@sha256:' + 'a' * 64

    def layout(self):
        layout = self.root / 'image'; blobs = layout / 'blobs/sha256'; blobs.mkdir(parents=True)
        def blob(raw, media):
            digest = M.METADATA.sha(raw)
            (blobs / digest[7:]).write_bytes(raw)
            return {'digest': digest, 'size': len(raw), 'mediaType': media}
        config = blob(b'{"fixture":"config"}', next(iter(M.METADATA.CONFIG_TYPES)))
        layer = blob(b'compressed-layer-fixture', next(iter(M.METADATA.LAYER_TYPES)))
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'config': config, 'layers': [layer]}
        raw = json.dumps(manifest).encode(); descriptor = blob(raw, manifest['mediaType'])
        digestfile = self.root / 'digest'; digestfile.write_text(descriptor['digest'])
        (layout / 'oci-layout').write_text(json.dumps({'imageLayoutVersion': '1.0.0'}))
        (layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [descriptor]}))
        return layout, digestfile, descriptor['digest'], raw, {'config': config, 'layers': [layer]}

    def test_independent_manifest_config_and_compressed_layer_hashes(self):
        args = self.layout()
        receipt = M.verify_layout(*args)
        self.assertTrue(receipt['manifestConfigLayersVerified'])
        self.assertEqual(receipt['uniqueBlobCount'], 3)
        self.assertFalse(receipt['uncompressedDiffIdsVerified'])
        for descriptor in [args[4]['config'], args[4]['layers'][0], {'digest': args[2]}]:
            path = args[0] / 'blobs/sha256' / descriptor['digest'][7:]
            original = path.read_bytes(); path.write_bytes(b'x' * len(original))
            with self.subTest(descriptor=descriptor), self.assertRaisesRegex(ValueError, 'digest verification'):
                M.verify_layout(*args)
            path.write_bytes(original)

    def test_missing_extra_linked_or_wrong_size_blobs_fail(self):
        args = self.layout(); blobs = args[0] / 'blobs/sha256'
        extra = blobs / ('f' * 64); extra.write_text('extra')
        with self.assertRaises(ValueError): M.verify_layout(*args)
        extra.unlink()
        layer = blobs / args[4]['layers'][0]['digest'][7:]
        original = layer.read_bytes(); layer.unlink()
        with self.assertRaises(ValueError): M.verify_layout(*args)
        external = self.root / 'external'; external.write_bytes(original); layer.symlink_to(external)
        with self.assertRaises(ValueError): M.verify_layout(*args)
        layer.unlink(); layer.write_bytes(original + b'x')
        with self.assertRaises(ValueError): M.verify_layout(*args)

    def test_copy_digest_and_layout_pointer_cannot_substitute_another_image(self):
        args = self.layout(); args[1].write_text('sha256:' + '0' * 64)
        with self.assertRaisesRegex(ValueError, 'immutable image'): M.verify_layout(*args)
        args[1].write_text(args[2])
        path = args[0] / 'index.json'; value = json.loads(path.read_text())
        value['manifests'][0]['digest'] = 'sha256:' + '0' * 64; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'requested manifest'): M.verify_layout(*args)

    def test_duplicate_metadata_and_links_rejected(self):
        path = self.root / 'metadata'; path.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'): M.read(path)
        link = self.root / 'link'; link.symlink_to(path)
        with self.assertRaises(ValueError): M.read(link)

    def test_only_one_or_two_copies_preserve_exact_production_flags(self):
        for copies in (1, 2):
            command = M.copy_command(self.image, self.root / 'image', self.root / 'digest', copies)
            for flag in ('--all', '--preserve-digests', '--src-no-creds'): self.assertIn(flag, command)
            self.assertEqual(command[command.index('--retry-times') + 1], '3')
            self.assertEqual(command[command.index('--image-parallel-copies') + 1], str(copies))
        for copies in (0, 3, 100):
            with self.assertRaises(ValueError): M.copy_command(self.image, self.root, self.root, copies)
        with self.assertRaises(ValueError): M.copy_command(self.image.split('@')[0] + ':latest', self.root, self.root, 1)

    def test_local_guard_and_secret_guard_precede_commands(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(M.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'GitHub-hosted'): M.benchmark(argparse.Namespace())
        launch.assert_not_called()
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/test',
            'GITHUB_WORKFLOW_REF': 'closure-labs/finite/.github/workflows/benchmark-image-transfer.yml@refs/heads/test',
            'GITHUB_SHA': 'a' * 40, 'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageVersion': 'fixture'}
        M.hosted(env)
        for change in ({'COSIGN_PRIVATE_KEY': 'secret'}, {'ImageVersion': ''}, {'GITHUB_EVENT_NAME': 'pull_request'}):
            with self.subTest(change=change), self.assertRaises(ValueError): M.hosted(dict(env, **change))

    def test_log_drain_caps_retained_bytes_without_layer_rlimit(self):
        target = self.root / 'log'
        self.assertEqual(M.drain(io.BytesIO(b'x' * (M.LOG_LIMIT + 100)), target), M.LOG_LIMIT + 100)
        self.assertEqual(target.stat().st_size, M.LOG_LIMIT)

    def test_insufficient_memory_fails_before_launch(self):
        with patch.object(Path, 'read_text', return_value='MemAvailable: 1000 kB\n'), patch.object(M.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'Insufficient available memory'):
                M.measured_copy([], self.root, self.root, {})
        launch.assert_not_called()

    def test_worker_rejects_unbounded_or_foreign_cgroup(self):
        args = argparse.Namespace(unit='finite-transfer-' + 'a' * 16)
        for group in ('0::/system.slice/foreign.service', '1:memory:/old'):
            with patch.object(Path, 'read_text', return_value=group), patch.object(M.subprocess, 'run') as run:
                with self.assertRaises(ValueError): M.worker(args)
            run.assert_not_called()

    def test_worker_records_success_and_nonzero_status_inside_valid_cgroup(self):
        args = argparse.Namespace(unit='finite-transfer-' + 'a' * 16, image=self.image,
            layout=self.root / 'image', digestfile=self.root / 'digest', copies=2, output=self.root)
        def read(path):
            return {'cgroup': '0::/system.slice/' + args.unit + '.service', 'memory.max': str(M.MEMORY),
                    'memory.swap.max': '0', 'memory.peak': '1024', 'memory.events': 'oom 0\noom_kill 0\n'}[path.name]
        for status in (0, 9):
            with patch.object(Path, 'read_text', read), patch.object(M.subprocess, 'run', return_value=argparse.Namespace(returncode=status)), \
                    patch.object(M.time, 'monotonic', side_effect=[10, 20]):
                self.assertEqual(M.worker(args), status)
            value = json.loads((self.root / 'copy-resources.json').read_text())
            self.assertEqual(value['seconds'], 10)
            self.assertEqual(value['exitCode'], status)
            if status:
                with self.assertRaises(ValueError): M.resource_receipt(value)
            else: M.resource_receipt(value)
        value['exitCode'] = 0; value['memoryEvents'] = 'oom 1\noom_kill 1\n'
        with self.assertRaisesRegex(ValueError, 'OOM'): M.resource_receipt(value)

    def test_stop_timeout_still_kills_client_joins_reader_and_checks_unit(self):
        process, reader, record = Mock(), Mock(), {}
        process.poll.return_value = None; reader.is_alive.return_value = False
        responses = [subprocess.TimeoutExpired('systemctl stop', 15),
                     argparse.Namespace(stdout='LoadState=loaded\nActiveState=active\n')]
        with patch.object(M.subprocess, 'run', side_effect=responses) as command:
            with self.assertRaisesRegex(ValueError, 'cleanup failed'): M.stop_service('fixture', process, reader, record)
        self.assertEqual(command.call_count, 2)
        process.kill.assert_called_once(); reader.join.assert_called_once()
        self.assertFalse(record['serviceQuiescent'])

    def test_layout_not_deleted_when_service_shutdown_unconfirmed(self):
        for quiescent in (False, True):
            record = {'serviceStarted': True, 'serviceQuiescent': quiescent}
            with patch.dict(os.environ, {'RUNNER_TEMP': str(self.root)}):
                with M.workspace(record) as directory:
                    (directory / 'blob').write_text('owned')
            self.assertEqual(directory.exists(), not quiescent)

    def test_real_buildkit_attestation_accepts_only_canonical_empty_config(self):
        path = ROOT / 'tests/fixtures/image-transfer/buildkit-attestation.json'
        raw = path.read_bytes()
        self.assertEqual(M.METADATA.sha(raw), 'sha256:f26f09e719156a600a5d891b4f06f1e0cf9f2dc4c94bf5a10bc2c94680f57d23')
        manifest = json.loads(raw); native = manifest['subject']
        descriptor, config = M.empty_attestation_config(manifest, native)
        self.assertEqual(config, b'{}')
        self.assertEqual(descriptor, {key: M.EMPTY_CONFIG[key] for key in ('mediaType', 'digest', 'size')})
        for mutation in ({'data': 'e30'}, {'data': 'e30=\n'}, {'data': 'W10='}, {'data': ''},
                {'size': 3}, {'size': '2'}, {'digest': 'sha256:' + '0' * 64}, {'urls': ['https://elsewhere']},
                {'mediaType': 'application/vnd.oci.image.config.v1+json'}, {'extra': True}):
            value = copy.deepcopy(manifest); value['config'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): M.empty_attestation_config(value, native)
        for mutation in ({'artifactType': 'other'}, {'subject': dict(native, size=native['size'] + 1)},
                         {'subject': dict(native, digest='sha256:' + '0' * 64)}, {'subject': None}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                M.empty_attestation_config(dict(manifest, **mutation), native)

    def test_native_manifest_still_rejects_empty_or_inline_configs(self):
        for descriptor in (M.EMPTY_CONFIG, dict(M.EMPTY_CONFIG, mediaType='application/vnd.oci.image.config.v1+json')):
            manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                        'config': descriptor, 'layers': []}
            raw = json.dumps(manifest).encode()
            args = argparse.Namespace(digest=M.METADATA.sha(raw), profile='finite-dev', source='a' * 40, identity='v1:' + 'b' * 64)
            recorder = Mock(directory=self.root)
            def fetch(stage, command, **kwargs):
                (self.root / (stage + '.stdout')).write_bytes(raw)
                return raw
            recorder.command.side_effect = fetch
            with self.subTest(descriptor=descriptor), self.assertRaisesRegex(ValueError, 'descriptor'):
                M.metadata_binding(recorder, args, {})
            self.assertEqual(recorder.command.call_count, 1)

    def test_signed_index_budgets_and_binds_native_and_attestation_graph(self):
        source, identity = 'a' * 40, 'v1:' + 'b' * 64
        objects, configs = {}, {}
        def blob(value, kind):
            raw = json.dumps(value).encode(); digest = M.METADATA.sha(raw); objects[digest] = raw
            return {'digest': digest, 'size': len(raw), 'mediaType': kind}
        config = {'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'c' * 64]},
            'config': {'Labels': {'io.finite.profile': 'finite-dev', 'io.finite.build-inputs': identity,
                'org.opencontainers.image.revision': source, 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                'org.opencontainers.image.base.digest': 'sha256:' + 'd' * 64}}}
        native_config = blob(config, 'application/vnd.oci.image.config.v1+json')
        native_layer = blob({'layer': 'native'}, 'application/vnd.oci.image.layer.v1.tar+gzip')
        native_manifest = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': native_config, 'layers': [native_layer]}, 'application/vnd.oci.image.manifest.v1+json')
        configs[native_manifest['digest']] = objects[native_config['digest']]
        attestation_config = dict(M.EMPTY_CONFIG)
        objects[attestation_config['digest']] = b'{}'
        attestation_layer = blob({'predicateType': 'fixture'}, M.ATTESTATION_TYPE)
        attestation = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'artifactType': 'application/vnd.docker.attestation.manifest.v1+json', 'subject': native_manifest,
            'config': attestation_config, 'layers': [attestation_layer]}, 'application/vnd.oci.image.manifest.v1+json')
        configs[attestation['digest']] = objects[attestation_config['digest']]
        entries = [dict(native_manifest, platform={'os': 'linux', 'architecture': 'amd64'}),
            dict(attestation, platform={'os': 'unknown', 'architecture': 'unknown'}, annotations={
                'vnd.docker.reference.type': 'attestation-manifest', 'vnd.docker.reference.digest': native_manifest['digest']})]
        top = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': entries},
                   'application/vnd.oci.image.index.v1+json')
        args = argparse.Namespace(digest=top['digest'], profile='finite-dev', source=source, identity=identity)
        class Recorder:
            directory = self.root
            def command(recorder, stage, command, **kwargs):
                digest = command[-1].split('@')[1]
                if '--config' in command and digest == attestation['digest']:
                    raise AssertionError('Canonical inline config should not invoke image-config inspection')
                raw = configs[digest] if '--config' in command else objects[digest]
                (recorder.directory / (stage + '.stdout')).write_bytes(raw)
                return raw
        raw, binding = M.metadata_binding(Recorder(), args, {})
        self.assertEqual(len(binding['transportBlobs']), 7)
        self.assertEqual(binding['nativeDigest'], native_manifest['digest'])
        self.assertIn({key: M.EMPTY_CONFIG[key] for key in ('mediaType', 'digest', 'size')}, binding['transportBlobs'])
        layout = self.root / 'index-layout'; blobs = layout / 'blobs/sha256'; blobs.mkdir(parents=True)
        for digest, value in objects.items(): (blobs / digest[7:]).write_bytes(value)
        (layout / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
        (layout / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [top]}))
        digestfile = self.root / 'digest'; digestfile.write_text(top['digest'])
        self.assertTrue(M.verify_layout(layout, digestfile, args.digest, raw, binding)['compressedBlobsVerified'])
        empty_blob = blobs / M.EMPTY_CONFIG['digest'][7:]
        empty_blob.write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError, 'digest verification'): M.verify_layout(layout, digestfile, args.digest, raw, binding)
        empty_blob.unlink()
        with self.assertRaisesRegex(ValueError, 'missing OCI blob'): M.verify_layout(layout, digestfile, args.digest, raw, binding)
        empty_blob.write_bytes(b'{}')
        path = blobs / attestation_layer['digest'][7:]; path.write_bytes(b'x' * path.stat().st_size)
        with self.assertRaises(ValueError): M.verify_layout(layout, digestfile, args.digest, raw, binding)
        entries[1]['annotations']['vnd.docker.reference.digest'] = 'sha256:' + 'f' * 64
        bad = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': entries}, top['mediaType'])
        args.digest = bad['digest']
        with self.assertRaisesRegex(ValueError, 'bound attestation'): M.metadata_binding(Recorder(), args, {})

    def reports(self):
        reports, jobs = [], []
        for copies in (1, 2):
            for repetition in (1, 2, 3):
                reports.append({'schema': 1, 'experiment': 'bounded-image-transfer', 'status': 'success',
                    'copies': copies, 'repetition': repetition, 'revision': 'a' * 40, 'run': 123, 'attempt': 1,
                    'profile': 'finite-dev', 'digest': 'sha256:' + 'b' * 64, 'source': 'c' * 40, 'identity': 'v1:' + 'd' * 64,
                    'policy': M.POLICY, 'runnerImage': 'fixture-image', 'runnerHardware': {'logicalCPUs': 4}, 'platform': 'Linux-X64', 'lockSha256': 'lock',
                    'cosignKeySha256': 'key', 'versions': {'skopeo': 'pinned', 'cosign': 'pinned'}, 'binding': {},
                    'integrity': {'manifestConfigLayersVerified': True, 'compressedBlobsVerified': True, 'uniqueBlobBytes': 1024},
                    'copy': {'exitCode': 0, 'timedOut': False, 'serviceQuiescent': True, 'seconds': 10, 'boundedServiceSeconds': 11,
                        'peakMemoryBytes': 1024, 'blobBytesPerSecond': 102.4,
                        'resources': {'exitCode': 0, 'seconds': 10, 'peakMemoryBytes': 1024, 'memoryMaxBytes': M.MEMORY,
                                      'memorySwapMaxBytes': 0, 'memoryEvents': 'oom 0\noom_kill 0\n'}},
                    'setupSeconds': 10, 'diagnosticSeconds': 20, 'setupPlusDiagnosticSeconds': 30})
                jobs.append({'id': len(jobs) + 1, 'name': f'transfer-{copies}-{repetition}', 'run_id': 123,
                    'run_attempt': 1, 'head_sha': 'a' * 40, 'status': 'completed', 'conclusion': 'success',
                    'started_at': '2026-10-28T00:00:00Z', 'completed_at': '2026-10-28T00:01:00Z'})
        return reports, [{'jobs': jobs}]

    def test_complete_matched_cohort_includes_whole_job_but_never_adopts(self):
        reports, pages = self.reports(); result = M.comparison(reports, pages)
        self.assertEqual(result['medians']['1']['wholeJobSeconds'], 60)
        self.assertEqual(result['medians']['2']['copySeconds'], 10)
        self.assertFalse(result['productionChangeRecommended'])

    def test_failures_drift_duplicates_missing_and_unverified_cannot_select_winner(self):
        original, pages = self.reports()
        for mutation in ({'status': 'error'}, {'runnerImage': 'other'}, {'versions': {'skopeo': 'other'}},
                {'digest': 'other'}, {'integrity': None}, {'repetition': 2}, {'policy': {}}, {'setupPlusDiagnosticSeconds': 100}):
            reports = copy.deepcopy(original); reports[0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): M.comparison(reports, pages)
        for key, value in (('timedOut', True), ('exitCode', 9), ('seconds', float('nan')), ('peakMemoryBytes', M.MEMORY + 1)):
            reports = copy.deepcopy(original); reports[0]['copy'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): M.comparison(reports, pages)
        with self.assertRaises(ValueError): M.comparison(original[:-1], pages)

    def test_impossible_timing_throughput_and_resource_receipts_fail(self):
        original, pages = self.reports()
        for key, value in (('seconds', 6000), ('boundedServiceSeconds', 5), ('blobBytesPerSecond', 999999999), ('resources', {})):
            reports = copy.deepcopy(original); reports[0]['copy'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): M.comparison(reports, pages)
        reports = copy.deepcopy(original); reports[0]['copy']['resources']['memoryEvents'] = 'oom 1\noom_kill 1\n'
        with self.assertRaises(ValueError): M.comparison(reports, pages)

    def test_whole_job_identity_and_final_success_are_mandatory(self):
        reports, original = self.reports()
        for mutation in ({'status': 'in_progress'}, {'conclusion': 'failure'}, {'run_attempt': 2},
                {'run_id': 124}, {'head_sha': 'other'}, {'completed_at': None}):
            pages = copy.deepcopy(original); pages[0]['jobs'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): M.comparison(reports, pages)

    def test_manual_workflow_has_bounded_matrix_without_publication_or_credentials(self):
        workflow = (ROOT / '.github/workflows/benchmark-image-transfer.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertIn('max-parallel: 1', workflow)
        self.assertEqual(workflow.count('- {copies:'), 6)
        self.assertIn('cache-mode: none', workflow)
        self.assertNotIn('secrets.', workflow)
        self.assertNotIn('packages: write', workflow)
        source = (ROOT / 'scripts/bluebuild/security-scan.py').read_text()
        self.assertIn("'--image-parallel-copies', '1'", source)

    def test_impact_preserves_source_checks_without_image_work(self):
        import sys
        sys.path.insert(0, str(ROOT / 'scripts/ci'))
        spec = importlib.util.spec_from_file_location('transfer_impact', ROOT / 'scripts/ci/impact.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.classify(['scripts/ci/benchmark-image-transfer.py', '.github/workflows/benchmark-image-transfer.yml']),
                         {'checks': True, 'nix': False, 'profiles': []})


if __name__ == '__main__':
    unittest.main()
