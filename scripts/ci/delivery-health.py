#!/usr/bin/env python3
"""Report delivery blockers and dispatch preparation; never sign or publish."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from github_api import get_json
from release_readiness import CHANNELS, PREFIX, eligible_build, release_status, root_version


def inspect(revision, version, bot, api=get_json, now=None):
    now = now or datetime.now(timezone.utc)
    document = api(PREFIX + '/actions/workflows/build.yml/runs?branch=main&status=completed&per_page=30')
    runs = document['workflow_runs']
    if not isinstance(runs, list) or len(runs) > 30:
        raise ValueError('Invalid build health inventory')
    runs = [run for run in runs if run.get('head_branch') == 'main'
            and run.get('head_repository', {}).get('full_name') == 'closure-labs/finite'
            and run.get('event') in ('push', 'schedule', 'workflow_dispatch')
            and run.get('status') == 'completed']
    channels = {channel: {'qualified': None, 'promoted': None} for channel in CHANNELS}
    failures, selected = [], None
    for index, run in enumerate(runs):
        run_id, attempt = run.get('id'), run.get('run_attempt')
        if type(run_id) is not int or type(attempt) is not int or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', '')):
            raise ValueError('Invalid trusted build identity')
        jobs = api(PREFIX + f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
        if jobs['total_count'] > 100:
            raise ValueError('Build job inventory is incomplete')
        names = {job['name'] for job in jobs['jobs'] if job.get('conclusion') == 'success'}
        receipt = {'runId': run_id, 'revision': run['head_sha'], 'completedAt': run['updated_at']}
        for channel in CHANNELS:
            for kind, name in [('qualified', 'qualification / aggregate'), ('promoted', 'promote')]:
                if channels[channel][kind] is None and f'Publish ({channel}) / {name}' in names:
                    channels[channel][kind] = receipt
        if index == 0 and run.get('conclusion') == 'failure':
            failures = [job['name'] for job in jobs['jobs'] if job.get('conclusion') == 'failure']
        if selected is None and run['head_sha'] == revision and run.get('conclusion') == 'success':
            artifacts = api(PREFIX + f'/actions/runs/{run_id}/artifacts?per_page=100')
            if artifacts['total_count'] > 100:
                raise ValueError('Build artifact inventory is incomplete')
            if eligible_build(run, jobs['jobs'], artifacts['artifacts'], revision):
                selected = run_id
        if all(value for channel in channels.values() for value in channel.values()) and (selected or index >= 9):
            break
    problems = []
    if failures:
        problems.append('Latest main build failed: ' + ', '.join(failures))
    for channel, states in channels.items():
        promoted = states['promoted']
        if promoted is None:
            problems.append(channel + ': no recorded successful promotion in the recent build window.')
        else:
            timestamp = datetime.fromisoformat(promoted['completedAt'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None or timestamp > now + timedelta(minutes=5):
                raise ValueError('Invalid promotion timestamp')
            if now - timestamp >= timedelta(hours=36):
                problems.append(channel + ': latest recorded promotion is at least 36 hours old.')
    release = release_status(version, api, bot)
    if release['state'] == 'unprepared' and selected is None:
        release['reason'] = 'Waiting for both successful same-revision qualifications and preserved ISOs.'
        problems.append('Release ' + version + ': ' + release['reason'])
    if release['state'] == 'recovery':
        problems.append(release['reason'])
    return {'schema': 1, 'healthy': not problems, 'problems': problems, 'channels': channels,
            'version': version, 'release': release, 'buildRun': selected}


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
    lines += ['', 'Release readiness: ' + report['release']['reason'], '']
    lines.extend('- ' + problem for problem in report['problems'])
    return '\n'.join(lines) + '\n'


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Delivery health requires trusted hosted main')
    revision = os.environ['GITHUB_SHA']
    report = inspect(revision, root_version(), os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    Path('.bluebuild').mkdir(exist_ok=True)
    Path('.bluebuild/delivery-health.json').write_text(json.dumps(report, indent=2) + '\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write(summary(report))
        output.write('\n' + dispatch(report, revision) + '\n')
    return 0 if report['healthy'] else 1


if __name__ == '__main__':
    sys.exit(main())
