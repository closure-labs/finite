#!/usr/bin/env python3
"""Manual hosted cold-DB AB/BA scan experiment; never release clearance."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = 'closure-labs/finite/.github/workflows/benchmark-database-overlap.yml@refs/heads/main'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/ci' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


REUSE = module('overlap_reuse_helpers', 'benchmark-security-reuse.py')
# This imported module instance is private to this process, not a production
# allowlist change. Its existing authentication still requires this exact workflow.
REUSE.WORKFLOW = WORKFLOW
TRANSFER = module('overlap_resource_helpers', 'benchmark-image-transfer.py')
MEMORY = 10 * 1024**3
HEADROOM = 4 * 1024**3
SECONDS = 3600
EVIDENCE_BYTES = 2 * 1024**3
RETAIN_BYTES = 64 * 1024**2
ORDERS = {'serial-first': ('serial', 'overlap'), 'overlap-first': ('overlap', 'serial')}
POLICY = {'memoryMaxBytes': MEMORY, 'memorySwapMaxBytes': 0, 'headroomBytes': HEADROOM,
          'scanTimeoutSeconds': SECONDS, 'serviceRuntimeMaxSeconds': SECONDS + 180, 'tasksMax': 256, 'minimumFreeDiskBytes': HEADROOM,
          'sampleIntervalSeconds': 1, 'cache': 'new-private-home-tmp-db-and-inventory-per-arm',
          'imageParallelCopies': 1, 'syftParallelism': 1,
          'serialDatabaseTimeoutSeconds': 1800, 'overlapDatabaseTimeoutSeconds': 600,
          'maxEvidenceBytes': EVIDENCE_BYTES, 'maxRetainedNativeBytes': RETAIN_BYTES}
REQUIRED = ('security-result.json', 'coverage.json', 'database-coverage.json',
            'inventory-provenance.json', 'phase-timings.json', 'extraction.json',
            'image-manifest.json', 'image-config.json')
RETAIN = set(REQUIRED) | {'database-overlap.json', 'platform-manifest.json', 'extraction-manifest.json',
                        'extraction-layout.json', 'approved-baseline.json', 'upstream-verification.json'}
read = REUSE.read


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def number(value, maximum, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not (0 < value if positive else 0 <= value) or value > maximum:
        raise ValueError('Invalid bounded benchmark number')
    return value


def hosted():
    REUSE.hosted()
    if (os.environ.get('RUNNER_OS') != 'Linux' or os.environ.get('RUNNER_ARCH') != 'X64'
            or not os.environ.get('ImageVersion')
            or any(not re.fullmatch(r'[1-9][0-9]*', os.environ.get(key, ''))
                   for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))):
        raise ValueError('Require the exact hosted Linux/X64 image and run identity')


def private_path(path):
    path = path.absolute()
    if ('..' in path.parts or any(p.is_symlink() for p in (path, *path.parents))
            or any(ord(c) < 32 for c in str(path))):
        raise ValueError('Diagnostic paths must be absolute and unlinked')
    return path


def owned_database(value, temporary):
    """Match all scanner-declared identity fields except the owned location."""
    value = json.loads(json.dumps(value, allow_nan=False))
    status = value['status']
    path = private_path(Path(status['path']))
    if not path.is_relative_to(temporary) or path == temporary:
        raise ValueError('Database is not located in this arm private workspace')
    if (status.get('valid') is not True or status.get('error')
            or not isinstance(status.get('schemaVersion'), str)
            or not re.fullmatch(r'v?[1-9][0-9]*(?:\.[0-9]+){0,3}', status['schemaVersion'])
            or not isinstance(status.get('from'), str) or not status['from']):
        raise ValueError('Missing scanner-reported database identity')
    REUSE.stamp(status['built'])
    providers = value.get('providers')
    if not isinstance(providers, dict) or not providers:
        raise ValueError('Missing scanner provider identities')
    for name, provider in providers.items():
        if (not isinstance(name, str) or not name or not isinstance(provider, dict)
                or not isinstance(provider.get('input'), str) or not provider['input']):
            raise ValueError('Missing scanner provider input digest')
        REUSE.stamp(provider['captured'])
    del status['path']
    return value


def phases_valid(value, lane):
    if value.get('inventoryReused') is not False:
        raise ValueError('Both arms must generate fresh inventory')
    phases = value.get('phases')
    if not isinstance(phases, list) or not 0 < len(phases) <= 64:
        raise ValueError('Missing bounded native phase timings')
    for phase in phases:
        if not isinstance(phase, dict) or phase.get('success') is not True:
            raise ValueError('Native scan phase failed')
        number(phase.get('seconds'), SECONDS)
    for name in ('image-transfer', 'rootfs-extraction', 'inventory-cataloging', 'database-update',
                 'database-coverage', 'vulnerability-scan', 'policy-evaluation'):
        matches = [p for p in phases if p.get('phase') == name]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate native phase: ' + name)
        if name == 'database-update' and matches[0].get('concurrentWithInventory', False) is not (lane == 'overlap'):
            raise ValueError('Wrong database overlap execution lane')
    return phases


def native_receipt(evidence, temporary, lane, image, policy_hash, tools):
    result = read(evidence / 'security-result.json')
    policy = read(ROOT / 'automation/security/image-policy.json')
    if (not REUSE.native_scan_health(result, policy) or result.get('image') != image
            or result.get('policySha256') != policy_hash
            or not re.search(r'\b(?:v)?' + re.escape(result['scanner']) + r'(?![0-9A-Za-z.-])', tools['grype'])):
        raise ValueError('Native scanner health, image, policy or tool binding failed')
    phases = phases_valid(read(evidence / 'phase-timings.json'), lane)
    # Revalidate the complete native SBOM/manifests/evidence binding before
    # dropping large raw files; this does not substitute for native policy.
    security = module('overlap_security_policy', '../bluebuild/security-policy.py')
    inventory = module('overlap_inventory_evidence', 'inventory-evidence.py')
    provenance = inventory.verify(evidence, image, security, policy.get('mode') in security.RISK_MODES)
    overlap = None
    if lane == 'overlap':
        overlap = read(evidence / 'database-overlap.json')
        if (overlap.get('updateSucceeded') is not True or overlap.get('privateColdDatabase') is not True
                or overlap.get('updateTimeoutSeconds') != 600):
            raise ValueError('Missing successful isolated overlap receipt')
        number(overlap.get('waitAfterInventorySeconds'), 600)
    elif (evidence / 'database-overlap.json').exists():
        raise ValueError('Serial arm unexpectedly enabled overlap')
    return {'scannerStatus': result['status'], 'scanner': result['scanner'],
            'scannerReportedDatabaseIdentity': owned_database(result['database'], temporary),
            'policyResultSha256': REUSE.policy_equivalence(result),
            'coverage': result['coverage'], 'databaseCoverageRecords': result['databaseCoverageRecords'],
            'platformDigest': provenance['platformDigest'], 'inventoryGeneration': provenance['generation'],
            'phases': phases, 'overlap': overlap,
            'nativeInventoryVerified': True, 'humanAdmissionEvaluated': False}


def retain_evidence(evidence, output, require_complete=True):
    """Census before reads; retain small native receipts and hash larger files."""
    entries = list(evidence.iterdir())
    if len(entries) > 64 or (require_complete and not set(REQUIRED) <= {p.name for p in entries}):
        raise ValueError('Missing or oversized native evidence census')
    total = 0
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Native evidence must contain regular files only')
        total += path.stat().st_size
    if total > EVIDENCE_BYTES:
        raise ValueError('Native evidence exceeds the two-GiB census cap')
    selected = [p for p in entries if p.name in RETAIN]
    if any(p.stat().st_size > 16 * 1024**2 for p in selected) or sum(p.stat().st_size for p in selected) > RETAIN_BYTES:
        raise ValueError('Native retained evidence exceeds its bounded artifact cap')
    output.mkdir(parents=True, exist_ok=False)
    census = {}
    for path in sorted(entries):
        size = path.stat().st_size
        census[path.name] = {'bytes': size, 'sha256': REUSE.sha(path, size), 'retained': path.name in RETAIN}
        if path.name in RETAIN:
            shutil.copyfile(path, output / path.name)
            if REUSE.sha(output / path.name) != census[path.name]['sha256']:
                raise ValueError('Retained native evidence changed during copying')
    return census


def cgroup_path(unit):
    if not re.fullmatch(r'finite-db-benchmark-[0-9a-f]{16}', unit):
        raise ValueError('Invalid owned service nonce')
    group = Path('/proc/self/cgroup').read_text().strip()
    if not group.startswith('0::/') or Path(group[4:]).name != unit + '.service' or '..' in Path(group[4:]).parts:
        raise ValueError('Worker is not inside its real owned unified cgroup')
    path = Path('/sys/fs/cgroup') / group[4:]
    if (path.joinpath('memory.max').read_text().strip() != str(MEMORY)
            or path.joinpath('memory.swap.max').read_text().strip() != '0'
            or path.joinpath('pids.max').read_text().strip() != '256'):
        raise ValueError('Worker cgroup does not enforce the declared caps')
    return path



def io_valid(raw):
    if not isinstance(raw, str) or not 0 < len(raw) <= 65536:
        raise ValueError('Missing bounded cgroup I/O telemetry')
    devices = set()
    for line in raw.splitlines():
        fields = line.split()
        if not fields or not re.fullmatch(r'[0-9]+:[0-9]+', fields[0]) or fields[0] in devices:
            raise ValueError('Invalid or duplicate I/O device')
        devices.add(fields[0])
        counters = {}
        for field in fields[1:]:
            if not re.fullmatch(r'[a-z_]+=[0-9]+', field):
                raise ValueError('Malformed I/O counter')
            key, value = field.split('=')
            if key in counters:
                raise ValueError('Duplicate I/O counter')
            counters[key] = int(value)
        if not {'rbytes', 'wbytes', 'rios', 'wios'} <= counters.keys():
            raise ValueError('Incomplete I/O counters')
    if not devices:
        raise ValueError('Missing I/O devices')


def resources_valid(value):
    if (type(value.get('exitCode')) is not int or value['exitCode'] != 0 or value.get('memoryMaxBytes') != MEMORY
            or value.get('memorySwapMaxBytes') != 0 or value.get('diskFloorBreached') is not False
            or type(value.get('peakMemoryBytes')) is not int):
        raise ValueError('Failed, unbounded or disk-exhausted worker')
    number(value['peakMemoryBytes'], MEMORY, True)
    number(value.get('scanWallSeconds'), SECONDS, True)
    events = value.get('memoryEvents')
    if (not isinstance(events, dict) or events.get('oom') != 0 or events.get('oom_kill') != 0
            or any(type(v) is not int or v < 0 for v in events.values())):
        raise ValueError('Missing or nonzero cgroup OOM evidence')
    if (type(value.get('diskFreeMinimumBytes')) is not int or value['diskFreeMinimumBytes'] < HEADROOM
            or type(value.get('diskFreeStartBytes')) is not int
            or value['diskFreeStartBytes'] < value['diskFreeMinimumBytes']
            or type(value.get('diskSamples')) is not int or value['diskSamples'] < 1
            or not isinstance(value.get('ioStat'), str) or len(value['ioStat']) > 65536):
        raise ValueError('Missing or invalid disk/I/O observations')
    io_valid(value['ioStat'])
    network = value.get('runnerNetworkDelta')
    if (not isinstance(network, dict) or set(network) != {'rx_bytes', 'tx_bytes'}
            or any(type(v) is not int or v < 0 for v in network.values())):
        raise ValueError('Missing runner network observations')
    return value


@contextmanager
def cancellation():
    handlers = {}
    def stop(number, _frame):
        # Ignore repeated signals until owned service cleanup finishes.
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        raise InterruptedError('Database benchmark cancelled by signal ' + str(number))
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            handlers[number] = signal.signal(number, stop)
        yield
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)


def worker(args):
    hosted()
    group = cgroup_path(args.unit)
    temporary = private_path(args.temporary)
    output = private_path(args.output)
    if not temporary.is_dir() or list(temporary.iterdir()):
        raise ValueError('Worker workspace must start empty')
    home, temp, db = temporary / 'home', temporary / 'tmp', temporary / 'db'
    home.mkdir(); temp.mkdir()
    evidence = temporary / 'evidence'
    env = {key: os.environ[key] for key in ('PATH', 'GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_ACTIONS')}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), XDG_CACHE_HOME=str(home / 'cache'),
               TMPDIR=str(temp), GRYPE_DB_CACHE_DIR=str(db), GRYPE_DB_AUTO_UPDATE='false',
               GRYPE_DB_REQUIRE_UPDATE_CHECK='true', GRYPE_DB_VALIDATE_BY_HASH_ON_START='true',
               GRYPE_DB_VALIDATE_AGE='true', GRYPE_CHECK_FOR_APP_UPDATE='false', SYFT_CHECK_FOR_APP_UPDATE='false',
               FINITE_SCANNER_BOUNDED='true', FINITE_REUSE_INVENTORY='false', FINITE_GRYPE_DB_CACHE='false',
               SYFT_PARALLELISM='1', SYFT_LOG_LEVEL='info', GOMEMLIMIT='8192MiB')
    command = [sys.executable, str(ROOT / 'scripts/bluebuild/security-scan.py'), args.image, str(evidence)]
    if args.lane == 'overlap': command.append('--experimental-database-overlap')
    record = {'schema': 1, 'lane': args.lane, 'exitCode': None, 'diskFloorBreached': False,
              'memoryMaxBytes': MEMORY, 'memorySwapMaxBytes': 0, 'diskSamples': 0,
              'diskFreeStartBytes': shutil.disk_usage(temporary).free}
    record['diskFreeMinimumBytes'] = record['diskFreeStartBytes']
    before = time.monotonic()
    network = TRANSFER.METADATA.network_bytes()
    process = None
    try:
        if record['diskFreeStartBytes'] < HEADROOM:
            raise ValueError('Insufficient disk headroom before native scan')
        process = subprocess.Popen(command, cwd=ROOT, env=env)
        while True:
            free = shutil.disk_usage(temporary).free
            record['diskSamples'] += 1
            record['diskFreeMinimumBytes'] = min(free, record['diskFreeMinimumBytes'])
            if free < HEADROOM:
                record['diskFloorBreached'] = True
                raise ValueError('Runner disk headroom fell below safety floor')
            remaining = SECONDS - (time.monotonic() - before)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, SECONDS)
            try:
                record['exitCode'] = process.wait(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        record['scanWallSeconds'] = round(time.monotonic() - before, 3)
        if record['exitCode'] != 0:
            raise ValueError('Native scanner failed; no second arm or performance conclusion')
        tools = read(args.context)['tools']
        record['native'] = native_receipt(evidence, temporary, args.lane, args.image, read(args.context)['policySha256'], tools)
        record['nativeEvidence'] = retain_evidence(evidence, output / 'native')
        if args.lane == 'overlap' and list(temp.glob('finite-security-db-*')):
            raise ValueError('Overlap left its private database behind')
        if list(temp.iterdir()):
            raise ValueError('Native scanner left temporary work behind')
        record['nativeTemporaryCleanupVerified'] = True
    except BaseException as error:
        record['error'] = str(error)
        raise
    finally:
        # The parent stops the entire owned service on every outcome. Do not
        # treat killing only this direct child as proof of descendant cleanup.
        if process is not None and process.poll() is None:
            process.terminate()
        record.setdefault('scanWallSeconds', round(time.monotonic() - before, 3))
        record['peakMemoryBytes'] = int((group / 'memory.peak').read_text())
        record['memoryEvents'] = {key: int(value) for key, value in
                                  (line.split() for line in (group / 'memory.events').read_text().splitlines())}
        record['ioStat'] = (group / 'io.stat').read_text()
        after = TRANSFER.METADATA.network_bytes()
        record['runnerNetworkDelta'] = {key: after[key] - value for key, value in network.items() if key in after}
        record['workerWallSeconds'] = round(time.monotonic() - before, 3)
        save(output / 'worker.json', record)
    resources_valid(record)


@contextmanager
def deferred_signals():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def stop_owned_service(unit, process, reader, record):
    # The first cancellation must not abandon an in-progress stop/reap/show.
    with deferred_signals():
        _stop_owned_service(unit, process, reader, record)


def _stop_owned_service(unit, process, reader, record):
    """Clean up a known nonce even when launch or log-thread setup was interrupted."""
    record['cleanupAttempted'] = True
    errors = []
    try:
        subprocess.run(['sudo', '--non-interactive', 'systemctl', 'stop', unit + '.service'],
                       check=False, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    try:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if reader is not None and reader.ident is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                errors.append('Scanner log pipe did not close')
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        errors.append(str(error))
    try:
        result = subprocess.run(['sudo', '--non-interactive', 'systemctl', 'show', unit + '.service',
            '--property=LoadState', '--property=ActiveState', '--property=Result', '--property=ExecMainStatus'],
            timeout=15, text=True, capture_output=True, check=False)
        record['service'] = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        record['serviceQuiescent'] = (record['service'].get('ActiveState') in ('inactive', 'failed')
                                     and record['service'].get('LoadState') in ('loaded', 'not-found') and not errors)
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    record['shutdownErrors'] = errors


def measured_arm(lane, image, output, context):
    output.mkdir(parents=True, exist_ok=False)
    record = {'lane': lane, 'launchAttempted': False, 'serviceStarted': False, 'serviceQuiescent': False, 'timedOut': False}
    temporary = Path(tempfile.mkdtemp(prefix='finite-db-benchmark-', dir=os.environ['RUNNER_TEMP']))
    unit = 'finite-db-benchmark-' + os.urandom(8).hex()
    process = reader = None
    started = time.monotonic()
    try:
        available = re.search(r'^MemAvailable:\s+([0-9]+) kB$', Path('/proc/meminfo').read_text(), re.M)
        if not available or int(available[1]) * 1024 < MEMORY + HEADROOM:
            raise ValueError('Insufficient available RAM for fixed 10-GiB cap plus 4-GiB headroom')
        record['initialAvailableMemoryBytes'] = int(available[1]) * 1024
        properties = ['MemoryMax=' + str(MEMORY), 'MemorySwapMax=0', 'OOMPolicy=stop',
                      'RuntimeMaxSec=' + str(SECONDS + 180), 'TimeoutStopSec=5', 'KillMode=control-group',
                      'SendSIGKILL=yes', 'TasksMax=256', 'NoNewPrivileges=yes', 'CapabilityBoundingSet=',
                      'ProtectControlGroups=yes', 'MemoryAccounting=yes', 'IOAccounting=yes',
                      'User=' + str(os.getuid()), 'Group=' + str(os.getgid())]
        command = ['sudo', '--non-interactive', 'systemd-run', '--unit=' + unit, '--wait', '--pipe', '--service-type=exec',
                   '--working-directory=' + str(ROOT)] + ['--property=' + prop for prop in properties]
        keys = ('PATH', 'GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_ACTIONS', 'GITHUB_REF', 'GITHUB_EVENT_NAME',
                'GITHUB_WORKFLOW_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')
        command += ['--setenv=' + key + '=' + os.environ[key] for key in keys]
        command += [sys.executable, str(Path(__file__).resolve()), 'worker', '--unit', unit, '--lane', lane,
                    '--image', image, '--temporary', str(temporary), '--output', str(output), '--context', str(context)]
        # Do not lose process ownership if cancellation arrives between fork
        # and assignment. systemd, not this launcher, starts the service worker.
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        record['launchAttempted'] = True
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            record['serviceStarted'] = True
            reader = threading.Thread(target=TRANSFER.drain, args=(process.stdout, output / 'scanner.log'), daemon=True)
            reader.start()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        try:
            record['exitCode'] = process.wait(timeout=SECONDS + 210)
        except subprocess.TimeoutExpired:
            record['timedOut'] = True
            raise
        finally:
            stop_owned_service(unit, process, reader, record)
        worker_record = read(output / 'worker.json')
        record['worker'] = worker_record
        if record.get('exitCode') != 0 or not record['serviceQuiescent'] or record['timedOut']:
            raise ValueError('Bounded service failed or shutdown is unconfirmed')
        resources_valid(worker_record)
        if worker_record.get('nativeTemporaryCleanupVerified') is not True:
            raise ValueError('Native temporary cleanup was not verified')
        return record
    except BaseException as error:
        record['error'] = str(error)
        raise
    finally:
        with deferred_signals():
            if record['launchAttempted'] and not record.get('cleanupAttempted'):
                stop_owned_service(unit, process, reader, record)
            if not record['launchAttempted'] or record['serviceQuiescent']:
                # Read failed scanner files only after the whole service is stopped;
                # timed-out descendants must not still be mutating these receipts.
                if (temporary / 'evidence').is_dir() and not (output / 'native').exists():
                    try:
                        record['failedNativeEvidence'] = retain_evidence(temporary / 'evidence', output / 'native', require_complete=False)
                    except (OSError, ValueError) as error:
                        record['evidenceRetentionError'] = str(error)
                shutil.rmtree(temporary)
                record['workspaceRemoved'] = True
            else:
                record['workspaceRemoved'] = False
            record['armWallSeconds'] = round(time.monotonic() - started, 3)
            save(output / 'arm.json', record)


def pair_valid(arms):
    if len(arms) != 2 or {r.get('lane') for r in arms} != {'serial', 'overlap'}:
        raise ValueError('Require exactly one successful arm of each lane')
    matched = ('scanner', 'scannerStatus', 'scannerReportedDatabaseIdentity', 'policyResultSha256', 'coverage',
               'databaseCoverageRecords', 'platformDigest', 'inventoryGeneration')
    for arm in arms:
        if (type(arm.get('exitCode')) is not int or arm['exitCode'] != 0 or arm.get('serviceQuiescent') is not True or arm.get('timedOut') is not False
                or arm.get('workspaceRemoved') is not True):
            raise ValueError('Failed arm or unconfirmed service/workspace cleanup')
        resources_valid(arm['worker'])
        if arm['worker'].get('lane') != arm['lane']:
            raise ValueError('Worker lane differs from arm receipt')
        native = arm['worker']['native']
        if native.get('nativeInventoryVerified') is not True or arm['worker'].get('nativeTemporaryCleanupVerified') is not True:
            raise ValueError('Native inventory or cleanup integrity is missing')
        phases_valid({'inventoryReused': False, 'phases': native['phases']}, arm['lane'])
        if (any(key not in native or native[key] is None for key in matched)
                or not REUSE.HEX.fullmatch(native.get('policyResultSha256', ''))
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', native.get('platformDigest', ''))
                or any(native[key] != arms[0]['worker']['native'].get(key) for key in matched)):
            raise ValueError('Incomparable DB/provider, image, inventory, tools, policy or coverage cohort')
        if (not isinstance(native['scannerReportedDatabaseIdentity'], dict) or not native['scannerReportedDatabaseIdentity']
                or not isinstance(native['inventoryGeneration'], dict) or not native['inventoryGeneration']
                or not isinstance(native['coverage'], dict) or not native['coverage']
                or type(native['databaseCoverageRecords']) is not int or native['databaseCoverageRecords'] <= 0
                or not isinstance(native['scanner'], str) or not native['scanner']):
            raise ValueError('Missing native comparison identities or coverage')
        if any(p['seconds'] > arm['worker']['scanWallSeconds'] + 2 for p in native['phases']):
            raise ValueError('Native phase exceeds observed scan wall time')
        number(arm['armWallSeconds'], SECONDS + 240, True)
        if arm['worker']['scanWallSeconds'] > arm['armWallSeconds'] + .1:
            raise ValueError('Scan wall time exceeds complete arm wall time')
    by_lane = {arm['lane']: arm for arm in arms}
    return {'scanWallSavedSeconds': by_lane['serial']['worker']['scanWallSeconds'] - by_lane['overlap']['worker']['scanWallSeconds'],
            'armWallSavedSeconds': by_lane['serial']['armWallSeconds'] - by_lane['overlap']['armWallSeconds'],
            'peakMemoryDeltaBytes': by_lane['overlap']['worker']['peakMemoryBytes'] - by_lane['serial']['worker']['peakMemoryBytes']}


def benchmark(args):
    hosted()
    REUSE.inputs(args.image, args.profile, args.origin)
    if args.order not in ORDERS or type(args.repetition) is not int or args.repetition not in (1, 2, 3):
        raise ValueError('Invalid benchmark order/repetition')
    args.output = private_path(args.output)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'schema': 1, 'experiment': 'database-overlap', 'status': 'error', 'order': args.order,
              'repetition': args.repetition, 'policy': POLICY, 'arms': [], 'releaseEligibilityEstablished': False,
              'productionChangeRecommended': False}
    try:
        report.update(REUSE.context())
        report['runnerHardware'] = TRANSFER.runner_cohort()
        report['binding'] = REUSE.authenticate(args.image, args.profile, args.origin)
        report['setupSeconds'] = number(started - read(args.start, 4096)['monotonicSeconds'], 1800)
        context = args.output / 'context.json'
        save(context, {key: report[key] for key in ('tools', 'policySha256')})
        with cancellation():
            for lane in ORDERS[args.order]:
                report['arms'].append(measured_arm(lane, args.image, args.output / lane, context))
        report['comparison'] = pair_valid(report['arms'])
        report['status'] = 'matched-scanner-observations'
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        report['pairWallSeconds'] = round(time.monotonic() - started, 3)
        report['setupPlusPairSeconds'] = round(report.get('setupSeconds', 0) + report['pairWallSeconds'], 3)
        save(args.output / 'benchmark.json', report)


def comparison(reports, pages):
    hosted()
    expected = {(order, repetition) for order in ORDERS for repetition in (1, 2, 3)}
    if (len(reports) != 6 or any(type(r.get('repetition')) is not int for r in reports)
            or {(r['order'], r['repetition']) for r in reports} != expected):
        raise ValueError('Require all six unique reversed-order repeated pairs')
    keys = ('revision', 'runId', 'attempt', 'lockSha256', 'policySha256', 'platform', 'tools', 'nixVersion',
            'runner', 'runnerHardware', 'binding', 'policy')
    if any(any(r[key] != reports[0][key] for key in keys) for r in reports):
        raise ValueError('Different image, tools, policy, resource or runner cohort')
    if not isinstance(pages, list) or not 0 < len(pages) <= 10:
        raise ValueError('Invalid complete job metadata pages')
    jobs = [job for page in pages for job in page['jobs']]
    if (any(not isinstance(page.get('jobs'), list) or len(page['jobs']) > 100 for page in pages)
            or any(page.get('total_count') != len(jobs) for page in pages)
            or len({j['id'] for j in jobs}) != len(jobs)):
        raise ValueError('Incomplete or duplicate job metadata')
    rows = []
    identities = []
    for report in reports:
        if (report.get('status') != 'matched-scanner-observations' or report.get('policy') != POLICY
                or report.get('revision') != os.environ['GITHUB_SHA']
                or report.get('runId') != os.environ['GITHUB_RUN_ID'] or report.get('attempt') != os.environ['GITHUB_RUN_ATTEMPT']
                or [a['lane'] for a in report['arms']] != list(ORDERS[report['order']])):
            raise ValueError('Failed pair, wrong execution identity or order')
        delta = pair_valid(report['arms'])
        if delta != report['comparison']:
            raise ValueError('Reported comparison differs from arm measurements')
        identities.append(report['arms'][0]['worker']['native'])
        name = f'Database overlap ({report["order"]}, {report["repetition"]})'
        selected = [j for j in jobs if j.get('name') == name]
        if len(selected) != 1:
            raise ValueError('Missing or duplicate exact pair job')
        job = selected[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or job.get('run_id') != int(report['runId']) or job.get('run_attempt') != int(report['attempt'])
                or job.get('head_sha') != report['revision']):
            raise ValueError('Job is not a successful same-attempt/source pair')
        duration = REUSE.whole_job_seconds(job, report['setupPlusPairSeconds'], 120 * 60)
        number(report['setupSeconds'], 1800)
        number(report['pairWallSeconds'], 120 * 60, True)
        if (abs(report['setupSeconds'] + report['pairWallSeconds'] - report['setupPlusPairSeconds']) > .01
                or sum(a['armWallSeconds'] for a in report['arms']) > report['pairWallSeconds'] + .1):
            raise ValueError('Inconsistent pair/setup timing')
        rows.append({'order': report['order'], 'repetition': report['repetition'], 'jobId': job['id'],
                     'wholePairJobSeconds': duration, **delta})
    for value in identities:
        for key in ('scannerReportedDatabaseIdentity', 'policyResultSha256', 'coverage', 'databaseCoverageRecords',
                    'platformDigest', 'inventoryGeneration', 'scanner'):
            if value[key] != identities[0][key]:
                raise ValueError('Database publication or native observation changed across repeated pairs')
    return {'schema': 1, 'status': 'matched-scanner-observations', 'pairs': rows,
            'scanWallMedianSavedSeconds': statistics.median(row['scanWallSavedSeconds'] for row in rows),
            'armWallMedianSavedSeconds': statistics.median(row['armWallSavedSeconds'] for row in rows),
            'orderMedians': {order: statistics.median(r['scanWallSavedSeconds'] for r in rows if r['order'] == order) for order in ORDERS},
            'releaseEligibilityEstablished': False, 'productionChangeRecommended': False,
            'limitations': ['This compares scanner wall time, not separate whole-job savings.',
                           'Cold application workspaces do not imply cold host/page/network caches; both orders are repeated.',
                           'DB/provider identities are scanner-reported, not an independently hashed database-file comparison.',
                           'Disk and network are sampled runner-wide observations, not exclusive per-process counters.',
                           'Policy health is not human publication admission; no production rollout is enabled.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    marker = commands.add_parser('mark-start'); marker.add_argument('output', type=Path)
    run = commands.add_parser('run')
    for name in ('image', 'profile', 'origin', 'order'): run.add_argument('--' + name, required=True)
    run.add_argument('--repetition', type=int, required=True)
    for name in ('start', 'output'): run.add_argument('--' + name, type=Path, required=True)
    child = commands.add_parser('worker')
    for name in ('unit', 'image'): child.add_argument('--' + name, required=True)
    child.add_argument('--lane', choices=('serial', 'overlap'), required=True)
    for name in ('temporary', 'output', 'context'): child.add_argument('--' + name, type=Path, required=True)
    summary = commands.add_parser('summarize')
    for name in ('directory', 'jobs', 'output'): summary.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == 'mark-start':
        save(args.output, {'monotonicSeconds': time.monotonic()})
    elif args.command == 'run':
        benchmark(args)
    elif args.command == 'worker':
        worker(args)
    else:
        result = {'schema': 1, 'status': 'rejected', 'releaseEligibilityEstablished': False,
                  'productionChangeRecommended': False}
        try:
            result = comparison([read(p) for p in sorted(args.directory.rglob('benchmark.json'))], read(args.jobs))
            result['jobMetadataSha256'] = REUSE.sha(args.jobs)
        except (OSError, ValueError, KeyError, TypeError) as error:
            result['error'] = str(error)
            raise
        finally:
            save(args.output, result)


if __name__ == '__main__':
    main()
