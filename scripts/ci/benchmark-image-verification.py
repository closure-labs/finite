#!/usr/bin/env python3
"""Hosted registry-pull diagnostics; never authorizes local-image substitution.

Pinned BlueBuild v0.9.37 selects one exporter in build_tag_push_cmd:
https://github.com/blue-build/cli/blob/v0.9.37/process/drivers/docker_driver.rs
Pushed images use type=image with OCI media types; LocalTar uses type=oci in a
separate invocation. The present pipeline retains no exact dual-export bytes.
https://docs.docker.com/build/exporters/#multiple-exporters requires Buildx and
BuildKit >=0.13; https://docs.docker.com/build/exporters/oci-docker/ documents
different exporter defaults. A Docker config ID is not a manifest/layer proof.

This experiment records the current immutable remote path on isolated runners.
A warm sample explicitly includes a separately timed seed pull, not a build.
No local exporter/importer or independently hashed compressed layers are tested.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import grp
from pathlib import Path
import re
import resource
import shutil
import signal
import statistics
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'ghcr.io/closure-labs/finite'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
PROFILES = ('finite', 'finite-dev')
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'}
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.oci.image.layer.v1.tar+zstd', 'application/vnd.docker.image.rootfs.diff.tar.gzip'}
METADATA_LIMIT = 4 * 1024 * 1024
OUTPUT_LIMIT = 16 * 1024 * 1024
DAEMON_LOG_LIMIT = 1024 * 1024
DOCKER_INFO = ('{"version":{{json .ServerVersion}},"driver":{{json .Driver}},'
               '"dataRoot":{{json .DockerRootDir}},"os":{{json .OSType}},"architecture":{{json .Architecture}}}')
ISOLATION_POLICY = {'schema': 1, 'mode': 'private-dockerd', 'storage-driver': 'overlay2',
    'features': {'containerd-snapshotter': False}, 'bridge': 'none', 'iptables': False, 'ip6tables': False,
    'ip-forward': False, 'ip-masq': False, 'userland-proxy': False, 'shutdown-timeout': 10,
    'max-concurrent-downloads': 3, 'max-download-attempts': 3,
    'containerd': '/run/containerd/containerd.sock',
    'containerd-namespace': 'finite-verification', 'containerd-plugins-namespace': 'finite-verification-plugins',
    'startupSeconds': 60, 'lifetimeSeconds': 2700, 'runtimeReadSeconds': 30,
    'runtimeNetwork': 'none', 'daemonLogLimit': DAEMON_LOG_LIMIT}


def isolation_config(root, group):
    """Docker's documented multiple-daemon bootstrap, with no host networking.

    https://docs.docker.com/reference/cli/dockerd/#run-multiple-daemons
    Docker 28 automatically selects system containerd even with an empty address:
    https://github.com/moby/moby/blob/v28.0.4/cmd/dockerd/daemon.go#L961-L981
    Explicitly retain that service with unique namespaces, never its lifecycle.
    Classic overlay2 image/layer/reference stores use the private data root:
    https://github.com/moby/moby/blob/v28.0.4/daemon/daemon.go#L1008-L1071
    Content/lease services remain shared and are not claimed as a cold store.
    """
    config = {key: value for key, value in ISOLATION_POLICY.items() if key not in
              {'schema', 'mode', 'startupSeconds', 'lifetimeSeconds', 'runtimeReadSeconds', 'runtimeNetwork', 'daemonLogLimit'}}
    # tempfile names may end in '_' or contain repeated separators, which are
    # invalid containerd namespace identifiers. Bind a stable alphanumeric nonce
    # to the unique owned path instead of interpolating its basename.
    nonce = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    config.update({key: config[key] + '-' + nonce for key in ('containerd-namespace', 'containerd-plugins-namespace')})
    return dict(config, hosts=['unix://' + str(root / 'docker.sock')], group=group,
                **{'data-root': str(root / 'data'), 'exec-root': str(root / 'exec'), 'pidfile': str(root / 'dockerd.pid')})


def docker_environment():
    # Explicit socket/config flags must not inherit a host context, TLS or API
    # override. This changes only diagnostic child processes, not the job env.
    return {key: value for key, value in os.environ.items() if not key.startswith('DOCKER_')}


class PrivateDaemon:
    def __init__(self, recorder):
        self.recorder, self.process, self.reader = recorder, None, None
        self.root = Path(tempfile.mkdtemp(prefix='finite-vfy-', dir=os.environ['RUNNER_TEMP'])).resolve()
        if len(str(self.root / 'exec/containerd/containerd.sock').encode()) >= 104:
            raise ValueError('Private daemon socket path exceeds the Unix socket budget')
        self.client = self.root / 'client'; self.client.mkdir()
        (self.root / 'tmp').mkdir()
        self.config_path = self.root / 'daemon.json'
        self.config = isolation_config(self.root, grp.getgrgid(os.getgid()).gr_name)
        self.config_path.write_text(json.dumps(self.config))
        self.config_path.chmod(0o600)
        self.group, self.log_bytes, self.ready = None, 0, False
        self.dockerd = shutil.which('dockerd', path='/usr/sbin:/usr/bin:/sbin:/bin')
        self.ctr = shutil.which('ctr', path='/usr/sbin:/usr/bin:/sbin:/bin')
        if not self.dockerd or not self.ctr: raise ValueError('Hosted Docker/containerd diagnostic binary is missing')

    def cli(self, *args):
        return ['docker', '--host=unix://' + str(self.root / 'docker.sock'), '--config=' + str(self.client), *args]

    def _runtime_empty(self, phase):
        # Read-only namespace queries; never stop, prune or remove shared
        # containerd content/leases. Only Docker owns its runtime cleanup.
        for label, key in (('runtime', 'containerd-namespace'), ('plugins', 'containerd-plugins-namespace')):
            for kind in ('tasks', 'containers'):
                command = ['/usr/bin/sudo', '--non-interactive', '--', self.ctr,
                    '--address', self.config['containerd'], '--namespace', self.config[key], kind, 'list', '--quiet']
                # A hosted sample exhausted 5s before daemon startup. Allow
                # bounded service latency, retaining every failed/slow read;
                # never retry a timeout, command error or nonempty namespace.
                if self.recorder.command(phase + '-' + label + '-' + kind, command, metadata=True,
                        timeout=ISOLATION_POLICY['runtimeReadSeconds']).strip():
                    raise ValueError('Diagnostic containerd namespace has remaining ' + kind)

    def _owned_group(self):
        pidfile = self.root / 'dockerd.pid'
        candidates = [self.process.pid]
        if pidfile.is_file() and not pidfile.is_symlink() and pidfile.stat().st_size <= 32:
            raw = pidfile.read_text().strip()
            if re.fullmatch(r'[1-9][0-9]*', raw): candidates.insert(0, int(raw))
        marker = '--config-file=' + str(self.config_path)
        for pid in candidates:
            try:
                argv = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
                if (marker.encode() in argv and Path(os.fsdecode(argv[0])).name in ('dockerd', 'timeout', 'sudo')):
                    group = os.getpgid(pid)
                    leader = (Path('/proc') / str(group) / 'cmdline').read_bytes().split(b'\0')
                    if marker.encode() in leader and Path(os.fsdecode(leader[0])).name in ('dockerd', 'timeout', 'sudo'):
                        return group
            except (OSError, ProcessLookupError):
                continue
        raise ValueError('Cannot establish the private daemon process-group ownership')

    def _logs(self):
        # Do not give dockerd an RLIMIT_FSIZE: it also writes large image layers.
        # Drain all output while retaining only a parent-managed bounded log.
        with (self.recorder.directory / 'private-dockerd.log').open('xb') as output:
            while chunk := self.process.stdout.read(65536):
                remaining = max(0, DAEMON_LOG_LIMIT - self.log_bytes)
                if remaining: output.write(chunk[:remaining])
                self.log_bytes += len(chunk)

    def start(self):
        self._runtime_empty('initial-containerd')
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'DOCKER_TMPDIR': str(self.root / 'tmp')}
        command = ['/usr/bin/sudo', '--non-interactive', '--preserve-env=DOCKER_TMPDIR', '--', '/usr/bin/timeout',
                   '--signal=TERM', '--kill-after=5s', str(ISOLATION_POLICY['lifetimeSeconds']) + 's',
                   self.dockerd, '--config-file=' + str(self.config_path)]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        start_new_session=True, env=env)
        self.reader = threading.Thread(target=self._logs, daemon=True); self.reader.start()
        deadline = time.monotonic() + ISOLATION_POLICY['startupSeconds']
        attempts = 0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ValueError('Private daemon exited during startup; inspect its bounded log')
            try:
                result = subprocess.run(self.cli('info', '--format', DOCKER_INFO), env=docker_environment(),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2, check=False)
                attempts += 1
                self.recorder.report['lastPrivateHealth'] = {'attempts': attempts, 'exitCode': result.returncode,
                    'stdout': result.stdout[:1024].decode(errors='replace'), 'truncated': len(result.stdout) > 1024}
                if result.returncode == 0:
                    # Docker can render a zero-value server object and exit 0
                    # before the socket serves a ready daemon. Retry that state;
                    # populated responses identifying a foreign store fail closed.
                    info = document(result.stdout) if result.stdout.strip() else {}
                    if not any(info.get(key) for key in ('version', 'driver', 'dataRoot', 'os', 'architecture')):
                        time.sleep(0.2)
                        continue
                    if (info.get('dataRoot') != str(self.root / 'data') or info.get('driver') != 'overlay2'
                            or info.get('os') != 'linux' or info.get('architecture') not in ('x86_64', 'amd64')):
                        raise ValueError('Daemon health response does not identify the private native overlay2 store')
                    self.group = self._owned_group()
                    self.ready = True
                    return info
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.2)
        raise ValueError('Private Docker daemon did not become ready within 60 seconds')

    def close(self):
        if self.process is None: return
        errors = []
        try:
            if self.ready:
                try:
                    ids = self.recorder.command('private-container-state', self.cli('container', 'ls', '--all', '--quiet', '--no-trunc'),
                        metadata=True, timeout=5, env=docker_environment()).decode().split()
                    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in ids):
                        raise ValueError('Invalid private runtime container identifiers')
                    if ids: self.recorder.command('private-container-cleanup', self.cli('container', 'rm', '--force', *ids),
                        timeout=5, env=docker_environment())
                    self._runtime_empty('cleaned-containerd')
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    errors.append(str(error))
            if self.process.poll() is None:
                group = self._owned_group()
                result = subprocess.run(['/usr/bin/sudo', '--non-interactive', '--', '/bin/kill', '-TERM', '--', '-' + str(group)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                if result.returncode: raise ValueError('Could not stop the owned private daemon group')
            try:
                status = self.process.wait(timeout=15)
                if status not in (0, -signal.SIGTERM, 128 + signal.SIGTERM):
                    errors.append('Private daemon exited abnormally: ' + str(status))
            except subprocess.TimeoutExpired:
                # Revalidate ownership before escalation; never signal the host
                # daemon, a name match, or an unowned process group.
                group = self._owned_group()
                subprocess.run(['/usr/bin/sudo', '--non-interactive', '--', '/bin/kill', '-KILL', '--', '-' + str(group)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)
                self.process.wait(timeout=5)
                errors.append('Private daemon required forced shutdown')
        finally:
            if self.reader: self.reader.join(timeout=3)
            if self.reader and self.reader.is_alive(): errors.append('Private daemon log pipe did not close')
            self.recorder.report['isolationCleanup'] = {'logBytes': self.log_bytes,
                'logTruncated': self.log_bytes > DAEMON_LOG_LIMIT,
                'sharedContainerdServiceStopped': False,
                'sharedContainerdContentPruned': False,
                'privateStoreRemoval': 'Ephemeral runner disposal; no shared-store prune or recursive deletion.'}
        if errors: raise ValueError('; '.join(errors))


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def document(data, expected=None, size=None):
    if not 0 < len(data) <= METADATA_LIMIT or (expected and sha(data) != expected) or (size is not None and len(data) != size):
        raise ValueError('Metadata size or digest does not match its immutable descriptor')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Expected a metadata object')
    return value


def descriptor(value, types, limit):
    if (not isinstance(value, dict) or not DIGEST.fullmatch(value.get('digest', ''))
            or type(value.get('size')) is not int or not 0 < value['size'] <= limit
            or value.get('mediaType') not in types or value.get('urls') or value.get('data')):
        raise ValueError('Unsupported or unbounded image descriptor')
    return {key: value[key] for key in ('mediaType', 'digest', 'size')}


def native_descriptor(top, digest):
    if type(top.get('schemaVersion')) is not int or top['schemaVersion'] != 2:
        raise ValueError('Unsupported image manifest schema')
    if top.get('mediaType') in MANIFEST_TYPES:
        return {'digest': digest, 'size': None}
    if top.get('mediaType') not in INDEX_TYPES:
        raise ValueError('Unsupported image index media type')
    entries = top.get('manifests')
    if not isinstance(entries, list) or not 0 < len(entries) <= 64:
        raise ValueError('Invalid image index')
    if any(not isinstance(entry, dict) or not isinstance(entry.get('platform', {}), dict) for entry in entries):
        raise ValueError('Invalid platform descriptor')
    matches = [entry for entry in entries if isinstance(entry, dict)
               and entry.get('platform', {}).get('os') == 'linux'
               and entry.get('platform', {}).get('architecture') == 'amd64'
               and entry.get('platform', {}).get('variant', '') == '']
    if len(matches) != 1:
        raise ValueError('Expected exactly one native linux/amd64 manifest')
    return descriptor(matches[0], MANIFEST_TYPES, METADATA_LIMIT)


def image_binding(manifest, config, profile, source, identity):
    if type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 2 or manifest.get('mediaType') not in MANIFEST_TYPES:
        raise ValueError('Expected a runnable native image manifest')
    config_descriptor = descriptor(manifest.get('config'), CONFIG_TYPES, METADATA_LIMIT)
    layers = manifest.get('layers')
    if not isinstance(layers, list) or not 0 < len(layers) <= 1024:
        raise ValueError('Invalid image layers')
    layers = [descriptor(entry, LAYER_TYPES, 32 * 1024**3) for entry in layers]
    if sum(entry['size'] for entry in layers) > 32 * 1024**3:
        raise ValueError('Image exceeds diagnostic transfer budget')
    if config.get('os') != 'linux' or config.get('architecture') != 'amd64':
        raise ValueError('Image config is not native linux/amd64')
    rootfs = config.get('rootfs', {})
    diffs = rootfs.get('diff_ids')
    if (rootfs.get('type') != 'layers' or not isinstance(diffs, list) or len(diffs) != len(layers)
            or not all(isinstance(item, str) and DIGEST.fullmatch(item) for item in diffs)):
        raise ValueError('Config does not identify the ordered image filesystem layers')
    labels = config.get('config', {}).get('Labels', {})
    expected = {'io.finite.profile': profile, 'io.finite.build-inputs': identity,
                'org.opencontainers.image.revision': source,
                'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()) or not DIGEST.fullmatch(labels.get('org.opencontainers.image.base.digest', '')):
        raise ValueError('Image labels do not match the declared candidate provenance')
    return {'config': config_descriptor, 'layers': layers, 'diffIds': diffs,
            'labels': expected, 'baseDigest': labels['org.opencontainers.image.base.digest']}


def verify_docker(value, config, binding, digest, native):
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError('Expected exactly one pulled Docker image')
    image = value[0]
    refs = {REPOSITORY + '@' + digest, REPOSITORY + '@' + native}
    if (image.get('Id') != binding['config']['digest'] or image.get('Os') != 'linux'
            or image.get('Architecture') != 'amd64'
            or not refs.intersection(image.get('RepoDigests', []))
            or image.get('RootFS', {}).get('Type') != 'layers'
            or image['RootFS'].get('Layers') != binding['diffIds']
            or image.get('Config', {}).get('Labels') != config.get('config', {}).get('Labels')):
        raise ValueError('Pulled image does not match the authenticated native manifest/config/filesystem association')


def network_bytes():
    try:
        for row in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = row.split()
            if fields[1] == '00000000':
                directory = Path('/sys/class/net') / fields[0] / 'statistics'
                return {key: int((directory / key).read_text()) for key in ('rx_bytes', 'tx_bytes')}
    except (OSError, ValueError, IndexError):
        pass
    return {}


class Recorder:
    def __init__(self, directory, report):
        self.directory, self.report = directory, report

    def operation(self, stage, operation):
        before, counters, status = time.monotonic(), network_bytes(), 1
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = operation(); status = 0
            return result
        finally:
            after = network_bytes()
            self.report['stages'].append({'stage': stage, 'startedAt': started, 'status': status,
                'seconds': round(time.monotonic() - before, 3),
                'runnerNetworkDelta': {key: max(0, after[key] - value) for key, value in counters.items() if key in after}})

    def command(self, stage, command, *, timeout=150, metadata=False, env=None):
        before, counters = time.monotonic(), network_bytes()
        started = datetime.now(timezone.utc).isoformat()
        status = 127
        output = self.directory / (stage + '.stdout')
        try:
            with output.open('xb') as stdout, (self.directory / (stage + '.stderr')).open('xb') as stderr:
                try:
                    result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout, env=env,
                                            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT)))
                except subprocess.TimeoutExpired:
                    status = 124
                    raise
                status = result.returncode
            if status:
                raise ValueError('Diagnostic stage ' + stage + ' failed with exit ' + str(status))
            if metadata and output.stat().st_size > METADATA_LIMIT:
                raise ValueError('Oversized diagnostic metadata')
            return output.read_bytes() if metadata else None
        finally:
            after = network_bytes()
            self.report['stages'].append({'stage': stage, 'startedAt': started,
                'seconds': round(time.monotonic() - before, 3), 'status': status, 'timeoutSeconds': timeout,
                'runnerNetworkDelta': {key: max(0, after[key] - value) for key, value in counters.items() if key in after}})


def benchmark(args):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('RUNNER_OS') != 'Linux' or os.environ.get('RUNNER_ARCH') != 'X64'):
        raise ValueError('Run diagnostics only in the GitHub-hosted linux/amd64 workflow')
    if (not DIGEST.fullmatch(args.digest) or not re.fullmatch(r'[0-9a-f]{40}', args.source)
            or not re.fullmatch(r'v1:[0-9a-f]{64}', args.identity)
            or (args.phase, args.repetition) not in [('cold', 1), *[('warm', n) for n in range(1, 6)]]):
        raise ValueError('Invalid immutable candidate or diagnostic repetition')
    started = document(args.start.read_bytes())['unixSeconds']
    if type(started) not in (int, float) or not 0 <= time.time() - started <= 3600:
        raise ValueError('Invalid setup timing marker')
    args.output.mkdir(parents=True, exist_ok=False)
    before = time.monotonic()
    report = {'schema': 1, 'experiment': 'registry-pull-diagnostic', 'phase': args.phase, 'repetition': args.repetition,
        'revision': os.environ['GITHUB_SHA'], 'candidateSource': args.source, 'profile': args.profile,
        'run': int(os.environ['GITHUB_RUN_ID']), 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'digest': args.digest, 'buildIdentity': args.identity, 'platform': 'linux/amd64',
        'lockSha256': sha((ROOT / 'flake.lock').read_bytes()),
        'runtimeHarnessSha256': sha((ROOT / 'scripts/bluebuild/verify-image.sh').read_bytes()),
        'cosignKeySha256': sha((ROOT / 'cosign.pub').read_bytes()),
        'bluebuildSourceSha256': sha((ROOT / 'sources/bluebuild-cli.json').read_bytes()),
        'isolationPolicySha256': sha(json.dumps(ISOLATION_POLICY, sort_keys=True, separators=(',', ':')).encode()),
        'isolationStorageDriver': 'overlay2',
        'coldStoreScope': 'Private Docker classic overlay2 image/layer/reference store only; containerd runtime/content/leases are shared.',
        'runner': {'os': os.environ['RUNNER_OS'], 'arch': os.environ['RUNNER_ARCH'], 'image': os.environ.get('ImageVersion')},
        'setupSeconds': round(time.time() - started, 3), 'stages': [],
        'localExportSeconds': None, 'localImportSeconds': None, 'localCompressedLayersVerified': False,
        'limitations': ['Registry transport diagnostic, not retained build-output equivalence.',
                       'Warm cache is explicitly seeded by a full pull; its cost is retained separately.',
                       'Docker validates pulled content; compressed registry layers are not independently rehashed here.',
                       'Runner traffic includes unrelated activity; it is not per-process transfer accounting.',
                       'Docker documents multiple daemons as experimental; this fixes the diagnostic store, not production behavior.',
                       'Private/host engine and storage backends are recorded; differences prevent production-equivalence claims.',
                       'Containerd runtime/content/leases use the shared host service with unique diagnostic namespaces; only Docker overlay2 image/layer/reference state is private.',
                       'Timings exclude queue wait and artifact upload; Actions timestamps are needed for complete job cost.']}
    recorder = Recorder(args.output, report)
    image = REPOSITORY + '@' + args.digest
    daemon = None
    previous_term = signal.getsignal(signal.SIGTERM)
    def cancelled(signum, frame):
        raise KeyboardInterrupt('Diagnostic cancelled by signal ' + str(signum))
    signal.signal(signal.SIGTERM, cancelled)
    try:
        host = document(recorder.command('host-docker-info', ['docker', '--host=unix:///var/run/docker.sock', 'info', '--format', DOCKER_INFO],
            metadata=True, env=docker_environment()))
        daemon = PrivateDaemon(recorder)
        private = recorder.operation('private-daemon-start', daemon.start)
        report['setupIncludingIsolationSeconds'] = round(report['setupSeconds'] + next(stage['seconds'] for stage in report['stages'] if stage['stage'] == 'private-daemon-start'), 3)
        report['isolation'] = {'policy': ISOLATION_POLICY, 'privateDocker': private, 'hostDocker': host,
            'configSha256': sha(daemon.config_path.read_bytes()),
            'sharedContainerd': {'address': daemon.config['containerd'],
                'namespace': daemon.config['containerd-namespace'], 'pluginsNamespace': daemon.config['containerd-plugins-namespace'],
                'serviceOwned': False, 'contentStoreColdProven': False},
            'productionBackendMatches': all(host.get(key) == private.get(key) for key in ('version', 'driver')),
            'sameStore': False, 'privateRoot': str(daemon.root)}
        if host.get('dataRoot') == private.get('dataRoot'):
            raise ValueError('Diagnostic daemon did not isolate the host image store')
        docker = daemon.cli
        report['versions'] = {name: recorder.command('version-' + name, command, metadata=True,
            env=docker_environment() if name == 'docker' else None).decode().strip()
            for name, command in [('docker', docker('version', '--format', '{{.Server.Version}}')),
                                  ('skopeo', ['skopeo', '--version']), ('cosign', ['cosign', 'version', '--json'])]}
        # Baked-in host images are irrelevant: only this private, empty daemon
        # serves either pull. Never prune or change the host's shared state.
        for kind in ('image', 'container'):
            if recorder.command('initial-' + kind + '-state', docker(kind, 'ls', '--all', '--quiet'), metadata=True, env=docker_environment()).strip():
                raise ValueError('Private diagnostic daemon has preexisting Docker state')
        recorder.command('signature-verification', ['cosign', 'verify', '--new-bundle-format=false', '--key', 'cosign.pub', image])
        top_bytes = recorder.command('top-manifest', ['skopeo', '--command-timeout', '30s', 'inspect', '--no-creds', '--raw', 'docker://' + image], metadata=True)
        top = document(top_bytes, args.digest)
        native = native_descriptor(top, args.digest)
        native_bytes = top_bytes if native['digest'] == args.digest else recorder.command('native-manifest',
            ['skopeo', '--command-timeout', '30s', 'inspect', '--no-creds', '--raw', 'docker://' + REPOSITORY + '@' + native['digest']], metadata=True)
        manifest = document(native_bytes, native['digest'], native['size'])
        config_descriptor = descriptor(manifest.get('config'), CONFIG_TYPES, METADATA_LIMIT)
        config_bytes = recorder.command('native-config', ['skopeo', '--command-timeout', '30s', 'inspect', '--no-creds', '--config', '--raw',
                                                       'docker://' + REPOSITORY + '@' + native['digest']], metadata=True)
        config = document(config_bytes, config_descriptor['digest'], config_descriptor['size'])
        binding = image_binding(manifest, config, args.profile, args.source, args.identity)
        report['binding'] = dict(binding, nativeDigest=native['digest'])
        required = max((32 if args.profile == 'finite-dev' else 20) * 1024**3, 2 * sum(layer['size'] for layer in binding['layers']) + 4 * 1024**3)
        report['diskBeforePull'] = {'freeBytes': shutil.disk_usage(daemon.root).free, 'requiredBytes': required}
        if report['diskBeforePull']['freeBytes'] < required:
            raise ValueError('Insufficient free space for bounded private-store verification')
        pull = docker('pull', '--platform', 'linux/amd64', image)
        if args.phase == 'warm':
            recorder.command('warm-seed-pull', pull, timeout=900, env=docker_environment())
            seeded = recorder.command('warm-seed-inspect', docker('image', 'inspect', image), metadata=True, env=docker_environment())
            verify_docker(json.loads(seeded), config, binding, args.digest, native['digest'])
        recorder.command('measured-image-pull', pull, timeout=900, env=docker_environment())
        inspected = recorder.command('measured-image-inspect', docker('image', 'inspect', image), metadata=True, env=docker_environment())
        verify_docker(json.loads(inspected), config, binding, args.digest, native['digest'])
        recorder.command('runtime-checks', docker('run', '--rm', '--name', 'finite-verification-runtime', '--network', 'none', '--privileged', '--platform', 'linux/amd64', '--entrypoint', '/bin/bash',
            '--volume', str(ROOT / 'scripts/bluebuild/verify-image.sh') + ':/run/verify-image.sh:ro', image,
            '/run/verify-image.sh', args.profile, REPOSITORY), timeout=600, env=docker_environment())
        report['status'] = 'success'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        report.update(status='error', error=str(error))
        raise
    finally:
        try:
            if daemon: recorder.operation('private-daemon-cleanup', daemon.close)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report.update(status='error', cleanupError=str(error))
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            report['diagnosticSeconds'] = round(time.monotonic() - before, 3)
            report['setupPlusDiagnosticSeconds'] = round(report['setupSeconds'] + report['diagnosticSeconds'], 3)
            (args.output / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')


def whole_jobs(reports, pages):
    if not isinstance(pages, list) or not 0 < len(pages) <= 10:
        raise ValueError('Invalid paginated job metadata')
    jobs = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get('jobs'), list) or len(page['jobs']) > 100:
            raise ValueError('Invalid job metadata page')
        jobs.extend(page['jobs'])
    receipts = []
    for report in reports:
        name = f"verification-{report['phase']}-{report['repetition']}"
        matches = [job for job in jobs if isinstance(job, dict) and job.get('name') == name]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous completed diagnostic job: ' + name)
        job = matches[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or type(job.get('id')) is not int or job['id'] <= 0
                or type(job.get('run_id')) is not int or job['run_id'] != report['run']
                or type(job.get('run_attempt')) is not int or job['run_attempt'] != report['attempt']
                or job.get('head_sha') != report['revision']):
            raise ValueError('Diagnostic job does not bind a successful matching run/attempt/revision')
        times = []
        for key in ('started_at', 'completed_at'):
            value = job.get(key, '')
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
                raise ValueError('Missing complete diagnostic job timestamps')
            times.append(datetime.fromisoformat(value.replace('Z', '+00:00')))
        seconds = (times[1] - times[0]).total_seconds()
        if not 0 < seconds <= 7200 or seconds + 2 < report['setupPlusDiagnosticSeconds']:
            raise ValueError('Job duration does not cover the complete diagnostic')
        receipts.append({'phase': report['phase'], 'repetition': report['repetition'], 'jobID': job['id'],
                         'name': name, 'run': job['run_id'], 'attempt': job['run_attempt'], 'revision': job['head_sha'],
                         'startedAt': job['started_at'], 'completedAt': job['completed_at'], 'seconds': seconds})
    return receipts


def summarize(directory, output, jobs_path):
    reports = [json.loads(path.read_text()) for path in sorted(directory.rglob('benchmark.json'))]
    expected = {('cold', 1), *{('warm', n) for n in range(1, 6)}}
    keys = [(report.get('phase'), report.get('repetition')) for report in reports]
    if len(keys) != 6 or set(keys) != expected:
        raise ValueError('Require one cold and five unique warm diagnostics')
    if any(report.get('status') != 'success' or report.get('schema') != 1 or report.get('experiment') != 'registry-pull-diagnostic' for report in reports):
        raise ValueError('Failed diagnostics cannot establish a completed measurement set')
    associated = ('revision', 'run', 'attempt', 'candidateSource', 'profile', 'digest', 'buildIdentity', 'platform', 'lockSha256',
                  'runtimeHarnessSha256', 'cosignKeySha256', 'bluebuildSourceSha256', 'versions', 'binding')
    associated += ('isolationPolicySha256', 'isolationStorageDriver')
    if len({json.dumps({key: report[key] for key in associated}, sort_keys=True) for report in reports}) != 1:
        raise ValueError('Diagnostics do not share the exact candidate, tools and verification inputs')
    def timing(report, stage):
        matches = [entry for entry in report['stages'] if entry['stage'] == stage]
        if len(matches) != 1 or matches[0]['status'] != 0:
            raise ValueError('Missing or failed measured stage: ' + stage)
        value = matches[0]['seconds']
        if type(value) not in (int, float) or not 0 <= value <= 3600:
            raise ValueError('Invalid stage timing')
        return value
    cold = next(report for report in reports if report['phase'] == 'cold')
    warm = [report for report in reports if report['phase'] == 'warm']
    rows = ['| Stage | Cold observation | Five warm median |', '| --- | ---: | ---: |']
    for stage in ('signature-verification', 'measured-image-pull', 'measured-image-inspect', 'runtime-checks'):
        rows.append(f'| {stage} | {timing(cold, stage):.3f} s | {statistics.median(timing(report, stage) for report in warm):.3f} s |')
    for key in ('setupSeconds', 'setupIncludingIsolationSeconds', 'setupPlusDiagnosticSeconds'):
        if any(type(report.get(key)) not in (int, float) or not 0 <= report[key] <= 7200 for report in reports):
            raise ValueError('Invalid diagnostic total')
        rows.append(f'| {key} | {cold[key]:.3f} s | {statistics.median(report[key] for report in warm):.3f} s |')
    jobs_bytes = jobs_path.read_bytes()
    if not 0 < len(jobs_bytes) <= 4 * 1024 * 1024:
        raise ValueError('Oversized or missing completed-job metadata')
    jobs = whole_jobs(reports, json.loads(jobs_bytes))
    cold_job = next(job for job in jobs if job['phase'] == 'cold')
    warm_jobs = [job for job in jobs if job['phase'] == 'warm']
    rows.append(f"| Complete job including setup, seed, upload and post-job | {cold_job['seconds']:.3f} s | {statistics.median(job['seconds'] for job in warm_jobs):.3f} s |")
    seed = statistics.median(timing(report, 'warm-seed-pull') for report in warm)
    for report in reports:
        for stage in ('private-daemon-start', 'private-daemon-cleanup'): timing(report, stage)
        for phase in ('initial', 'cleaned'):
            for namespace in ('runtime', 'plugins'):
                for kind in ('tasks', 'containers'): timing(report, phase + '-containerd-' + namespace + '-' + kind)
    images = sorted({report['runner']['image'] or 'unknown' for report in reports})
    content = ('Registry verification diagnostic for `' + cold['digest'] + '` at `' + cold['revision'] + '`\n\n'
        + '\n'.join(rows) + f'\n\nWarm seed pull median: {seed:.3f} s, excluded from the measured warm pull and included in diagnostic totals.\n\n'
        + 'Runner images: ' + ', '.join(images) + '. Different images limit timing comparisons.\n\n'
        + 'Every lane used an initially empty private overlay2 image/layer/reference store. Private startup and cleanup are included in complete jobs. '
          'Containerd runtime/content/lease services are shared with unique diagnostic namespaces; runtime tasks and containers '
          'were checked empty initially and after Docker cleanup. Shared service/content coldness is not claimed, and its lifecycle/content were not pruned. '
          'Host/private engine and storage metadata remain in each receipt; backend differences and the experimental multiple-daemon '
          'setup limit comparisons with production. The host image store and firewall were not changed.\n\n'
        + 'One cold observation and five explicitly warmed readers passed exact remote manifest/config/native-platform binding, '
          'signature and runtime checks. This is a transport diagnostic. No retained local OCI bytes, export/import costs or '
          'independent compressed-layer equivalence were measured. Production registry verification stays enabled. '
          'A same-build dual-export experiment with exact manifest/config/layer bytes and complete job costs remains required '
          'before recommending a replacement. Complete-job durations use authenticated same-attempt Actions timestamps and include '
          'setup, the full warm seed, artifact upload and post-job handling. Queue wait is excluded and summed time is not billed cost.\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    output.with_suffix('.json').write_text(json.dumps({'schema': 1, 'experiment': 'registry-pull-diagnostic',
        'revision': cold['revision'], 'run': cold['run'], 'attempt': cold['attempt'], 'digest': cold['digest'],
        'isolationPolicySha256': cold['isolationPolicySha256'], 'privateGraphdriverStore': True,
        'sharedContainerdService': True, 'sharedContentStoreColdProven': False,
        'jobMetadataSha256': sha(jobs_bytes), 'jobs': jobs, 'productionReplacementRecommended': False}, indent=2) + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    marker = commands.add_parser('mark-start'); marker.add_argument('output', type=Path)
    aggregate = commands.add_parser('summarize'); aggregate.add_argument('directory', type=Path); aggregate.add_argument('output', type=Path)
    aggregate.add_argument('--jobs', type=Path, required=True)
    run = commands.add_parser('run')
    run.add_argument('--phase', choices=['cold', 'warm'], required=True)
    run.add_argument('--repetition', type=int, required=True)
    run.add_argument('--profile', choices=PROFILES, required=True)
    for name in ('digest', 'source', 'identity'):
        run.add_argument('--' + name, required=True)
    run.add_argument('--start', type=Path, required=True); run.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'unixSeconds': time.time()}) + '\n')
    elif args.command == 'summarize':
        summarize(args.directory, args.output, args.jobs)
    else:
        benchmark(args)


if __name__ == '__main__':
    main()
