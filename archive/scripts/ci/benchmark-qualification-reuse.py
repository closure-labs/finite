#!/usr/bin/env python3
"""Hosted receipt-restore experiment; never grants publication clearance."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import statistics
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REPO = 'closure-labs/finite'
REPO_ID = 1293375784
ARCHIVE = 8 * 1024**2
META = 4 * 1024**2
PROFILES = ('finite', 'finite-dev')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


REUSE = module('benchmark_production_reuse', ROOT / 'scripts/bluebuild/reuse-qualification.py')
PREFLIGHT = module('benchmark_production_preflight', ROOT / 'scripts/bluebuild/qualification-preflight.py')
# A stricter transport budget narrows this diagnostic; eligibility predicates
# and production source files remain unchanged.
REUSE.ARCHIVE_LIMIT = ARCHIVE


def positive(value): return type(value) is int and value > 0
def matches(value, pattern): return isinstance(value, str) and re.fullmatch(pattern, value) is not None
def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
def timestamp(value):
    if not matches(value, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'): raise ValueError('Missing complete job timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class API:
    def __init__(self): self.calls, self.bytes, self.retries = 0, 0, []
    def read(self, path, paginated=False):
        patterns = (r'actions/runs/[1-9][0-9]*(?:/artifacts\?per_page=100|/attempts/[1-9][0-9]*/jobs\?per_page=100)?',
            r'actions/workflows/build\.yml/runs\?branch=main&status=success&per_page=100&page=[1-3]')
        if not any(re.fullmatch(pattern, path) for pattern in patterns): raise ValueError('Unapproved metadata endpoint')
        self.calls += 1
        if self.calls > 128: raise ValueError('Diagnostic metadata request budget exhausted')
        with tempfile.TemporaryFile() as stream:
            get_with_retries(['gh', 'api', *(['--paginate', '--slurp'] if paginated else []), 'repos/' + REPO + '/' + path],
                events=self.retries, stdout=stream, check=True, timeout=150,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (META, META)))
            size = stream.tell(); self.bytes += size
            if not 0 < size <= META or self.bytes > 32 * 1024**2: raise ValueError('Diagnostic metadata byte budget exhausted')
            stream.seek(0); return json.load(stream)


def get_with_retries(command, *, events, **kwargs):
    if command[:2] != ['gh', 'api'] or any(arg in command for arg in ('--method', '-X', '-f', '-F')):
        raise ValueError('Retries are restricted to read-only GitHub GETs')
    stdout = kwargs['stdout']; kwargs.pop('check', None)
    for attempt in range(1, 4):
        stdout.seek(0); stdout.truncate()
        with tempfile.TemporaryFile() as errors:
            result = subprocess.run(command, **dict(kwargs, stderr=errors, check=False))
            if result.returncode == 0: return result
            errors.seek(0); error = errors.read(META + 1)
        retryable = any(marker in error for marker in (b'HTTP 502', b'HTTP 503', b'HTTP 504', b'HTTP 429'))
        events.append({'attempt': attempt, 'exitCode': result.returncode, 'retryable': retryable})
        if not retryable or attempt == 3: raise subprocess.CalledProcessError(result.returncode, command)
        time.sleep(attempt * 2)


def flatten(pages, key):
    if not isinstance(pages, list) or not 0 < len(pages) <= 10: raise ValueError('Invalid metadata pagination')
    result = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get(key), list) or len(page[key]) > 100:
            raise ValueError('Invalid metadata page')
        result += page[key]
    return result


def origin_run(run, number, revision):
    if (not positive(number) or run.get('id') != number or not positive(run.get('run_attempt'))
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or run.get('head_sha') != revision or run.get('head_branch') != 'main'
            or run.get('path') != '.github/workflows/build.yml' or run.get('event') not in ('push', 'workflow_dispatch', 'schedule')
            or any(run.get(key, {}).get('full_name') != REPO or run[key].get('id') != REPO_ID for key in ('repository', 'head_repository'))):
        raise ValueError('Origin is not a successful exact-source same-repository main build')


def job_receipt(jobs, name, run, *, success=True, maximum=10800):
    selected = [job for job in jobs if job.get('name') == name]
    if len(selected) != 1: raise ValueError('Missing or ambiguous job: ' + name)
    job = selected[0]
    if (not positive(job.get('id')) or job.get('status') != 'completed'
            or (success and job.get('conclusion') != 'success') or job.get('run_id') != run['id']
            or job.get('run_attempt') != run['run_attempt'] or job.get('head_sha') != run['head_sha']):
        raise ValueError('Job does not identify the completed selected run/attempt/source')
    seconds = (timestamp(job.get('completed_at')) - timestamp(job.get('started_at'))).total_seconds()
    if not 0 < seconds <= maximum: raise ValueError('Invalid complete job duration')
    return {key: job[key] for key in ('id', 'name', 'run_id', 'run_attempt', 'head_sha', 'conclusion', 'started_at', 'completed_at')} | {'seconds': seconds}


def baseline(api, args):
    run = api.read('actions/runs/' + str(args.origin_run)); origin_run(run, args.origin_run, args.source)
    jobs = flatten(api.read(f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', True), 'jobs')
    prefix = f'Publish ({args.profile}) / qualification / '
    receipts = {key: job_receipt(jobs, prefix + name, run, maximum=900 if key in ('prepare', 'aggregate') else 10800)
        for key, name in (('prepare', 'prepare'), ('fresh', 'phase (fresh)'), ('upgrade', 'phase (upgrade)'), ('aggregate', 'aggregate'))}
    if any(timestamp(receipts[key]['started_at']) < timestamp(receipts['prepare']['completed_at']) for key in ('fresh', 'upgrade')):
        raise ValueError('Original qualification phase sequencing is inconsistent')
    if timestamp(receipts['aggregate']['started_at']) < max(timestamp(receipts[key]['completed_at']) for key in ('fresh', 'upgrade')):
        raise ValueError('Original aggregation preceded a required qualification phase')
    entries = flatten(api.read(f'actions/runs/{run["id"]}/artifacts?per_page=100', True), 'artifacts')
    artifact = artifact_metadata(entries, f'qualification-{args.profile}-{run["id"]}-{run["run_attempt"]}', run)
    REUSE.metadata(run, jobs, artifact, args.profile)
    return {'run': run['id'], 'attempt': run['run_attempt'], 'revision': run['head_sha'], 'jobs': receipts,
        'artifact': artifact, 'runnerImages': 'Original runner image not inferred from job labels; see original hosted logs.',
        'summedRunnerSeconds': sum(job['seconds'] for job in receipts.values()),
        'criticalPathServiceSeconds': receipts['prepare']['seconds'] + max(receipts[key]['seconds'] for key in ('fresh', 'upgrade')) + receipts['aggregate']['seconds'],
        'elapsedIncludingQueueSeconds': (timestamp(receipts['aggregate']['completed_at']) - timestamp(receipts['prepare']['started_at'])).total_seconds()}


def artifact_metadata(entries, name, run):
    selected = [item for item in entries if item.get('name') == name]
    if len(selected) != 1: raise ValueError('Missing or ambiguous exact-attempt diagnostic artifact')
    value = selected[0]; binding = value.get('workflow_run', {})
    if (not positive(value.get('id')) or value.get('expired') is not False
            or type(value.get('size_in_bytes')) is not int or not 0 < value['size_in_bytes'] <= ARCHIVE
            or not matches(value.get('digest'), r'sha256:[0-9a-f]{64}')
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha'] or binding.get('head_branch') != 'main'
            or binding.get('repository_id') != REPO_ID or binding.get('head_repository_id') != REPO_ID
            or timestamp(value.get('expires_at')) <= datetime.now(timezone.utc)):
        raise ValueError('Artifact lacks immutable bounded same-repository/run/source provenance')
    return {key: value[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run', 'expires_at', 'expired')}


def hosted(args):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') != 'refs/heads/main' or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_WORKFLOW_REF') != REPO + '/.github/workflows/benchmark-vm-reuse.yml@refs/heads/main'
            or not matches(os.environ.get('GITHUB_SHA'), r'[0-9a-f]{40}') or os.environ.get('FINITE_VALIDATION_ONLY') == 'true'):
        raise ValueError('Run only in the manual hosted main diagnostic workflow')
    if (args.profile not in PROFILES or not positive(args.origin_run) or args.repetition not in (1, 2, 3)
            or not matches(args.source, r'[0-9a-f]{40}') or not matches(args.identity, r'v1:[0-9a-f]{64}')
            or not matches(args.candidate, r'sha256:[0-9a-f]{64}') or not matches(args.previous, r'sha256:[0-9a-f]{64}')):
        raise ValueError('Require exact candidate/predecessor/source/build identities')


def stage(report, name, operation):
    before = time.monotonic(); success = False
    try:
        result = operation(); success = True; return result
    finally: report['stages'].append({'stage': name, 'success': success, 'seconds': round(time.monotonic() - before, 3)})


def handoff_name(args):
    return f'qualification-benchmark-handoff-{args.profile}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}-{args.repetition}'


def execute(args):
    hosted(args)
    api = API(); REUSE.github = api.read
    REUSE.subprocess = SimpleNamespace(run=lambda command, **kwargs: get_with_retries(command, events=api.retries, **kwargs))
    report = {'schema': 1, 'experiment': 'whole-qualification-reuse-diagnostic', 'diagnostic': True,
        'publicationClearance': False, 'operation': args.operation, 'repetition': args.repetition, 'profile': args.profile,
        'run': int(os.environ['GITHUB_RUN_ID']), 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'revision': os.environ['GITHUB_SHA'], 'candidate': args.candidate, 'previous': args.previous,
        'sourceRevision': args.source, 'buildIdentity': args.identity, 'stages': [],
        'runnerImage': os.environ.get('ImageVersion'),
        'productionReuseSourceSha256': digest(ROOT / 'scripts/bluebuild/reuse-qualification.py'),
        'contextSourceSha256': digest(ROOT / 'scripts/bluebuild/qualification-context.py'),
        'lockSha256': digest(ROOT / 'flake.lock'), 'archiveBudgetBytes': ARCHIVE}
    args.output.mkdir(parents=True, exist_ok=False)
    directory = args.output / 'receipts'; directory.mkdir()
    try:
        stage(report, 'production-current-preflight', lambda: PREFLIGHT.require_eligible(os.environ['GITHUB_SHA']))
        report['baseline'] = stage(report, 'authenticate-original-qualification', lambda: baseline(api, args))
        if args.operation == 'restore':
            context = stage(report, 'actual-runner-context', REUSE.qualification.context)
            Path('.bluebuild').mkdir(exist_ok=True)
            Path('.bluebuild/qualification-context.json').write_text(json.dumps(context))
            os.environ.update(CANDIDATE_DIGEST=args.candidate, PREVIOUS_DIGEST=args.previous,
                SOURCE_REVISION=args.source, BUILD_IDENTITY=args.identity)
            output = args.output / 'restored'
            origin = stage(report, 'production-reuse-resolver', lambda: REUSE.reuse(args.profile, output))
            expected = report['baseline']
            if (origin['run'] != expected['run'] or origin['attempt'] != expected['attempt']
                    or origin['artifactId'] != expected['artifact']['id'] or origin['artifactSha256'] != expected['artifact']['digest']
                    or origin['qualificationRevision'] != expected['revision']):
                raise ValueError('Production resolver selected another qualification origin')
            report['origin'] = origin
            for path in output.iterdir():
                if path.name not in (args.profile + '-acceptance.json', args.profile + '-desktop-acceptance.json'):
                    raise ValueError('Unexpected production reuse output')
                path.rename(directory / path.name)
            output.rmdir()
            report['qualificationContextSha256'] = REUSE.qualification.identity(context)
        else:
            run = api.read('actions/runs/' + os.environ['GITHUB_RUN_ID'])
            if (run.get('path') != '.github/workflows/benchmark-vm-reuse.yml' or run.get('head_branch') != 'main'
                    or run.get('head_sha') != os.environ['GITHUB_SHA'] or run.get('run_attempt') != report['attempt']
                    or any(run.get(key, {}).get('full_name') != REPO for key in ('repository', 'head_repository'))):
                raise ValueError('Handoff consumer does not identify this exact workflow/source/attempt')
            jobs = flatten(api.read(f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', True), 'jobs')
            report['restoreJob'] = job_receipt(jobs, f'restore-{args.repetition}', run, maximum=1800)
            entries = flatten(api.read(f'actions/runs/{run["id"]}/artifacts?per_page=100', True), 'artifacts')
            artifact = artifact_metadata(entries, handoff_name(args), run)
            with tempfile.TemporaryFile() as archive:
                stage(report, 'handoff-download', lambda: get_with_retries(['gh', 'api', f'repos/{REPO}/actions/artifacts/{artifact["id"]}/zip'], events=api.retries,
                    stdout=archive, check=True, timeout=180, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (ARCHIVE, ARCHIVE))))
                stage(report, 'authenticate-handoff', lambda: REUSE.extract(archive, artifact, directory, args.profile))
                archive.seek(0)
                with zipfile.ZipFile(archive) as zipped:
                    if set(zipped.namelist()) != {args.profile + '-acceptance.json', args.profile + '-desktop-acceptance.json', 'benchmark.json'}:
                        raise ValueError('Diagnostic handoff has unexpected contents')
                    info = zipped.getinfo('benchmark.json')
                    if (not 0 < info.file_size <= META or info.flag_bits & 1
                            or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
                        raise ValueError('Unsafe or oversized handoff sample receipt')
                    producer = json.loads(zipped.read(info))
                if (producer.get('status') != 'success' or producer.get('operation') != 'restore'
                        or any(producer.get(key) != report[key] for key in ('run', 'attempt', 'revision', 'profile', 'repetition',
                            'candidate', 'previous', 'sourceRevision', 'buildIdentity'))
                        or producer.get('receiptSha256') != {path.name: digest(path) for path in directory.iterdir()}):
                    raise ValueError('Handoff sample identity or acceptance bytes changed')
            report['handoffArtifact'] = artifact
        acceptance_path = directory / (args.profile + '-acceptance.json')
        acceptance = json.loads(REUSE.qualification.desktop.read(acceptance_path))
        if (acceptance.get('candidate') != 'ghcr.io/closure-labs/finite@' + args.candidate
                or acceptance.get('previousDigest') != args.previous or acceptance.get('sourceRevision') != args.source
                or acceptance.get('buildIdentity') != args.identity or acceptance.get('profile') != args.profile
                or acceptance.get('revision') != report['revision'] or acceptance.get('bootstrap') is not False
                or any(acceptance.get(key) is not True for key in ('accepted', 'secureBoot', 'encryptedRoot'))):
            raise ValueError('Restored acceptance differs from the explicit immutable qualification tuple')
        origin = acceptance.get('qualificationReuse', {})
        expected = report['baseline']
        if (origin.get('run') != expected['run'] or origin.get('attempt') != expected['attempt']
                or origin.get('artifactId') != expected['artifact']['id'] or origin.get('artifactSha256') != expected['artifact']['digest']
                or origin.get('job') != expected['jobs']['aggregate']['id'] or origin.get('qualificationRevision') != expected['revision']
                or acceptance.get('qualifiedIsoOrigin') != {'run': expected['run'], 'attempt': expected['attempt'], 'revision': expected['revision']}):
            raise ValueError('Reused acceptance changed its authenticated original origin')
        stage(report, 'production-revalidation', lambda: REUSE.verify_reused_acceptance(acceptance))
        stage(report, 'desktop-hash-and-phase-verification', lambda: REUSE.qualification.desktop.verify(directory, acceptance))
        report.update(status='success', qualifiedAt=acceptance['qualifiedAt'],
            qualificationContextSha256=acceptance['qualificationContextSha256'], origin=origin,
            receiptSha256={path.name: digest(path) for path in directory.iterdir()})
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report.update(status='error', error=str(error)); raise
    finally:
        report.update(metadataCalls=api.calls, metadataBytes=api.bytes, transportRetries=api.retries)
        (args.output / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')


def summarize(args):
    api = API()
    run = api.read('actions/runs/' + os.environ['GITHUB_RUN_ID'])
    if (run.get('head_sha') != os.environ['GITHUB_SHA'] or run.get('run_attempt') != int(os.environ['GITHUB_RUN_ATTEMPT'])
            or run.get('path') != '.github/workflows/benchmark-vm-reuse.yml' or run.get('head_branch') != 'main'):
        raise ValueError('Summary run/source/attempt mismatch')
    jobs = flatten(api.read(f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', True), 'jobs')
    reports = [json.loads(path.read_text()) for path in args.directory.rglob('benchmark.json')]
    expected = {(operation, number) for operation in ('restore', 'aggregate') for number in (1, 2, 3)}
    if len(reports) != 6 or {(r.get('operation'), r.get('repetition')) for r in reports} != expected:
        raise ValueError('Require all three independent restore/aggregate sample pairs')
    associated = ('profile', 'run', 'attempt', 'revision', 'candidate', 'previous', 'sourceRevision', 'buildIdentity',
                  'baseline', 'productionReuseSourceSha256', 'contextSourceSha256', 'lockSha256', 'qualificationContextSha256')
    if any(r.get('status') != 'success' or r.get('publicationClearance') is not False for r in reports):
        raise ValueError('Failed or incomplete diagnostics cannot establish qualification reuse savings')
    if any(r.get('run') != run['id'] or r.get('attempt') != run['run_attempt'] or r.get('revision') != run['head_sha'] for r in reports):
        raise ValueError('Measurement reports belong to another run/attempt/revision')
    if len({canonical({key: r[key] for key in associated}) for r in reports}) != 1:
        raise ValueError('Diagnostic pairs do not bind identical candidate, origin, context and tools')
    pairs = []
    for repetition in (1, 2, 3):
        first, second = [next(r for r in reports if r['operation'] == operation and r['repetition'] == repetition) for operation in ('restore', 'aggregate')]
        if first['receiptSha256'] != second['receiptSha256']: raise ValueError('Handoff acceptance bytes changed')
        restore = job_receipt(jobs, f'restore-{repetition}', run, maximum=1800)
        aggregate = job_receipt(jobs, f'aggregate-{repetition}', run, maximum=1800)
        if timestamp(aggregate['started_at']) < timestamp(restore['completed_at']): raise ValueError('Aggregate preceded its restore')
        pairs.append({'repetition': repetition, 'jobs': [restore, aggregate],
            'summedRunnerSeconds': restore['seconds'] + aggregate['seconds'],
            'criticalPathServiceSeconds': restore['seconds'] + aggregate['seconds'],
            'elapsedIncludingQueueSeconds': (timestamp(aggregate['completed_at']) - timestamp(restore['started_at'])).total_seconds()})
    baseline_receipt = reports[0]['baseline']
    summary = {'schema': 1, 'experiment': 'whole-qualification-reuse-diagnostic', 'diagnostic': True,
        'publicationClearance': False, 'adoptionRecommended': False, 'origin': reports[0]['origin'],
        'baseline': baseline_receipt, 'samples': pairs, 'reports': reports,
        'medianSummedRunnerSeconds': statistics.median(pair['summedRunnerSeconds'] for pair in pairs),
        'medianCriticalPathServiceSeconds': statistics.median(pair['criticalPathServiceSeconds'] for pair in pairs),
        'limitations': ['One historical exact-candidate baseline versus three fresh hosted restore/aggregate pairs; observational, not a repeated fresh-VM benchmark.',
            'Complete job durations include setup, receipt transport, uploads and post-job handling; queue-inclusive elapsed is separate.',
            'Matrix barriers can add scheduling wait; service critical paths exclude queue wait. Runner image versions and actual context hashes constrain comparisons.',
            'Additional diagnostic origin-metadata audits and receipt rechecks are retained in measured costs; they are not subtracted to predict a faster production path.',
            'No new ISO, VM qualification, image promotion or fresh security scan was performed. Fresh security remains mandatory outside qualification reuse.',
            'Diagnostic artifacts are not publication clearance and defaults are unchanged.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(f"Whole qualification reuse diagnostic: original runner time {baseline_receipt['summedRunnerSeconds']:.0f}s; three-pair median {summary['medianSummedRunnerSeconds']:.0f}s. Observational only; no adoption recommendation.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for operation in ('restore', 'aggregate'):
        command = sub.add_parser(operation)
        command.add_argument('--profile', choices=PROFILES, required=True)
        command.add_argument('--origin-run', type=int, required=True)
        command.add_argument('--repetition', type=int, required=True)
        for field in ('candidate', 'previous', 'identity', 'source'): command.add_argument('--' + field, required=True)
        command.add_argument('--output', type=Path, required=True)
    summary = sub.add_parser('summarize'); summary.add_argument('directory', type=Path); summary.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.operation == 'summarize':
        try: summarize(args)
        except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError) as error:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({'schema': 1, 'status': 'error', 'diagnostic': True,
                'adoptionRecommended': False, 'publicationClearance': False, 'error': str(error)}) + '\n')
            raise
    else: execute(args)


if __name__ == '__main__': main()
