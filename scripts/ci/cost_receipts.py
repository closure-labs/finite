"""Bounded native stage receipts for read-only cost accounting."""
from contextlib import contextmanager
import json
import resource
import subprocess
import tempfile
import re
import zipfile
from datetime import datetime

from archive_read import authenticate, chunks, members

MAX_ARCHIVE = 8 * 1024**2
MAX_RECEIPTS = 16


def nix_receipt(run, artifact, name, value, seen):
    """Join source phases to one producing job, never to a retry's reused job."""
    attempt = artifact['name'].rsplit('-', 1)[1]
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('kind') != 'finite-nix-observation'
            or value.get('authorizesPublication') is not False
            or value.get('repository') != run['repository']
            or str(value.get('runId')) != str(run['runId'])
            or str(value.get('runAttempt')) != attempt
            or value.get('revision') != run['sourceRevision'] or value.get('jobName') != 'checks'
            or not isinstance(value.get('checkoutRevision'), str)
            or not re.fullmatch('[0-9a-f]{40}', value['checkoutRevision'])
            or run['workflow'] != '.github/workflows/build.yml'
            or not isinstance(value.get('workflowRef'), str)
            or not value['workflowRef'].startswith(run['repository'] + '/.github/workflows/build.yml@')):
        raise ValueError('Nix observation differs from native producer')
    candidates = [j for j in run['jobs'] if j['profile'] == 'shared_or_unknown' and j['role'] == 'checks'
                  and str(j['runAttempt']) == attempt]
    if len(candidates) != 1:
        run['receiptCoverage']['unmatched'] += 1
        return
    job = candidates[0]
    job['checkoutRevision'] = value['checkoutRevision']
    if name == 'nix-setup.json':
        cache = value.get('cache')
        if cache is not None and (not isinstance(cache, dict) or set(cache) != {
                'STORE_KEY', 'SOURCE_KEY', 'STORE_HIT', 'SOURCE_HIT'} or any(
                item is not None and (not isinstance(item, str) or len(item) > 512)
                for item in cache.values()) or any(cache[key] not in (None, 'true', 'false')
                for key in ('STORE_HIT', 'SOURCE_HIT'))):
            raise ValueError('Invalid Nix cache observation')
        if value.get('status') not in (None, 'success', 'failure', 'cancelled'):
            raise ValueError('Invalid Nix setup status')
        stages = [{'stage': 'Nix setup', 'seconds': value.get('seconds'),
                   'status': value.get('status'), 'startedAt': value.get('startedAt')}]
    else:
        aggregate = value.get('aggregateDerivation')
        if aggregate is not None and (not isinstance(aggregate, str) or not re.fullmatch(
                r'/nix/store/[a-z0-9]{32}-finite-ci-checks\.drv', aggregate)):
            raise ValueError('Invalid observed aggregate derivation')
        job['nixAggregateDerivation'] = aggregate
        stages = value.get('phases')
        if not isinstance(stages, list) or not 1 <= len(stages) <= 2:
            raise ValueError('Invalid Nix phase observations')
        for index, row in enumerate(stages):
            if (not isinstance(row, dict) or row.get('stage') != ('Evaluate aggregate', 'Build aggregate')[index]
                    or row.get('outcome') not in ('success', 'failure', 'error')
                    or row.get('status') is not None and (type(row['status']) is not int or not 0 <= row['status'] <= 255)):
                raise ValueError('Invalid Nix phase result')
            attempts = row.get('attempts')
            if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
                raise ValueError('Invalid Nix retry observations')
            for number, trial in enumerate(attempts, 1):
                if (not isinstance(trial, dict) or type(trial.get('attempt')) is not int or trial['attempt'] != number
                        or type(trial.get('seconds')) not in (int, float) or not 0 <= trial['seconds'] <= 86400
                        or trial.get('status') is not None and (type(trial['status']) is not int or not -255 <= trial['status'] <= 255)):
                    raise ValueError('Invalid Nix retry result')
    for row in stages:
        elapsed = row.get('seconds')
        if elapsed is None and name != 'nix-setup.json' or elapsed is not None and (
                type(elapsed) not in (int, float) or not 0 <= elapsed <= 86400):
            raise ValueError('Invalid Nix observation duration')
        try:
            started = datetime.fromisoformat(row['startedAt'].replace('Z', '+00:00'))
            if started.tzinfo is None:
                raise ValueError('Missing timezone')
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ValueError('Invalid Nix observation timestamp') from error
        key = (job['jobId'], name, row['stage'])
        if key not in seen:
            seen.add(key)
            job['stages'].append({**row, 'nested': True})
    if name == 'nix-setup.json':
        job['nixCache'] = cache
    runner = value.get('runner')
    if not isinstance(runner, dict):
        raise ValueError('Invalid Nix runner observation')
    job['runner']['imageVersion'] = runner.get('ImageVersion')
    cohort = value.get('toolCohort')
    if not isinstance(cohort, dict):
        raise ValueError('Invalid Nix tool cohort')
    job['runner']['toolCohort'] = cohort


@contextmanager
def bounded_reader(artifact, repository):
    with tempfile.TemporaryFile() as archive:
        limit = artifact['size_in_bytes']
        subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, stderr=subprocess.PIPE, check=True, timeout=60,
                       preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)))
        authenticate(archive, artifact)
        yield archive


def join(run, artifacts, reader=bounded_reader):
    selected = [a for a in artifacts if re.fullmatch(
        r'(?:(?:image|security)-finite(?:-dev)?|qualification-phase-finite(?:-dev)?-(?:fresh|upgrade)|source-checks)-'
        + str(run['runId']) + r'-[1-9][0-9]*', a.get('name', ''))]
    run['receiptCoverage'] = {'selected': len(selected), 'read': 0, 'unavailable': [], 'unmatched': 0}
    if len(selected) > MAX_RECEIPTS:
        run['receiptCoverage']['unavailable'].append('receipt-count-bound')
        return
    seen = set()
    for artifact in selected:
        binding = artifact.get('workflow_run', {})
        if (binding.get('id') != run['runId'] or binding.get('head_sha') != run['sourceRevision']
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))):
            raise ValueError('Cost receipt artifact lacks native run/source binding')
        if artifact.get('expired') or not 0 < artifact.get('size_in_bytes', 0) <= MAX_ARCHIVE:
            run['receiptCoverage']['unavailable'].append('expired-or-size-bound')
            continue
        with reader(artifact, run['repository']) as archive:
            with zipfile.ZipFile(archive) as zipped:
                for name, entry in members(zipped, max_files=1024, max_bytes=MAX_ARCHIVE):
                    if artifact['name'].startswith('source-checks-'):
                        if name not in ('nix-checks.json', 'nix-setup.json'):
                            continue
                        if entry.file_size > 65536:
                            raise ValueError('Oversized Nix observation')
                        nix_receipt(run, artifact, name, json.loads(b''.join(chunks(zipped, entry))), seen)
                        continue
                    if name == 'phase-timings.json' and artifact['name'].startswith('security-'):
                        if entry.file_size > 65536:
                            raise ValueError('Oversized security phase receipt')
                        value = json.loads(b''.join(chunks(zipped, entry)))
                        lane = 'finite-dev' if '-finite-dev-' in artifact['name'] else 'finite'
                        candidates = [j for j in run['jobs'] if j['profile'] == lane and j['role'] == 'security'
                                      and str(j['runAttempt']) == artifact['name'].rsplit('-', 1)[1]]
                        reused = value.get('inventoryReused')
                        if len(candidates) == 1 and type(reused) is bool:
                            candidates[0]['inventoryReuse'] = {'eligible': True if reused else None,
                                'hit': True if reused else None, 'missReason': None, 'observedReused': reused}
                        continue
                    if re.fullmatch(r'vm-(?:local|fresh|upgrade)/(?:guest-)?timings\.json', name):
                        if entry.file_size > 16384:
                            raise ValueError('Oversized guest timing receipt')
                        value = json.loads(b''.join(chunks(zipped, entry)))
                        phase = 'upgrade' if '-upgrade-' in artifact['name'] else 'fresh'
                        lane = 'finite-dev' if '-finite-dev-' in artifact['name'] else 'finite'
                        role = 'build' if artifact['name'].startswith('image-') else 'qualification-' + phase
                        guest = name.endswith('/guest-timings.json')
                        expected_member = ('vm-local' if role == 'build' else 'vm-' + phase) + ('/guest-timings.json' if guest else '/timings.json')
                        if name != expected_member:
                            raise ValueError('Guest timing phase differs from native artifact role')
                        if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
                            raise ValueError('Invalid VM timing receipt schema')
                        if guest:
                            stages = value.get('stages')
                            if not isinstance(stages, list) or len(stages) > 4:
                                raise ValueError('Invalid guest timing receipt schema')
                        else:
                            seconds, statuses = value.get('seconds'), value.get('status', {})
                            if not isinstance(seconds, dict) or len(seconds) > 16 or not isinstance(statuses, dict):
                                raise ValueError('Invalid host VM timing receipt schema')
                            stages = [{'stage': stage, 'seconds': elapsed, 'status': statuses.get(stage)}
                                      for stage, elapsed in seconds.items()]
                        names = set()
                        for row in stages:
                            stage = row.get('stage') if isinstance(row, dict) else None
                            allowed = stage in ('startup-checks', 'homebrew-setup', 'predecessor-preparation', 'home-init') if guest else (
                                isinstance(stage, str) and re.fullmatch(r'(?:installation|persistence-customization|home-activation|cleanup|upgrade-staging|(?:first-boot|updated|rollback)-(?:ssh-ready|boot-contracts))', stage))
                            status = row.get('status') if isinstance(row, dict) else None
                            valid_status = (not guest and status is None) or (type(status) is int and 0 <= status <= 255)
                            if (not allowed or stage in names or type(row.get('seconds')) is not int
                                    or not 0 <= row['seconds'] <= 86400 or not valid_status):
                                raise ValueError('Duplicate or invalid guest/host VM timing receipt')
                            names.add(stage)
                        candidates = [j for j in run['jobs'] if j['profile'] == lane and j['role'] == role
                                      and str(j['runAttempt']) == artifact['name'].rsplit('-', 1)[1]]
                        if len(candidates) != 1:
                            run['receiptCoverage']['unmatched'] += 1
                            continue
                        job = candidates[0]
                        for row in stages:
                            key = (job['jobId'], name, row['stage'])
                            if key not in seen:
                                seen.add(key)
                                job['stages'].append({**row, 'nested': True})
                        continue
                    if not name.endswith(('-timings.jsonl', '-stages.jsonl')):
                        continue
                    if entry.file_size > 1024**2:
                        raise ValueError('Oversized stage receipt')
                    raw = b''.join(chunks(zipped, entry))
                    for line in raw.splitlines():
                        receipt = json.loads(line)
                        if receipt.get('kind') != 'finite-stage-timing' or receipt.get('schema') != 1:
                            raise ValueError('Unknown cost stage receipt schema')
                        if (receipt.get('repository') != run['repository']
                                or str(receipt.get('runId')) != str(run['runId'])
                                or receipt.get('revision') != run['sourceRevision']):
                            raise ValueError('Cost receipt differs from native producer')
                        candidates = [j for j in run['jobs'] if j['profile'] == receipt.get('profile')
                                      and str(j['runAttempt']) == str(receipt.get('runAttempt'))
                                      and (j['name'] == receipt.get('jobName') or
                                           receipt.get('jobName') == 'build' and j['role'] == 'build')]
                        if len(candidates) != 1:
                            run['receiptCoverage']['unmatched'] += 1
                            continue
                        job = candidates[0]
                        key = (job['jobId'], receipt.get('stage'), receipt.get('startedAt'))
                        if key in seen:
                            continue
                        seen.add(key)
                        elapsed = receipt.get('seconds')
                        if type(elapsed) not in (int, float) or not 0 <= elapsed <= 86400:
                            raise ValueError('Invalid receipt duration')
                        job.setdefault('stages', []).append(receipt)
                        job['candidateDigest'] = receipt.get('candidateDigest')
                        job['runner']['toolCohort'] = receipt.get('toolCohort')
                        job['runner']['imageVersion'] = receipt.get('runner', {}).get('ImageVersion')
                        if receipt.get('stage') == 'predecessor-iso-reuse':
                            status = receipt.get('status')
                            job['predecessorReuse'] = {'eligible': True,
                                'hit': status == 0 if status in (0, 3) else None,
                                'missReason': 'unavailable' if status == 3 else None}
        run['receiptCoverage']['read'] += 1
