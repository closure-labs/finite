#!/usr/bin/env python3
"""Hosted-only inventory/DB transport experiments; never release clearance."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'closure-labs/finite'
WORKFLOW = REPOSITORY + '/.github/workflows/benchmark-security-reuse.yml@refs/heads/main'
LANES = ('baseline', 'inventory-only', 'db-only')
PROFILES = ('bluefin-generic', 'bluefin-next', 'bluefin-dx-generic', 'bluefin-dx-next')
IMAGE = re.compile(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
HEX = re.compile(r'[0-9a-f]{64}')
MAX_DB_BYTES = 2 * 1024 ** 3
MAX_DB_FILES = 32
MAX_DB_METADATA_ENTRIES = 256
TRANSPORT_LIMITS = {'maxBytes': MAX_DB_BYTES, 'maxFiles': MAX_DB_FILES,
                    'maxMetadataEntries': MAX_DB_METADATA_ENTRIES}
SECRET_NAMES = ('CACHIX_AUTH_TOKEN', 'COSIGN_PRIVATE_KEY', 'COSIGN_PASSWORD',
                'MERGE_QUEUE_TOKEN', 'SECAUDIT_PEM', 'SECAUDIT_CLIENTID', 'REGISTRY_TOKEN',
                'GITHUB_ACTIONS_CACHIX_AUTH_TOKEN', 'GITHUB_ACTIONS_MERGE_QUEUE_TOKEN')


def sha(path, expected_bytes=None):
    with path.open('rb') as stream:
        if expected_bytes is None:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
        digest, size = hashlib.sha256(), 0
        while chunk := stream.read(min(1024 ** 2, expected_bytes - size + 1)):
            size += len(chunk)
            if size > expected_bytes:
                raise ValueError('DB file grew after its bounded metadata census')
            digest.update(chunk)
        if size != expected_bytes:
            raise ValueError('DB file shrank after its bounded metadata census')
        return digest.hexdigest()


def read(path, limit=16 * 1024 ** 2):
    if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
            or not 0 < path.stat().st_size <= limit):
        raise ValueError('Missing, linked or oversized benchmark receipt: ' + path.name)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate benchmark receipt field')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def hosted(env=None):
    env = os.environ if env is None else env
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY
            or env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or env.get('GITHUB_WORKFLOW_REF') != WORKFLOW or not SHA.fullmatch(env.get('GITHUB_SHA', ''))
            or any(env.get(name) for name in SECRET_NAMES)):
        raise ValueError('Security benchmark requires the manual main workflow without write/signing credentials')


def inputs(image, profile, origin):
    if not IMAGE.fullmatch(image) or profile not in PROFILES or not re.fullmatch(r'[1-9][0-9]*', origin):
        raise ValueError('Select an immutable Finite image, supported profile and explicit native build origin')


def load_reuse():
    path = ROOT / 'scripts/ci/reuse-image-inventory.py'
    spec = importlib.util.spec_from_file_location('benchmark_inventory', path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def authenticate(image, profile, origin):
    """Authenticate the small native build binding before any expensive scan."""
    hosted()
    inputs(image, profile, origin)
    fetch = load_reuse()
    run = fetch.publication.github('actions/runs/' + origin)
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise ValueError('Benchmark origin must be an overall successful native main build')
    attempt = run['run_attempt']
    artifacts = [item for page in fetch.publication.github(f'actions/runs/{origin}/artifacts?per_page=100', True)
                 for item in page['artifacts']]
    jobs = [item for page in fetch.publication.github(f'actions/runs/{origin}/attempts/{attempt}/jobs?per_page=100', True)
            for item in page['jobs']]
    artifact, build, build_job, security_job = fetch.reuse.metadata(run, jobs, artifacts, profile, origin)
    files = fetch.publication.origin_files(build, profile)
    record = json.loads(files[profile + '-publication.json'])
    if (files[profile + '-image-ref.txt'].decode().strip() != image
            or record.get('profile') != profile or record.get('publish') is not True
            or record.get('qualificationMode') != 'enforce' or 'resumeOrigin' in record
            or record.get('sourceRevision', record.get('revision')) != run['head_sha']
            or not re.fullmatch(r'v1:[0-9a-f]{64}', record.get('buildIdentity', ''))):
        raise ValueError('Selected image does not match its authenticated native build')
    subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', str(ROOT / 'cosign.pub'), image],
                   check=True, timeout=180, stdout=subprocess.DEVNULL)
    return {'image': image, 'profile': profile, 'originRun': int(origin), 'originAttempt': attempt,
            'originRevision': run['head_sha'], 'buildIdentity': record['buildIdentity'],
            'nativeBuildJob': build_job, 'nativeSecurityJob': security_job,
            'nativeSecurityArtifact': artifact['id'], 'nativeSecurityArtifactSha256': artifact['digest'],
            'signatureVerified': True}


def context():
    hosted()
    head = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT, text=True, timeout=30).strip()
    if head != os.environ['GITHUB_SHA']:
        raise ValueError('Benchmark checkout differs from its execution source')
    return {'revision': head, 'runId': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'lockSha256': sha(ROOT / 'flake.lock'), 'policySha256': sha(ROOT / 'automation/security/image-policy.json'),
            'runner': {name: os.environ.get(name) for name in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')},
            'platform': 'linux/amd64',
            'tools': {tool: subprocess.check_output(command, text=True, timeout=30).strip()
                      for tool, command in (
                          ('grype', ['grype', '--version']), ('syft', ['syft', '--version']),
                          ('umoci', ['umoci', '--version']), ('cosign', ['cosign', 'version', '--json']),
                          ('skopeo', ['skopeo', '--version']), ('python3', ['python3', '--version']))},
            'nixVersion': subprocess.check_output(['nix', '--version'], text=True, timeout=30).strip()}


def db_key():
    value = os.environ.get('BENCHMARK_DB_KEY', '')
    suffix = '-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'grype-security-benchmark-v1-Linux-X64-[0-9a-f]{64}' + re.escape(suffix), value):
        raise ValueError('DB cache key is not scoped to this Linux/X64 benchmark attempt')
    return value


def db_directory():
    path = ROOT / '.bluebuild/security-benchmark-db'
    if os.environ.get('GRYPE_DB_CACHE_DIR') != str(path) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('DB transport directory must be the fixed benchmark path without links')
    return path


class TransportRejected(ValueError):
    def __init__(self, reason, observation):
        super().__init__('DB transport rejected: ' + reason)
        self.observation = observation


def transport_metadata(path):
    """Count bytes before hashing; diagnostics remain bounded even on rejection."""
    observation = {'limits': dict(TRANSPORT_LIMITS), 'entriesObserved': 0,
                   'regularFilesObserved': 0, 'bytesObserved': 0, 'complete': True, 'files': {}}
    pending = [path]
    while pending:
        directory = pending.pop()
        if directory.is_symlink():
            observation.update(complete=False, issue='linked-directory')
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if observation['entriesObserved'] >= MAX_DB_METADATA_ENTRIES:
                        observation.update(complete=False, issue='metadata-entry-limit')
                        return observation
                    observation['entriesObserved'] += 1
                    name = str(Path(entry.path).relative_to(path))
                    if len(name) > 512:
                        observation.update(complete=False, issue='oversized-relative-path')
                        continue
                    if entry.is_symlink():
                        observation['issue'] = 'linked-entry'
                    elif entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        observation['regularFilesObserved'] += 1
                        observation['bytesObserved'] += size
                        observation['files'][name] = {'bytes': size}
                    else:
                        observation['issue'] = 'nonregular-entry'
        except OSError:
            observation.update(complete=False, issue='metadata-read-error')
            return observation
    return observation


def transport(path):
    observation = transport_metadata(path)
    if observation.get('issue'):
        raise TransportRejected(observation['issue'], observation)
    if observation['bytesObserved'] > MAX_DB_BYTES:
        raise TransportRejected('byte-limit', observation)
    if observation['regularFilesObserved'] > MAX_DB_FILES:
        raise TransportRejected('file-limit', observation)
    if not observation['regularFilesObserved'] or not observation['bytesObserved']:
        raise TransportRejected('empty-cache', observation)
    # Never read/hash DB contents until the entire metadata census fits the cap.
    try:
        files = {name: {**value, 'sha256': sha(path / name, value['bytes'])}
                 for name, value in sorted(observation['files'].items())}
    except (OSError, ValueError) as error:
        observation.update(complete=False, issue='file-changed-during-hash')
        raise TransportRejected(observation['issue'], observation) from error
    return {'bytes': observation['bytesObserved'], 'files': files, 'limits': dict(TRANSPORT_LIMITS)}


def database_status():
    value = json.loads(subprocess.check_output(['grype', 'db', 'status', '-o', 'json'], text=True, timeout=60))
    schema = value.get('schemaVersion')
    if (value.get('valid') is not True or not isinstance(value.get('built'), str)
            or not ((type(schema) is int and schema > 0)
                    or (isinstance(schema, str) and re.fullmatch(r'v?[1-9][0-9]*(?:\.[0-9]+){0,3}', schema)))):
        raise ValueError('Grype did not provide a valid built/schema DB receipt')
    return {key: value[key] for key in ('schemaVersion', 'built', 'valid')}


def seed(image, profile, origin, output):
    record = {'schema': 1, 'kind': 'db-seed', 'status': 'error',
              'transportLimits': dict(TRANSPORT_LIMITS), 'releaseEligibilityEstablished': False}
    try:
        record.update(context())
        record['binding'] = authenticate(image, profile, origin)
        record['cacheKey'] = db_key()
        directory = db_directory()
        if directory.exists():
            raise ValueError('DB seed must start cold on its independent runner')
        before = time.monotonic()
        subprocess.run(['grype', 'db', 'update'], check=True, timeout=900)
        record['database'] = database_status()
        record['updateSeconds'] = time.monotonic() - before
        record['transport'] = transport(directory)
        record['status'] = 'success'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        record['error'] = str(error)
        if isinstance(error, TransportRejected):
            record['transportObservation'] = error.observation
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2) + '\n')
    # No key is exported on failure, so rejected bytes cannot reach cache save.
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write('cache_key=' + record['cacheKey'] + '\n')


def scan(lane, repetition, image, profile, origin, start, seed_path, output):
    if lane not in LANES or type(repetition) is not int or repetition not in (1, 2, 3):
        raise ValueError('Unsupported security benchmark lane/repetition')
    info = context()
    report = {'schema': 1, 'kind': 'reader', 'lane': lane, 'repetition': repetition, **info,
              'startedAt': datetime.now(timezone.utc).isoformat(), 'status': 'error',
              'transportLimits': dict(TRANSPORT_LIMITS),
              'releaseEligibilityEstablished': False}
    before = time.monotonic()
    setup = before - read(start, 4096)['monotonicSeconds']
    try:
        report['binding'] = authenticate(image, profile, origin)
        directory = db_directory()
        if lane == 'db-only':
            source = read(seed_path)
            if (source.get('status') != 'success' or source.get('kind') != 'db-seed'
                    or source.get('transportLimits') != TRANSPORT_LIMITS
                    or source.get('cacheKey') != db_key() or os.environ.get('RESTORED_DB_KEY') != db_key()
                    or any(source.get(key) != info[key] for key in ('revision', 'runId', 'attempt', 'lockSha256',
                                                                  'policySha256', 'platform', 'tools', 'nixVersion'))
                    or source.get('binding') != report['binding']):
                raise ValueError('DB-only reader lacks the exact successful seed/cache binding')
            report['restoredCacheKey'] = db_key()
            report['restoredTransport'] = transport(directory)
            if report['restoredTransport'] != source['transport']:
                raise ValueError('Restored DB transport bytes differ from the successful seed')
            report['databaseBefore'] = database_status()
            if report['databaseBefore'] != source['database']:
                raise ValueError('Restored DB schema/status differs from the seed')
        elif directory.exists():
            raise ValueError('Baseline/inventory-only must have no transported database')
        evidence = ROOT / '.bluebuild/security-benchmark-scan'
        child = dict(os.environ, FINITE_REUSE_INVENTORY=str(lane == 'inventory-only').lower(),
                     FINITE_GRYPE_DB_CACHE=str(lane == 'db-only').lower(), FINITE_INVENTORY_ORIGIN_RUN=origin)
        status = subprocess.run(['bash', 'scripts/bluebuild/security-run.sh', image, str(evidence)],
                                cwd=ROOT, env=child, check=False, timeout=3600).returncode
        report['scanExitCode'] = status
        timings = read(evidence / 'phase-timings.json')
        result = read(evidence / 'security-result.json')
        provenance = read(evidence / 'inventory-provenance.json')
        if (status != 0 or result.get('status') != 'pass' or result.get('image') != image
                or result.get('policySha256') != info['policySha256']
                or timings.get('inventoryReused') is not (lane == 'inventory-only')
                or provenance.get('image') != image
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', provenance.get('platformDigest', ''))):
            raise ValueError('Fresh scan failed, reused the wrong lane, or changed its image/policy')
        phases = timings['phases']
        for phase in ('database-update', 'database-coverage', 'vulnerability-scan', 'policy-evaluation'):
            selected = [p for p in phases if p.get('phase') == phase]
            if len(selected) != 1 or selected[0].get('success') is not True:
                raise ValueError('Benchmark lacks a successful fresh ' + phase)
        if lane == 'inventory-only':
            inherited = read(evidence / 'inventory-origin.json')
            if inherited.get('originRun') != int(origin) or inherited.get('image') != image:
                raise ValueError('Inventory-only scan did not reuse the explicit authenticated origin')
        database = database_status()
        described = result['database']['status']
        if (described.get('valid') is not True or described.get('built') != database['built']
                or not re.search(r'\b(?:v)?' + re.escape(result['scanner']) + r'(?![0-9A-Za-z.-])', info['tools']['grype'])):
            raise ValueError('Fresh findings differ from the final DB or pinned Grype version')
        report.update(status='success', inventoryReused=timings['inventoryReused'], phases=phases,
                      inventoryGeneration=provenance['generation'], platformDigest=provenance['platformDigest'],
                      scannedAt=result['scannedAt'], scanner=result['scanner'], database=database,
                      databaseSnapshot=result['database'], scanSeconds=time.monotonic() - before,
                      setupSeconds=setup, setupPlusScanSeconds=setup + time.monotonic() - before)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        if isinstance(error, TransportRejected):
            report['transportObservation'] = error.observation
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Benchmark timestamp has no timezone')
    return result


def whole_job_seconds(job, measured, limit):
    seconds = (stamp(job['completed_at']) - stamp(job['started_at'])).total_seconds()
    if (type(measured) not in (int, float) or not math.isfinite(measured) or measured < 0
            or not 0 < seconds <= limit or seconds + 2 < measured):
        raise ValueError('Complete job duration does not cover its bounded measurement')
    return seconds


def summarize(reports, metadata, repetitions, output):
    run = read(metadata)
    if (run['head_sha'] != os.environ['GITHUB_SHA'] or run['id'] != int(os.environ['GITHUB_RUN_ID'])
            or type(run.get('run_attempt')) is not int
            or run['run_attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT'])):
        raise ValueError('Job metadata identifies another benchmark source/run/attempt')
    if type(repetitions) is not int or repetitions not in (1, 3):
        raise ValueError('Benchmark repetitions must be a canonical one or three')
    records = [read(p) for p in reports.rglob('benchmark.json')]
    readers = [r for r in records if r.get('kind') == 'reader']
    seeds = [r for r in records if r.get('kind') == 'db-seed']
    if any(type(r.get('repetition')) is not int for r in readers):
        raise ValueError('Reader repetition must be a canonical integer')
    expected = {(lane, rep) for lane in LANES for rep in range(1, repetitions + 1)}
    if (len(seeds) != 1 or seeds[0].get('status') != 'success' or len(readers) != len(expected)
            or {(r['lane'], r['repetition']) for r in readers} != expected
            or any(r.get('status') != 'success' for r in readers)):
        raise ValueError('Require every independent lane/repetition and its successful DB seed')
    if any(r.get('transportLimits') != TRANSPORT_LIMITS for r in (*readers, *seeds)):
        raise ValueError('Reader/seed transport cap differs from the current bounded pilot')
    if any(r.get('revision') != run['head_sha'] or str(r.get('runId')) != str(run['id'])
           or str(r.get('attempt')) != str(run['run_attempt']) for r in (*readers, *seeds)):
        raise ValueError('Reader/seed receipts identify a different run/source/attempt')
    matched = ('revision', 'runId', 'attempt', 'lockSha256', 'policySha256', 'platform', 'tools', 'nixVersion',
               'binding', 'inventoryGeneration', 'platformDigest', 'scanner')
    if any(any(r[key] != readers[0][key] for key in matched) for r in readers):
        raise ValueError('Security readers differ in source, image, policy, inventory generation or tools')
    if any(seeds[0].get(key) != readers[0][key] for key in ('revision', 'runId', 'attempt', 'lockSha256',
                                                         'policySha256', 'platform', 'tools', 'nixVersion', 'binding')):
        raise ValueError('Seed is not associated with the same image, policy and scanner tools')
    if len({json.dumps(r['database'], sort_keys=True) for r in readers}) != 1:
        raise ValueError('Fresh database built/schema changed between lanes; repeat for matched comparison')
    if len({json.dumps(r['databaseSnapshot'], sort_keys=True) for r in readers}) != 1:
        raise ValueError('Fresh database/provider snapshot changed between lanes')
    rows = []
    for r in readers:
        name = f'Scan ({r["lane"]}, {r["repetition"]})'
        jobs = [j for j in run['jobs'] if j['name'] == name]
        if len(jobs) != 1 or jobs[0].get('status') != 'completed' or jobs[0]['conclusion'] != 'success':
            raise ValueError('Reader report lacks its exact successful independent job')
        job = jobs[0]
        rows.append({**r, 'jobId': job['id'],
                     'wholeJobSeconds': whole_job_seconds(job, r['setupPlusScanSeconds'], 80 * 60)})
    seed_jobs = [j for j in run['jobs'] if j['name'] == 'Seed Grype DB transport']
    if len(seed_jobs) != 1 or seed_jobs[0].get('status') != 'completed' or seed_jobs[0]['conclusion'] != 'success':
        raise ValueError('DB seed job did not finish successfully, including cache save')
    seed_job = seed_jobs[0]
    seed_cost = whole_job_seconds(seed_job, seeds[0]['updateSeconds'], 25 * 60)
    summary = {'schema': 1, 'status': 'matched-pilot-observations', 'repetitions': repetitions,
               'releaseEligibilityEstablished': False, 'readers': rows, 'seed': seeds[0],
               'seedWholeJobSeconds': seed_cost, 'lanes': [],
               'limits': ['One repetition is diagnostic only; do not adopt defaults from one sample.',
                          'DB-only savings exclude separately reported seed cost; inventory and DB effects are separate.',
                          'Fresh DB update and current policy run in every reader; this benchmark grants no publication clearance.',
                          'Whole jobs include setup/restore/post-job costs and exclude queue wait; runner image drift remains visible.']}
    for lane in LANES:
        group = [r for r in rows if r['lane'] == lane]
        summary['lanes'].append({'lane': lane, 'samples': len(group),
            'wholeJobMedianSeconds': statistics.median(r['wholeJobSeconds'] for r in group),
            'setupPlusScanMedianSeconds': statistics.median(r['setupPlusScanSeconds'] for r in group),
            'runnerImageVersions': sorted({str(r['runner'].get('ImageVersion')) for r in group})})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'status': summary['status'], 'repetitions': repetitions,
                      'lanes': summary['lanes'], 'seedWholeJobSeconds': seed_cost}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    mark = sub.add_parser('mark-start'); mark.add_argument('output', type=Path)
    for name in ('seed', 'scan'):
        command = sub.add_parser(name)
        for field in ('image', 'profile', 'origin'):
            command.add_argument('--' + field, required=True)
        command.add_argument('--output', required=True, type=Path)
        if name == 'scan':
            command.add_argument('--lane', required=True, choices=LANES)
            command.add_argument('--repetition', type=int, choices=(1, 2, 3), required=True)
            command.add_argument('--start', type=Path, required=True)
            command.add_argument('--seed', type=Path, required=True)
    summary = sub.add_parser('summarize')
    summary.add_argument('--reports', type=Path, required=True)
    summary.add_argument('--metadata', type=Path, required=True)
    summary.add_argument('--repetitions', type=int, choices=(1, 3), required=True)
    summary.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    hosted()
    if args.operation == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'monotonicSeconds': time.monotonic()}) + '\n')
    elif args.operation == 'seed': seed(args.image, args.profile, args.origin, args.output)
    elif args.operation == 'scan': scan(args.lane, args.repetition, args.image, args.profile, args.origin, args.start, args.seed, args.output)
    else: summarize(args.reports, args.metadata, args.repetitions, args.output)


if __name__ == '__main__':
    main()
