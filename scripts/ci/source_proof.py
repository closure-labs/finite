"""Bounded source-only queue evidence; never grants publication authority."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

from archive_read import authenticate, members, chunks
from github_api import get_json
from nix_observation import identity

REPOSITORY = 'closure-labs/finite'
WORKFLOW = '.github/workflows/build.yml'
DERIVATION = re.compile(r'/nix/store/[a-z0-9]{32}-finite-ci-checks\.drv')
QUEUE = re.compile(r'gh-readonly-queue/main/pr-[1-9][0-9]*-[a-f0-9]{7,40}')
LIMIT = 2 * 1024 * 1024
DEADLINE = 15
SETTINGS = ('system', 'sandbox', 'experimental-features', 'max-jobs', 'cores', 'eval-cores',
            'pure-eval', 'restrict-eval', 'substituters', 'trusted-public-keys')
REASONS = {'disabled', 'no-exact-queue-proof', 'configuration-mismatch', 'lookup-timeout',
           'lookup-unavailable', 'invalid-lookup-result', 'oversized-lookup-result', 'verified-exact-queue-proof'}


def eligibility_reason(eligible, reason):
    if not isinstance(reason, str):
        return False
    if eligible is True:
        return reason == 'verified-exact-queue-proof'
    if eligible is False:
        return reason in ('no-exact-queue-proof', 'configuration-mismatch')
    return eligible is None and reason in REASONS - {
        'verified-exact-queue-proof', 'no-exact-queue-proof', 'configuration-mismatch'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate source proof JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite source proof JSON')))


def configuration(env=os.environ):
    # Never persist or print the full config: it can contain access tokens.
    version = subprocess.check_output(['nix', '--version'], stderr=subprocess.DEVNULL,
                                      text=True, timeout=5).strip()
    if 'Determinate' not in version or len(version) > 200:
        raise ValueError('Unknown source Nix tool')
    with tempfile.TemporaryFile() as output:
        subprocess.run(['nix', 'config', 'show', '--json'], stdout=output, stderr=subprocess.DEVNULL,
                       check=True, timeout=5)
        output.seek(0)
        raw = output.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Oversized Nix config')
        settings = decode(raw)
    spec = importlib.util.spec_from_file_location('source_ci_options', Path(__file__).with_name('ci-options.py'))
    options = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(options)
    public = options.options(env)
    public.pop('FINITE_SOURCE_PROOF_REUSE', None)
    cohort = identity(env)['toolCohort']
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL,
                                       text=True, timeout=5).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                    stderr=subprocess.DEVNULL, text=True, timeout=5)
    if checkout != env.get('GITHUB_SHA') or not re.fullmatch('[a-f0-9]{40}', checkout) or dirty:
        raise ValueError('Source proof requires the exact clean checkout')
    if set(cohort['lockSha256']) != {'flake.lock', 'devenv.lock'} or not cohort['nixExecutable']:
        raise ValueError('Unknown source inputs')
    selected = {}
    for key in SETTINGS:
        if key not in settings or not isinstance(settings[key], dict) or 'value' not in settings[key]:
            raise ValueError('Unknown selected Nix setting')
        selected[key] = digest(settings[key]['value'])
    cohort = {**cohort, 'sourceRevision': checkout, 'nixVersion': version, 'pythonVersion': sys.version.split()[0],
              'settingsSha256': selected, 'publicOptionsSha256': digest(public),
              'platform': {'os': env.get('RUNNER_OS'), 'arch': env.get('RUNNER_ARCH'), 'label': 'ubuntu-24.04'}}
    if cohort['platform']['os'] != 'Linux' or cohort['platform']['arch'] != 'X64':
        raise ValueError('Unsupported source platform')
    return {'schema': 1, 'fingerprint': digest(cohort), 'cohort': cohort}


def valid_configuration(value, head):
    if (not isinstance(value, dict) or set(value) != {'schema', 'fingerprint', 'cohort'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['cohort'], dict)):
        return False
    cohort = value['cohort']
    return (value['fingerprint'] == digest(cohort) and cohort.get('sourceRevision') == head
            and isinstance(cohort.get('nixVersion'), str) and 'Determinate' in cohort['nixVersion']
            and isinstance(cohort.get('pythonVersion'), str) and 0 < len(cohort['pythonVersion']) <= 200
            and isinstance(cohort.get('nixExecutable'), str)
            and re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/]+/bin/nix', cohort['nixExecutable']) is not None
            and isinstance(cohort.get('pythonExecutable'), str) and cohort['pythonExecutable'].startswith('/')
            and isinstance(cohort.get('lockSha256'), dict) and set(cohort['lockSha256']) == {'flake.lock', 'devenv.lock'}
            and isinstance(cohort.get('settingsSha256'), dict) and set(cohort['settingsSha256']) == set(SETTINGS)
            and all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v)
                    for v in [*cohort['lockSha256'].values(), *cohort['settingsSha256'].values(), cohort.get('publicOptionsSha256')])
            and cohort.get('platform') == {'os': 'Linux', 'arch': 'X64', 'label': 'ubuntu-24.04'})


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Source proof timestamp lacks timezone')
    return result


def native(run, head, repository_id, event):
    return (isinstance(run, dict) and run.get('path') == WORKFLOW and run.get('event') == event
            and run.get('head_sha') == head
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('repository', {}).get('id') == repository_id
            and run.get('head_repository', {}).get('full_name') == REPOSITORY
            and run.get('head_repository', {}).get('id') == repository_id)


def verify_receipt(value, run, job, current, now):
    attempt = str(run['run_attempt'])
    expected = {'schema': 1, 'kind': 'finite-nix-observation', 'authorizesPublication': False,
                'repository': REPOSITORY, 'revision': run['head_sha'], 'checkoutRevision': run['head_sha'],
                'runId': str(run['id']), 'runAttempt': attempt, 'jobName': 'checks',
                'workflowRef': REPOSITORY + '/' + WORKFLOW + '@refs/heads/' + run['head_branch']}
    if (not isinstance(value, dict) or type(value.get('schema')) is not int
            or value.get('authorizesPublication') is not False
            or any(value.get(key) != item for key, item in expected.items())
            or not isinstance(value.get('aggregateDerivation'), str)
            or not DERIVATION.fullmatch(value['aggregateDerivation'])):
        raise ValueError('Source receipt differs from native producer')
    proof = value.get('reuseProof')
    if not valid_configuration(proof, run['head_sha']) or not valid_configuration(current, run['head_sha']):
        raise ValueError('Source proof lacks versioned configuration')
    if proof != current:
        return False
    phases = value.get('phases')
    if not isinstance(phases, list) or len(phases) != 2:
        raise ValueError('Missing executed source phases')
    previous_end = timestamp(job['started_at'])
    for phase, name in zip(phases, ('Evaluate aggregate', 'Build aggregate')):
        if (not isinstance(phase, dict) or phase.get('stage') != name or phase.get('outcome') != 'success'
                or type(phase.get('status')) is not int or phase['status'] != 0
                or type(phase.get('seconds')) not in (int, float) or not 0 <= phase['seconds'] <= 86400):
            raise ValueError('Source phases were not successful executions')
        attempts = phase.get('attempts')
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
            raise ValueError('Missing source execution attempts')
        for number, trial in enumerate(attempts, 1):
            if (not isinstance(trial, dict) or type(trial.get('attempt')) is not int or trial['attempt'] != number
                    or type(trial.get('status')) is not int or trial['status'] != (0 if number == len(attempts) else 1)
                    or type(trial.get('seconds')) not in (int, float) or not 0 <= trial['seconds'] <= 86400):
                raise ValueError('Invalid source execution attempt')
        if sum(trial['seconds'] for trial in attempts) > phase['seconds'] + .01:
            raise ValueError('Source attempts exceed their phase')
        started = timestamp(phase['startedAt'])
        finished = started + timedelta(seconds=phase['seconds'])
        if started + timedelta(seconds=1) < previous_end or finished > timestamp(job['completed_at']) + timedelta(seconds=1):
            raise ValueError('Source phases exceed native job interval')
        previous_end = finished
    if (timestamp(run['updated_at']) > now or now - timestamp(run['updated_at']) > timedelta(hours=24)
            or now - timestamp(job['completed_at']) > timedelta(hours=24)
            or timestamp(job['completed_at']) > timestamp(run['updated_at']) + timedelta(seconds=1)):
        raise ValueError('Source proof is future-dated or expired')
    return True


@contextmanager
def archive(artifact):
    with tempfile.TemporaryFile() as output:
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=output, stderr=subprocess.DEVNULL, timeout=10, check=True)
        authenticate(output, artifact)
        yield output


def lookup(env, current, api=get_json, reader=archive, now=None):
    now = now or datetime.now(timezone.utc)
    head, run_id = env['GITHUB_SHA'], int(env['GITHUB_RUN_ID'])
    repository_id = int(env['GITHUB_REPOSITORY_ID'])
    consumer = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    if (not native(consumer, head, repository_id, 'push') or consumer.get('id') != run_id
            or consumer.get('head_branch') != 'main'
            or consumer.get('run_attempt') != int(env['GITHUB_RUN_ATTEMPT'])):
        raise ValueError('Consumer is not the current native main push')
    created = timestamp(consumer['created_at'])
    response = api(f'repos/{REPOSITORY}/actions/workflows/build.yml/runs?event=merge_group&status=success&head_sha={head}&per_page=5')
    runs = response.get('workflow_runs')
    if (not isinstance(runs, list) or len(runs) > 5 or type(response.get('total_count')) is not int
            or response['total_count'] != len(runs)):
        raise ValueError('Incomplete bounded source producer inventory')
    if not runs:
        return {'eligible': False, 'reason': 'no-exact-queue-proof'}
    run = max(runs, key=lambda row: timestamp(row['updated_at']))
    if (not native(run, head, repository_id, 'merge_group') or run.get('status') != 'completed'
            or run.get('conclusion') != 'success' or not QUEUE.fullmatch(run.get('head_branch', ''))
            or type(run.get('id')) is not int or run['id'] < 1
            or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1
            or timestamp(run['updated_at']) > created + timedelta(seconds=1)):
        raise ValueError('Invalid or unfinished native source producer')
    rid, attempt = run['id'], run['run_attempt']
    response = api(f'repos/{REPOSITORY}/actions/runs/{rid}/attempts/{attempt}/jobs?per_page=100')
    jobs = response.get('jobs')
    if (not isinstance(jobs, list) or type(response.get('total_count')) is not int
            or response['total_count'] != len(jobs) or len(jobs) > 100):
        raise ValueError('Incomplete native source job inventory')
    candidates = [j for j in jobs if j.get('name') == 'Nix and runtime contracts']
    if len(candidates) != 1:
        raise ValueError('Missing or ambiguous source job')
    job = candidates[0]
    if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
            or job.get('run_id') != rid or job.get('run_attempt') != attempt or job.get('head_sha') != head
            or type(job.get('id')) is not int or job['id'] < 1 or 'ubuntu-24.04' not in job.get('labels', [])
            or timestamp(job['completed_at']) > created + timedelta(seconds=1)):
        raise ValueError('Source job is failed, reused from another attempt or mismatched')
    response = api(f'repos/{REPOSITORY}/actions/runs/{rid}/artifacts?per_page=100')
    artifacts = response.get('artifacts')
    if (not isinstance(artifacts, list) or type(response.get('total_count')) is not int
            or response['total_count'] != len(artifacts) or len(artifacts) > 100):
        raise ValueError('Incomplete source artifact inventory')
    found = [a for a in artifacts if a.get('name') == f'source-checks-{rid}-{attempt}']
    if len(found) != 1:
        raise ValueError('Source proof archive unavailable')
    artifact = found[0]
    binding = artifact.get('workflow_run', {})
    if (artifact.get('expired') is not False or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= LIMIT or type(artifact.get('id')) is not int or artifact['id'] < 1
            or not isinstance(artifact.get('digest'), str)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', artifact['digest'])
            or binding.get('id') != rid or binding.get('head_sha') != head
            or binding.get('repository_id') != repository_id or binding.get('head_repository_id') != repository_id):
        raise ValueError('Source archive differs from native origin')
    value = None
    with reader(artifact) as raw, zipfile.ZipFile(raw) as zipped:
        for name, entry in members(zipped, max_files=3, max_bytes=3 * 65536):
            if name not in ('nix-checks.json', 'nix-setup.json') or entry.file_size > 65536:
                raise ValueError('Unexpected source archive member')
            if name == 'nix-checks.json':
                value = decode(b''.join(chunks(zipped, entry)))
    if not verify_receipt(value, run, job, current, now):
        return {'eligible': False, 'reason': 'configuration-mismatch'}
    return {'eligible': True, 'reason': 'verified-exact-queue-proof',
            'producer': {'runId': rid, 'runAttempt': attempt, 'jobId': job['id'], 'artifactId': artifact['id'],
                         'artifactDigest': artifact['digest'], 'revision': head,
                         'aggregateDerivation': value['aggregateDerivation']}}


def helper(command, env):
    """One process group bounds metadata, downloads and cleanup to 15 seconds."""
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen([sys.executable, str(Path(__file__).resolve()), command], env=dict(env),
                stdout=output, stderr=subprocess.DEVNULL, start_new_session=True,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))) as process:
            try:
                status = process.wait(timeout=DEADLINE)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                return {'eligible': None, 'reason': 'lookup-timeout'}
        if status:
            return {'eligible': None, 'reason': 'lookup-unavailable'}
        output.seek(0)
        raw = output.read(65537)
        if len(raw) > 65536:
            return {'eligible': None, 'reason': 'oversized-lookup-result'}
        try:
            value = decode(raw)
            if not isinstance(value, dict):
                raise ValueError('Invalid source lookup')
            return value
        except (ValueError, TypeError):
            return {'eligible': None, 'reason': 'invalid-lookup-result'}


def mode(env):
    value = env.get('FINITE_SOURCE_PROOF_REUSE') or 'off'
    if value not in ('off', 'shadow', 'enabled'):
        raise ValueError('Expected off, shadow or enabled for FINITE_SOURCE_PROOF_REUSE')
    return value


def valid_producer(value, head):
    return (isinstance(value, dict) and set(value) == {'runId', 'runAttempt', 'jobId', 'artifactId',
             'artifactDigest', 'revision', 'aggregateDerivation'}
            and all(type(value[key]) is int and value[key] > 0 for key in ('runId', 'runAttempt', 'jobId', 'artifactId'))
            and value['revision'] == head and isinstance(head, str) and re.fullmatch('[a-f0-9]{40}', head) is not None
            and isinstance(value['artifactDigest'], str)
            and re.fullmatch('sha256:[a-f0-9]{64}', value['artifactDigest']) is not None
            and isinstance(value['aggregateDerivation'], str) and DERIVATION.fullmatch(value['aggregateDerivation']) is not None)


def prepare(env):
    selected = mode(env)
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_JOB') != 'checks'
            or env.get('GITHUB_REPOSITORY') != REPOSITORY):
        return None, None
    if env.get('GITHUB_EVENT_NAME') == 'merge_group':
        try:
            value = helper('--configuration', env).get('configuration')
            return (value if valid_configuration(value, env.get('GITHUB_SHA')) else None), None
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return None, None
    if env.get('GITHUB_EVENT_NAME') != 'push' or env.get('GITHUB_REF') != 'refs/heads/main':
        return None, None
    record = {**identity(env), 'kind': 'finite-source-reuse', 'mode': selected, 'eligible': None,
              'hit': None, 'reason': 'disabled', 'seconds': None, 'startedAt': None,
              'producer': None, 'shadowMatch': None}
    if selected == 'off':
        return None, record
    started = time.monotonic()
    record['startedAt'] = datetime.now(timezone.utc).isoformat()
    try:
        result = helper('--lookup', env)
        record.update({key: result.get(key) for key in ('eligible', 'reason', 'producer')})
        if record['reason'] not in REASONS - {'disabled'}:
            raise ValueError('Invalid lookup reason')
        if record['eligible'] is not None and type(record['eligible']) is not bool:
            raise ValueError('Invalid lookup eligibility')
        if not eligibility_reason(record['eligible'], record['reason']):
            raise ValueError('Lookup reason contradicts eligibility')
        if record['eligible'] is True and (not valid_producer(record['producer'], env.get('GITHUB_SHA'))
                or not valid_configuration(result.get('configuration'), env.get('GITHUB_SHA'))):
            raise ValueError('Invalid producer result')
        if record['eligible'] is not True:
            record['producer'] = None
        record['hit'] = selected == 'enabled' if record['eligible'] is True else False if record['eligible'] is False else None
        return result.get('configuration'), record
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        record.update(eligible=None, hit=None, reason='lookup-unavailable', producer=None)
        return None, record
    finally:
        elapsed = time.monotonic() - started
        record['seconds'] = round(elapsed, 3) if elapsed >= 0 else None


def main():
    try:
        current = configuration()
        value = {'configuration': current}
        if sys.argv[1:] == ['--lookup']:
            value.update(lookup(os.environ, current))
        elif sys.argv[1:] != ['--configuration']:
            raise ValueError('Unknown source proof operation')
    except Exception:
        value = {'eligible': None, 'reason': 'lookup-unavailable'}
    print(json.dumps(value, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
