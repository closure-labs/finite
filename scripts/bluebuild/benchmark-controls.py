#!/usr/bin/env python3
"""Validate declared diagnostic cohorts before setup or VM work."""
import argparse
import json
import os
from pathlib import Path
import re


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def controls(raw, env):
    if not raw:
        return None
    if len(raw.encode()) > 4096:
        raise ValueError('Oversized installer benchmark control')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'planSha256', 'pair', 'temperature', 'runnerImage', 'runtimeCohorts'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not matches('[0-9a-f]{64}', value['planSha256'])
            or value['pair'] not in ('cold-1', *(f'warm-{i}' for i in range(1, 6)))
            or value['temperature'] != value['pair'].split('-')[0]
            or not matches(r'[0-9]{8}\.[0-9]+\.[0-9]+', value['runnerImage'])
            or not isinstance(value['runtimeCohorts'], dict)
            or set(value['runtimeCohorts']) != {'fresh', 'upgrade'}
            or any(not matches('[0-9a-f]{64}', v) for v in value['runtimeCohorts'].values())):
        raise ValueError('Incomplete installer benchmark control')
    if env.get('FINITE_VALIDATION_ONLY') != 'true':
        raise ValueError('Benchmark controls require validation-only qualification')
    # Prepare and aggregate do no measured installer work and may use another
    # runner image. Phase checks run before Nix, disk cleanup or image transfer.
    if env.get('FINITE_BENCHMARK_PHASE') in ('fresh', 'upgrade'):
        if env.get('ImageVersion') != value['runnerImage']:
            raise ValueError('Runner image differs from the predeclared benchmark cohort')
    return value


def record(value, env):
    phase = env['FINITE_BENCHMARK_PHASE']
    document = {'schema': 1, 'kind': 'finite-installer-benchmark-control',
        'authorizesPublication': False, 'controls': value,
        'repository': env['GITHUB_REPOSITORY'], 'revision': env['GITHUB_SHA'],
        'runId': int(env['GITHUB_RUN_ID']), 'runAttempt': int(env['GITHUB_RUN_ATTEMPT']),
        'profile': env['PROFILE'], 'phase': phase,
        'mode': env.get('FINITE_INSTALLER_COMPRESSION', 'default'),
        'inputs': {name: env[name] for name in
                   ('CANDIDATE_DIGEST', 'PREVIOUS_DIGEST', 'BUILD_IDENTITY', 'SOURCE_REVISION')}}
    directory = Path('.bluebuild'); directory.mkdir(exist_ok=True)
    (directory / f'{env["PROFILE"]}-{phase}-benchmark.json').write_text(json.dumps(document, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    value = controls(os.environ.get('FINITE_INSTALLER_BENCHMARK', ''), os.environ)
    if args.record and value:
        record(value, os.environ)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        # Warm means an authenticated exact Nix checks snapshot restore. It
        # does not seed guests, reuse qualification, or cache Lorax runtimes.
        output.write('cache-mode=' + ('optimized' if value and value['temperature'] == 'warm' else 'none') + '\n')


if __name__ == '__main__':
    main()
