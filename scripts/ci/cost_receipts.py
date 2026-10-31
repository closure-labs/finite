"""Bounded native stage receipts for read-only cost accounting."""
from contextlib import contextmanager
import json
import resource
import math
import subprocess
import tempfile
import re
import zipfile
from datetime import datetime

from archive_read import authenticate, chunks, members
from foundation_timings import STAGES as FOUNDATION_STAGES, validate as validate_foundation_timing

MAX_ARCHIVE = 8 * 1024**2
MAX_RECEIPTS = 16


def source_reuse_receipt(run, artifact, value, seen):
    """Account only the consumer lookup; producer execution is a reference."""
    from source_proof import valid_producer, eligibility_reason
    attempt = artifact['name'].rsplit('-', 1)[1]
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('kind') != 'finite-source-reuse' or value.get('authorizesPublication') is not False
            or value.get('repository') != run['repository'] or str(value.get('runId')) != str(run['runId'])
            or str(value.get('runAttempt')) != attempt or value.get('revision') != run['sourceRevision']
            or value.get('checkoutRevision') != run['sourceRevision'] or value.get('jobName') != 'checks'
            or run['workflow'] != '.github/workflows/build.yml' or run['event'] != 'push'
            or run.get('headBranch') != 'main'
            or value.get('workflowRef') != run['repository'] + '/.github/workflows/build.yml@refs/heads/main'):
        raise ValueError('Source reuse observation differs from native consumer')
    mode, eligible, hit = value.get('mode'), value.get('eligible'), value.get('hit')
    if (mode not in ('off', 'shadow', 'enabled') or not eligibility_reason(eligible, value.get('reason'))
            or any(item is not None and type(item) is not bool for item in (eligible, hit, value.get('shadowMatch')))
            or hit is True and (mode != 'enabled' or eligible is not True)
            or eligible is None and hit is not None
            or eligible is False and hit is not False
            or eligible is True and hit is not (mode == 'enabled')
            or eligible is True and not valid_producer(value.get('producer'), run['sourceRevision'])
            or eligible is not True and value.get('producer') is not None
            or mode == 'off' and (eligible is not None or hit is not None)
            or (mode == 'off') != (value.get('reason') == 'disabled')
            or value.get('shadowMatch') is not None and (mode != 'shadow' or eligible is not True)):
        raise ValueError('Invalid source reuse decision observation')
    elapsed = value.get('seconds')
    if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 86400):
        raise ValueError('Invalid source proof lookup duration')
    if mode == 'off' and (elapsed is not None or value.get('startedAt') is not None):
        raise ValueError('Disabled lookup cannot claim execution')
    if elapsed is not None:
        try:
            started = datetime.fromisoformat(value['startedAt'].replace('Z', '+00:00'))
            if started.tzinfo is None:
                raise ValueError('Missing timezone')
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise ValueError('Invalid source lookup timestamp') from error
    jobs = [job for job in run['jobs'] if job['role'] == 'checks' and str(job['runAttempt']) == attempt]
    if len(jobs) != 1:
        run['receiptCoverage']['unmatched'] += 1
        return
    job = jobs[0]
    binding = ('source-reuse', job['jobId'])
    fingerprint = json.dumps(value, sort_keys=True, allow_nan=False)
    previous = next((entry[2] for entry in seen if entry[:2] == binding), None)
    if previous is not None:
        if previous != fingerprint:
            raise ValueError('Conflicting source reuse observations')
        return
    seen.add((*binding, fingerprint))
    job['sourceReuse'] = {key: value.get(key) for key in ('mode', 'eligible', 'hit', 'reason', 'producer', 'shadowMatch')}
    job['sourceReuse']['lookupSeconds'] = elapsed
    if elapsed is not None:
        job['stages'].append({'stage': 'Source proof lookup', 'seconds': elapsed, 'startedAt': value['startedAt'],
                              'status': 0 if eligible is not None else 1, 'nested': True})


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
                usage = trial.get('childResourceUsage')
                if usage is not None:
                    if (not isinstance(usage, dict) or set(usage) != {
                            'scope', 'includesDaemonWork', 'userCpuSeconds', 'systemCpuSeconds',
                            'blockInputOperations', 'blockOutputOperations'}
                            or usage['scope'] != 'terminated-and-waited-children'
                            or usage['includesDaemonWork'] is not False
                            or any(type(usage[key]) not in (int, float) or not math.isfinite(usage[key])
                                   or not 0 <= usage[key] <= 86400 * 1024
                                   for key in ('userCpuSeconds', 'systemCpuSeconds'))
                            or any(type(usage[key]) is not int or not 0 <= usage[key] <= 2**63 - 1
                                   for key in ('blockInputOperations', 'blockOutputOperations'))):
                        raise ValueError('Invalid Nix child resource observation')
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



def security_receipt(run, artifact, value, seen):
    """Read the small phase projection without treating it as security clearance."""
    compact = artifact['name'].startswith('security-costs-')
    if (run['workflow'] != '.github/workflows/build.yml'
            or not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or type(value.get('inventoryReused')) is not bool):
        raise ValueError('Invalid security cost receipt')
    phases = value.get('phases')
    # Earlier full scanner archives can lack phase detail. Retain their reuse
    # observation without inventing any measured stages.
    if phases is None and not compact:
        phases = []
    if not isinstance(phases, list) or len(phases) > 32:
        raise ValueError('Invalid security phase observations')
    for row in phases:
        if (not isinstance(row, dict) or not isinstance(row.get('phase'), str)
                or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', row['phase'])
                or type(row.get('seconds')) not in (int, float)
                or not math.isfinite(row['seconds']) or not 0 <= row['seconds'] <= 86400
                or type(row.get('success')) is not bool):
            raise ValueError('Invalid security phase observation')
    lane = 'finite-dev' if '-finite-dev-' in artifact['name'] else 'finite'
    candidates = [j for j in run['jobs'] if j['profile'] == lane and j['role'] == 'security'
                  and str(j['runAttempt']) == artifact['name'].rsplit('-', 1)[1]]
    if len(candidates) != 1:
        run['receiptCoverage']['unmatched'] += 1
        return
    job = candidates[0]
    # A compact projection and its legacy full archive must agree. Repeated
    # commands remain separate samples; duplicate artifacts do not charge them
    # twice.
    fingerprint = json.dumps(value, sort_keys=True)
    binding = ('security-costs', job['jobId'])
    previous = next((entry[2] for entry in seen if entry[:2] == binding), None)
    if previous is not None:
        if previous != fingerprint:
            raise ValueError('Conflicting security cost receipts')
        return
    seen.add((*binding, fingerprint))
    reused = value['inventoryReused']
    # Resuming a candidate can copy the original scanner's phase-timings.json
    # verbatim, including its inventory flag. The new artifact's native binding
    # authenticates transport, not which job performed those phases. Successful
    # revalidation also permits a fresh-scan fallback, so native step success
    # alone establishes neither reuse nor current phase attribution. Preserve
    # the unbound observations without charging them to this job's stages.
    if run.get('category') == 'recovery' or any(
            step['name'] == 'Revalidate fresh security evidence for a resumed candidate'
            for step in job['steps']):
        job['securityTimingAttribution'] = {
            'status': 'unknown', 'reason': 'resumed-security-timings-lack-producer-binding',
            'reportedInventoryReused': reused, 'reportedPhases': phases}
        return
    job['inventoryReuse'] = {'eligible': True if reused else None,
                             'hit': True if reused else None, 'missReason': None, 'observedReused': reused}
    job['stages'].extend({'stage': 'security-' + row['phase'], 'seconds': row['seconds'],
                          'status': 'success' if row['success'] else 'failure', 'nested': True}
                         for row in phases)


def reconciliation_receipt(run, artifact, value, seen):
    """Bind controller phases to their actual producing job, including failures."""
    attempt = artifact['name'].rsplit('-', 1)[1]
    if (run['workflow'] != '.github/workflows/decision-proposals.yml'
            or not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('kind') != 'finite-reconciliation-costs' or value.get('authorizesPublication') is not False
            or value.get('repository') != run['repository'] or str(value.get('runId')) != str(run['runId'])
            or str(value.get('runAttempt')) != attempt or value.get('revision') != run['sourceRevision']
            or value.get('jobName') != 'reconcile'
            or value.get('workflowRef') != run['repository'] + '/.github/workflows/decision-proposals.yml@refs/heads/main'
            or type(value.get('truncated')) is not bool
            or value.get('historicalReadWorkers') is not None and (
                type(value['historicalReadWorkers']) is not int or value['historicalReadWorkers'] not in (1, 4))
            or value.get('checkoutRevision') is not None and (not isinstance(value['checkoutRevision'], str)
                or not re.fullmatch(r'[0-9a-f]{40}', value['checkoutRevision']))):
        raise ValueError('Reconciliation costs differ from native producer')
    rows = value.get('stages')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ValueError('Invalid reconciliation phase count')
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('stage'), str)
                or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', row['stage'])
                or row.get('profile') not in (None, 'finite', 'finite-dev')
                or row.get('outcome') not in ('running', 'success', 'error')
                or row.get('seconds') is not None and (type(row['seconds']) not in (int, float)
                    or not math.isfinite(row['seconds']) or not 0 <= row['seconds'] <= 86400)
                or row.get('outcome') == 'running' and row.get('seconds') is not None):
            raise ValueError('Invalid reconciliation phase result')
        try:
            if datetime.fromisoformat(row['startedAt'].replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('Missing timezone')
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ValueError('Invalid reconciliation timestamp') from error
    candidates = [job for job in run['jobs'] if job['name'] == 'reconcile' and str(job['runAttempt']) == attempt]
    if len(candidates) != 1:
        run['receiptCoverage']['unmatched'] += 1
        return
    job = candidates[0]
    fingerprint = json.dumps(value, sort_keys=True)
    binding = ('reconciliation-costs', job['jobId'])
    previous = next((entry[2] for entry in seen if entry[:2] == binding), None)
    if previous is not None:
        if previous != fingerprint:
            raise ValueError('Conflicting reconciliation cost receipts')
        return
    seen.add((*binding, fingerprint))
    job['checkoutRevision'] = value.get('checkoutRevision')
    job['reconciliationTimingsTruncated'] = value['truncated']
    job['reconciliationReadWorkers'] = value.get('historicalReadWorkers')
    job['stages'].extend({**row, 'stage': 'reconciliation-' + row['stage'], 'nested': True,
                          'status': None if row['outcome'] == 'running' else
                          'failure' if row['outcome'] == 'error' else 'success'} for row in rows)


def predecessor_reuse_receipt(run, artifact, value, seen):
    """Native-bound observations; no part of this document authorizes reuse."""
    reasons = {'no-successful-run', 'no-qualification-artifact', 'qualification-unavailable', 'legacy-evidence',
               'candidate-or-profile-mismatch', 'generation-inputs-missing',
               'generation-inputs-changed', 'generation-ineligible', 'preserved-iso-missing',
               'installation-tag-missing', 'iso-transfer-timeout', 'iso-transfer-unproductive'}
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('kind') != 'finite-predecessor-iso-reuse'
            or value.get('authorizesPublication') is not False
            or value.get('repository') != run['repository']
            or value.get('runId') != str(run['runId'])
            or value.get('revision') != run['sourceRevision']
            or value.get('profile') not in ('finite', 'finite-dev')
            or not isinstance(value.get('runAttempt'), str)
            or not re.fullmatch(r'[1-9][0-9]*', value['runAttempt'])
            or not isinstance(value.get('predecessorDigest'), str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', value['predecessorDigest'])
            or value.get('outcome') not in ('hit', 'miss', 'error')):
        raise ValueError('Predecessor observation differs from native producer')
    expected = f'qualification-phase-{value["profile"]}-upgrade-{run["runId"]}-{value["runAttempt"]}'
    if artifact['name'] != expected or run['workflow'] != '.github/workflows/build.yml':
        raise ValueError('Predecessor observation is outside production upgrade evidence')
    counts, paths = value.get('missCounts'), value.get('changedInputPaths')
    if (type(value.get('runsExamined')) is not int or not 0 <= value['runsExamined'] <= 20
            or type(value.get('artifactsExamined')) is not int or not 0 <= value['artifactsExamined'] <= 1000000
            or not isinstance(counts, dict) or not set(counts).issubset(reasons)
            or any(type(n) is not int or not 1 <= n <= 1000000 for n in counts.values())
            or not isinstance(paths, list) or len(paths) > 20
            or any(not isinstance(p, str) or len(p) > 200
                   or not re.fullmatch(r'[A-Za-z0-9_./-]+', p) or p.startswith('/')
                   or any(part in ('', '.', '..') for part in p.split('/')) for p in paths)
            or paths != sorted(set(paths))
            or type(value.get('changedInputPathsTruncated')) is not bool):
        raise ValueError('Invalid or oversized predecessor miss observations')
    jobs = [j for j in run['jobs'] if j['name'] == f'Publish ({value["profile"]}) / qualification / phase (upgrade)'
            and j['role'] == 'qualification-upgrade'
            and j['profile'] == value['profile'] and str(j['runAttempt']) == value['runAttempt']]
    if len(jobs) != 1:
        run['receiptCoverage']['unmatched'] += 1
        return
    job = jobs[0]
    fingerprint = json.dumps(value, sort_keys=True)
    binding = ('predecessor-reuse', job['jobId'])
    previous = next((entry[2] for entry in seen if entry[:2] == binding), None)
    if previous is not None and previous != fingerprint:
        raise ValueError('Conflicting predecessor reuse observations')
    seen.add((*binding, fingerprint))
    job['predecessorReuseDiagnostics'] = {**value, 'artifactId': artifact['id'],
                                         'artifactSha256': artifact['digest']}


def select(run, artifacts):
    """Plan the same complete run set that the authenticated reader consumes."""
    return [a for a in artifacts if re.fullmatch(
        r'(?:(?:image|security(?:-costs)?)-finite(?:-dev)?|qualification-phase-finite(?:-dev)?-(?:fresh|upgrade)|source-checks|reconciliation-costs)-'
        + str(run['runId']) + r'-[1-9][0-9]*', a.get('name', ''))]


def join(run, artifacts, reader=bounded_reader):
    selected = select(run, artifacts)
    run['receiptCoverage'] = {'selected': len(selected), 'read': 0, 'unavailable': [], 'unmatched': 0}
    if len(selected) > MAX_RECEIPTS:
        run['receiptCoverage']['unavailable'].append('receipt-count-bound')
        return
    seen = set()
    for artifact in selected:
        binding = artifact.get('workflow_run', {})
        if (binding.get('id') != run['runId'] or binding.get('head_sha') != run['sourceRevision']
                or not isinstance(artifact.get('digest'), str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])):
            raise ValueError('Cost receipt artifact lacks native run/source binding')
        if artifact.get('expired') or not 0 < artifact.get('size_in_bytes', 0) <= MAX_ARCHIVE:
            run['receiptCoverage']['unavailable'].append('expired-or-size-bound')
            continue
        with reader(artifact, run['repository']) as archive:
            with zipfile.ZipFile(archive) as zipped:
                reconciliation = artifact['name'].startswith('reconciliation-costs-')
                compact = reconciliation or artifact['name'].startswith('security-costs-')
                entries = list(members(zipped, max_files=1 if compact else 1024,
                                       max_bytes=65536 if compact else MAX_ARCHIVE))
                if compact and [name for name, _ in entries] != [
                        'reconciliation-costs.json' if reconciliation else 'phase-timings.json']:
                    raise ValueError('Missing or unexpected compact cost member')
                for name, entry in entries:
                    if reconciliation:
                        reconciliation_receipt(run, artifact, json.loads(b''.join(chunks(zipped, entry))), seen)
                        continue
                    if artifact['name'].startswith('source-checks-'):
                        if name == 'source-reuse.json':
                            if entry.file_size > 65536:
                                raise ValueError('Oversized source reuse observation')
                            source_reuse_receipt(run, artifact, decode_json(b''.join(chunks(zipped, entry))), seen)
                            continue
                        if name not in ('nix-checks.json', 'nix-setup.json'):
                            continue
                        if entry.file_size > 65536:
                            raise ValueError('Oversized Nix observation')
                        nix_receipt(run, artifact, name, json.loads(b''.join(chunks(zipped, entry))), seen)
                        continue
                    if name == 'phase-timings.json' and artifact['name'].startswith('security-'):
                        if entry.file_size > 65536:
                            raise ValueError('Oversized security phase receipt')
                        security_receipt(run, artifact, json.loads(b''.join(chunks(zipped, entry))), seen)
                        continue
                    if re.fullmatch(r'finite(?:-dev)?-predecessor-reuse\.json', name):
                        if entry.file_size > 16384:
                            raise ValueError('Oversized predecessor reuse observation')
                        value = decode_json(b''.join(chunks(zipped, entry)))
                        if (not isinstance(value, dict)
                                or name != str(value.get('profile', '')) + '-predecessor-reuse.json'):
                            raise ValueError('Predecessor observation filename/profile differs')
                        predecessor_reuse_receipt(run, artifact, value, seen)
                        continue
                    if re.fullmatch(r'vm-(?:local|fresh|upgrade)/(?:guest-)?timings\.json', name):
                        if entry.file_size > 16384:
                            raise ValueError('Oversized guest timing receipt')
                        value = decode_json(b''.join(chunks(zipped, entry)))
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
                        if guest and 'foundation' in value:
                            observation = value['foundation']
                            if (not isinstance(observation, dict) or set(observation) != {'schema', 'stages', 'rejectedRecords'}
                                    or type(observation['schema']) is not int or observation['schema'] != 1
                                    or not isinstance(observation['stages'], list)
                                    or len(observation['stages']) > len(FOUNDATION_STAGES)
                                    or type(observation['rejectedRecords']) is not int
                                    or not 0 <= observation['rejectedRecords'] <= 1000000):
                                raise ValueError('Invalid Foundation timing envelope')
                            records = [validate_foundation_timing(row) for row in observation['stages']]
                            if len({row['stage'] for row in records}) != len(records):
                                raise ValueError('Duplicate Foundation timing stage')
                            if job.get('foundationTimings') not in (None, observation):
                                raise ValueError('Conflicting Foundation timing observations')
                            job['foundationTimings'] = observation
                            for row in records:
                                key = (job['jobId'], name, 'foundation-' + row['stage'])
                                if key not in seen:
                                    seen.add(key)
                                    # Guest wall time is not an authenticated host-clock interval.
                                    job['stages'].append({'stage': 'foundation-' + row['stage'],
                                        'seconds': row['seconds'], 'status': row['status'],
                                        'outcome': row['outcome'], 'guestStartedAt': row['startedAt'], 'nested': True})
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
    for job in run['jobs']:
        observation = job.get('predecessorReuseDiagnostics')
        if observation is not None:
            expected = {'hit': 0, 'miss': 3, 'error': 2}[observation['outcome']]
            if any(stage.get('status') != expected for stage in job['stages']
                   if stage.get('stage') == 'predecessor-iso-reuse'):
                raise ValueError('Predecessor observation differs from measured command outcome')
        if job.get('sourceReuse', {}).get('hit') is True and any(
                stage['stage'] in ('Evaluate aggregate', 'Build aggregate') for stage in job['stages']):
            raise ValueError('Reused source cannot claim executed consumer phases')


def decode_json(raw):
    from source_proof import decode
    return decode(raw)
