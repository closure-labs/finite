#!/usr/bin/env python3
"""Small fixtures for exact image association and honest diagnostic claims."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('image_verification_benchmark', ROOT / 'scripts/ci/benchmark-image-verification.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ImageVerificationBenchmark(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = 'a' * 40
        self.identity = 'v1:' + 'b' * 64
        self.config = {'architecture': 'amd64', 'os': 'linux',
            'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'c' * 64]},
            'config': {'Labels': {'io.finite.profile': 'bluefin-generic', 'io.finite.build-inputs': self.identity,
                'org.opencontainers.image.revision': self.source,
                'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
                'org.opencontainers.image.base.digest': 'sha256:' + 'd' * 64}}}
        self.config_bytes = json.dumps(self.config).encode()
        self.manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                       'digest': MODULE.sha(self.config_bytes), 'size': len(self.config_bytes)},
            'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip', 'digest': 'sha256:' + 'e' * 64, 'size': 123}]}
        self.manifest_bytes = json.dumps(self.manifest).encode()
        self.digest = MODULE.sha(self.manifest_bytes)
        self.binding = MODULE.image_binding(self.manifest, self.config, 'bluefin-generic', self.source, self.identity)
        self.docker = [{'Id': self.binding['config']['digest'], 'Os': 'linux', 'Architecture': 'amd64',
            'RepoDigests': [MODULE.REPOSITORY + '@' + self.digest],
            'RootFS': {'Type': 'layers', 'Layers': self.binding['diffIds']}, 'Config': self.config['config']}]

    def test_raw_metadata_requires_exact_digest_and_size(self):
        self.assertEqual(MODULE.document(self.manifest_bytes, self.digest, len(self.manifest_bytes)), self.manifest)
        for digest, size in [('sha256:' + 'f' * 64, len(self.manifest_bytes)), (self.digest, len(self.manifest_bytes) + 1)]:
            with self.assertRaises(ValueError):
                MODULE.document(self.manifest_bytes, digest, size)
        with self.assertRaises(ValueError):
            MODULE.document(b'x' * (MODULE.METADATA_LIMIT + 1))

    def test_native_index_requires_unique_supported_platform(self):
        descriptor = dict(digest=self.digest, size=len(self.manifest_bytes), mediaType=self.manifest['mediaType'],
                          platform={'os': 'linux', 'architecture': 'amd64'})
        index = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [descriptor]}
        self.assertEqual(MODULE.native_descriptor(index, 'sha256:' + '0' * 64)['digest'], self.digest)
        for entries in [[], [descriptor, descriptor], [dict(descriptor, platform={'os': 'linux', 'architecture': 'arm64'})],
                        [dict(descriptor, platform=['amd64'])]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                MODULE.native_descriptor(dict(index, manifests=entries), self.digest)

    def test_descriptor_rejects_external_unbounded_or_wrong_content(self):
        base = self.manifest['layers'][0]
        for changed in [dict(base, size=True), dict(base, size=0), dict(base, size=33 * 1024**3),
                        dict(base, digest='sha256:bad'), dict(base, urls=['https://elsewhere.example/layer']),
                        dict(base, mediaType='application/octet-stream')]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                MODULE.descriptor(changed, MODULE.LAYER_TYPES, 32 * 1024**3)

    def test_config_platform_provenance_and_ordered_layers_required(self):
        for modify in [lambda value: value.update(architecture='arm64'),
                       lambda value: value['rootfs'].update(diff_ids=[]),
                       lambda value: value['config']['Labels'].update({'io.finite.build-inputs': 'v1:' + '0' * 64}),
                       lambda value: value['config']['Labels'].update({'org.opencontainers.image.source': 'https://example.com'})]:
            value = copy.deepcopy(self.config); modify(value)
            with self.assertRaises(ValueError):
                MODULE.image_binding(self.manifest, value, 'bluefin-generic', self.source, self.identity)

    def test_docker_config_match_alone_cannot_establish_association(self):
        MODULE.verify_docker(self.docker, self.config, self.binding, self.digest, self.digest)
        for modify in [lambda image: image.update(RepoDigests=[]),
                       lambda image: image.update(RepoDigests=['ghcr.io/other/finite@' + self.digest]),
                       lambda image: image.update(Id='sha256:' + '0' * 64),
                       lambda image: image.update(Architecture='arm64'),
                       lambda image: image['RootFS'].update(Layers=['sha256:' + '0' * 64]),
                       lambda image: image['Config']['Labels'].update({'io.finite.profile': 'bluefin-next'})]:
            value = copy.deepcopy(self.docker); modify(value[0])
            with self.assertRaises(ValueError):
                MODULE.verify_docker(value, self.config, self.binding, self.digest, self.digest)

    def reports(self):
        jobs = []
        for phase, repetition in [('cold', 1), *[('warm', number) for number in range(1, 6)]]:
            directory = self.directory / f'{phase}-{repetition}'; directory.mkdir()
            stages = ['signature-verification', 'measured-image-pull', 'measured-image-inspect', 'runtime-checks']
            if phase == 'warm': stages.append('warm-seed-pull')
            report = {'schema': 1, 'experiment': 'registry-pull-diagnostic', 'status': 'success', 'phase': phase, 'repetition': repetition,
                'revision': self.source, 'run': 123, 'attempt': 1, 'candidateSource': self.source, 'profile': 'bluefin-generic', 'digest': self.digest,
                'buildIdentity': self.identity, 'platform': 'linux/amd64', 'lockSha256': 'sha256:' + '0' * 64,
                'runtimeHarnessSha256': 'sha256:' + '1' * 64, 'cosignKeySha256': 'sha256:' + '2' * 64,
                'bluebuildSourceSha256': 'sha256:' + '3' * 64, 'versions': {'docker': 'test', 'cosign': 'test', 'skopeo': 'test'},
                'binding': self.binding, 'runner': {'image': 'fixture'}, 'setupSeconds': 10, 'setupPlusDiagnosticSeconds': 60,
                'stages': [{'stage': stage, 'status': 0, 'seconds': repetition} for stage in stages]}
            (directory / 'benchmark.json').write_text(json.dumps(report))
            jobs.append({'id': len(jobs) + 1, 'name': f'verification-{phase}-{repetition}',
                'run_id': 123, 'run_attempt': 1, 'head_sha': self.source, 'status': 'completed', 'conclusion': 'success',
                'started_at': '2026-10-15T00:00:00Z', 'completed_at': '2026-10-15T00:02:00Z'})
        self.jobfile = self.directory / 'jobs.json'
        self.jobfile.write_text(json.dumps([{'jobs': jobs}]))

    def test_complete_diagnostics_leave_production_change_deferred(self):
        self.reports()
        output = self.directory / 'summary.md'
        MODULE.summarize(self.directory, output, self.jobfile)
        content = output.read_text()
        self.assertIn('Five warm median', content)
        self.assertIn('Warm seed pull median: 3.000 s', content)
        self.assertIn('No retained local OCI bytes', content)
        self.assertIn('Production registry verification stays enabled', content)
        self.assertIn('setupPlusDiagnosticSeconds', content)
        self.assertIn('Complete job including setup, seed, upload and post-job | 120.000 s | 120.000 s', content)
        receipt = json.loads(output.with_suffix('.json').read_text())
        self.assertEqual(len(receipt['jobs']), 6)
        self.assertFalse(receipt['productionReplacementRecommended'])

    def test_incomplete_duplicate_failed_or_mismatched_set_is_rejected(self):
        self.reports()
        path = self.directory / 'warm-5/benchmark.json'
        original = json.loads(path.read_text())
        for mutation in [{'status': 'error'}, {'repetition': 4}, {'digest': 'sha256:' + '0' * 64},
                         {'versions': {'docker': 'different'}}, {'setupSeconds': -1}]:
            path.write_text(json.dumps(dict(original, **mutation)))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                MODULE.summarize(self.directory, self.directory / 'summary.md', self.jobfile)
        path.unlink()
        with self.assertRaises(ValueError):
            MODULE.summarize(self.directory, self.directory / 'summary.md', self.jobfile)

    def test_whole_job_metadata_must_match_completed_run_attempt_and_revision(self):
        self.reports()
        pages = json.loads(self.jobfile.read_text())
        original = copy.deepcopy(pages)
        for mutation in [{'status': 'in_progress'}, {'conclusion': 'failure'}, {'run_id': 124}, {'run_attempt': 2},
                         {'head_sha': '0' * 40}, {'completed_at': None}, {'completed_at': '2026-10-14T23:59:59Z'},
                         {'completed_at': '2026-10-15T00:00:01Z'}]:
            pages = copy.deepcopy(original)
            pages[0]['jobs'][0].update(mutation)
            self.jobfile.write_text(json.dumps(pages))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                MODULE.summarize(self.directory, self.directory / 'summary.md', self.jobfile)
        pages = copy.deepcopy(original); pages[0]['jobs'].append(pages[0]['jobs'][0])
        self.jobfile.write_text(json.dumps(pages))
        with self.assertRaises(ValueError):
            MODULE.summarize(self.directory, self.directory / 'summary.md', self.jobfile)

    def test_recorder_retains_command_failure_and_timeout(self):
        report = {'stages': []}
        recorder = MODULE.Recorder(self.directory, report)
        with patch.object(MODULE.subprocess, 'run', return_value=argparse.Namespace(returncode=7)):
            with self.assertRaises(ValueError): recorder.command('failure', ['fixture'])
        self.assertEqual(report['stages'][-1]['status'], 7)
        with patch.object(MODULE.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['fixture'], 1)):
            with self.assertRaises(subprocess.TimeoutExpired): recorder.command('timeout', ['fixture'])
        self.assertEqual(report['stages'][-1]['status'], 124)

    def test_local_guard_precedes_all_real_commands(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(MODULE.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'GitHub-hosted'):
                MODULE.benchmark(argparse.Namespace())
        command.assert_not_called()

    def run_fixture(self, phase, *, existing=False, wrong_seed=False):
        start = self.directory / 'start.json'
        start.write_text(json.dumps({'unixSeconds': MODULE.time.time()}))
        args = argparse.Namespace(phase=phase, repetition=1, digest=self.digest, source=self.source,
            identity=self.identity, profile='bluefin-generic', start=start, output=self.directory / phase)
        commands = []
        def command(recorder, stage, argv, **kwargs):
            commands.append((stage, argv))
            recorder.report['stages'].append({'stage': stage, 'status': 0, 'seconds': 0.01})
            if stage.startswith('version-'): return b'fixture-version'
            if stage == 'native-docker': return b'linux/x86_64\n'
            if stage.startswith('initial-'): return b'existing-image' if existing else b''
            if stage == 'top-manifest': return self.manifest_bytes
            if stage == 'native-config': return self.config_bytes
            if stage in ('warm-seed-inspect', 'measured-image-inspect'):
                value = copy.deepcopy(self.docker)
                if wrong_seed and stage == 'warm-seed-inspect': value[0]['RepoDigests'] = []
                return json.dumps(value).encode()
            return None
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'GITHUB_SHA': self.source,
                       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        with patch.dict(os.environ, environment), patch.object(MODULE.Recorder, 'command', command):
            try:
                MODULE.benchmark(args)
            except ValueError:
                if not existing and not wrong_seed: raise
        return commands, json.loads((args.output / 'benchmark.json').read_text())

    def test_warm_reader_is_explicitly_seeded_and_never_claims_export_equivalence(self):
        commands, report = self.run_fixture('warm')
        stages = [stage for stage, _ in commands]
        self.assertLess(stages.index('signature-verification'), stages.index('warm-seed-pull'))
        self.assertLess(stages.index('warm-seed-inspect'), stages.index('measured-image-pull'))
        self.assertEqual(sum(stage.endswith('-pull') for stage in stages), 2)
        self.assertEqual(report['status'], 'success')
        self.assertIsNone(report['localExportSeconds'])
        self.assertFalse(report['localCompressedLayersVerified'])
        self.assertEqual(report['binding']['layers'], self.manifest['layers'])
        self.assertFalse(any(word in ('push', 'save', 'load', 'build') for _, command in commands for word in command))

    def test_cold_reader_does_not_hide_a_preparation_pull(self):
        commands, report = self.run_fixture('cold')
        self.assertEqual(sum(stage.endswith('-pull') for stage, _ in commands), 1)
        self.assertNotIn('warm-seed-pull', [stage for stage, _ in commands])
        self.assertEqual(report['status'], 'success')

    def test_existing_state_or_wrong_seed_fails_before_measured_reader(self):
        commands, report = self.run_fixture('cold', existing=True)
        self.assertEqual(report['status'], 'error')
        self.assertNotIn('measured-image-pull', [stage for stage, _ in commands])
        commands, report = self.run_fixture('warm', wrong_seed=True)
        self.assertEqual(report['status'], 'error')
        self.assertNotIn('measured-image-pull', [stage for stage, _ in commands])

    def test_workflow_has_isolated_bounded_matrix_without_credentials_or_publication(self):
        workflow = (ROOT / '.github/workflows/benchmark-image-verification.yml').read_text()
        self.assertIn('max-parallel: 2', workflow)
        self.assertEqual(workflow.count('- {phase: warm,'), 5)
        self.assertEqual(workflow.count('- {phase: cold,'), 1)
        self.assertIn('cache-mode: none', workflow)
        self.assertNotIn('secrets.', workflow)
        self.assertNotIn('packages: write', workflow)


if __name__ == '__main__':
    unittest.main()
