#!/usr/bin/env python3
"""Compare identical Home Manager proof matrices, without image or VM work."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
import time

MODES = ('serial', 'paired')
ORDER = ('serial', 'paired', 'paired', 'serial', 'serial', 'paired')
GIB = 1024**3


def fingerprint(value):
    if (not isinstance(value, dict) or set(value) != {'cases', 'paths', 'aggregateDrvPath', 'checkNames'}
            or not isinstance(value['cases'], list) or not 1 <= len(value['cases']) <= 128
            or not isinstance(value['paths'], list) or len(value['paths']) != len(value['cases'])
            or any(not isinstance(p, str) or not re.fullmatch(r'/nix/store/[a-z0-9]{32}-.+\.drv', p)
                   for p in value['paths']) or any(not isinstance(p, dict) for p in value['cases'])
            or not isinstance(value['aggregateDrvPath'], str)
            or not re.fullmatch(r'/nix/store/[a-z0-9]{32}-finite-ci-checks\.drv', value['aggregateDrvPath'])
            or not isinstance(value['checkNames'], list) or not 1 <= len(value['checkNames']) <= 128
            or any(not isinstance(p, str) for p in value['checkNames'])
            or len(set(value['checkNames'])) != len(value['checkNames'])):
        raise ValueError('Invalid proof matrix; every case requires one derivation')
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def assess(rows):
    warm = [r for r in rows if not r['seed']]
    complete = ([r['mode'] for r in warm] == list(ORDER) and len(rows) == 7
                and rows[0]['seed'] and rows[0]['mode'] == 'public')
    correct = complete and all(type(r.get('status')) is int and r['status'] == 0
                               and r.get('fingerprint') and not r.get('error') for r in rows)
    identical = correct and len({r['fingerprint'] for r in rows}) == 1
    timed = correct and all(type(r.get('seconds')) in (float, int) and 0 < r['seconds'] <= 1000
                            and type(r.get('maxRSSKiB')) is int and 0 < r['maxRSSKiB'] <= 6 * GIB // 1024
                            for r in rows)
    medians = {m: statistics.median(r['seconds'] for r in warm if r['mode'] == m)
               for m in MODES} if timed else None
    saved = medians['serial'] - medians['paired'] if medians else None
    return {'complete': complete, 'identicalProofMatrices': bool(identical),
            'measurementComplete': bool(timed), 'warmMedianSeconds': medians,
            'secondsSaved': saved,
            'performanceGatePassed': bool(identical and timed and saved >= 10
                                          and saved >= medians['serial'] * .1),
            'authorizesPublication': False}


def command(mode, number, metrics, env=os.environ):
    unit = f'finite-home-evaluation-{env["GITHUB_RUN_ID"]}-{env["GITHUB_RUN_ATTEMPT"]}-{number}'
    nix = shutil.which('nix')
    if not nix:
        raise ValueError('Installed Nix client required')
    argv = ['sudo', '--preserve-env=NIX_CONFIG,NIX_SSL_CERT_FILE', 'systemd-run', '--quiet',
            '--wait', '--pipe', '--service-type=exec', '--unit=' + unit,
            '--property=MemoryMax=6G', '--property=MemorySwapMax=0', '--property=RuntimeMaxSec=900',
            '--property=NoNewPrivileges=yes', '--property=CapabilityBoundingSet=',
            '--uid=' + str(os.getuid()), '--gid=' + str(os.getgid()),
            '--working-directory=' + str(Path.cwd()), '--setenv=PATH=' + env['PATH'],
            '--setenv=HOME=' + env['HOME'], '--setenv=NIX_CONFIG', '--setenv=NIX_SSL_CERT_FILE',
            '/usr/bin/time', '--quiet', '--format={"maxRSSKiB":%M,"status":%x}',
            '--output=' + str(metrics.resolve()), nix, 'eval', '--accept-flake-config',
            '--no-update-lock-file', '--no-write-lock-file', '--no-eval-cache', '--json',
            ]
    if mode == 'public':
        argv += ['.#ci-checks', '--apply', 'c: builtins.deepSeq c.drvPath { aggregateDrvPath = c.drvPath; checkNames = c.checkNames; cases = c.homeProofCases; paths = c.homeProofPaths; }']
    elif mode == 'preflight':
        argv += ['--impure', '--file', 'lib/ci-home-proofs.nix', '--apply', 'f: f { preflight = true; }']
    else:
        argv += ['--impure', '--file', 'lib/ci-home-proofs.nix', '--apply',
                 'f: f { strategy = "' + mode + '"; }']
    return unit, argv


def measure(mode, number, directory):
    metrics = directory / f'metrics-{number}.json'
    unit, argv = command(mode, number, metrics)
    row = {'mode': mode, 'seed': number == 0, 'status': None, 'seconds': None,
           'maxRSSKiB': None, 'fingerprint': None}
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(argv, stdout=output, timeout=930, check=False)
            row['status'] = result.returncode
            if result.returncode == 0:
                output.seek(0)
                raw = output.read(1024**2 + 1)
                if len(raw) > 1024**2:
                    raise ValueError('Oversized proof matrix')
                value = json.loads(raw)
                if mode == 'preflight':
                    if (value.get('revision') != os.environ.get('GITHUB_SHA')
                            or type(value.get('proofCount')) is not int or not 1 <= value['proofCount'] <= 128
                            or not isinstance(value.get('checkNames'), list) or not value['checkNames']):
                        raise ValueError('Diagnostic preflight differs from the pinned checkout or matrix')
                    row['preflight'] = value
                else:
                    row.update(fingerprint=fingerprint(value), cases=len(value['cases']))
                    (directory / f'proof-matrix-{number}.json').write_text(json.dumps(value, indent=2) + '\n')
            if metrics.is_file() and metrics.stat().st_size <= 4096:
                measured = json.loads(metrics.read_text())
                if measured.get('status') == row['status']:
                    row['maxRSSKiB'] = measured.get('maxRSSKiB')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        row['error'] = str(error)[:500]
    finally:
        # Also stop a service if interruption killed the waiting launcher. The
        # service has its own runtime bound and cgroup-wide process cleanup.
        try:
            subprocess.run(['sudo', 'systemctl', 'stop', unit], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            row['error'] = 'Service cleanup failed: ' + str(error)[:500]
        row['seconds'] = round(time.monotonic() - started, 3)
        (directory / f'sample-{number}.json').write_text(json.dumps(row, indent=2) + '\n')
    return row


def main(env=os.environ):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Use the read-only hosted manual evaluation trial')
    directory = Path('.bluebuild/home-evaluation')
    directory.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'finite-home-evaluation-trial', 'authorizesPublication': False,
              'revision': env['GITHUB_SHA'], 'runId': env['GITHUB_RUN_ID'],
              'runAttempt': env['GITHUB_RUN_ATTEMPT'], 'samples': [],
              'runner': {k: env.get(k) for k in ('ImageVersion', 'RUNNER_OS', 'RUNNER_ARCH')},
              'lockSha256': hashlib.sha256(Path('flake.lock').read_bytes()).hexdigest(),
              'nixVersion': subprocess.check_output(['nix', '--version'], text=True, timeout=15).strip(),
              'limitations': ['One runner and checkout; seed cost is retained but excluded from warm medians.',
                             'Source/derivation caches are warm; the flake evaluation cache is disabled.',
                             'Trial stage times include service setup; native complete-job costs remain separate.',
                             'Maximum RSS covers the evaluator; the complete service cgroup is capped at 6 GiB with no swap.',
                             'The public pinned aggregate and image/guest behavior remain independently checked.']}
    try:
        report['preflight'] = measure('preflight', -1, directory)
        probe = report['preflight']
        if (probe['status'] != 0 or probe.get('error')
                or type(probe.get('maxRSSKiB')) is not int or not 0 < probe['maxRSSKiB'] <= 6 * GIB // 1024):
            raise ValueError('Diagnostic preflight failed before seed evaluation')
        for number, mode in enumerate(('public',) + ORDER):
            row = measure(mode, number, directory)
            report['samples'].append(row)
            if row['status'] != 0 or row.get('error'):
                raise ValueError('Evaluation failed; retain the partial result')
    finally:
        report['assessment'] = assess(report['samples'])
        (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report['assessment']))


if __name__ == '__main__':
    main()
