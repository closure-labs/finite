#!/usr/bin/env python3
"""Bounded GET requests for source updates; exit 3 only for an allowed 404."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import os
from pathlib import Path
import signal
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from http.client import HTTPException


class ScopedRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not newurl.startswith('https://'):
            raise ValueError('Source downloads require HTTPS redirects')
        if request.has_header('Authorization') and not newurl.startswith('https://api.github.com/'):
            raise ValueError('Refusing to redirect GitHub credentials to another host')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def urlopen(request, timeout):
    return build_opener(ScopedRedirect()).open(request, timeout=timeout)


class MissingRelease(Exception):
    pass


def retry_delay(value, default):
    try:
        seconds = float(value)
        return max(default, seconds) if math.isfinite(seconds) else default
    except (TypeError, ValueError):
        try:
            return max(default, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return default


def timed_out(_signum, _frame):
    raise TimeoutError('request exceeded 30 seconds')


def fetch(url, github=False, allow_missing=False):
    if not url.startswith('https://'):
        raise ValueError('Source downloads require HTTPS')
    headers = {'User-Agent': 'finite-source-update'}
    if github:
        if not url.startswith('https://api.github.com/'):
            raise ValueError('GitHub credentials may only be used with api.github.com')
        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not token:
            raise ValueError('GitHub release lookup requires GH_TOKEN or GITHUB_TOKEN')
        headers['Authorization'] = f'Bearer {token}'
        headers['Accept'] = 'application/vnd.github+json'
    deadline = time.monotonic() + 150
    previous_handler = signal.signal(signal.SIGALRM, timed_out)
    try:
        for attempt in range(4):
            delay = 2 ** (attempt + 1)
            try:
                signal.alarm(30)
                with urlopen(Request(url, headers=headers), timeout=10) as response:
                    return response.read()
            except HTTPError as error:
                if error.code == 404 and allow_missing:
                    raise MissingRelease(url) from error
                if error.code != 429 and not 500 <= error.code < 600:
                    raise RuntimeError(f'GET {url}: HTTP {error.code}; not retrying') from error
                delay = retry_delay(error.headers.get('Retry-After'), delay)
                reason = f'HTTP {error.code}'
            except (URLError, TimeoutError, ConnectionError, HTTPException) as error:
                reason = type(error).__name__
            finally:
                signal.alarm(0)
            if attempt == 3 or time.monotonic() + delay + 30 > deadline:
                raise RuntimeError(f'GET {url}: {reason}; retry budget exhausted')
            print(f'GET {url}: {reason}; retry {attempt + 1}/3 in {delay:g}s', file=sys.stderr)
            time.sleep(delay)
    finally:
        signal.signal(signal.SIGALRM, previous_handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--github', action='store_true')
    parser.add_argument('--allow-missing', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        data = fetch(args.url, args.github, args.allow_missing)
        if args.output:
            args.output.write_bytes(data)
        else:
            sys.stdout.buffer.write(data)
    except MissingRelease:
        return 3
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
