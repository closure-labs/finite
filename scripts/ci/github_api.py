"""Bounded fresh GitHub GETs; no mutation retries or authority cache."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import math
import re
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

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


class MetadataOperation:
    """One bounded metadata discovery; stores counters, never authority verdicts."""
    def __init__(self, total=150, max_reads=120):
        if (type(total) not in (int, float) or not math.isfinite(total) or not 0 < total <= 300
                or type(max_reads) is not int or not 0 < max_reads <= 300):
            raise ValueError('Invalid GitHub metadata operation budget')
        self.deadline = time.monotonic() + total
        self.max_reads, self.reads = max_reads, 0

    def read(self, endpoint):
        if time.monotonic() >= self.deadline:
            raise GitHubReadError('GitHub metadata discovery deadline exhausted', transient=True)
        if self.reads >= self.max_reads:
            raise GitHubReadError('GitHub metadata discovery read limit exhausted')
        self.reads += 1
        return get_json(endpoint, deadline=self.deadline)

    def pages(self, endpoint, collection, max_pages=20):
        if collection not in ('artifacts', 'jobs', 'actions_caches', 'workflow_runs'):
            raise ValueError('Unsupported GitHub metadata collection')
        if type(max_pages) is not int or not 0 < max_pages <= 20:
            raise ValueError('Invalid GitHub metadata page limit')
        url = urlsplit(endpoint)
        query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        if (url.scheme or url.netloc or url.fragment
                or len({key for key, _ in query}) != len(query)
                or dict(query).get('per_page') != '100' or 'page' in dict(query)):
            raise ValueError('GitHub metadata pagination requires one explicit page size')
        pages, seen, total = [], set(), None
        for number in range(1, max_pages + 1):
            page = self.read(url.path + '?' + urlencode(query + [('page', str(number))]))
            if (not isinstance(page, dict) or type(page.get('total_count')) is not int
                    or page['total_count'] < 0 or not isinstance(page.get(collection), list)
                    or len(page[collection]) > 100):
                raise GitHubReadError('Invalid GitHub metadata page')
            if total is not None and page['total_count'] != total:
                raise GitHubReadError('GitHub metadata count changed during pagination')
            total = page['total_count']
            for item in page[collection]:
                if (not isinstance(item, dict) or type(item.get('id')) is not int
                        or item['id'] <= 0 or item['id'] in seen):
                    raise GitHubReadError('Invalid or duplicate GitHub metadata item')
                seen.add(item['id'])
            if len(seen) > total:
                raise GitHubReadError('GitHub metadata exceeds declared count')
            pages.append(page)
            if len(seen) == total:
                return pages
            if len(page[collection]) < 100:
                raise GitHubReadError('GitHub metadata listing is incomplete')
        raise GitHubReadError('GitHub metadata page limit exhausted')


_METADATA_OPERATION = ContextVar('github_metadata_operation', default=None)


@contextmanager
def metadata_operation(total=150, max_reads=120):
    current = _METADATA_OPERATION.get()
    if current is not None:
        # Nested discovery consumes the parent's counters and deadline; it
        # cannot reset either budget or leak state into the next operation.
        yield current
        return
    operation = MetadataOperation(total, max_reads)
    token = _METADATA_OPERATION.set(operation)
    try:
        yield operation
    finally:
        _METADATA_OPERATION.reset(token)


def bounded_metadata(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with metadata_operation():
            return function(*args, **kwargs)
    return wrapped


def get_metadata(endpoint, *, collection=None):
    with metadata_operation() as operation:
        return operation.pages(endpoint, collection) if collection is not None else operation.read(endpoint)
