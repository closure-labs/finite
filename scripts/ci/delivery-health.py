#!/usr/bin/env python3
"""Read-only delivery blockers and authenticated publisher state."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from publisher_health import inspect_publisher
from security_decisions import canonical_hash, load_json
from github_api import get_json
from release_readiness import CHANNELS, PREFIX, eligible_build, release_status, root_version


def snapshot_identity(env=os.environ):
    identity = {'schema': 1, 'repository': env.get('GITHUB_REPOSITORY'),
                'revision': env.get('GITHUB_SHA'), 'runId': env.get('GITHUB_RUN_ID'),
                'runAttempt': env.get('GITHUB_RUN_ATTEMPT'), 'jobName': env.get('GITHUB_JOB')}
    if (identity['repository'] != 'closure-labs/finite'
            or not isinstance(identity['revision'], str) or not re.fullmatch('[a-f0-9]{40}', identity['revision'])
            or any(not isinstance(identity[key], str) or not re.fullmatch('[1-9][0-9]*', identity[key])
                   for key in ('runId', 'runAttempt'))
            or not isinstance(identity['jobName'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', identity['jobName'])):
        raise ValueError('Delivery snapshot requires the exact native job identity')
    return identity


def read_snapshot(path, env=os.environ):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError('Delivery snapshot must be a bounded regular file')
    report = load_json(path)
    if (not isinstance(report, dict) or not isinstance(report.get('snapshot'), dict)
            or type(report['snapshot'].get('schema')) is not int
            or report['snapshot'] != snapshot_identity(env)
            or type(report.get('healthy')) is not bool or not isinstance(report.get('release'), dict)
            or not isinstance(report['release'].get('state'), str)
            or len(report['release']['state']) > 64 or 'buildRun' not in report
            or report['buildRun'] is not None and (type(report['buildRun']) is not int or report['buildRun'] <= 0)):
        raise ValueError('Delivery snapshot differs from this job or has invalid dispatch fields')
    return report


def failed_phases(jobs):
    phases = []
    for job in jobs:
        if job.get('conclusion') in ('failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure'):
            steps = [step['name'] for step in job.get('steps', [])
                     if step.get('conclusion') in ('failure', 'timed_out', 'cancelled')]
            phases.append(job['name'] + (': ' + ', '.join(steps) if steps else ''))
    return phases


# Bound discovery independently of source-only build volume. Do not stop at an
# old creation date: an old run can have a recently completed retry/promotion.
HISTORY_PAGE_SIZE = 30
HISTORY_MAX_PAGES = 5
# Request-admission budget; an admitted metadata GET retains its own bounded
# transport timeout/retries. This is not a hard wall-clock cancellation.
HISTORY_SECONDS = 120


def build_history(api, deadline):
    runs, seen = [], set()
    for page in range(1, HISTORY_MAX_PAGES + 1):
        if time.monotonic() >= deadline:
            raise ValueError('Build history unavailable: observation time budget exhausted')
        endpoint = PREFIX + f'/actions/workflows/build.yml/runs?branch=main&per_page={HISTORY_PAGE_SIZE}'
        if page > 1:
            endpoint += f'&page={page}'
        document = api(endpoint)
        if time.monotonic() >= deadline:
            raise ValueError('Build history unavailable: observation time budget exhausted')
        batch = document.get('workflow_runs') if isinstance(document, dict) else None
        if not isinstance(batch, list) or len(batch) > HISTORY_PAGE_SIZE:
            raise ValueError('Invalid build health inventory')
        for run in batch:
            run_id = run.get('id') if isinstance(run, dict) else None
            if type(run_id) is not int or run_id <= 0 or run_id in seen:
                # A moving offset inventory must not silently hide a run.
                raise ValueError('Build history unavailable: invalid or repeated run identity')
            seen.add(run_id)
            runs.append(run)
        if len(batch) < HISTORY_PAGE_SIZE:
            return runs, {'state': 'exhausted', 'pages': page, 'runs': len(runs)}
    return runs, {'state': 'limited', 'pages': HISTORY_MAX_PAGES, 'runs': len(runs)}


def completed_at(job, now):
    value = job.get('completed_at')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('Publication evidence unavailable: missing job completion timestamp') from error
    if stamp.tzinfo is None or stamp > now + timedelta(minutes=5):
        raise ValueError('Invalid publication job completion timestamp')
    return value


def inspect(revision, version, bot, api=get_json, now=None):
    now = now or datetime.now(timezone.utc)
    deadline = time.monotonic() + HISTORY_SECONDS
    runs, history = build_history(api, deadline)
    def observe(endpoint):
        if time.monotonic() >= deadline:
            raise ValueError('Build history unavailable: observation time budget exhausted')
        result = api(endpoint)
        if time.monotonic() >= deadline:
            raise ValueError('Build history unavailable: observation time budget exhausted')
        return result
    runs = [run for run in runs if run.get('head_branch') == 'main'
            and run.get('head_repository', {}).get('full_name') == 'closure-labs/finite'
            and run.get('event') in ('push', 'schedule', 'workflow_dispatch')]
    active, active_problems, active_blockers = [], [], []
    for run in runs:
        if run.get('status') == 'completed':
            continue
        if run.get('status') not in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
            raise ValueError('Unknown active build status')
        run_id, attempt = run.get('id'), run.get('run_attempt')
        if type(run_id) is not int or type(attempt) is not int or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', '')):
            raise ValueError('Invalid active build identity')
        jobs = observe(PREFIX + f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
        if jobs['total_count'] > 100 or len(jobs['jobs']) != jobs['total_count']:
            raise ValueError('Active build job inventory is incomplete')
        failed = failed_phases(jobs['jobs'])
        running = [job['name'] for job in jobs['jobs'] if job.get('status') == 'in_progress']
        active.append({'runId': run_id, 'runAttempt': attempt, 'revision': run['head_sha'],
                       'status': run.get('status'), 'failedPhases': failed, 'runningPhases': running})
        if failed:
            active_problems.append('Active main run ' + str(run_id) + ' has failed phases: ' + ', '.join(failed))
        if run.get('status') == 'waiting':
            active_blockers.append('Main run ' + str(run_id) + ' is waiting; inspect its approval or environment gate.')
    runs = [run for run in runs if run.get('status') == 'completed']
    channels = {channel: {'qualified': None, 'promoted': None} for channel in CHANNELS}
    failures, selected = [], None
    for index, run in enumerate(runs):
        run_id, attempt = run.get('id'), run.get('run_attempt')
        if type(run_id) is not int or type(attempt) is not int or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', '')):
            raise ValueError('Invalid trusted build identity')
        jobs = observe(PREFIX + f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
        if jobs['total_count'] > 100 or len(jobs['jobs']) != jobs['total_count']:
            raise ValueError('Build job inventory is incomplete')
        successful = {job['name']: job for job in jobs['jobs'] if job.get('conclusion') == 'success'}
        for channel in CHANNELS:
            for kind, name in [('qualified', 'qualification / aggregate'), ('promoted', 'promote')]:
                job = successful.get(f'Publish ({channel}) / {name}')
                if job is not None:
                    completion = completed_at(job, now)
                    previous = channels[channel][kind]
                    # Runs are creation-ordered, but an older run can promote
                    # more recently on retry. Compare native job completion.
                    stamp = datetime.fromisoformat(completion.replace('Z', '+00:00'))
                    prior_stamp = (datetime.fromisoformat(previous['completedAt'].replace('Z', '+00:00'))
                                   if previous is not None else None)
                    if prior_stamp is None or stamp > prior_stamp:
                        channels[channel][kind] = {'runId': run_id, 'revision': run['head_sha'],
                                                   'completedAt': completion}
        if index == 0 and run.get('conclusion') == 'failure':
            failures = failed_phases(jobs['jobs'])
        if selected is None and run['head_sha'] == revision and run.get('conclusion') == 'success':
            artifacts = observe(PREFIX + f'/actions/runs/{run_id}/artifacts?per_page=100')
            if artifacts['total_count'] > 100 or len(artifacts['artifacts']) != artifacts['total_count']:
                raise ValueError('Build artifact inventory is incomplete')
            if eligible_build(run, jobs['jobs'], artifacts['artifacts'], revision):
                selected = run_id
    problems = active_problems
    if failures:
        problems.append('Latest main build failed: ' + ', '.join(failures))
    for channel, states in channels.items():
        promoted = states['promoted']
        if promoted is None:
            reason = ('promotion evidence unavailable within the bounded build history'
                      if history['state'] == 'limited' else 'no recorded successful promotion in available build history')
            problems.append(channel + ': ' + reason + '; this does not establish a failed publication.')
        else:
            timestamp = datetime.fromisoformat(promoted['completedAt'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None or timestamp > now + timedelta(minutes=5):
                raise ValueError('Invalid promotion timestamp')
            if now - timestamp >= timedelta(hours=36):
                problems.append(channel + ': latest recorded promotion is at least 36 hours old.')
    release = release_status(version, api, bot)
    decisions = Path(__file__).resolve().parents[2] / 'automation/decisions/releases'
    proposals = []
    for path in decisions.glob('*.json'):
        proposal = load_json(path)
        if proposal.get('kind') == 'release-set' and proposal.get('payload', {}).get('version') == version:
            if path.stem != canonical_hash(proposal):
                raise ValueError('Merged release decision identity mismatch')
            proposals.append(proposal)
    if len(proposals) > 1:
        raise ValueError('Multiple release decisions claim this version; inspect reservations')
    blockers = active_blockers
    if proposals:
        release = inspect_publisher(proposals[0], api)
        if release['state'] in ('failed', 'partial', 'not_started', 'unknown'):
            problems.append('Release ' + version + ': ' + release['reason'])
        if release['state'] == 'waiting_approval':
            blockers.append(release['reason'])
    elif release['state'] == 'published':
        release = {'state': 'unknown', 'reason': 'Public release lacks a merged decision for publisher correlation; inspect manually.'}
        problems.append(release['reason'])
    if not proposals:
        if release['state'] == 'unprepared' and selected is None:
            release['reason'] = 'Waiting for both successful same-revision qualifications and preserved ISOs.'
            problems.append('Release ' + version + ': ' + release['reason'])
        if release['state'] == 'recovery':
            problems.append(release['reason'])
    return {'schema': 1, 'healthy': not problems, 'blockers': blockers, 'problems': problems, 'channels': channels,
            'version': version, 'release': release, 'buildRun': selected, 'activeBuilds': active, 'buildHistory': history}


def dispatch(report, revision, api=get_json):
    if report['release']['state'] != 'unprepared' or report['buildRun'] is None:
        return 'No preparation dispatch needed.'
    if api(PREFIX + '/git/ref/heads/main')['object']['sha'] != revision:
        return 'Main advanced; waiting for its delivery reconciliation.'
    runs = api(PREFIX + f'/actions/workflows/release-set.yml/runs?branch=main&head_sha={revision}&per_page=100')['workflow_runs']
    if len(runs) >= 100:
        raise ValueError('Preparation run inventory is incomplete')
    if any(run.get('head_sha') == revision and run.get('status') != 'completed' for run in runs):
        return 'Preparation is already queued or running.'
    if any(run.get('head_sha') == revision and run.get('conclusion') == 'success' for run in runs):
        return 'Preparation already succeeded; inspect its proposal or explicitly recover its retained packet.'
    if any(run.get('head_sha') == revision and run.get('status') == 'completed'
           and run.get('conclusion') != 'success' for run in runs):
        raise ValueError('Paired preparation already failed or was cancelled at this revision; '
                         'inspect release-set.yml and explicitly rerun preparation after resolving the failure.')
    # Dispatch once. On an ambiguous write failure, the next health run first
    # reconciles remote runs/proposals; the HTTP request itself is never retried.
    result = subprocess.run(['gh', 'api', '--method', 'POST', PREFIX + '/actions/workflows/release-set.yml/dispatches',
                             '--input', '-'], input=json.dumps({'ref': 'main', 'inputs': {'build_run': str(report['buildRun'])}}),
                            text=True, capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise ValueError('Preparation dispatch did not confirm success; next reconciliation checks remote state.')
    return 'Dispatched paired preparation for build ' + str(report['buildRun']) + '.'


def summary(report):
    lines = ['### Delivery health', '', '| Channel | Latest recorded qualification | Latest recorded promotion |', '| --- | --- | --- |']
    def link(receipt):
        return (f'[{receipt["revision"][:12]}](https://github.com/closure-labs/finite/actions/runs/{receipt["runId"]})'
                if receipt else 'Unavailable in recent runs')
    for channel, state in report['channels'].items():
        lines.append(f'| {channel} | {link(state["qualified"])} | {link(state["promoted"])} |')
    for run in report.get('activeBuilds', []):
        url = 'https://github.com/closure-labs/finite/actions/runs/' + str(run['runId'])
        lines += ['', f'Active main run [{run["runId"]}]({url}): {run["status"]}.']
        lines.extend('- Failed phase: ' + phase for phase in run['failedPhases'])
        lines.extend('- Running phase: ' + phase for phase in run['runningPhases'])
    if history := report.get('buildHistory'):
        lines += ['', f'Build history: {history["runs"]} runs across {history["pages"]} pages ({history["state"]}).']
    release = report['release']
    lines += ['', 'Release publication: ' + release['state'] + ' — ' + release['reason'], '']
    if release.get('runUrl'):
        lines.append('[Publisher run](' + release['runUrl'] + ')')
    if release.get('phase'):
        lines.append('Failing or blocked phase: ' + release['phase'])
    lines.extend('- Informational blocker: ' + blocker for blocker in report.get('blockers', []))
    lines.extend('- ' + problem for problem in report['problems'])
    return '\n'.join(lines) + '\n'


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Delivery health requires trusted hosted main')
    revision = os.environ['GITHUB_SHA']
    target = Path('.bluebuild/delivery-health.json')
    target.parent.mkdir(exist_ok=True)
    target.unlink(missing_ok=True)
    identity = snapshot_identity()
    report = inspect(revision, root_version(), os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    report = {**report, 'snapshot': identity}
    raw = json.dumps(report, indent=2) + '\n'
    if len(raw.encode()) > 1024 * 1024:
        raise ValueError('Delivery snapshot exceeds size budget')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(raw)
    temporary.replace(target)
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            stream.write('snapshot=true\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write(summary(report))
    return 0 if report['healthy'] else 1


if __name__ == '__main__':
    sys.exit(main())
