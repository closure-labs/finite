"""Read-only publisher correlation. Identity metadata conveys no approval authority."""
from datetime import datetime
import json
import re
import subprocess
import tempfile
import zipfile

import archive_read
from release_readiness import CHANNELS, PREFIX, REPOSITORY
from release_versions import prerelease
from security_decisions import canonical_hash

IDENTITY_LIMIT = 64 * 1024


def correlation_identity(artifacts, run, api):
    prefix = f'release-execution-identity-{run["id"]}-'
    current = [item for item in artifacts if item.get('name') == prefix + str(run['run_attempt'])]
    if current:
        if len(current) != 1:
            raise ValueError('Ambiguous current publisher identity')
        return current[0], run
    earlier = []
    for item in artifacts:
        match = re.fullmatch(re.escape(prefix) + r'([1-9][0-9]*)', item.get('name', ''))
        if match and int(match[1]) < run['run_attempt']:
            earlier.append((int(match[1]), item))
    if not earlier:
        raise ValueError('Missing identity; inspect this legacy or starting publisher run')
    attempt = max(value[0] for value in earlier)
    matches = [item for number, item in earlier if number == attempt]
    if len(matches) != 1:
        raise ValueError('Ambiguous earlier publisher identity')
    producer = api(PREFIX + f'/actions/runs/{run["id"]}/attempts/{attempt}')
    expected = {'id': run['id'], 'run_attempt': attempt, 'head_sha': run['head_sha'],
                'head_branch': 'main', 'path': run['path'], 'event': run['event'], 'status': 'completed'}
    if (not isinstance(producer, dict) or any(producer.get(k) != v for k, v in expected.items())
            or producer.get('head_repository', {}).get('full_name') != REPOSITORY):
        raise ValueError('Earlier identity differs from its native producing attempt')
    preparations = []
    for number in (run['run_attempt'], attempt):
        jobs = api(PREFIX + f'/actions/runs/{run["id"]}/attempts/{number}/jobs?per_page=100')
        if jobs['total_count'] > 100:
            raise ValueError('Publisher job inventory is incomplete')
        prepared = [job for job in jobs['jobs'] if job.get('name') == 'prepare']
        if (len(prepared) != 1 or prepared[0].get('status') != 'completed'
                or prepared[0].get('conclusion') != 'success'):
            raise ValueError('Earlier identity requires reused successful native preparation')
        times = tuple(prepared[0].get(field) for field in ('started_at', 'completed_at'))
        if (any(not isinstance(value, str) or not value.endswith('Z') for value in times)
                or datetime.fromisoformat(times[0]) >= datetime.fromisoformat(times[1])):
            raise ValueError('Native preparation timestamps are missing or invalid')
        preparations.append(times)
    if preparations[0] != preparations[1]:
        raise ValueError('Current attempt did not reuse the identity-producing preparation')
    return matches[0], producer


def read_identity(artifact, run):
    binding = artifact.get('workflow_run', {})
    if (artifact.get('name') != f'release-execution-identity-{run["id"]}-{run["run_attempt"]}'
            or artifact.get('expired') is not False
            or type(artifact.get('id')) is not int or artifact['id'] <= 0
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha']
            or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= 128 * 1024
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))):
        raise ValueError('Publisher identity lacks native artifact binding')
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', PREFIX + f'/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, stderr=subprocess.PIPE, check=True, timeout=30,
                       preexec_fn=lambda: archive_read.resource.setrlimit(archive_read.resource.RLIMIT_FSIZE,
                           (artifact['size_in_bytes'], artifact['size_in_bytes'])))
        archive_read.authenticate(archive, artifact)
        with zipfile.ZipFile(archive) as zipped:
            entries = list(archive_read.members(zipped))
            if (len(entries) != 1 or entries[0][0] != 'release-execution-identity.json'
                    or not 0 < entries[0][1].file_size <= IDENTITY_LIMIT):
                raise ValueError('Publisher identity JSON exceeds bounds or has unexpected members')
            return json.loads(b''.join(archive_read.chunks(zipped, entries[0][1])))


def publication_state(proposal, api):
    """Check public products independently of discovery metadata and job success."""
    identity = canonical_hash(proposal['payload'])
    states = []
    for channel in CHANNELS:
        entry = proposal['payload']['channels'][channel]
        release = api(PREFIX + '/releases/tags/' + entry['tag'], missing=True)
        if release is None or release.get('draft') is not False:
            states.append(False)
            continue
        assets = release.get('assets', [])
        hashes = {item['name']: item.get('digest') for item in assets if item.get('state') == 'uploaded'}
        if (release.get('tag_name') != entry['tag']
                or release.get('prerelease') is not prerelease(proposal['payload']['version'])
                or (release.get('body') or '').count('<!-- finite-release-set:' + identity + ' -->') != 1
                or len({item['name'] for item in assets}) != len(assets)
                or any(hashes.get(name) != 'sha256:' + digest for name, digest in entry['assets'].items())
                or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', hashes.get(name) or '')
                       for name in ('SHA256SUMS', 'SHA256SUMS.bundle.json'))):
            raise ValueError('Published products do not match the recorded payload; inspect immutable assets')
        reference = api(PREFIX + '/git/ref/tags/' + entry['tag'], missing=True)
        obj = reference.get('object', {}) if reference else {}
        for _ in range(5):
            if obj.get('type') != 'tag':
                break
            obj = api(PREFIX + '/git/tags/' + obj['sha'])['object']
        if obj.get('type') != 'commit' or obj.get('sha') != proposal['payload']['sourceRevision']:
            raise ValueError('Published source tag differs from recorded payload')
        states.append(True)
    return 'published' if all(states) else 'partial' if any(states) else None


def inspect_publisher(proposal, api, identity_reader=read_identity):
    proposal_hash = canonical_hash(proposal)
    expected = {'schema': 1, 'proposalHash': proposal_hash, 'payloadDigest': canonical_hash(proposal['payload']),
                'version': proposal['payload']['version'], 'repository': REPOSITORY,
                'workflow': 'publish-release-set.yml'}
    runs = api(PREFIX + '/actions/workflows/publish-release-set.yml/runs?branch=main&per_page=100')['workflow_runs']
    if not isinstance(runs, list) or len(runs) >= 100:
        raise ValueError('Publisher run inventory is incomplete')
    candidates, unknown = [], []
    for run in runs:
        if (run.get('path') != '.github/workflows/publish-release-set.yml' or run.get('head_branch') != 'main'
                or run.get('head_repository', {}).get('full_name') != REPOSITORY
                or run.get('event') not in ('push', 'workflow_dispatch')
                or type(run.get('id')) is not int or type(run.get('run_attempt')) is not int
                or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', ''))):
            continue
        artifacts = api(PREFIX + f'/actions/runs/{run["id"]}/artifacts?per_page=100')
        if artifacts['total_count'] > 100:
            raise ValueError('Publisher artifact inventory is incomplete')
        link = f'https://github.com/{REPOSITORY}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}'
        try:
            artifact, producer = correlation_identity(artifacts['artifacts'], run, api)
            identity = identity_reader(artifact, producer)
            if (not isinstance(identity, dict) or any(identity.get(k) != v for k, v in {
                    'schema': 1, 'repository': REPOSITORY, 'workflow': 'publish-release-set.yml',
                    'runId': run['id'], 'runAttempt': producer['run_attempt'], 'headSha': run['head_sha']}.items())):
                raise ValueError('Publisher identity differs from its native run')
            if identity.get('proposalHash') != proposal_hash:
                continue
            if any(identity.get(k) != v for k, v in expected.items()):
                raise ValueError('Publisher identity differs from merged decision')
        except (ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
            unknown.append({'runUrl': link, 'reason': str(error) + '; inspect identity and native producer.'})
            continue
        candidates.append((run, link, producer['run_attempt']))
    public = publication_state(proposal, api)
    if not candidates:
        if unknown:
            return {'state': 'unknown', **unknown[0], 'uncorrelatedRuns': unknown}
        return {'state': 'not_started', 'reason': 'No correlated publisher run; inspect the merged release decision.'}
    run, link, identity_attempt = max(candidates, key=lambda value: (value[0]['id'], value[0]['run_attempt']))
    jobs = api(PREFIX + f'/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100')
    if jobs['total_count'] > 100:
        raise ValueError('Publisher job inventory is incomplete')
    failed = [job for job in jobs['jobs'] if job.get('conclusion') in ('failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure')]
    phase = None
    if failed:
        job = failed[0]
        steps = [step['name'] for step in job.get('steps', []) if step.get('conclusion') == 'failure']
        phase = job['name'] + (' / ' + steps[0] if steps else '')
    status = run.get('status')
    if public == 'partial':
        state, reason = 'partial', 'One channel is published; inspect and resume the original approved execution.'
    elif status == 'completed' and run.get('conclusion') != 'success':
        state, reason = 'failed', 'Publisher failed; inspect the failing phase before explicit recovery.'
    elif public == 'published':
        state, reason = 'published', 'Both matching release inventories are public.'
    elif status == 'completed':
        state, reason = 'unknown', 'Publisher reported success without both matching public channels; inspect publication.'
    elif status in ('waiting', 'pending'):
        pending = api(PREFIX + f'/actions/runs/{run["id"]}/pending_deployments')
        if any(item.get('environment', {}).get('name') == 'release' for item in pending):
            state, reason, phase = 'waiting_approval', 'Publisher awaits native release environment approval.', 'sign'
        else:
            state, reason = 'queued', 'Publisher is waiting to start its next job.'
    elif status in ('queued', 'requested'):
        state, reason = 'queued', 'Publisher is queued.'
    elif status == 'in_progress':
        state, reason = 'running', 'Publisher is running.'
    else:
        state, reason = 'unknown', 'Unrecognized publisher status; inspect the native run.'
    return {'state': state, 'reason': reason, 'runUrl': link, 'phase': phase,
            'proposalHash': proposal_hash, 'identityRunAttempt': identity_attempt, 'uncorrelatedRuns': unknown}
