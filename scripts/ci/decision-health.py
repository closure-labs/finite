#!/usr/bin/env python3
"""Report stale scans and human decisions; never grant or revoke approval."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys

REPOSITORY = 'closure-labs/finite'
TITLE = 'Maintainer decision pipeline health'
MARKER = '<!-- finite-maintainer-decision-health:v1 -->'
DECISION_PATH = re.compile(r'automation/decisions/(?:security|releases)/[0-9a-f]{64}\.json')


class HealthError(ValueError):
    pass


def github(endpoint, method='GET', payload=None):
    command = ['gh', 'api', '--method', method, endpoint]
    if payload is not None:
        command.extend(['--input', '-'])
    try:
        result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                capture_output=True, text=True, check=False, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise HealthError('GitHub health API timed out') from error
    if result.returncode:
        raise HealthError('GitHub health API failed: ' + endpoint.split('?')[0])
    if len(result.stdout.encode()) > 4 * 1024 * 1024:
        raise HealthError('GitHub health response exceeds size budget')
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise HealthError('Invalid GitHub health API JSON') from error


def collection(api, endpoint, key=None):
    values = []
    for page in range(1, 11):
        response = api(endpoint + ('&' if '?' in endpoint else '?') + f'per_page=100&page={page}')
        if key:
            if not isinstance(response, dict) or key not in response:
                raise HealthError('Invalid GitHub health collection envelope')
            response = response[key]
        if not isinstance(response, list) or len(response) > 100 or any(not isinstance(item, dict) for item in response):
            raise HealthError('Invalid GitHub health collection')
        values.extend(response)
        if len(response) < 100:
            return values
    raise HealthError('GitHub health pagination budget exhausted')


def timestamp(value, now):
    if not isinstance(value, str):
        raise HealthError('Missing health record timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise HealthError('Invalid health record timestamp') from error
    if parsed.tzinfo is None or parsed > now + timedelta(minutes=5):
        raise HealthError('Untrusted health record timestamp')
    return parsed


def number(value):
    if type(value) is not int or value < 1:
        raise HealthError('Invalid GitHub health record identifier')
    return value


def context(repository, bot):
    if (repository != REPOSITORY or os.environ.get('GITHUB_REPOSITORY') != repository
            or os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise HealthError('Decision health requires trusted hosted main execution')
    if not isinstance(bot, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\[bot\]', bot):
        raise HealthError('FINITE_REVIEW_BOT_LOGIN must identify the configured GitHub App bot')


def inspect(repository, bot, api=github, now=None):
    now = now or datetime.now(timezone.utc)
    prefix = 'repos/' + repository
    runs = collection(api, prefix + '/actions/workflows/image-security.yml/runs?branch=main&status=completed', 'workflow_runs')
    trusted = []
    for run in runs:
        if (run.get('head_branch') != 'main' or run.get('event') not in ('schedule', 'workflow_dispatch')
                or run.get('head_repository', {}).get('full_name') != repository):
            continue
        if run.get('status') != 'completed' or not isinstance(run.get('conclusion'), str):
            raise HealthError('Invalid completed audit run')
        trusted.append((timestamp(run.get('updated_at'), now), number(run.get('id')), run))
    trusted.sort(key=lambda value: (value[0], value[1]), reverse=True)
    failures = []
    latest = trusted[0][2] if trusted else None
    if latest and latest['conclusion'] != 'success':
        failures.append(f'Latest completed image-security audit #{latest["id"]} concluded {latest["conclusion"]}.')
    successful = next((value for value in trusted if value[2]['conclusion'] == 'success'), None)
    if successful is None:
        failures.append('No successful trusted main image-security audit is available.')
    elif now - successful[0] >= timedelta(hours=36):
        failures.append(f'Latest successful image-security audit #{successful[1]} is at least 36 hours old.')
    pending = []
    pulls = collection(api, prefix + '/pulls?state=open&base=main')
    for pull in pulls:
        author = pull.get('user', {})
        if author.get('login') != bot or author.get('type') != 'Bot':
            continue
        if (pull.get('base', {}).get('ref') != 'main'
                or pull.get('head', {}).get('repo', {}).get('full_name') != repository):
            continue
        pr = number(pull.get('number'))
        created = timestamp(pull.get('created_at'), now)
        if now - created < timedelta(hours=72):
            continue
        files = collection(api, prefix + f'/pulls/{pr}/files')
        if any(isinstance(entry.get('filename'), str) and DECISION_PATH.fullmatch(entry['filename']) for entry in files):
            pending.append(pr)
    if pending:
        failures.append('Bot decision PRs pending at least 72 hours: ' + ', '.join('#' + str(pr) for pr in sorted(pending)) + '.')
    # Read every required endpoint before creating, updating or closing an issue.
    issues = collection(api, prefix + '/issues?state=open')
    owned = []
    for issue in issues:
        if (issue.get('title') == TITLE and issue.get('user', {}).get('login') == bot
                and issue.get('user', {}).get('type') == 'Bot' and not issue.get('pull_request')
                and isinstance(issue.get('body'), str) and MARKER in issue['body']):
            number(issue.get('number'))
            owned.append(issue)
    owned.sort(key=lambda issue: issue['number'])
    report = {'schema': 1, 'healthy': not failures, 'problems': failures,
              'latestAuditRun': latest['id'] if latest else None,
              'latestSuccessfulAuditRun': successful[1] if successful else None,
              'pendingDecisionPRs': sorted(pending)}
    return report, owned


def reconcile(repository, report, issues, api=github):
    prefix = 'repos/' + repository + '/issues'
    if report['healthy']:
        for issue in issues:
            api(prefix + '/' + str(issue['number']), 'PATCH', {'state': 'closed', 'state_reason': 'completed'})
        return
    lines = [MARKER, '', 'The maintainer decision pipeline needs attention.', '']
    lines.extend('- ' + problem for problem in report['problems'])
    lines.append('')
    if report['latestAuditRun']:
        lines.append(f'[Latest completed audit](https://github.com/{repository}/actions/runs/{report["latestAuditRun"]})')
    for pr in report['pendingDecisionPRs']:
        lines.append(f'[Decision PR #{pr}](https://github.com/{repository}/pull/{pr})')
    lines.extend(['', 'This monitor does not approve, reject or revoke any security finding or release.'])
    body = '\n'.join(lines)
    if not issues:
        api(prefix, 'POST', {'title': TITLE, 'body': body})
    else:
        if issues[0]['body'] != body:
            api(prefix + '/' + str(issues[0]['number']), 'PATCH', {'body': body})
        for duplicate in issues[1:]:
            api(prefix + '/' + str(duplicate['number']), 'PATCH', {'state': 'closed', 'state_reason': 'not_planned'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--bot-login', default=os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    args = parser.parse_args()
    try:
        context(args.repository, args.bot_login)
        report, issues = inspect(args.repository, args.bot_login)
        reconcile(args.repository, report, issues)
    except (HealthError, OSError, KeyError, TypeError, AttributeError) as error:
        print('Decision health failed: ' + str(error), file=sys.stderr)
        return 2
    # Findings belong in the dedicated issue. Keep logs independent of report
    # fields so future metadata additions cannot expose sensitive values.
    if report['healthy']:
        print('Decision pipeline health: healthy')
    else:
        print('Decision pipeline health: needs attention; see the repository health issue')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
