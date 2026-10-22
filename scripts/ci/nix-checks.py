#!/usr/bin/env python3
"""Retry Nix transport failures without repeating failed tests or evaluations."""
from collections import deque
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def transient(output):
    # A transport warning earlier in the log must not hide a later build,
    # evaluation, authentication or integrity failure.
    permanent = (
        r'builder (?:for .*? failed|failed) with exit code|'
        r'hash mismatch|syntax error|undefined variable|attribute .* missing|'
        r'HTTP (?:error |response:? )?(?:400|401|403|404)\b|'
        r'Permission denied|unauthorized|forbidden'
    )
    transport = (
        r'HTTP (?:error |response:? )?(?:408|429|500|502|503|504)\b|'
        r'(?:could not|couldn.t) resolve (?:host|hostname)|'
        r'(?:connection|network) (?:reset|timed out|is unreachable)|'
        r'(?:unable|failed) to download .*?(?:timed out|Timeout)|'
        r'Temporary failure in name resolution|TLS connect error'
    )
    return not re.search(permanent, output, re.I) and bool(re.search(transport, output, re.I))


def build(command, attempts=3, delay=30):
    for attempt in range(1, attempts + 1):
        tail = deque(maxlen=500)
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors='replace') as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                tail.append(line)
            status = process.wait()
        if not status:
            return 0
        if status < 0 or attempt == attempts or not transient(''.join(tail)):
            return status if status > 0 else 128 - status
        print(f'::warning::Nix download failed (attempt {attempt}/{attempts}); '
              f'retrying in {attempt * delay}s.', flush=True)
        time.sleep(attempt * delay)
    return 1


def check_command(env=os.environ):
    command = ['nix', 'build', '--accept-flake-config', '--verbose', '--print-build-logs']
    if env.get('GITHUB_ACTIONS') == 'true':
        temporary = Path(env.get('RUNNER_TEMP', ''))
        if not temporary.is_absolute():
            raise ValueError('Hosted checks require an absolute runner temporary directory')
        # Keep the successful aggregate and its proof outputs alive during the
        # bounded cache's post-job GC. No image, VM or signing material is rooted.
        command += ['--out-link', str(temporary / 'finite-checks-cache-root')]
    else:
        command += ['--no-link']
    return command + ['.#ci-checks']


if __name__ == '__main__':
    sys.exit(build(check_command()))
