#!/usr/bin/env python3
"""Small fixtures for exact image association and honest diagnostic claims."""
import argparse
import copy
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

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
            stages = ['private-daemon-start', 'signature-verification', 'measured-image-pull', 'measured-image-inspect', 'runtime-checks', 'private-daemon-cleanup']
            stages += [f'{phase}-containerd-{namespace}-{kind}' for phase in ('initial', 'cleaned')
                       for namespace in ('runtime', 'plugins') for kind in ('tasks', 'containers')]
            if phase == 'warm': stages.append('warm-seed-pull')
            report = {'schema': 1, 'experiment': 'registry-pull-diagnostic', 'status': 'success', 'phase': phase, 'repetition': repetition,
                'revision': self.source, 'run': 123, 'attempt': 1, 'candidateSource': self.source, 'profile': 'bluefin-generic', 'digest': self.digest,
                'buildIdentity': self.identity, 'platform': 'linux/amd64', 'lockSha256': 'sha256:' + '0' * 64,
                'runtimeHarnessSha256': 'sha256:' + '1' * 64, 'cosignKeySha256': 'sha256:' + '2' * 64,
                'bluebuildSourceSha256': 'sha256:' + '3' * 64, 'versions': {'docker': 'test', 'cosign': 'test', 'skopeo': 'test'},
                'isolationPolicySha256': 'sha256:' + '4' * 64, 'isolationStorageDriver': 'overlay2',
                'binding': self.binding, 'runner': {'image': 'fixture'}, 'setupSeconds': 10, 'setupPlusDiagnosticSeconds': 60,
                'setupIncludingIsolationSeconds': 11,
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
        self.assertTrue(receipt['sharedContainerdService'])
        self.assertFalse(receipt['sharedContentStoreColdProven'])

    def test_incomplete_duplicate_failed_or_mismatched_set_is_rejected(self):
        self.reports()
        path = self.directory / 'warm-5/benchmark.json'
        original = json.loads(path.read_text())
        for mutation in [{'status': 'error'}, {'repetition': 4}, {'digest': 'sha256:' + '0' * 64},
                         {'versions': {'docker': 'different'}}, {'setupSeconds': -1}, {'isolationPolicySha256': 'sha256:' + '0' * 64}]:
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

    def run_fixture(self, phase, *, existing=False, wrong_seed=False, startup_failure=False, cleanup_failure=False, free=80 * 1024**3):
        start = self.directory / 'start.json'
        start.write_text(json.dumps({'unixSeconds': MODULE.time.time()}))
        args = argparse.Namespace(phase=phase, repetition=1, digest=self.digest, source=self.source,
            identity=self.identity, profile='bluefin-generic', start=start, output=self.directory / phase)
        commands = []
        def command(recorder, stage, argv, **kwargs):
            commands.append((stage, argv))
            recorder.report['stages'].append({'stage': stage, 'status': 0, 'seconds': 0.01})
            if stage.startswith('version-'): return b'fixture-version'
            if stage == 'host-docker-info': return json.dumps({'version': 'fixture', 'driver': 'overlay2', 'dataRoot': '/host/preloaded', 'os': 'linux', 'architecture': 'x86_64'}).encode()
            if stage.startswith('initial-'): return b'existing-image' if existing else b''
            if stage == 'top-manifest': return self.manifest_bytes
            if stage == 'native-config': return self.config_bytes
            if stage in ('warm-seed-inspect', 'measured-image-inspect'):
                value = copy.deepcopy(self.docker)
                if wrong_seed and stage == 'warm-seed-inspect': value[0]['RepoDigests'] = []
                return json.dumps(value).encode()
            return None
        fixture_root = self.directory / 'private'; fixture_root.mkdir()
        class FixtureDaemon:
            def __init__(daemon, recorder):
                daemon.root = fixture_root
                daemon.config_path = fixture_root / 'daemon.json'
                daemon.config = MODULE.isolation_config(fixture_root, 'fixture')
                daemon.config_path.write_text(json.dumps(daemon.config))
            def cli(daemon, *args): return ['docker', '--host=unix:///fixture/private.sock', '--config=/fixture/client', *args]
            def start(daemon):
                if startup_failure: raise ValueError('Fixture cannot isolate')
                return {'version': 'fixture', 'driver': 'overlay2', 'dataRoot': str(fixture_root / 'data'), 'os': 'linux', 'architecture': 'x86_64'}
            def close(daemon):
                if cleanup_failure: raise ValueError('Fixture cleanup failed')
        environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                       'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'GITHUB_SHA': self.source,
                       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        with patch.dict(os.environ, environment), patch.object(MODULE.Recorder, 'command', command), \
                patch.object(MODULE, 'PrivateDaemon', FixtureDaemon), patch.object(MODULE.shutil, 'disk_usage', return_value=argparse.Namespace(free=free)):
            try:
                MODULE.benchmark(args)
            except ValueError:
                if not any((existing, wrong_seed, startup_failure, cleanup_failure)) and free >= 20 * 1024**3: raise
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
        for stage, command in commands:
            if command[0] == 'docker' and stage != 'host-docker-info':
                self.assertIn('--host=unix:///fixture/private.sock', command)
        runtime = next(command for stage, command in commands if stage == 'runtime-checks')
        self.assertEqual(runtime[runtime.index('--network') + 1], 'none')
        self.assertFalse(report['isolation']['sameStore'])

    def test_cold_reader_does_not_hide_a_preparation_pull(self):
        commands, report = self.run_fixture('cold')
        self.assertEqual(sum(stage.endswith('-pull') for stage, _ in commands), 1)
        self.assertNotIn('warm-seed-pull', [stage for stage, _ in commands])
        self.assertEqual(report['status'], 'success')

    def test_existing_private_state_fails_before_measured_reader(self):
        commands, report = self.run_fixture('cold', existing=True)
        self.assertEqual(report['status'], 'error')
        self.assertNotIn('measured-image-pull', [stage for stage, _ in commands])

    def test_wrong_seed_fails_before_measured_reader(self):
        commands, report = self.run_fixture('warm', wrong_seed=True)
        self.assertEqual(report['status'], 'error')
        self.assertNotIn('measured-image-pull', [stage for stage, _ in commands])

    def test_isolation_startup_space_and_cleanup_failures_do_not_pass(self):
        for parameters in ({'startup_failure': True}, {'cleanup_failure': True}, {'free': 0}):
            with self.subTest(parameters=parameters):
                # Each fixture needs an independent small directory, just as
                # each hosted lane owns its daemon state.
                original = self.directory
                self.directory = original / ('case-' + str(len(list(original.iterdir())))); self.directory.mkdir()
                try: commands, report = self.run_fixture('cold', **parameters)
                finally: self.directory = original
                self.assertEqual(report['status'], 'error')
                self.assertIn('private-daemon-cleanup', [stage['stage'] for stage in report['stages']])
                if not parameters.get('cleanup_failure'):
                    self.assertNotIn('measured-image-pull', [stage for stage, _ in commands])

    def private_daemon_fixture(self):
        recorder = MODULE.Recorder(self.directory, {'stages': []})
        with patch.dict(os.environ, {'RUNNER_TEMP': str(self.directory)}), patch.object(MODULE.shutil, 'which', side_effect=lambda name, **kwargs: '/usr/bin/' + name):
            daemon = MODULE.PrivateDaemon(recorder)
        return daemon

    def test_private_startup_uses_bounded_owner_process_without_layer_file_limit(self):
        daemon = self.private_daemon_fixture()
        process = Mock(pid=1234); process.poll.return_value = None
        thread = Mock()
        info = {'version': 'fixture', 'driver': 'overlay2', 'dataRoot': str(daemon.root / 'data'), 'os': 'linux', 'architecture': 'x86_64'}
        with patch.object(MODULE.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(MODULE.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout=json.dumps(info).encode())), \
                patch.object(MODULE.threading, 'Thread', return_value=thread), patch.object(daemon, '_owned_group', return_value=1234):
            self.assertEqual(daemon.start(), info)
        command, = launch.call_args.args
        self.assertIn('2700s', command)
        self.assertIn('--kill-after=5s', command)
        self.assertNotIn('preexec_fn', launch.call_args.kwargs)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(set(launch.call_args.kwargs['env']), {'PATH', 'DOCKER_TMPDIR'})
        for key in ('iptables', 'ip6tables', 'ip-forward', 'ip-masq', 'userland-proxy'):
            self.assertIs(daemon.config[key], False)
        self.assertEqual(daemon.config['bridge'], 'none')
        self.assertEqual(daemon.config['data-root'], str(daemon.root / 'data'))
        self.assertNotIn('--containerd', command)
        self.assertEqual(daemon.config['containerd'], '/run/containerd/containerd.sock')
        self.assertNotIn('runtimeReadSeconds', daemon.config)
        self.assertRegex(daemon.config['containerd-namespace'], r'^finite-verification-[0-9a-f]{16}$')
        self.assertRegex(daemon.config['containerd-plugins-namespace'], r'^finite-verification-plugins-[0-9a-f]{16}$')

    def test_namespace_nonce_is_valid_unique_and_stable_for_tempfile_paths(self):
        roots = [self.directory / name for name in ('finite-vfy-yw5a293_', '_leading', 'consecutive__separators')]
        pattern = re.compile(r'[A-Za-z0-9]+(?:[._-](?:[A-Za-z0-9]+))*')
        namespaces = set()
        for root in roots:
            config = MODULE.isolation_config(root, 'fixture')
            self.assertEqual(config, MODULE.isolation_config(root, 'fixture'))
            for key in ('containerd-namespace', 'containerd-plugins-namespace'):
                namespace = config[key]
                self.assertIsNotNone(pattern.fullmatch(namespace))
                self.assertNotIn(namespace, namespaces)
                namespaces.add(namespace)
        self.assertEqual(len(namespaces), 6)

    def test_startup_timeout_and_foreign_group_fail_without_host_signals(self):
        daemon = self.private_daemon_fixture()
        daemon.process = Mock(pid=1234)
        with patch.object(Path, 'read_bytes', return_value=b'/usr/bin/dockerd\0--config-file=/etc/docker/daemon.json\0'), \
                patch.object(MODULE.subprocess, 'run') as command:
            with self.assertRaises(ValueError): daemon._owned_group()
        command.assert_not_called()
        with patch.object(MODULE.subprocess, 'Popen', return_value=daemon.process), patch.object(MODULE.threading, 'Thread'), \
                patch.object(MODULE.time, 'monotonic', side_effect=[0, 61]), patch.object(daemon, '_runtime_empty'), \
                patch.object(MODULE.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, '60 seconds'): daemon.start()
        command.assert_not_called()

    def test_empty_successful_health_response_retries_until_private_server_is_ready(self):
        daemon = self.private_daemon_fixture()
        process = Mock(pid=1234); process.poll.return_value = None
        empty = {key: '' for key in ('version', 'driver', 'dataRoot', 'os', 'architecture')}
        info = dict(empty, version='28.0.4', driver='overlay2', dataRoot=str(daemon.root / 'data'), os='linux', architecture='x86_64')
        responses = [argparse.Namespace(returncode=0, stdout=json.dumps(value).encode()) for value in (empty, info)]
        with patch.object(MODULE.subprocess, 'Popen', return_value=process), patch.object(MODULE.threading, 'Thread'), \
                patch.object(daemon, '_runtime_empty'), patch.object(daemon, '_owned_group', return_value=1234), \
                patch.object(MODULE.time, 'sleep') as sleep, patch.object(MODULE.subprocess, 'run', side_effect=responses) as probe:
            self.assertEqual(daemon.start(), info)
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(0.2)
        self.assertEqual(daemon.recorder.report['lastPrivateHealth']['attempts'], 2)
        self.assertTrue(daemon.ready)

    def test_empty_health_deadline_is_bounded_and_populated_foreign_root_fails_immediately(self):
        for populated in (False, True):
            with self.subTest(populated=populated):
                daemon = self.private_daemon_fixture()
                process = Mock(pid=1234); process.poll.return_value = None
                info = {'version': '28.0.4', 'driver': 'overlay2', 'dataRoot': '/var/lib/docker', 'os': 'linux', 'architecture': 'x86_64'} if populated else {}
                with patch.object(MODULE.subprocess, 'Popen', return_value=process), patch.object(MODULE.threading, 'Thread'), \
                        patch.object(daemon, '_runtime_empty'), patch.object(MODULE.time, 'monotonic', side_effect=[0, 0, 61]), \
                        patch.object(MODULE.time, 'sleep') as sleep, \
                        patch.object(MODULE.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout=json.dumps(info).encode())):
                    with self.assertRaisesRegex(ValueError, 'private native' if populated else '60 seconds'): daemon.start()
                self.assertFalse(daemon.ready)
                self.assertLessEqual(len(daemon.recorder.report['lastPrivateHealth']['stdout']), 1024)
                if populated: sleep.assert_not_called()

    def test_shared_runtime_queries_are_readonly_exact_namespace_and_reject_remaining_work(self):
        daemon = self.private_daemon_fixture()
        with patch.object(daemon.recorder, 'command', return_value=b'') as command:
            daemon._runtime_empty('initial-containerd')
        self.assertEqual(command.call_count, 4)
        for call in command.call_args_list:
            argv = call.args[1]
            self.assertEqual(call.kwargs['timeout'], 30)
            self.assertEqual(argv[argv.index('--address') + 1], '/run/containerd/containerd.sock')
            self.assertIn(argv[argv.index('--namespace') + 1], [daemon.config[key] for key in ('containerd-namespace', 'containerd-plugins-namespace')])
            self.assertEqual(argv[-2:], ['list', '--quiet'])
            self.assertFalse(set(argv).intersection({'delete', 'kill', 'prune', 'remove'}))
        with patch.object(daemon.recorder, 'command', return_value=b'remaining-task\n'):
            with self.assertRaisesRegex(ValueError, 'remaining tasks'): daemon._runtime_empty('cleaned-containerd')

    def test_runtime_read_timeout_or_command_failure_is_recorded_and_never_retried(self):
        daemon = self.private_daemon_fixture()
        for phase, response, expected_status in (
                ('timeout-containerd', subprocess.TimeoutExpired(['fixture-ctr'], 30), 124),
                ('failed-containerd', argparse.Namespace(returncode=7), 7)):
            with self.subTest(phase=phase):
                kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                with patch.object(MODULE.subprocess, 'run', **kwargs) as command:
                    with self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                        daemon._runtime_empty(phase)
                command.assert_called_once()
                self.assertEqual(command.call_args.kwargs['timeout'], 30)
                stage = daemon.recorder.report['stages'][-1]
                self.assertEqual(stage['stage'], phase + '-runtime-tasks')
                self.assertEqual(stage['status'], expected_status)
                self.assertEqual(stage['timeoutSeconds'], 30)

    def test_summary_requires_final_namespace_cleanup_evidence(self):
        self.reports()
        path = self.directory / 'cold-1/benchmark.json'
        value = json.loads(path.read_text())
        value['stages'] = [entry for entry in value['stages'] if entry['stage'] != 'cleaned-containerd-runtime-tasks']
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'cleaned-containerd-runtime-tasks'):
            MODULE.summarize(self.directory, self.directory / 'summary.md', self.jobfile)

    def test_cleanup_signals_only_revalidated_owned_group_and_records_duration(self):
        daemon = self.private_daemon_fixture()
        daemon.process = Mock(pid=1234); daemon.process.poll.return_value = None; daemon.process.wait.return_value = 0
        daemon.reader = Mock(); daemon.reader.is_alive.return_value = False
        with patch.object(daemon, '_owned_group', return_value=1234) as ownership, \
                patch.object(MODULE.subprocess, 'run', return_value=argparse.Namespace(returncode=0)) as command:
            daemon.recorder.operation('private-daemon-cleanup', daemon.close)
        ownership.assert_called_once()
        self.assertEqual(command.call_args.args[0][-1], '-1234')
        self.assertIn('-TERM', command.call_args.args[0])
        self.assertEqual(daemon.recorder.report['stages'][-1]['status'], 0)
        self.assertIn('no shared-store prune', daemon.recorder.report['isolationCleanup']['privateStoreRemoval'])

    def test_daemon_log_is_bounded_without_capping_image_layer_writes(self):
        daemon = self.private_daemon_fixture()
        daemon.process = argparse.Namespace(stdout=io.BytesIO(b'x' * (MODULE.DAEMON_LOG_LIMIT + 17)))
        daemon._logs()
        self.assertEqual((self.directory / 'private-dockerd.log').stat().st_size, MODULE.DAEMON_LOG_LIMIT)
        self.assertEqual(daemon.log_bytes, MODULE.DAEMON_LOG_LIMIT + 17)

    def test_docker_context_and_tls_overrides_are_child_only(self):
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://host', 'DOCKER_CONTEXT': 'shared', 'DOCKER_TLS_VERIFY': '1', 'KEEP': 'yes'}):
            env = MODULE.docker_environment()
            self.assertFalse(any(key.startswith('DOCKER_') for key in env))
            self.assertEqual(env['KEEP'], 'yes')
            self.assertEqual(os.environ['DOCKER_CONTEXT'], 'shared')

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
