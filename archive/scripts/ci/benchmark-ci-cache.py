#!/usr/bin/env python3
"""Measure cache setup and cold/warm tool realization on GitHub-hosted runners."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
MODES = ('baseline', 'optimized', 'none')
TOOLS = ('image-tools', 'scanner-tools', 'ci-repository-security-audit')


def transport_bytes():
    totals = {'receivedBytes': 0, 'sentBytes': 0}
    for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
        interface, fields = line.split(':', 1)
        if interface.strip() == 'lo':
            continue
        values = fields.split()
        totals['receivedBytes'] += int(values[0])
        totals['sentBytes'] += int(values[8])
    return totals


def snapshot():
    disk = shutil.disk_usage('/nix' if Path('/nix').exists() else '/')
    return {'monotonicSeconds': time.monotonic(), 'transport': transport_bytes(),
            'filesystem': {'totalBytes': disk.total, 'usedBytes': disk.used, 'freeBytes': disk.free}}


def delta(before, after):
    return {'seconds': after['monotonicSeconds'] - before['monotonicSeconds'],
            'transport': {key: after['transport'][key] - value for key, value in before['transport'].items()},
            'filesystemUsedBytesDelta': after['filesystem']['usedBytes'] - before['filesystem']['usedBytes']}


def store_metrics(path=None):
    args = ['nix', 'path-info', '--json', '--json-format', '1']
    args += ['--closure-size', str(path)] if path else ['--all']
    records = json.loads(subprocess.check_output(args, text=True, timeout=180))
    if not isinstance(records, dict):
        raise ValueError('Unexpected Nix path-info format')
    if path:
        if len(records) != 1:
            raise ValueError('Expected one tool closure')
        return next(iter(records.values()))['closureSize']
    return {'paths': len(records), 'narBytes': sum(item['narSize'] for item in records.values())}


def measure(tool, phase):
    store_before = store_metrics()
    before = snapshot()
    result = subprocess.run(['nix', 'build', '--file', 'lib/ci-tools.nix', tool,
                             '--no-link', '--print-out-paths'], text=True, stdout=subprocess.PIPE,
                            check=True, timeout=1800)
    after = snapshot()
    paths = result.stdout.splitlines()
    if len(paths) != 1 or not paths[0].startswith('/nix/store/') or not Path(paths[0]).is_dir():
        raise ValueError('Invalid realized tool output')
    output = paths[0]
    store_after = store_metrics()
    return dict(delta(before, after), phase=phase, output=output, storeBefore=store_before,
                storeAfter=store_after, addedStoreNarBytes=store_after['narBytes'] - store_before['narBytes'],
                closureNarBytes=store_metrics(output))


def benchmark(mode, tool, repetition, start, output):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Run the benchmark in its GitHub-hosted workflow')
    setup_after = snapshot()
    report = {'schema': 1, 'mode': mode, 'tool': tool, 'repetition': repetition,
              'revision': os.environ['GITHUB_SHA'], 'runId': os.environ['GITHUB_RUN_ID'],
              'runner': {key: os.environ.get(key) for key in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')},
              'lockSha256': hashlib.sha256((ROOT / 'flake.lock').read_bytes()).hexdigest(),
              'setup': delta(json.loads(start.read_text()), setup_after), 'passes': [],
              'measurementNotes': ['Cold is a fresh runner after the configured cache restore; warm reuses that runner.',
                                   'Transport bytes are runner interface counters, including all concurrent traffic.',
                                   'Closure and store diagnostics are excluded from realization timings.',
                                   'Setup includes Nix installation, cache configuration and restore; post-job save is excluded.']}
    try:
        report['nixVersion'] = subprocess.check_output(['nix', '--version'], text=True, timeout=30).strip()
        for phase in ('cold', 'warm'):
            report['passes'].append(measure(tool, phase))
        report['setupPlusColdSeconds'] = report['setup']['seconds'] + report['passes'][0]['seconds']
        report['status'] = 'success'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


def summarize(directory, output):
    reports = [json.loads(path.read_text()) for path in sorted(directory.rglob('benchmark.json'))]
    expected = {(mode, tool, rep) for mode in MODES for tool in TOOLS for rep in (1, 2, 3)}
    seen, groups = set(), {}
    revisions = set()
    for report in reports:
        identity = (report['mode'], report['tool'], report['repetition'])
        if identity not in expected or identity in seen or report.get('schema') != 1:
            raise ValueError('Unexpected or duplicate benchmark report')
        seen.add(identity)
        revisions.add((report['revision'], report['lockSha256'], report['runId']))
        groups.setdefault(identity[:2], []).append(report)
    if seen != expected or len(revisions) != 1:
        raise ValueError('Benchmark requires three matched repetitions of every mode/tool at one revision')
    rows = ['| Tool | Mode | Successful runs | Setup median s | Setup + cold median s | Warm median s | Cold received median bytes |',
            '|---|---|---:|---:|---:|---:|---:|']
    failed = False
    for (mode, tool), entries in sorted(groups.items()):
        successful = [entry for entry in entries if entry['status'] == 'success']
        failed |= len(successful) != 3
        def median_values(values):
            return f'{statistics.median(values):.2f}' if values else '—'
        rows.append('| ' + ' | '.join([tool, mode, str(len(successful)),
                    median_values([entry['setup']['seconds'] for entry in successful]),
                    median_values([entry['setupPlusColdSeconds'] for entry in successful]),
                    median_values([entry['passes'][1]['seconds'] for entry in successful]),
                    median_values([entry['passes'][0]['transport']['receivedBytes'] for entry in successful])]) + ' |')
    content = ('Cache benchmark at `' + next(iter(revisions))[0] + '`\n\n' + '\n'.join(rows)
               + '\n\nCold starts after cache restore; warm reuses the same runner. Network counters include concurrent traffic. '
               'Post-job cache save overhead is excluded; inspect complete job timings before enabling a cache lane.\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as summary:
            summary.write(content)
    if failed:
        raise ValueError('Some benchmark runs failed; partial medians are diagnostic only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='operation', required=True)
    mark = subparsers.add_parser('mark-start')
    mark.add_argument('output', type=Path)
    run = subparsers.add_parser('run')
    run.add_argument('mode', choices=MODES)
    run.add_argument('tool', choices=TOOLS)
    run.add_argument('repetition', type=int, choices=(1, 2, 3))
    run.add_argument('start', type=Path)
    run.add_argument('output', type=Path)
    summary = subparsers.add_parser('summarize')
    summary.add_argument('directory', type=Path)
    summary.add_argument('output', type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.operation == 'mark-start':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(snapshot()) + '\n')
    elif args.operation == 'run':
        benchmark(args.mode, args.tool, args.repetition, args.start, args.output)
    else:
        summarize(args.directory, args.output)


if __name__ == '__main__':
    main()
