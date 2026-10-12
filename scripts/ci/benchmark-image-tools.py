#!/usr/bin/env python3
"""Measure image tool setup on fresh hosted runners, without building an image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def command(mode):
    if mode == 'baseline':
        return ['nix', 'develop', '--file', 'lib/ci-tools.nix', 'shell', '--command', 'true']
    if mode == 'candidate':
        return ['nix', 'build', '--file', 'lib/ci-tools.nix', 'image-tools', '--no-link', '--print-out-paths']
    raise ValueError('Unknown benchmark mode')


def store_metrics(path=None):
    args = ['nix', 'path-info', '--json', '--json-format', '1']
    args += ['--closure-size', str(path)] if path else ['--all']
    records = json.loads(subprocess.check_output(args, text=True, timeout=180))
    if path:
        if len(records) != 1:
            raise ValueError('Expected exactly one environment closure')
        return next(iter(records.values()))['closureSize']
    return {'paths': len(records), 'narBytes': sum(item['narSize'] for item in records.values())}


def measure(mode, phase):
    env = dict(os.environ)
    timings = []
    started = time.monotonic()
    output = None
    if mode == 'candidate':
        before = time.monotonic()
        result = subprocess.run(command(mode), text=True, stdout=subprocess.PIPE, check=True, timeout=1800)
        output = Path(result.stdout.strip())
        if not str(output).startswith('/nix/store/') or not (output / 'bin/python3').is_file():
            raise ValueError('Invalid pinned image tool output')
        for name in ('nix', 'bluebuild'):
            if (output / 'bin' / name).exists():
                raise ValueError('Pinned tools shadow host ' + name)
        env['PATH'] = str(output / 'bin') + os.pathsep + env['PATH']
        timings.append({'stage': 'realize-tools', 'seconds': time.monotonic() - before})
    for index in range(7):
        before = time.monotonic()
        subprocess.run(command(mode) if mode == 'baseline' else ['true'], env=env, check=True, timeout=1800)
        timings.append({'stage': 'command-' + str(index + 1), 'seconds': time.monotonic() - before})
    return {'phase': phase, 'seconds': time.monotonic() - started, 'stages': timings}, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['baseline', 'candidate'])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Run this benchmark only in its GitHub-hosted workflow.')
    os.chdir(ROOT)
    report = {'schema': 1, 'mode': args.mode, 'revision': os.environ['GITHUB_SHA'],
              'lockSha256': hashlib.sha256((ROOT / 'flake.lock').read_bytes()).hexdigest(),
              'runner': {'os': os.environ.get('RUNNER_OS'), 'arch': os.environ.get('RUNNER_ARCH'),
                         'image': os.environ.get('ImageVersion')},
              'nix': shutil.which('nix'), 'passes': [],
              'cache': 'No Actions cache restore/save; warm pass reuses first-pass store and evaluator downloads.'}
    try:
        report['nixVersion'] = subprocess.check_output(['nix', '--version'], text=True, timeout=30).strip()
        report['storeBefore'] = store_metrics()
        output = None
        for phase in ('cold', 'warm'):
            result, output = measure(args.mode, phase)
            report['passes'].append(result)
        report['storeAfter'] = store_metrics()
        report['addedStoreNarBytes'] = report['storeAfter']['narBytes'] - report['storeBefore']['narBytes']
        if args.mode == 'baseline':
            # Measure the actual development environment closure only AFTER
            # both passes; this diagnostic invocation cannot warm either pass.
            output = Path(os.environ['RUNNER_TEMP']) / 'finite-baseline-env'
            subprocess.run(['nix', 'develop', '--file', 'lib/ci-tools.nix', 'shell',
                            '--profile', str(output), '--command', 'true'], check=True, timeout=1800)
            output = output.resolve(strict=True)
        report['environmentClosureNarBytes'] = store_metrics(output)
        report['closureMeasurementExcludedFromTimings'] = True
        report['status'] = 'success'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
