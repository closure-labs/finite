"""Bounded GitHub metadata reads. Never retry a mutation or log response bodies."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
import subprocess
import sys
import time


class GitHubReadError(RuntimeError):
    pass


def delay_seconds(headers, fallback):
    value = headers.get('retry-after')
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            if headers.get('x-ratelimit-remaining') == '0':
                try:
                    delay = float(headers['x-ratelimit-reset']) - time.time()
                except (KeyError, ValueError):
                    delay = fallback
            else:
                delay = fallback
    return max(fallback, delay) if math.isfinite(delay) else fallback


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
        if sep:
            headers[key.lower()] = value.strip()
    return int(match[1]), headers, body


def get_json(endpoint, *, environment=None, missing=False):
    if not re.fullmatch(r'(?:repos|orgs)/[A-Za-z0-9_./%?=&+,:@~-]+', endpoint):
        raise GitHubReadError('Invalid GitHub metadata endpoint')
    label = endpoint.split('?')[0]
    deadline = time.monotonic() + 100
    for attempt in range(1, 4):
        status, headers, body = None, {}, ''
        try:
            # Authority, leases and release state must be revalidated at the
            # origin, including immediately after a successful write.
            result = subprocess.run(['gh', 'api', '--method', 'GET', '--include',
                                     '-H', 'Cache-Control: no-cache', endpoint],
                                    capture_output=True, text=True, check=False,
                                    timeout=30, env=environment)
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
                    return json.loads(body)
                except ValueError as error:
                    raise GitHubReadError('Invalid GitHub JSON: ' + label) from error
            limited = status == 403 and (headers.get('x-ratelimit-remaining') == '0'
                                         or 'retry-after' in headers)
            retry = status in (408, 429, 500, 502, 503, 504) or limited or status is None
            reason = 'HTTP ' + str(status) if status else 'transport failure'
        except subprocess.TimeoutExpired:
            reason, retry = 'timeout', True
        request_id = headers.get('x-github-request-id', 'unavailable')
        if not re.fullmatch(r'[A-Za-z0-9:-]{1,100}', request_id):
            request_id = 'unavailable'
        message = f'GitHub GET {label}: {reason}; request={request_id}; attempt={attempt}/3'
        delay = delay_seconds(headers, 2 ** attempt)
        if not retry or attempt == 3 or time.monotonic() + delay + 30 > deadline:
            raise GitHubReadError(message + ('; retry budget exhausted' if retry else '; not retrying'))
        print(message + f'; retrying in {delay:g}s', file=sys.stderr)
        time.sleep(delay)
    raise AssertionError('Unreachable retry state')
