#!/usr/bin/env python3
"""Measure credential-free legacy and selective Cachix preparation on hosted runners."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
MODES = ('legacy', 'candidate')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


cache = module('cache_writer', ROOT / 'scripts/ci/cache-publish.py')
metrics = module('cache_metrics', ROOT / 'scripts/ci/benchmark-ci-cache.py')


def hosted():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Run preparation experiments in the hosted manual workflow')
    if any(os.environ.get(key) for key in cache.CREDENTIALS):
        raise ValueError('Preparation experiments must not receive credentials')
    head = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT,
                                   env=cache.preparation_env(), text=True, timeout=30).strip()
    if not cache.re.fullmatch(r'[0-9a-f]{40}', head) or head != os.environ.get('GITHUB_SHA'):
        raise ValueError('Experiment checkout differs from its fixed source revision')


def benchmark(mode, repetition, start, output):
    hosted()
    report = {'schema': 1, 'mode': mode, 'repetition': repetition,
              'revision': os.environ['GITHUB_SHA'], 'runId': os.environ['GITHUB_RUN_ID'],
              'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'lockSha256': hashlib.sha256((ROOT / 'flake.lock').read_bytes()).hexdigest(),
              'nixVersion': subprocess.check_output(['nix', '--version'], env=cache.preparation_env(),
                                                    text=True, timeout=30).strip(),
              'runner': {key: os.environ.get(key) for key in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')},
              'setup': metrics.delta(json.loads(start.read_text()), metrics.snapshot()), 'passes': [],
              'notes': ['No publication boundary is bypassed: only credential-free realization is measured.',
                        'Legacy realizes all checks and four tools serially; candidate realizes only four tools in a batch.',
                        'Cold means a fresh runner after public substitutions; warm reuses its own store.',
                        'Preparation includes evaluation, realization, root validation and closure queries.',
                        'Network counters include all runner traffic; closure sizes overlap.',
                        'Complete jobs include two preparation passes; Cachix push and post-push reader savings are not measured.']}
    try:
        for phase in ('cold', 'warm'):
            before = metrics.snapshot()
            roots = cache.realize_roots(include_proofs=mode == 'legacy', batch=mode != 'legacy')
            report['passes'].append(dict(metrics.delta(before, metrics.snapshot()), phase=phase, roots=roots))
        report['status'] = 'success'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['status'] = 'error'
        report['error'] = str(error)
        if isinstance(error, cache.ToolIdentityError):
            report['identityDiagnostics'] = error.diagnostics
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')


def summarize(directory, jobs_file, output):
    reports = [json.loads(path.read_text()) for path in sorted(directory.rglob('benchmark.json'))]
    pages = json.loads(jobs_file.read_text())
    if not isinstance(pages, list) or any(not isinstance(page, dict) or not isinstance(page.get('jobs'), list) for page in pages):
        raise ValueError('Expected paginated whole-job timing receipts')
    jobs = [job for page in pages for job in page['jobs']]
    expected = {(mode, repetition) for mode in MODES for repetition in (1, 2, 3)}
    seen, bindings, outputs, groups = set(), set(), {}, {}
    for report in reports:
        identity = (report.get('mode'), report.get('repetition'))
        if (report.get('schema') != 1 or identity not in expected or identity in seen
                or type(report.get('repetition')) is not int or report.get('status') != 'success'):
            raise ValueError('Missing, failed, unexpected or duplicate preparation measurement')
        seen.add(identity)
        revision, lock = report['revision'], report['lockSha256']
        if (not cache.re.fullmatch(r'[0-9a-f]{40}', revision)
                or not cache.re.fullmatch(r'[0-9a-f]{64}', lock)):
            raise ValueError('Invalid measurement source identity')
        bindings.add((revision, lock, report['runId'], report['runAttempt'], report['nixVersion'],
                      report['runner']['RUNNER_OS'], report['runner']['RUNNER_ARCH']))
        if report['runner']['RUNNER_OS'] != 'Linux' or report['runner']['RUNNER_ARCH'] != 'X64':
            raise ValueError('Unexpected preparation runner platform')
        passes = report.get('passes')
        if not isinstance(passes, list) or [entry.get('phase') for entry in passes] != ['cold', 'warm']:
            raise ValueError('Incomplete cold/warm preparation passes')
        for entry in passes:
            seconds = entry['seconds']
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError('Invalid preparation duration')
            cache.validate_roots(entry['roots'])
            tools = {root['name']: (root['path'], root['bytes']) for root in entry['roots'] if root['kind'] == 'tool'}
            if set(tools) != set(cache.TOOLS):
                raise ValueError('Preparation did not realize every declared tool')
            if report['mode'] == 'candidate' and len(entry['roots']) != len(cache.TOOLS):
                raise ValueError('Candidate unexpectedly realized check proofs')
            if report['mode'] == 'legacy' and not any(root['kind'] == 'proof' for root in entry['roots']):
                raise ValueError('Legacy did not realize check proofs')
            if outputs and tools != outputs:
                raise ValueError('Preparation tool outputs or closure sizes differ between lanes')
            outputs = tools
        matching = [job for job in jobs if job.get('name') == f'writer-{identity[0]}-{identity[1]}']
        if len(matching) != 1:
            raise ValueError('Missing or ambiguous whole-job timing receipt')
        job = matching[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or str(job.get('run_id')) != report['runId']
                or str(job.get('run_attempt')) != report['runAttempt']
                or job.get('head_sha') != revision):
            raise ValueError('Whole-job receipt differs from the measured successful source/attempt')
        elapsed = (datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
                   - datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))).total_seconds()
        if elapsed < 0:
            raise ValueError('Invalid whole-job duration')
        groups.setdefault(identity[0], []).append((report, elapsed))
    if seen != expected or len(bindings) != 1:
        raise ValueError('Require three matched repetitions of both lanes at one source/lock/platform/Nix version')
    rows = ['| Preparation | Complete job median s | Cold preparation median s | Warm preparation median s | Cold traffic received median bytes |',
            '|---|---:|---:|---:|---:|']
    for mode in MODES:
        entries = groups[mode]
        values = [mode, f'{statistics.median(elapsed for _, elapsed in entries):.2f}',
                  f'{statistics.median(report["passes"][0]["seconds"] for report, _ in entries):.2f}',
                  f'{statistics.median(report["passes"][1]["seconds"] for report, _ in entries):.2f}',
                  str(statistics.median(report['passes'][0]['transport']['receivedBytes'] for report, _ in entries))]
        rows.append('| ' + ' | '.join(values) + ' |')
    images = {mode: sorted({report['runner'].get('ImageVersion') or 'unknown' for report, _ in groups[mode]}) for mode in MODES}
    content = ('Credential-free preparation benchmark at `' + next(iter(bindings))[0] + '`\n\n'
               + '\n'.join(rows) + '\n\nTool output paths and closure sizes match across all six jobs and both passes. '
               'Complete job time includes cold and warm preparation plus setup and artifact handling; queue wait is excluded. '
               'Neither Cachix upload cost nor subsequent reader savings is measured, so this comparison cannot authorize automatic writing. '
               'Runner images: `' + json.dumps(images, sort_keys=True) + '`. Different runner images limit causal claims.\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:
            stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='operation', required=True)
    mark = subparsers.add_parser('mark-start')
    mark.add_argument('output', type=Path)
    run = subparsers.add_parser('run')
    run.add_argument('mode', choices=MODES)
    run.add_argument('repetition', type=int, choices=(1, 2, 3))
    run.add_argument('start', type=Path)
    run.add_argument('output', type=Path)
    summary = subparsers.add_parser('summarize')
    summary.add_argument('directory', type=Path)
    summary.add_argument('jobs', type=Path)
    summary.add_argument('output', type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.operation == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(metrics.snapshot()) + '\n')
    elif args.operation == 'run':
        benchmark(args.mode, args.repetition, args.start, args.output)
    else:
        summarize(args.directory, args.jobs, args.output)


if __name__ == '__main__':
    main()
