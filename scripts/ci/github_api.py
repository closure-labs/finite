"""Bounded fresh GitHub GETs; no mutation retries or authority cache."""
import json
import math
import re
import subprocess
import sys
import time

from github_retry import RetryBudget, RetryDeadline, number, retry_after


class GitHubReadError(RuntimeError):
    def __init__(self, message, *, transient=False, rate_limited=False):
        super().__init__(message)
        self.transient = transient
        self.rate_limited = rate_limited


def response_parts(output):
    # gh --include emits HTTP headers followed by a blank line and JSON.
    match = re.match(r'HTTP/\S+ (\d{3})[^\n]*\n', output)
    if not match:
        raise GitHubReadError('GitHub response lacks HTTP metadata')
    head, separator, body = output.partition('\n\n')
    if not separator:
        raise GitHubReadError('GitHub response lacks header boundary')
    headers = {}
    for line in head.splitlines()[1:]:
        key, sep, value = line.partition(':')
        if not sep or not re.fullmatch(r'[A-Za-z0-9!#$%&*+.^_`|~-]+', key):
            raise GitHubReadError('Malformed GitHub response header')
        key = key.lower()
        if key in headers and key in ('retry-after', 'x-ratelimit-reset', 'x-ratelimit-remaining'):
            raise GitHubReadError('Ambiguous GitHub retry header')
        headers[key] = value.strip()
    return int(match[1]), headers, body


def public_response(endpoint, *, timeout=30):
    """Credential-free official API GET, with no redirects and a wall timeout."""
    return subprocess.run([
        'curl', '--disable', '--silent', '--show-error', '--fail-with-body',
        '--include', '--suppress-connect-headers', '--proto', '=https',
        '--max-time', str(timeout), '--max-filesize', str(8 * 1024 * 1024),
        '--request', 'GET', '--header', 'Accept: application/vnd.github+json',
        '--header', 'X-GitHub-Api-Version: 2022-11-28',
        '--header', 'Cache-Control: no-cache',
        'https://api.github.com/' + endpoint,
    ], capture_output=True, text=True, check=False, timeout=timeout)


def get_json(endpoint, *, environment=None, missing=False, public=False, deadline=None):
    if not re.fullmatch(r'(?:repos|orgs)/[A-Za-z0-9_./%?=&+,:@~-]+', endpoint):
        raise GitHubReadError('Invalid GitHub metadata endpoint')
    label = endpoint.split('?')[0]
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise GitHubReadError('Invalid GitHub GET operation deadline')
    total = min(45.0, deadline - time.monotonic()) if deadline is not None else 45.0
    if total <= 0:
        raise GitHubReadError('GitHub GET operation deadline exhausted', transient=True)
    budget = RetryBudget(total=total)
    for attempt in range(1, 4):
        status, headers, body = None, {}, ''
        try:
            timeout = budget.remaining()
            if public:
                result = public_response(endpoint, timeout=timeout)
            else:
                result = subprocess.run(['gh', 'api', '--method', 'GET', '--include',
                                         '-H', 'Cache-Control: no-cache', endpoint],
                                        capture_output=True, text=True, check=False,
                                        timeout=timeout, env=environment)
            budget.remaining()
            if result.returncode < 0:
                raise GitHubReadError('GitHub GET transport terminated by signal: ' + label)
            output = result.stdout.replace('\r\n', '\n')
            if len(output.encode()) > 8 * 1024 * 1024:
                raise GitHubReadError('GitHub response exceeds size budget: ' + label)
            if output.startswith('HTTP/'):
                status, headers, body = response_parts(output)
            elif not result.returncode:
                raise GitHubReadError('GitHub response lacks HTTP metadata: ' + label)
            if status == 404 and missing:
                return None
            if result.returncode == 0 and status == 200:
                try:
                    value = json.loads(body)
                except ValueError as error:
                    raise GitHubReadError('Invalid GitHub JSON: ' + label) from error
                budget.remaining()
                return value
            reason = 'HTTP ' + str(status) if status else 'transport failure'
        except (subprocess.TimeoutExpired, TimeoutError):
            reason = 'timeout'
        except RetryDeadline as error:
            raise GitHubReadError('GitHub GET operation deadline exhausted: ' + label, transient=True) from error
        limited = status == 429 or status == 403 and (headers.get('x-ratelimit-remaining') == '0' or 'retry-after' in headers)
        request_id = headers.get('x-github-request-id', 'unavailable')
        if not re.fullmatch(r'[A-Za-z0-9:-]{1,100}', request_id):
            request_id = 'unavailable'
        message = f'GitHub GET {label}: {reason}; request={request_id}; attempt={attempt}/3'
        encoded = {}
        try:
            encoded = {key.encode('ascii'): value.encode('ascii') for key, value in headers.items()
                       if key in ('retry-after', 'x-ratelimit-reset', 'x-ratelimit-remaining')}
        except UnicodeError as error:
            raise GitHubReadError(message + '; invalid retry metadata', rate_limited=limited) from error
        for key, label_name in ((b'x-ratelimit-remaining', 'rate-remaining'), (b'x-ratelimit-reset', 'rate-reset')):
            value = number(encoded.get(key))
            if value is not None:
                message += f'; {label_name}={value}'
        after = retry_after(encoded.get(b'retry-after'), budget.epoch + budget.clock() - budget.start)
        if after is not None:
            message += f'; retry-after-seconds={after:g}'
        try:
            again = budget.wait(attempt, status, encoded)
        except RetryDeadline:
            again = False
            budget.reason = 'deadline-exhausted'
        if not again:
            transient = (status in (None, 408, 429, 500, 502, 503, 504) or limited)
            if budget.reason in ('invalid-not-before', 'missing-or-stale-reset', 'invalid-jitter'):
                transient = False
            suffix = '; retry budget exhausted' if transient else '; not retrying'
            raise GitHubReadError(message + suffix + '; reason=' + str(budget.reason),
                                  transient=transient, rate_limited=limited)
        print(message + '; retrying fresh GET', file=sys.stderr)
    raise AssertionError('Unreachable retry state')
