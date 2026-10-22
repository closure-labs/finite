#!/usr/bin/env python3
"""Retry Nix transport failures without repeating failed tests or evaluations."""
from collections import deque
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

DERIVATION = re.compile(r'/nix/store/[a-z0-9]{32}-finite-ci-checks\.drv')


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


def build(command, attempts=3, delay=30, *, stdout=None):
    for attempt in range(1, attempts + 1):
        tail = deque(maxlen=500)
        if stdout is not None:
            stdout.seek(0)
            stdout.truncate()
        with subprocess.Popen(command, stdout=stdout if stdout is not None else subprocess.PIPE,
                              stderr=subprocess.PIPE if stdout is not None else subprocess.STDOUT,
                              text=True, errors='replace') as process:
            for line in process.stderr if stdout is not None else process.stdout:
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


def check_command(derivation, env=os.environ):
    if not DERIVATION.fullmatch(derivation):
        raise ValueError('Checks require one evaluated aggregate derivation')
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
    return command + [derivation + '^*']


def run_checks(env=os.environ):
    # Release the Flake/Home Manager evaluator before builders start. Only the
    # exact evaluated aggregate is built, with its successful GC root retained.
    phases = {}
    try:
        started = time.monotonic()
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output:
            status = build(['nix', 'eval', '--accept-flake-config', '--no-update-lock-file',
                            '--no-write-lock-file', '--raw', '.#ci-checks.drvPath'], stdout=output)
            phases['Evaluate aggregate'] = time.monotonic() - started
            if status:
                return status
            output.seek(0)
            value = output.read(4097)
            if len(value) > 4096:
                raise ValueError('Oversized aggregate evaluation result')
            derivation = value.strip()
        command = check_command(derivation, env)
        started = time.monotonic()
        status = build(command)
        phases['Build aggregate'] = time.monotonic() - started
        return status
    finally:
        summary = env.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as output:
                output.write('\n### Nix check phases\n\n| Phase | Seconds including retries |\n| --- | ---: |\n')
                for phase, elapsed in phases.items():
                    output.write(f'| {phase} | {elapsed:.2f} |\n')


if __name__ == '__main__':
    try:
        sys.exit(run_checks())
    except ValueError as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(2)
