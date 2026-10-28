#!/usr/bin/env python3
"""Opt-in bounded skopeo transport experiment; never security or release clearance."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
import platform
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('transfer_metadata', ROOT / 'scripts/ci/benchmark-image-verification.py')
METADATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METADATA)
MEMORY = 4 * 1024**3
HEADROOM = 4 * 1024**3
TRANSFER_SECONDS = 1800
LOG_LIMIT = 1024**2
POLICY = {'memoryMaxBytes': MEMORY, 'memorySwapMaxBytes': 0, 'headroomBytes': HEADROOM,
          'runtimeMaxSeconds': TRANSFER_SECONDS, 'tasksMax': 64, 'retryTimes': 3,
          'cache': 'new-empty-oci-layout-no-actions-cache', 'copies': [1, 2]}
SECRET_NAMES = ('CACHIX_AUTH_TOKEN', 'COSIGN_PRIVATE_KEY', 'COSIGN_PASSWORD', 'REGISTRY_TOKEN',
                'MERGE_QUEUE_TOKEN', 'SECAUDIT_PEM', 'SECAUDIT_CLIENTID')
ATTESTATION_TYPE = 'application/vnd.in-toto+json'


def metadata_binding(recorder, args, env):
    """Budget every --all child, including attestations, before copying the index."""
    def fetch(stage, digest, config=False):
        command = ['skopeo', '--command-timeout', '30s', 'inspect', '--no-creds']
        if config: command += ['--config']
        raw = recorder.command(stage, command + ['--raw', 'docker://' + METADATA.REPOSITORY + '@' + digest], metadata=True, env=env)
        read(recorder.directory / (stage + '.stdout'))
        return raw
    top_raw = fetch('manifest', args.digest)
    top = METADATA.document(top_raw, args.digest)
    native = METADATA.native_descriptor(top, args.digest)
    if top.get('mediaType') in METADATA.INDEX_TYPES:
        children = top['manifests']
        if len(children) > 8: raise ValueError('Too many copied index children')
        if len({entry['digest'] for entry in children}) != len(children):
            raise ValueError('Duplicate copied child descriptors')
        for entry in children:
            METADATA.descriptor(entry, METADATA.MANIFEST_TYPES, METADATA.METADATA_LIMIT)
            if entry['digest'] != native['digest']:
                annotations = entry.get('annotations', {})
                if (not isinstance(annotations, dict) or annotations.get('vnd.docker.reference.type') != 'attestation-manifest'
                        or annotations.get('vnd.docker.reference.digest') != native['digest']):
                    raise ValueError('Only native image and bound attestation children are admitted')
    else:
        children = [{'digest': args.digest, 'size': len(top_raw), 'mediaType': top['mediaType']}]
    blobs = {args.digest: {'digest': args.digest, 'size': len(top_raw), 'mediaType': top['mediaType']}}
    def retain(entry):
        old = blobs.get(entry['digest'])
        if old and old['size'] != entry['size']: raise ValueError('Conflicting copied blob sizes')
        blobs[entry['digest']] = entry
    binding = None
    for number, entry in enumerate(children):
        raw = top_raw if entry['digest'] == args.digest else fetch('child-' + str(number), entry['digest'])
        manifest = METADATA.document(raw, entry['digest'], entry['size'])
        if manifest.get('schemaVersion') != 2 or manifest.get('mediaType') not in METADATA.MANIFEST_TYPES or 'manifests' in manifest:
            raise ValueError('Copied child must be a single manifest')
        retain(METADATA.descriptor(entry, METADATA.MANIFEST_TYPES, METADATA.METADATA_LIMIT))
        descriptor = METADATA.descriptor(manifest.get('config'), METADATA.CONFIG_TYPES, METADATA.METADATA_LIMIT)
        config_raw = fetch('config-' + str(number), entry['digest'], config=True)
        config = METADATA.document(config_raw, descriptor['digest'], descriptor['size'])
        retain(descriptor)
        layers = manifest.get('layers')
        if not isinstance(layers, list) or not 0 < len(layers) <= 1024:
            raise ValueError('Invalid copied child layers')
        native_child = entry['digest'] == native['digest']
        types = METADATA.LAYER_TYPES if native_child else {ATTESTATION_TYPE}
        for layer in layers: retain(METADATA.descriptor(layer, types, 32 * 1024**3))
        if native_child:
            if binding is not None: raise ValueError('Duplicate native child')
            binding = METADATA.image_binding(manifest, config, args.profile, args.source, args.identity)
    if binding is None or sum(entry['size'] for entry in blobs.values()) > 32 * 1024**3:
        raise ValueError('Missing native image or total --all graph exceeds transfer budget')
    return top_raw, dict(binding, nativeDigest=native['digest'], transportBlobs=sorted(blobs.values(), key=lambda v: v['digest']))


def runner_cohort():
    memory = re.search(r'^MemTotal:\s+([0-9]+) kB$', Path('/proc/meminfo').read_text(), re.M)
    models = sorted(set(re.findall(r'^model name\s*:\s*(.+)$', Path('/proc/cpuinfo').read_text(), re.M)))
    if not memory or not models or not os.cpu_count(): raise ValueError('Missing runner hardware cohort')
    return {'logicalCPUs': os.cpu_count(), 'cpuModels': models, 'memoryTotalKiB': int(memory[1]),
            'kernelRelease': platform.release()}


def resource_receipt(value):
    if (not isinstance(value, dict) or value.get('exitCode') != 0
            or value.get('memoryMaxBytes') != MEMORY or value.get('memorySwapMaxBytes') != 0
            or type(value.get('peakMemoryBytes')) is not int or not 0 < value['peakMemoryBytes'] <= MEMORY
            or type(value.get('seconds')) not in (int, float) or not 0 < value['seconds'] <= TRANSFER_SECONDS):
        raise ValueError('Invalid or failed bounded worker resource receipt')
    events = value.get('memoryEvents', '')
    if not isinstance(events, str) or len(events) > 4096: raise ValueError('Invalid memory events')
    rows = events.splitlines()
    if any(not re.fullmatch(r'[a-z_]+ [0-9]+', row) for row in rows): raise ValueError('Malformed memory events')
    counters = dict(row.split() for row in rows)
    if len(counters) != len(rows) or counters.get('oom') != '0' or counters.get('oom_kill') != '0':
        raise ValueError('Missing or nonzero cgroup OOM evidence')
    return value


def read(path, limit=METADATA.METADATA_LIMIT):
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
            or not 0 < path.stat().st_size <= limit):
        raise ValueError('Missing, linked or oversized diagnostic metadata')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate diagnostic metadata key')
            result[key] = value
        return result
    raw = path.read_bytes()
    if len(raw) > limit: raise ValueError('Metadata grew beyond its budget')
    return json.loads(raw, object_pairs_hook=unique)


def hosted(env=None):
    env = os.environ if env is None else env
    workflow = 'closure-labs/finite/.github/workflows/benchmark-image-transfer.yml@' + env.get('GITHUB_REF', '')
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or env.get('GITHUB_WORKFLOW_REF') != workflow
            or env.get('RUNNER_OS') != 'Linux' or env.get('RUNNER_ARCH') != 'X64'
            or not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))
            or not env.get('ImageVersion') or any(env.get(key) for key in SECRET_NAMES)):
        raise ValueError('Use the manual GitHub-hosted Linux/X64 transfer workflow without write/signing credentials')


def copy_command(image, layout, digestfile, copies):
    if copies not in (1, 2) or not re.fullmatch(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}', image):
        raise ValueError('Unsupported immutable image or copy concurrency')
    return ['skopeo', '--command-timeout', '1800s', 'copy', '--all', '--preserve-digests', '--src-no-creds',
            '--image-parallel-copies', str(copies), '--retry-times', '3', '--digestfile', str(digestfile),
            'docker://' + image, 'oci:' + str(layout) + ':audit']


def drain(source, target):
    """Bound retained logs without RLIMIT_FSIZE, which would also cap layer files."""
    total = 0
    with target.open('xb') as output:
        while chunk := source.read(65536):
            remaining = max(0, LOG_LIMIT - total)
            output.write(chunk[:remaining])
            total += len(chunk)
    return total


def worker(args):
    """Read cgroup peak before systemd releases the completed service's counters."""
    group = Path('/proc/self/cgroup').read_text().strip()
    if not re.fullmatch(r'finite-transfer-[0-9a-f]{16}', args.unit) or not group.startswith('0::/'):
        raise ValueError('Worker requires the owned unified cgroup')
    relative = group[4:]
    if Path(relative).name != args.unit + '.service' or '..' in Path(relative).parts:
        raise ValueError('Worker is not in its bounded service')
    cgroup = Path('/sys/fs/cgroup') / relative
    if (cgroup.joinpath('memory.max').read_text().strip() != str(MEMORY)
            or cgroup.joinpath('memory.swap.max').read_text().strip() != '0'):
        raise ValueError('Worker memory and swap limits differ from the control')
    before = time.monotonic()
    result = subprocess.run(copy_command(args.image, args.layout, args.digestfile, args.copies), check=False,
                            timeout=TRANSFER_SECONDS)
    receipt = {'exitCode': result.returncode, 'seconds': round(time.monotonic() - before, 3),
               'peakMemoryBytes': int(cgroup.joinpath('memory.peak').read_text()),
               'memoryMaxBytes': MEMORY, 'memorySwapMaxBytes': 0,
               'memoryEvents': cgroup.joinpath('memory.events').read_text()}
    args.output.joinpath('copy-resources.json').write_text(json.dumps(receipt) + '\n')
    return result.returncode


def measured_copy(command, output, home, record):
    available = re.search(r'^MemAvailable:\s+([0-9]+) kB$', Path('/proc/meminfo').read_text(), re.M)
    if not available or int(available[1]) * 1024 < MEMORY + HEADROOM:
        raise ValueError('Insufficient available memory for fixed cap plus reserved headroom')
    record['initialAvailableMemoryBytes'] = int(available[1]) * 1024
    unit = 'finite-transfer-' + os.urandom(8).hex()
    properties = ['MemoryMax=' + str(MEMORY), 'MemorySwapMax=0', 'OOMPolicy=stop',
                  'RuntimeMaxSec=' + str(TRANSFER_SECONDS), 'TimeoutStopSec=5', 'KillMode=control-group',
                  'SendSIGKILL=yes', 'TasksMax=64', 'NoNewPrivileges=yes',
                  'CapabilityBoundingSet=', 'ProtectControlGroups=yes', 'MemoryAccounting=yes',
                  'User=' + str(os.getuid()), 'Group=' + str(os.getgid())]
    launch = ['sudo', '--non-interactive', 'systemd-run', '--unit=' + unit, '--wait', '--pipe', '--service-type=exec',
              '--working-directory=' + str(ROOT)]
    launch += ['--property=' + value for value in properties]
    # The worker executes the same skopeo argv and snapshots the cgroup before
    # exit. Reading systemctl MemoryPeak after a successful unit unloads races GC.
    copies = command[command.index('--image-parallel-copies') + 1]
    digestfile = command[command.index('--digestfile') + 1]
    image, layout = command[-2][9:], command[-1][4:].removesuffix(':audit')
    launch += ['--setenv=PATH=' + os.environ['PATH'], '--setenv=HOME=' + str(home),
               '--setenv=XDG_CONFIG_HOME=' + str(home), '--setenv=TMPDIR=' + str(home),
               '--setenv=GOMEMLIMIT=3GiB', sys.executable, str(Path(__file__).resolve()), 'worker',
               '--unit', unit, '--copies', copies, '--image', image, '--layout', layout,
               '--digestfile', digestfile, '--output', str(output.resolve())]
    before, counters = time.monotonic(), METADATA.network_bytes()
    process = None
    record.update(exitCode=None, timedOut=False, service={}, serviceStarted=False, serviceQuiescent=False)
    try:
        process = subprocess.Popen(launch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        record['serviceStarted'] = True
        reader = threading.Thread(target=drain, args=(process.stdout, output / 'copy.log'), daemon=True)
        reader.start()
        try:
            record['exitCode'] = process.wait(timeout=TRANSFER_SECONDS + 30)
        except subprocess.TimeoutExpired:
            record['timedOut'] = True
        finally:
            # Stop only this owned nonce unit; do not mutate host containers or caches.
            stop_service(unit, process, reader, record)
        if not record['serviceQuiescent']:
            raise ValueError('Service shutdown is unconfirmed; retain private layout for runner disposal')
        resources = read(output / 'copy-resources.json')
        record['resources'] = resources
        if record['timedOut'] or record['exitCode'] != 0:
            raise ValueError('Bounded copy failed or has missing/invalid memory accounting')
        resource_receipt(resources)
        record['peakMemoryBytes'] = resources['peakMemoryBytes']
        record['seconds'] = resources['seconds']
    finally:
        record['boundedServiceSeconds'] = round(time.monotonic() - before, 3)
        after = METADATA.network_bytes()
        record['runnerNetworkDelta'] = {key: max(0, after[key] - value) for key, value in counters.items() if key in after}
        if record['serviceQuiescent']:
            try:
                subprocess.run(['sudo', '--non-interactive', 'systemctl', 'reset-failed', unit + '.service'],
                               check=False, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as error:
                record['resetError'] = str(error)


def stop_service(unit, process, reader, record):
    errors = []
    try:
        subprocess.run(['sudo', '--non-interactive', 'systemctl', 'stop', unit + '.service'],
                       check=False, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    try:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        reader.join(timeout=5)
        if reader.is_alive(): errors.append('Transfer log pipe did not close')
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    try:
        properties = subprocess.run(['sudo', '--non-interactive', 'systemctl', 'show', unit + '.service',
            '--property=LoadState', '--property=ActiveState', '--property=Result', '--property=ExecMainStatus',
            '--property=MemoryPeak'], timeout=15, text=True, capture_output=True, check=False)
        record['service'] = dict(line.split('=', 1) for line in properties.stdout.splitlines() if '=' in line)
        record['serviceQuiescent'] = (record['service'].get('ActiveState') in ('inactive', 'failed')
                                      and record['service'].get('LoadState') in ('loaded', 'not-found'))
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    record['shutdownErrors'] = errors
    if errors: raise ValueError('Bounded service cleanup failed: ' + '; '.join(errors))


@contextmanager
def workspace(record):
    directory = Path(tempfile.mkdtemp(prefix='finite-transfer-', dir=os.environ['RUNNER_TEMP']))
    try:
        yield directory
    finally:
        if record.get('serviceStarted') and not record.get('serviceQuiescent'):
            record['layoutCleanup'] = 'retained-for-ephemeral-runner-disposal-service-state-unknown'
        else:
            shutil.rmtree(directory)
            record['layoutCleanup'] = 'removed-after-service-quiescent-or-before-launch'


def verify_layout(layout, digestfile, digest, manifest_bytes, binding):
    """Independently stream-hash every compressed blob; never accept a config ID alone."""
    if digestfile.is_symlink() or digestfile.stat().st_size > 80 or digestfile.read_text().strip() != digest:
        raise ValueError('Copy changed the immutable image digest')
    if read(layout / 'oci-layout') != {'imageLayoutVersion': '1.0.0'}:
        raise ValueError('Unsupported OCI layout')
    index = read(layout / 'index.json')
    manifests = index.get('manifests')
    if (index.get('schemaVersion') != 2 or not isinstance(manifests, list) or len(manifests) != 1
            or not isinstance(manifests[0], dict) or manifests[0].get('digest') != digest
            or manifests[0].get('size') != len(manifest_bytes)
            or manifests[0].get('mediaType') not in METADATA.MANIFEST_TYPES | METADATA.INDEX_TYPES):
        raise ValueError('Layout does not select the requested manifest')
    expected = {digest: len(manifest_bytes)}
    for entry in binding.get('transportBlobs', [binding['config'], *binding['layers']]):
        if entry['digest'] in expected and expected[entry['digest']] != entry['size']:
            raise ValueError('Conflicting blob size descriptors')
        expected[entry['digest']] = entry['size']
    blobs = layout / 'blobs/sha256'
    if set(p.name for p in blobs.iterdir()) != {key[7:] for key in expected}:
        raise ValueError('Unexpected or missing OCI blob')
    for digest, size in expected.items():
        path = blobs / digest[7:]
        if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_size != size):
            raise ValueError('Linked, missing or incorrectly sized OCI blob')
        actual, count = hashlib.sha256(), 0
        with path.open('rb') as stream:
            while chunk := stream.read(min(1024**2, size - count + 1)):
                count += len(chunk)
                if count > size: raise ValueError('OCI blob grew beyond its descriptor')
                actual.update(chunk)
        if count != size or 'sha256:' + actual.hexdigest() != digest:
            raise ValueError('OCI blob failed independent digest verification')
    return {'compressedBlobsVerified': True, 'manifestConfigLayersVerified': True,
            'uniqueBlobBytes': sum(expected.values()), 'uniqueBlobCount': len(expected),
            'uncompressedDiffIdsVerified': False}


def benchmark(args):
    hosted()
    if (args.copies not in (1, 2) or args.repetition not in (1, 2, 3) or args.profile not in METADATA.PROFILES
            or not METADATA.DIGEST.fullmatch(args.digest) or not re.fullmatch(r'[0-9a-f]{40}', args.source)
            or not re.fullmatch(r'v1:[0-9a-f]{64}', args.identity)):
        raise ValueError('Invalid diagnostic input')
    args.output.mkdir(parents=True, exist_ok=False)
    before = time.monotonic()
    setup = time.time() - read(args.start)['unixSeconds']
    report = {'schema': 1, 'experiment': 'bounded-image-transfer', 'status': 'error',
        'copies': args.copies, 'repetition': args.repetition, 'revision': os.environ['GITHUB_SHA'],
        'run': int(os.environ['GITHUB_RUN_ID']), 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'profile': args.profile, 'digest': args.digest, 'source': args.source, 'identity': args.identity,
        'policy': POLICY, 'runnerImage': os.environ['ImageVersion'], 'runnerHardware': runner_cohort(), 'platform': 'Linux-X64',
        'lockSha256': METADATA.sha((ROOT / 'flake.lock').read_bytes()),
        'cosignKeySha256': METADATA.sha((ROOT / 'cosign.pub').read_bytes()),
        'setupSeconds': round(setup, 3), 'stages': [], 'copy': {}, 'integrity': None,
        'productionChangeRecommended': False}
    recorder = METADATA.Recorder(args.output, report)
    try:
        if not 0 <= setup <= 1800: raise ValueError('Invalid setup start marker')
        with workspace(report['copy']) as temporary:
            home = temporary / 'home'; home.mkdir()
            env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'XDG_CONFIG_HOME': str(home), 'TMPDIR': str(home)}
            report['versions'] = {tool: recorder.command('version-' + tool, [tool, '--version'], metadata=True, env=env).decode().strip()
                                  for tool in ('skopeo',)}
            report['versions']['cosign'] = recorder.command('version-cosign', ['cosign', 'version', '--json'], metadata=True, env=env).decode().strip()
            image = METADATA.REPOSITORY + '@' + args.digest
            recorder.command('signature-verification', ['cosign', 'verify', '--new-bundle-format=false', '--key', 'cosign.pub', image], env=env)
            raw, binding = metadata_binding(recorder, args, env)
            report['binding'] = binding
            required = sum(blob['size'] for blob in binding['transportBlobs']) + HEADROOM
            free = shutil.disk_usage(temporary).free
            report['disk'] = {'freeBytes': free, 'requiredBytes': required}
            if free < required: raise ValueError('Insufficient disk for bounded compressed image transfer')
            layout, digestfile = temporary / 'image', temporary / 'digest'
            if layout.exists(): raise ValueError('Transfer destination must start empty')
            measured_copy(copy_command(image, layout, digestfile, args.copies), args.output, home, report['copy'])
            report['integrity'] = recorder.operation('independent-integrity', lambda: verify_layout(layout, digestfile, args.digest, raw, binding))
            report['copy']['blobBytesPerSecond'] = report['integrity']['uniqueBlobBytes'] / report['copy']['seconds']
            report['status'] = 'success'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        raise
    finally:
        report['diagnosticSeconds'] = round(time.monotonic() - before, 3)
        report['setupPlusDiagnosticSeconds'] = round(setup + report['diagnosticSeconds'], 3)
        (args.output / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')


def comparison(reports, pages):
    expected = {(copies, repetition) for copies in (1, 2) for repetition in (1, 2, 3)}
    if len(reports) != 6 or {(r['copies'], r['repetition']) for r in reports} != expected:
        raise ValueError('Require all six unique baseline/candidate measurements, including failed arms')
    keys = ('revision', 'run', 'attempt', 'profile', 'digest', 'source', 'identity', 'policy', 'runnerImage',
            'platform', 'runnerHardware', 'lockSha256', 'cosignKeySha256', 'versions', 'binding', 'integrity')
    if len({json.dumps({key: r[key] for key in keys}, sort_keys=True) for r in reports}) != 1:
        raise ValueError('Different immutable image, tool, runner-image or cache/resource cohort')
    if not reports[0]['runnerImage'] or reports[0]['policy'] != POLICY:
        raise ValueError('Unknown runner or resource/cache policy')
    if not isinstance(pages, list) or not 0 < len(pages) <= 10:
        raise ValueError('Invalid complete-job metadata')
    jobs = []
    for page in pages:
        if not isinstance(page.get('jobs'), list) or len(page['jobs']) > 100:
            raise ValueError('Invalid job metadata page')
        jobs.extend(page['jobs'])
    rows = []
    for report in reports:
        if (report.get('schema') != 1 or report.get('experiment') != 'bounded-image-transfer'
                or report.get('status') != 'success' or not isinstance(report.get('integrity'), dict)
                or report['integrity'].get('manifestConfigLayersVerified') is not True
                or report['integrity'].get('compressedBlobsVerified') is not True
                or report['copy'].get('serviceQuiescent') is not True
                or report['copy'].get('exitCode') != 0 or report['copy'].get('timedOut') is not False):
            raise ValueError('Failed, timed-out or unverified arm; no performance conclusion')
        name = f"transfer-{report['copies']}-{report['repetition']}"
        matched = [job for job in jobs if job.get('name') == name]
        if len(matched) != 1: raise ValueError('Missing or duplicate complete job: ' + name)
        job = matched[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or job.get('run_id') != report['run'] or job.get('run_attempt') != report['attempt']
                or job.get('head_sha') != report['revision']):
            raise ValueError('Job does not bind successful exact run/attempt/revision')
        stamps = [job.get(key, '') for key in ('started_at', 'completed_at')]
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9T:Z-]{20}', value) for value in stamps):
            raise ValueError('Missing job timestamps')
        seconds = (datetime.fromisoformat(stamps[1].replace('Z', '+00:00')) - datetime.fromisoformat(stamps[0].replace('Z', '+00:00'))).total_seconds()
        for value in (report['copy']['seconds'], report['copy']['peakMemoryBytes'], report['copy']['blobBytesPerSecond'],
                      report['setupPlusDiagnosticSeconds'], seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid measured metric')
        if (report['copy']['peakMemoryBytes'] > MEMORY or not 0 < seconds <= 2700
                or seconds + 2 < report['setupPlusDiagnosticSeconds']):
            raise ValueError('Invalid memory bound or incomplete job duration')
        resources = resource_receipt(report['copy'].get('resources'))
        if any(report['copy'][key] != resources[key] for key in ('seconds', 'peakMemoryBytes')):
            raise ValueError('Copy metrics differ from the bounded worker receipt')
        transfer, service, diagnostic, setup = (report['copy']['seconds'], report['copy']['boundedServiceSeconds'],
                                               report['diagnosticSeconds'], report['setupSeconds'])
        if (any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (service, diagnostic, setup))
                or transfer > service + .01 or service > diagnostic + .01
                or abs(setup + diagnostic - report['setupPlusDiagnosticSeconds']) > .01):
            raise ValueError('Impossible transfer/service/diagnostic/setup timing order')
        size = report['integrity'].get('uniqueBlobBytes')
        if (type(size) is not int or not 0 < size <= 32 * 1024**3
                or not math.isclose(report['copy']['blobBytesPerSecond'], size / transfer, rel_tol=1e-9)):
            raise ValueError('Throughput does not match independently verified blob bytes')
        rows.append({'copies': report['copies'], 'repetition': report['repetition'], 'jobId': job['id'],
                     'copySeconds': report['copy']['seconds'], 'peakMemoryBytes': report['copy']['peakMemoryBytes'],
                     'blobBytesPerSecond': report['copy']['blobBytesPerSecond'], 'wholeJobSeconds': seconds})
    return {'schema': 1, 'experiment': 'bounded-image-transfer', 'cohort': {key: reports[0][key] for key in keys},
            'measurements': rows, 'medians': {str(copies): {key: statistics.median(row[key] for row in rows if row['copies'] == copies)
                for key in ('copySeconds', 'peakMemoryBytes', 'blobBytesPerSecond', 'wholeJobSeconds')} for copies in (1, 2)},
            'productionChangeRecommended': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    marker = commands.add_parser('mark-start'); marker.add_argument('output', type=Path)
    run = commands.add_parser('run')
    for name in ('copies', 'repetition'): run.add_argument('--' + name, type=int, required=True)
    for name in ('profile', 'digest', 'source', 'identity'): run.add_argument('--' + name, required=True)
    for name in ('start', 'output'): run.add_argument('--' + name, type=Path, required=True)
    child = commands.add_parser('worker')
    for name in ('unit', 'image'): child.add_argument('--' + name, required=True)
    child.add_argument('--copies', type=int, required=True)
    for name in ('layout', 'digestfile', 'output'): child.add_argument('--' + name, type=Path, required=True)
    summary = commands.add_parser('summarize')
    for name in ('directory', 'jobs', 'output'): summary.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'unixSeconds': time.time()}) + '\n')
    elif args.command == 'run':
        benchmark(args)
    elif args.command == 'worker':
        sys.exit(worker(args))
    else:
        result = comparison([read(path) for path in sorted(args.directory.rglob('benchmark.json'))], read(args.jobs))
        result['jobMetadataSha256'] = METADATA.sha(args.jobs.read_bytes())
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result['medians'], indent=2))


if __name__ == '__main__':
    main()
