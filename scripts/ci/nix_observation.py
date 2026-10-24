"""Small native observations; these receipts never authorize publication."""
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import time
import shutil

DIRECTORY = Path('.bluebuild')
MAX_BYTES = 65536


def identity(env):
    executable = shutil.which('nix')
    return {'schema': 1, 'kind': 'finite-nix-observation', 'authorizesPublication': False,
            'repository': env.get('GITHUB_REPOSITORY'), 'runId': env.get('GITHUB_RUN_ID'),
            'runAttempt': env.get('GITHUB_RUN_ATTEMPT'),
            'revision': env.get('FINITE_OBSERVATION_REVISION') or env.get('GITHUB_SHA'),
            'checkoutRevision': env.get('GITHUB_SHA'),
            'jobName': env.get('GITHUB_JOB'), 'workflowRef': env.get('GITHUB_WORKFLOW_REF'),
            'runner': {key: env.get(key) for key in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')},
            'toolCohort': {'pythonExecutable': str(Path(sys.executable).resolve()),
                           'nixExecutable': str(Path(executable).resolve()) if executable else None,
                           'lockSha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                                          for name in ('flake.lock', 'devenv.lock') if Path(name).is_file()}}}


def write(name, value):
    raw = json.dumps(value, sort_keys=True) + '\n'
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('Oversized Nix observation')
    DIRECTORY.mkdir(exist_ok=True)
    target = DIRECTORY / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(raw)
    temporary.replace(target)


def setup(command, env=os.environ):
    # Existing source checks and explicit diagnostics retain setup observations.
    if env.get('GITHUB_JOB') != 'checks' and env.get('FINITE_NIX_OBSERVATION') != 'true':
        return
    target = DIRECTORY / 'nix-setup.json'
    if command == 'setup-start':
        record = {**identity(env), 'startedAt': datetime.now(timezone.utc).isoformat(),
                  'monotonicStart': time.monotonic(), 'seconds': None, 'status': None,
                  'cache': None}
    else:
        if not target.is_file() or target.stat().st_size > MAX_BYTES:
            raise ValueError('Missing or oversized Nix setup observation')
        record = json.loads(target.read_text())
        if any(record.get(key) != value for key, value in identity(env).items() if key != 'toolCohort'):
            raise ValueError('Nix setup observation differs from this job')
        if command == 'cache-selection':
            # Empty restored keys do not distinguish a miss, disabled restore or
            # an interrupted restore. Preserve that uncertainty explicitly.
            record['cache'] = {key: env.get(key) or None for key in
                               ('STORE_KEY', 'SOURCE_KEY', 'STORE_HIT', 'SOURCE_HIT')}
        elif command == 'setup-finish':
            record['seconds'] = round(time.monotonic() - record.pop('monotonicStart'), 3)
            record['status'] = env.get('SETUP_STATUS') or None
            record['toolCohort'] = identity(env)['toolCohort']
        else:
            raise ValueError('Unknown Nix setup observation command')
    write('nix-setup.json', record)


if __name__ == '__main__':
    setup(sys.argv[1])
