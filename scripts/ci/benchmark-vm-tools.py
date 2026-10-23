#!/usr/bin/env python3
"""Compare VM provisioning on matched hosted runners, without publication."""
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

import vm_tools

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ('apt', 'apt-minimal', 'nix')
spec = importlib.util.spec_from_file_location('vm_metrics', ROOT / 'scripts/ci/benchmark-ci-cache.py')
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def benchmark(provider, repetition, start, output):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('pull_request', 'workflow_dispatch')):
        raise ValueError('Use the read-only hosted VM-tools experiment')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=30).strip()
    if head != os.environ['GITHUB_SHA']:
        raise ValueError('Benchmark checkout differs from native revision')
    report = {'schema': 1, 'provider': provider, 'repetition': repetition,
              'revision': head, 'proposalRevision': os.environ['PROPOSAL_REVISION'],
              'runId': os.environ['GITHUB_RUN_ID'], 'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'lockSha256': hashlib.sha256((ROOT / 'flake.lock').read_bytes()).hexdigest(),
              'nixVersion': subprocess.check_output(['nix', '--version'], text=True, timeout=30).strip(),
              'runner': {name: os.environ.get(name) for name in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')},
              'setup': metrics.delta(json.loads(start.read_text()), metrics.snapshot()), 'passes': []}
    try:
        for phase in ('cold', 'warm'):
            before = metrics.snapshot()
            env = vm_tools.provision(provider)
            identity = vm_tools.smoke(env)
            elapsed = metrics.delta(before, metrics.snapshot())
            report['passes'].append({**elapsed, 'phase': phase, 'identity': identity})
        if report['passes'][0]['identity'] != report['passes'][1]['identity']:
            raise ValueError('Tool or firmware identity changed between passes')
        report['status'] = 'success'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')


def summarize(directory, jobs_file, output):
    reports = [json.loads(path.read_text()) for path in directory.rglob('benchmark.json')]
    pages = json.loads(jobs_file.read_text())
    if not isinstance(pages, list) or any(not isinstance(page.get('jobs'), list) for page in pages):
        raise ValueError('Missing native whole-job metadata')
    jobs = [job for page in pages for job in page['jobs']]
    expected = {(provider, rep) for provider in PROVIDERS for rep in (1, 2, 3)}
    seen, bindings, groups, identities = set(), set(), {}, {}
    for report in reports:
        key = (report.get('provider'), report.get('repetition'))
        if (report.get('schema') != 1 or key not in expected or key in seen
                or type(report.get('repetition')) is not int or report.get('status') != 'success'):
            raise ValueError('Missing, duplicate or failed benchmark')
        seen.add(key)
        runner = report['runner']
        if runner.get('RUNNER_OS') != 'Linux' or runner.get('RUNNER_ARCH') != 'X64' or not runner.get('ImageVersion'):
            raise ValueError('Unknown runner platform or image')
        bindings.add(tuple(report[name] for name in ('revision', 'proposalRevision', 'runId', 'runAttempt', 'lockSha256', 'nixVersion')))
        passes = report.get('passes', [])
        if [entry.get('phase') for entry in passes] != ['cold', 'warm']:
            raise ValueError('Incomplete cold/warm measurement')
        for entry in [report['setup'], *passes]:
            if type(entry.get('seconds')) not in (int, float) or not math.isfinite(entry['seconds']) or entry['seconds'] < 0:
                raise ValueError('Invalid duration')
        if passes[0]['identity'] != passes[1]['identity']:
            raise ValueError('Inconsistent cold/warm tools')
        old = identities.setdefault(key[0], passes[0]['identity'])
        if old != passes[0]['identity']:
            raise ValueError('Tool or firmware identities differ within a lane')
        name = f'vm-tools-{key[0]}-{key[1]}'
        matching = [job for job in jobs if job.get('name') in (name, 'VM tool provisioning trial / ' + name)]
        if len(matching) != 1:
            raise ValueError('Missing or ambiguous native job')
        job = matching[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or str(job.get('run_id')) != report['runId'] or str(job.get('run_attempt')) != report['runAttempt']
                or job.get('head_sha') != report['proposalRevision']):
            raise ValueError('Native job does not match successful proposal/run/attempt')
        seconds = (datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
                   - datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))).total_seconds()
        if seconds < 0:
            raise ValueError('Invalid native job duration')
        if report['setup']['seconds'] + sum(entry['seconds'] for entry in passes) > seconds + 2:
            raise ValueError('Reported phases exceed complete native job')
        groups.setdefault(key[0], []).append((report, seconds))
    if seen != expected or len(bindings) != 1:
        raise ValueError('Require all nine matched measurements at one source/lock/run/attempt')
    image_sets = {provider: sorted({r['runner']['ImageVersion'] for r, _ in rows}) for provider, rows in groups.items()}
    medians = {provider: {
        'coldSeconds': statistics.median(r['passes'][0]['seconds'] for r, _ in rows),
        'warmSeconds': statistics.median(r['passes'][1]['seconds'] for r, _ in rows),
        'setupPlusColdSeconds': statistics.median(r['setup']['seconds'] + r['passes'][0]['seconds'] for r, _ in rows),
        'jobSeconds': statistics.median(seconds for _, seconds in rows),
        'coldReceivedBytes': statistics.median(r['passes'][0]['transport']['receivedBytes'] for r, _ in rows),
    } for provider, rows in groups.items()}
    comparable = len({tuple(images) for images in image_sets.values()}) == 1 and len(image_sets['nix']) == 1
    candidate = medians['nix']
    # A small noisy difference cannot authorize rollout. Require both apt lanes
    # to lose on end-to-end time and a material common-setup/cold improvement.
    faster = comparable and all(
        candidate['jobSeconds'] < medians[baseline]['jobSeconds']
        and candidate['setupPlusColdSeconds'] <= medians[baseline]['setupPlusColdSeconds'] * .9
        and medians[baseline]['setupPlusColdSeconds'] - candidate['setupPlusColdSeconds'] >= 5
        for baseline in ('apt', 'apt-minimal'))
    result = {'schema': 1, 'faster': faster, 'comparableRunnerImages': comparable,
              'binding': list(next(iter(bindings))), 'medians': medians, 'runnerImages': image_sets,
              'notes': ['Cold starts after common Determinate/image-tool setup; warm reuses the same runner.',
                        'This provisioning experiment excludes the preceding Docker build; full PR image/VM jobs exercise the post-build path.',
                        'Whole-job times include both passes and artifact handling; queue time is excluded.',
                        'Network counters include all runner traffic. Apt and Nix have different tool/firmware versions.',
                        'Rollout also requires successful image/VM checks and native maintainer authority.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    rows = ['| Provider | Cold s | Warm s | Setup + cold s | Complete job s |', '| --- | ---: | ---: | ---: | ---: |']
    for provider in PROVIDERS:
        m = medians[provider]
        rows.append('| ' + provider + ' | ' + ' | '.join(f'{m[k]:.2f}' for k in ('coldSeconds', 'warmSeconds', 'setupPlusColdSeconds', 'jobSeconds')) + ' |')
    text = 'Nix meets the measured speed gate: **' + str(faster).lower() + '**.\n\n' + '\n'.join(rows) + '\n\n' + '\n'.join(result['notes']) + '\n'
    output.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(text)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    mark = commands.add_parser('mark-start'); mark.add_argument('output', type=Path)
    run = commands.add_parser('run')
    run.add_argument('--provider', choices=PROVIDERS, required=True)
    run.add_argument('--repetition', type=int, choices=(1, 2, 3), required=True)
    run.add_argument('--start', type=Path, required=True); run.add_argument('--output', type=Path, required=True)
    summary = commands.add_parser('summarize')
    summary.add_argument('directory', type=Path); summary.add_argument('jobs', type=Path); summary.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(metrics.snapshot()) + '\n')
    elif args.command == 'run':
        benchmark(args.provider, args.repetition, args.start, args.output)
    else:
        summarize(args.directory, args.jobs, args.output)


if __name__ == '__main__':
    main()
