"""Read-only native workflow measurements. Reports never grant release authority."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import re
import statistics

from github_api import get_json

REPOSITORY = 'closure-labs/finite'
PROFILES = ('finite', 'finite-dev')
OBSERVATION_ENDPOINT = '2026-10-30T05:01:17Z'


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing native timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Native timestamps require timezone')
    return parsed.astimezone(timezone.utc)


def seconds(start, end):
    value = (timestamp(end) - timestamp(start)).total_seconds()
    if value < 0:
        raise ValueError('Native timing is reversed')
    return value


def inventory(api, endpoint, key, limit=10000):
    items, total = [], None
    for page in range(1, limit // 100 + 1):
        document = api(endpoint + ('&' if '?' in endpoint else '?') + f'per_page=100&page={page}')
        count, values = document.get('total_count'), document.get(key)
        if type(count) is not int or not isinstance(values, list) or len(values) > 100 or count > limit:
            raise ValueError('Incomplete or oversized native ' + key + ' inventory')
        if total is not None and count != total:
            raise ValueError('Native inventory changed while collecting; repeat observation')
        total = count
        items.extend(values)
        if len(items) == total:
            return items
        if len(items) > total or len(values) < 100:
            break
    raise ValueError('Incomplete native ' + key + ' pagination')


def category(run, jobs):
    if run['event'] == 'pull_request':
        return 'pull_request'
    if run['event'] == 'merge_group':
        return 'merge_queue'
    if any(step.get('name') == 'Validate and resume immutable candidate' and step.get('conclusion') == 'success'
           for job in jobs for step in job.get('steps', [])) or 'recovery' in run['path']:
        return 'recovery'
    if run['event'] == 'schedule':
        return 'scheduled'
    if run.get('head_branch') == 'main' and run.get('head_repository', {}).get('full_name') == REPOSITORY and run['path'].endswith(('build.yml', 'publish-release-set.yml', 'release-set.yml', 'release.yml')):
        return 'publication'
    return 'other'


def profile(name):
    matches = [p for p in PROFILES if re.search(r'\(' + re.escape(p) + r'\)', name)]
    return matches[0] if len(matches) == 1 else 'shared_or_unknown'


def job_role(name):
    # Resolve exact native display names before reusable job suffixes.
    source_roles = {'Nix and runtime contracts': 'checks', 'Documentation checks': 'docs',
                    'Select checks': 'selection', 'CI gate': 'gate'}
    if name in source_roles:
        return source_roles[name]
    for role in ('fresh', 'upgrade'):
        if f'phase ({role})' in name:
            return 'qualification-' + role
    # Historical monolithic qualification is distinct from today's VM phases.
    if re.fullmatch(r'Publish \([a-z0-9-]+\) / qualification / qualify', name):
        return 'qualification'
    for role in ('build', 'security', 'sign', 'promote', 'aggregate', 'prepare', 'checks', 'docs', 'gate'):
        if re.search(r'(?:^| / )' + role + r'$', name, re.I):
            return role
    return 'unknown'


def observe(run, api, now):
    if (type(run.get('id')) is not int or type(run.get('run_attempt')) is not int
            or not 1 <= run['run_attempt'] <= 100
            or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', ''))
            or run.get('repository', {}).get('full_name') != REPOSITORY):
        raise ValueError('Invalid native workflow identity')
    attempts, jobs, seen = [], [], set()
    # Attempt endpoints include reused jobs. Charge each native job ID once,
    # retaining its original producing attempt instead of multiplying its cost.
    for attempt in range(1, run['run_attempt'] + 1):
        native = (run if attempt == run['run_attempt'] else
                  api(f'repos/{REPOSITORY}/actions/runs/{run["id"]}/attempts/{attempt}'))
        if (native.get('id') != run['id'] or native.get('run_attempt') != attempt
                or native.get('head_sha') != run['head_sha'] or native.get('path') != run['path']):
            raise ValueError('Run attempt differs from native source binding')
        values = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run["id"]}/attempts/{attempt}/jobs', 'jobs')
        attempts.append({'attempt': attempt, 'status': native['status'], 'conclusion': native.get('conclusion')})
        for job in values:
            if (type(job.get('id')) is not int or job.get('run_id') != run['id']
                    or job.get('head_sha') != run['head_sha'] or type(job.get('run_attempt')) is not int
                    or not 1 <= job['run_attempt'] <= attempt):
                raise ValueError('Job differs from its native run/attempt/source')
            if job['id'] in seen:
                continue
            seen.add(job['id'])
            started, completed = job.get('started_at'), job.get('completed_at')
            active = job.get('status') == 'in_progress'
            end = completed or (now.isoformat() if active else None)
            # Skipped jobs can have reversed synthetic timestamps and used no runner.
            skipped = job.get('conclusion') == 'skipped'
            anomalies = []
            def duration(start, finish, label):
                if not start or not finish:
                    return None
                try:
                    return seconds(start, finish)
                except ValueError:
                    anomalies.append(label + ': invalid or reversed native timestamps')
                    return None
            elapsed = 0 if skipped else duration(started, end, 'runner')
            queue = duration(job.get('created_at'), started, 'queue') if not skipped else None
            phases = []
            for step in job.get('steps', []):
                if step.get('conclusion') == 'skipped':
                    continue
                elapsed_step = duration(step.get('started_at'), step.get('completed_at'), step['name'])
                phases.append({'name': step['name'], 'seconds': elapsed_step, 'conclusion': step.get('conclusion')})
            # A successful reuse-check command alone cannot prove a hit. This
            # upload runs only after exact qualification reuse was accepted.
            reuse = [s for s in job.get('steps', []) if s.get('name') == 'Save authenticated reusable qualification']
            eligibility = any(s.get('name') == 'Install context tools for the reuse pilot'
                              and s.get('conclusion') == 'success' for s in job.get('steps', []))
            jobs.append({'jobId': job['id'], 'runAttempt': job['run_attempt'], 'name': job['name'],
                         'profile': profile(job['name']), 'role': job_role(job['name']),
                         'candidateDigest': None, 'stages': [],
                         'predecessorReuse': {'eligible': None, 'hit': None, 'missReason': None},
                         'inventoryReuse': {'eligible': None, 'hit': None, 'missReason': None, 'observedReused': None}, 'status': job['status'], 'conclusion': job.get('conclusion'),
                         'runnerSeconds': elapsed, 'queueSeconds': queue, 'steps': phases,
                         'startedAt': started, 'completedAt': completed, 'timingAnomalies': anomalies,
                         'runner': {'labels': job.get('labels', []), 'name': job.get('runner_name'),
                                    'imageVersion': None, 'toolCohort': None},
                         'qualificationReuseEligible': eligibility if reuse else None,
                         'qualificationReuseHit': (any(s.get('conclusion') == 'success' for s in reuse)
                             if eligibility and any(s.get('name') == 'Check exact qualification reuse'
                             and s.get('conclusion') == 'success' for s in job.get('steps', [])) else None)})
    end = max((job['completed_at'] for job in values if job.get('completed_at')), default=None) if run['status'] == 'completed' else None
    elapsed = seconds(run['created_at'], end or (run.get('updated_at') if run['status'] == 'completed' else None) or now.isoformat())
    return {'repository': REPOSITORY, 'runId': run['id'], 'runAttempt': run['run_attempt'],
            'sourceRevision': run['head_sha'], 'workflow': run['path'], 'event': run['event'],
            'headBranch': run.get('head_branch'),
            'url': run['html_url'], 'createdAt': run['created_at'], 'status': run['status'],
            'conclusion': run.get('conclusion'), 'category': category(run, jobs=[{'steps': job['steps']} for job in jobs]),
            'decisionRequest': (re.search(r'\[decision:([0-9a-f]{64})\]', run.get('display_title', '')) or [None, None])[1],
            'candidateDigest': None, 'retryAttempts': run['run_attempt'] - 1, 'downloadRetries': None, 'elapsedSeconds': elapsed, 'attempts': attempts, 'jobs': jobs}


def exclusive_occupancy(run):
    """Measure sole-runner intervals as a lower bound on workflow blocking time."""
    jobs = run['jobs']
    measured = run['status'] == 'completed' and all(
        j['runnerSeconds'] == 0 or j['runnerSeconds'] is not None and j['startedAt'] and j['completedAt']
        for j in jobs)
    for job in jobs:
        job['exclusiveRunnerSeconds'] = 0.0 if measured else None
    if not measured:
        return
    events = defaultdict(list)
    by_id = {job['jobId']: job for job in jobs}
    for job in jobs:
        if not job['runnerSeconds']:
            continue
        events[timestamp(job['startedAt'])].append((job['jobId'], True))
        events[timestamp(job['completedAt'])].append((job['jobId'], False))
    active, previous = set(), None
    for current, changes in sorted(events.items()):
        if previous is not None and len(active) == 1:
            by_id[next(iter(active))]['exclusiveRunnerSeconds'] += (current - previous).total_seconds()
        for job_id, starting in changes:
            if starting:
                active.add(job_id)
            else:
                active.discard(job_id)
        previous = current


def aggregate(runs):
    groups = defaultdict(list)
    for run in runs:
        for job in run['jobs']:
            groups[(run['category'], job['profile'], run['workflow'], run['event'], job.get('role', 'unknown'), run['sourceRevision'])].append((run, job))
    rows = []
    for (kind, lane, workflow, event, role, revision), entries in sorted(groups.items()):
        samples = [job['runnerSeconds'] for _, job in entries if job['runnerSeconds'] is not None]
        queue = [job['queueSeconds'] for _, job in entries if job['queueSeconds'] is not None]
        eligible = [job for _, job in entries if job['qualificationReuseEligible'] is True]
        rows.append({'category': kind, 'profile': lane, 'workflow': workflow, 'event': event,
                     'role': role, 'rolloutRevision': revision, 'runs': len({r['runId'] for r, _ in entries}),
                     'jobs': len(entries), 'timedJobs': len(samples), 'runnerSeconds': sum(samples),
                     'medianJobSeconds': statistics.median(samples) if samples else None,
                     'queueSeconds': sum(queue), 'timedQueues': len(queue),
                     'conclusions': dict(Counter(job['conclusion'] or 'active' for _, job in entries)),
                     'qualificationReuseEligible': len(eligible),
                     'qualificationReuseHits': sum(job['qualificationReuseHit'] is True for job in eligible),
                     'qualificationReuseUnknown': sum(job['qualificationReuseHit'] is None for _, job in entries),
                     'candidateDigests': sorted({j['candidateDigest'] for _, j in entries if j.get('candidateDigest')}),
                     'criticalPathJobs': sum(job.get('onObservedCriticalPath') is True for _, job in entries),
                     'exclusiveRunnerSeconds': (sum(job.get('exclusiveRunnerSeconds') or 0 for _, job in entries)
                         if any(job.get('exclusiveRunnerSeconds') is not None for _, job in entries) else None),
                     'exclusiveOccupancyUnknownJobs': sum(job.get('exclusiveRunnerSeconds') is None for _, job in entries)})
    return rows


def stage_opportunities(runs):
    groups = defaultdict(list)
    for run in runs:
        for job in run['jobs']:
            for stage in job.get('stages', []):
                key = (run['workflow'], run['event'], job['profile'], job['role'], run['sourceRevision'], stage['stage'])
                groups[key].append((run, job, stage))
    rows = []
    for (workflow, event, lane, role, revision, stage), entries in groups.items():
        measured = [s['seconds'] for _, _, s in entries if s.get('seconds') is not None]
        rows.append({'workflow': workflow, 'event': event, 'profile': lane, 'role': role,
                     'rolloutRevision': revision, 'stage': stage, 'samples': len(entries),
                     'timedSamples': len(measured), 'unknownDurationSamples': len(entries) - len(measured),
                     'runs': len({r['runId'] for r, _, _ in entries}),
                     'seconds': sum(measured) if measured else None,
                     'medianSeconds': statistics.median(measured) if measured else None,
                     'failedSamples': sum((type(s.get('status')) is int and s['status'] != 0)
                         or s.get('status') in ('failure', 'cancelled') or s.get('outcome') in ('failure', 'error')
                         for _, _, s in entries),
                     'unknownStatusSamples': sum(s.get('status') is None for _, _, s in entries),
                     'criticalPathContribution': None})
    return sorted(rows, key=lambda r: (r['seconds'] is not None, r['seconds'] or 0), reverse=True)


def source_proof_rollout(runs):
    """Summarize authenticated consumer receipts without inferring activation."""
    rows, seen = [], {}
    for run in runs:
        if (run['repository'] != REPOSITORY or run['workflow'] != '.github/workflows/build.yml'
                or run['event'] != 'push' or run.get('headBranch') != 'main'):
            continue
        for job in run['jobs']:
            if job['role'] != 'checks':
                continue
            projection = (run['runId'], run['sourceRevision'], job)
            if job['jobId'] in seen:
                if seen[job['jobId']] != projection:
                    raise ValueError('Conflicting native source-job projections')
                continue
            seen[job['jobId']] = projection
            receipt = job.get('sourceReuse') or {}
            rows.append({'runId': run['runId'], 'jobId': job['jobId'], 'runAttempt': job['runAttempt'],
                         'sourceRevision': run['sourceRevision'], 'status': job['status'],
                         'conclusion': job['conclusion'],
                         **{key: receipt.get(key) for key in ('mode', 'eligible', 'hit', 'reason',
                                                            'producer', 'shadowMatch', 'lookupSeconds')}})
    return {'authorizesPublication': False, 'activationDecision': None,
            'shadowMatches': sum(row['mode'] == 'shadow' and row['shadowMatch'] is True
                                 and row['status'] == 'completed' and row['conclusion'] == 'success' for row in rows),
            'shadowMismatches': sum(row['shadowMatch'] is False for row in rows),
            'enabledHits': sum(row['hit'] is True for row in rows),
            'unknownJobs': sum(row['eligible'] is None for row in rows), 'rows': rows}


def source_repetition(runs):
    """Measure repeated recorded inputs; never decide whether checks may be skipped."""
    proofs, targets, seen = [], [], {}
    for run in runs:
        if run['repository'] != REPOSITORY or run['workflow'] != '.github/workflows/build.yml':
            continue
        proof_completed = None
        if (run['event'] == 'merge_group' and run['status'] == 'completed'
                and run['conclusion'] == 'success'
                and isinstance(run.get('headBranch'), str)
                and run['headBranch'].startswith('gh-readonly-queue/main/')):
            try:
                proof_completed = max(timestamp(job['completedAt']) for job in run['jobs']
                                      if job['conclusion'] != 'skipped')
            except (ValueError, TypeError):
                pass
        for job in run['jobs']:
            if job['role'] != 'checks':
                continue
            projection = (run['runId'], run['sourceRevision'], job)
            if job['jobId'] in seen:
                if seen[job['jobId']] != projection:
                    raise ValueError('Conflicting native source-job projections')
                continue
            seen[job['jobId']] = projection
            row = {'runId': run['runId'], 'jobId': job['jobId'], 'runAttempt': job['runAttempt'],
                   'sourceRevision': run['sourceRevision'], 'checkoutRevision': job.get('checkoutRevision'),
                   'aggregateDerivation': job.get('nixAggregateDerivation'),
                   'runnerSeconds': job['runnerSeconds'], 'exclusiveRunnerSeconds': job.get('exclusiveRunnerSeconds'),
                   'state': 'unknown', 'missing': [], 'queueProof': None, 'nestedPhaseSeconds': None,
                   'reuseEligible': None, 'reuseHit': None, 'nativeRunnerImage': None}
            if run['event'] in ('push', 'schedule', 'workflow_dispatch') and run.get('headBranch') != 'main':
                row['missing'].append('native-main-branch')
            if job['status'] != 'completed' or job['conclusion'] != 'success':
                row['missing'].append('successful-source-job')
            if row['checkoutRevision'] != run['sourceRevision']:
                row['missing'].append('exact-checkout-revision')
            if not isinstance(row['aggregateDerivation'], str) or not re.fullmatch(
                    r'/nix/store/[a-z0-9]{32}-finite-ci-checks\.drv', row['aggregateDerivation']):
                row['missing'].append('aggregate-derivation')
            cohort = job['runner'].get('toolCohort')
            if (not isinstance(cohort, dict) or not isinstance(cohort.get('lockSha256'), dict)
                    or any(not isinstance(cohort['lockSha256'].get(lock), str)
                           or not re.fullmatch('[0-9a-f]{64}', cohort['lockSha256'][lock])
                           for lock in ('flake.lock', 'devenv.lock'))
                    or any(not isinstance(cohort.get(key), str) or not cohort[key].startswith('/')
                           for key in ('nixExecutable', 'pythonExecutable'))):
                row['missing'].append('recorded-tool-cohort')
            try:
                cohort_key = json.dumps(cohort, sort_keys=True, allow_nan=False)
            except (ValueError, TypeError):
                cohort_key = None
                row['missing'].append('serializable-tool-cohort')
            phases = [s for s in job['stages'] if s['stage'] in ('Evaluate aggregate', 'Build aggregate')]
            if (len(phases) != 2 or {s['stage'] for s in phases} != {'Evaluate aggregate', 'Build aggregate'}
                    or any(s.get('outcome') != 'success' or type(s.get('status')) is not int or s['status'] != 0
                           or type(s.get('seconds')) not in (int, float) or not math.isfinite(s['seconds'])
                           or not 0 <= s['seconds'] <= 86400 for s in phases)):
                row['missing'].append('successful-aggregate-phases')
            else:
                row['nestedPhaseSeconds'] = sum(s['seconds'] for s in phases)
                if (job['runnerSeconds'] is not None and row['nestedPhaseSeconds'] > job['runnerSeconds'] + 1):
                    row['missing'].append('phases-within-native-occupancy')
            try:
                started, completed = timestamp(job['startedAt']), timestamp(job['completedAt'])
                if completed < started:
                    raise ValueError('Reversed source-job interval')
            except (ValueError, TypeError):
                started = completed = None
                row['missing'].append('native-job-interval')
            if started is not None and row['nestedPhaseSeconds'] is not None:
                try:
                    intervals = {s['stage']: (timestamp(s['startedAt']),
                                 timestamp(s['startedAt']) + timedelta(seconds=s['seconds'])) for s in phases}
                    tolerance = timedelta(seconds=1)
                    if any(begin < started - tolerance or end > completed + tolerance
                           for begin, end in intervals.values()):
                        row['missing'].append('phase-native-interval')
                    if intervals['Build aggregate'][0] < intervals['Evaluate aggregate'][1] - tolerance:
                        row['missing'].append('serial-aggregate-phases')
                except (KeyError, ValueError, TypeError, OverflowError):
                    row['missing'].append('aggregate-phase-intervals')
            key = (run['sourceRevision'], row['checkoutRevision'], row['aggregateDerivation'], cohort_key)
            if proof_completed is not None and not row['missing']:
                proofs.append((key, proof_completed, row))
            if run['event'] in ('push', 'schedule', 'workflow_dispatch'):
                targets.append((key, started, row))
    rows = []
    for key, started, row in targets:
        if not row['missing']:
            earlier = [(completed, proof) for candidate, completed, proof in proofs
                       if candidate == key and completed <= started and proof['runId'] != row['runId']]
            if earlier:
                _, proof = max(earlier, key=lambda item: (item[0], item[1]['jobId']))
                row['state'] = 'repeated-recorded-inputs'
                row['queueProof'] = {field: proof[field] for field in ('runId', 'jobId', 'runAttempt')}
            else:
                row['state'] = 'no-earlier-matching-queue-proof-observed'
        rows.append(row)
    repeated = [row for row in rows if row['state'] == 'repeated-recorded-inputs']
    return {'authorizesPublication': False, 'productionReuseEnabled': False,
            'eligibilityEvaluated': False, 'observedQueueProofs': len(proofs),
            'repeatedJobs': len(repeated), 'unknownJobs': sum(row['state'] == 'unknown' for row in rows),
            'repeatedKnownRunnerSeconds': sum(row['runnerSeconds'] or 0 for row in repeated),
            'repeatedRunnerTimeUnknownJobs': sum(row['runnerSeconds'] is None for row in repeated),
            'repeatedNestedPhaseSeconds': sum(row['nestedPhaseSeconds'] for row in repeated),
            'repeatedKnownExclusiveRunnerSeconds': sum(row['exclusiveRunnerSeconds'] or 0 for row in repeated),
            'repeatedExclusiveTimeUnknownJobs': sum(row['exclusiveRunnerSeconds'] is None for row in repeated),
            'rows': sorted(rows, key=lambda row: (row['state'] != 'repeated-recorded-inputs',
                                                -(row['runnerSeconds'] or 0), row['jobId']))}


def collect(api=get_json, now=None, rollout=None, *, receipts=False):
    now = now or datetime.now(timezone.utc)
    anchor = rollout or now
    if anchor > now:
        raise ValueError('Rollout cannot be in the future')
    start, finish = anchor - timedelta(days=14), min(now, anchor + timedelta(days=7))
    runs, seen = [], set()
    day = start
    # GitHub caps a filtered search at 1,000 runs. Daily bounded searches fail
    # explicitly at that limit rather than silently dropping busy cohorts.
    while day < finish:
        end = min(day + timedelta(days=1), finish)
        query = day.strftime('%Y-%m-%dT%H:%M:%SZ') + '..' + end.strftime('%Y-%m-%dT%H:%M:%SZ')
        values = inventory(api, f'repos/{REPOSITORY}/actions/runs?created={query}', 'workflow_runs', limit=1000)
        if len(values) >= 1000:
            raise ValueError('Daily run search reached GitHub search limit')
        selected = []
        for run in values:
            created = timestamp(run['created_at'])
            if run['id'] not in seen and start <= created < finish:
                seen.add(run['id'])
                selected.append(run)
        # Independent native run reads share no mutation or authority state.
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs.extend(pool.map(lambda run: observe(run, api, now), selected))
        day = end
    receipt_budget = 40
    for run in sorted(runs, key=lambda r: r['createdAt'], reverse=True):
        exclusive_occupancy(run)
        # This is observed tail occupancy, not a reconstructed dependency DAG.
        tail = max((j['completedAt'] for j in run['jobs'] if j.get('completedAt')), default=None)
        for job in run['jobs']:
            job['onObservedCriticalPath'] = bool(tail and job['completedAt'] == tail and job['runnerSeconds'])
        if receipts:
            from cost_receipts import join
            if receipt_budget >= 16:
                import subprocess
                try:
                    join(run, inventory(api, f'repos/{REPOSITORY}/actions/runs/{run["runId"]}/artifacts', 'artifacts'))
                except (subprocess.SubprocessError, OSError):
                    run['receiptCoverage']['unavailable'].append('transport-failure')
                receipt_budget -= min(16, run['receiptCoverage']['selected'])
            else:
                run['receiptCoverage'] = {'read': 0, 'unavailable': ['collection-receipt-budget']}
    baseline = [r for r in runs if timestamp(r['createdAt']) < anchor]
    observation = [r for r in runs if timestamp(r['createdAt']) >= anchor]
    return {'schema': 1, 'kind': 'finite-workflow-costs', 'repository': REPOSITORY,
            'observedAt': now.isoformat(), 'originalObservationEndpoint': OBSERVATION_ENDPOINT,
            'receiptCollectionEnabled': receipts, 'receiptArchiveLimit': 40, 'authorizesPublication': False,
            'baseline': {'start': start.isoformat(), 'end': anchor.isoformat(), 'cohorts': aggregate(baseline)},
            'observation': {'start': anchor.isoformat() if rollout else None, 'end': finish.isoformat() if rollout else None,
                            'complete': bool(rollout and now >= anchor + timedelta(days=7)),
                            'cohorts': aggregate(observation)}, 'runs': runs,
            'rankedStages': stage_opportunities(observation or baseline),
            'rankedRecurringWork': sorted(aggregate(observation or baseline), key=lambda row: row['runnerSeconds'], reverse=True),
            'sourceRepetition': source_repetition(runs),
            'sourceProofRollout': source_proof_rollout(runs),
            'limitations': ['Runner seconds are elapsed occupancy, not billed cost; active work is right-censored.',
                           'Shared jobs are reported separately; skipped jobs count with zero runner time.',
                           'Native step times include setup and post-job handling; composite cache restore/save substeps are not exposed.',
                           'Internal download retries, inventory eligibility/hits, candidate digests and exact runner/tool versions require retained producer receipts; unknown values are not zero or cache misses.',
                           'Unknown receipt coverage, candidate identities, cohorts and reuse are explicit; unavailable is a miss reason, not an inferred context mismatch.',
                           'Rollout revisions are exact producer source revisions; later changes are separate cohorts, with no causal savings attribution.',
                           'Exclusive runner seconds measure sole-job intervals as a lower bound on blocking time; final-job counts mark the workflow tail. Exact dependency DAG contribution remains unknown.',
                           'Source repetition matches recorded checkout, aggregate and tool inputs to an earlier successful queue job; it does not evaluate reuse eligibility, verify native runner image identity or establish savings. Missing receipts and unseen queue proofs are not cache misses.',
                           'No percentile estimates; sample counts accompany medians. Reports grant no approval authority.']}


def markdown(report):
    lines = ['# Workflow cost observation', '', 'Observed at ' + report['observedAt'] + '.', '',
             '| Window | Workflow | Event | Role | Revision | Profile | Runs | Jobs | Runner seconds | Median job seconds | Queue seconds |',
             '| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for window in ('baseline', 'observation'):
        for row in report[window]['cohorts']:
            median = row['medianJobSeconds']
            lines.append(f'| {window} | {row["workflow"]} | {row["event"]} | {row["role"]} | {row["rolloutRevision"][:12]} | {row["profile"]} | {row["runs"]} | {row["jobs"]} | '
                         f'{row["runnerSeconds"]:.1f} | {median if median is not None else "unknown"} | {row["queueSeconds"]:.1f} |')
    lines += ['', 'Seven-day observation complete: ' + str(report['observation']['complete']).lower() + '.', '']
    lines += ['', 'Recurring work ranked by measured runner occupancy (frequency and final-job counts retained in JSON):', '']
    for row in report.get('rankedRecurringWork', [])[:20]:
        exclusive = 'unknown' if row['exclusiveRunnerSeconds'] is None else f"{row['exclusiveRunnerSeconds']:.1f}s"
        lines.append(f'- {row["workflow"]}, {row["event"]}, {row["role"]}, {row["profile"]}, {row["rolloutRevision"][:12]}: {row["runnerSeconds"]:.1f}s across {row["jobs"]} jobs; {exclusive} sole-runner occupancy; final job in {row["criticalPathJobs"]}.')
    lines += ['']
    repetition = report.get('sourceRepetition')
    if repetition:
        lines += ['Repeated source work after an observed matching queue proof: '
                  f'{repetition["repeatedJobs"]} jobs, {repetition["repeatedKnownRunnerSeconds"]:.1f} known native runner seconds, '
                  f'{repetition["repeatedNestedPhaseSeconds"]:.1f} nested evaluation/build seconds. '
                  'These measurements overlap; no check reuse or savings is inferred.',
                  f'Unknown source coverage: {repetition["unknownJobs"]} jobs. Unseen queue proofs are not cache misses.', '']
    rollout = report.get('sourceProofRollout')
    if rollout:
        lines += [f'Authenticated source-proof rollout: {rollout["shadowMatches"]} successful shadow matches, '
                  f'{rollout["shadowMismatches"]} mismatches, {rollout["enabledHits"]} enabled hits and '
                  f'{rollout["unknownJobs"]} jobs with unknown eligibility. No activation decision is inferred.', '']
    lines.extend('- ' + item for item in report['limitations'])
    return '\n'.join(lines) + '\n'
