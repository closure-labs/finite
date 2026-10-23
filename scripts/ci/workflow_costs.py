"""Read-only native workflow measurements. Reports never grant release authority."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
import statistics

from github_api import get_json

REPOSITORY = 'closure-labs/finite'
PROFILES = ('finite', 'finite-dev')


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
                         'profile': profile(job['name']), 'status': job['status'], 'conclusion': job.get('conclusion'),
                         'runnerSeconds': elapsed, 'queueSeconds': queue, 'steps': phases,
                         'startedAt': started, 'completedAt': completed, 'timingAnomalies': anomalies,
                         'runner': {'labels': job.get('labels', []), 'name': job.get('runner_name'),
                                    'imageVersion': None, 'toolCohort': None},
                         'qualificationReuseEligible': eligibility if reuse else None,
                         'qualificationReuseHit': any(s.get('conclusion') == 'success' for s in reuse) if reuse else None})
    end = max((job['completed_at'] for job in values if job.get('completed_at')), default=None) if run['status'] == 'completed' else None
    elapsed = seconds(run['created_at'], end or (run.get('updated_at') if run['status'] == 'completed' else None) or now.isoformat())
    return {'repository': REPOSITORY, 'runId': run['id'], 'runAttempt': run['run_attempt'],
            'sourceRevision': run['head_sha'], 'workflow': run['path'], 'event': run['event'],
            'url': run['html_url'], 'createdAt': run['created_at'], 'status': run['status'],
            'conclusion': run.get('conclusion'), 'category': category(run, jobs=[{'steps': job['steps']} for job in jobs]),
            'decisionRequest': (re.search(r'\[decision:([0-9a-f]{64})\]', run.get('display_title', '')) or [None, None])[1],
            'candidateDigest': None, 'retryAttempts': run['run_attempt'] - 1, 'downloadRetries': None, 'elapsedSeconds': elapsed, 'attempts': attempts, 'jobs': jobs}


def aggregate(runs):
    groups = defaultdict(list)
    for run in runs:
        for job in run['jobs']:
            groups[(run['category'], job['profile'])].append((run, job))
    rows = []
    for (kind, lane), entries in sorted(groups.items()):
        samples = [job['runnerSeconds'] for _, job in entries if job['runnerSeconds'] is not None]
        queue = [job['queueSeconds'] for _, job in entries if job['queueSeconds'] is not None]
        eligible = [job for _, job in entries if job['qualificationReuseEligible'] is True]
        rows.append({'category': kind, 'profile': lane, 'runs': len({r['runId'] for r, _ in entries}),
                     'jobs': len(entries), 'timedJobs': len(samples), 'runnerSeconds': sum(samples),
                     'medianJobSeconds': statistics.median(samples) if samples else None,
                     'queueSeconds': sum(queue), 'timedQueues': len(queue),
                     'conclusions': dict(Counter(job['conclusion'] or 'active' for _, job in entries)),
                     'qualificationReuseEligible': len(eligible),
                     'qualificationReuseHits': sum(job['qualificationReuseHit'] is True for job in eligible)})
    return rows


def collect(api=get_json, now=None, rollout=None):
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
    baseline = [r for r in runs if timestamp(r['createdAt']) < anchor]
    observation = [r for r in runs if timestamp(r['createdAt']) >= anchor]
    return {'schema': 1, 'kind': 'finite-workflow-costs', 'repository': REPOSITORY,
            'observedAt': now.isoformat(), 'authorizesPublication': False,
            'baseline': {'start': start.isoformat(), 'end': anchor.isoformat(), 'cohorts': aggregate(baseline)},
            'observation': {'start': anchor.isoformat() if rollout else None, 'end': finish.isoformat() if rollout else None,
                            'complete': bool(rollout and now >= anchor + timedelta(days=7)),
                            'cohorts': aggregate(observation)}, 'runs': runs,
            'limitations': ['Runner seconds are elapsed occupancy, not billed cost; active work is right-censored.',
                           'Shared jobs are reported separately; skipped jobs count with zero runner time.',
                           'Native step times include setup and post-job handling; composite cache restore/save substeps are not exposed.',
                           'Internal download retries, inventory eligibility/hits, candidate digests and exact runner/tool versions require retained producer receipts; unknown values are not zero or cache misses.',
                           'Qualification eligibility is observed from context-tool execution; hits require the conditional reused-evidence upload.',
                           'No percentile estimates; sample counts accompany medians. Reports grant no approval authority.']}


def markdown(report):
    lines = ['# Workflow cost observation', '', 'Observed at ' + report['observedAt'] + '.', '',
             '| Window | Category | Profile | Runs | Jobs | Runner seconds | Median job seconds | Queue seconds |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for window in ('baseline', 'observation'):
        for row in report[window]['cohorts']:
            median = row['medianJobSeconds']
            lines.append(f'| {window} | {row["category"]} | {row["profile"]} | {row["runs"]} | {row["jobs"]} | '
                         f'{row["runnerSeconds"]:.1f} | {median if median is not None else "unknown"} | {row["queueSeconds"]:.1f} |')
    lines += ['', 'Seven-day observation complete: ' + str(report['observation']['complete']).lower() + '.', '']
    lines.extend('- ' + item for item in report['limitations'])
    return '\n'.join(lines) + '\n'
