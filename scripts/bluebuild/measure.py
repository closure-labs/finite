#!/usr/bin/env python3
"""Record bounded stage timings without changing command output or exit status."""
from datetime import datetime, timezone
import json
import hashlib
import shutil
import os
from pathlib import Path
import subprocess
import sys
import time


def identity(directory, env=os.environ):
    profile = env.get('PROFILE', 'ci')
    candidate = {}
    if profile in ('finite', 'finite-dev'):
        path = directory / (profile + '-publication.json')
        if path.is_file() and path.stat().st_size <= 64 * 1024:
            try:
                candidate = json.loads(path.read_text())
            except ValueError:
                pass
    locks = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
             for name in ('flake.lock', 'devenv.lock') if Path(name).is_file()}
    return {'schema': 1, 'kind': 'finite-stage-timing', 'authorizesPublication': False,
            'repository': env.get('GITHUB_REPOSITORY'), 'runId': env.get('GITHUB_RUN_ID'),
            'runAttempt': env.get('GITHUB_RUN_ATTEMPT'), 'revision': env.get('GITHUB_SHA'),
            'jobName': env.get('FINITE_TIMING_JOB_NAME') or env.get('GITHUB_JOB'),
            'phase': env.get('PHASE'),
            'profile': profile, 'sourceRevision': env.get('SOURCE_REVISION') or candidate.get('sourceRevision'),
            'candidateDigest': env.get('CANDIDATE_DIGEST'),
            'buildIdentity': env.get('BUILD_IDENTITY') or candidate.get('buildIdentity'),
            'runner': {key: env.get(key) for key in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')},
            'lockSha256': locks,
            'toolCohort': {'pythonExecutable': str(Path(sys.executable).resolve()),
                           'nixExecutable': str(Path(shutil.which('nix')).resolve()) if shutil.which('nix') else None,
                           'vmManifest': env.get('FINITE_VM_TOOLS_MANIFEST'),
                           'firmwareDirectory': env.get('FINITE_VM_FIRMWARE_DIR')}}


def network_bytes():
    try:
        for route in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = route.split()
            if fields[1] == '00000000':
                statistics = Path('/sys/class/net') / fields[0] / 'statistics'
                return {name: int((statistics / name).read_text()) for name in ('rx_bytes', 'tx_bytes')}
    except (OSError, ValueError, IndexError):
        pass
    return {}


def main():
    name, *command = sys.argv[1:]
    started = datetime.now(timezone.utc).isoformat()
    before = time.monotonic()
    network_before = network_bytes()
    status = 127
    try:
        status = subprocess.run(command, check=False).returncode
    finally:
        directory = Path('.bluebuild')
        directory.mkdir(exist_ok=True)
        network_after = network_bytes()
        traffic = {name: max(0, value - network_before[name]) for name, value in network_after.items()
                   if name in network_before}
        with (directory / (os.environ.get('PROFILE', 'ci') + '-timings.jsonl')).open('a') as output:
            print(json.dumps({**identity(directory), 'stage': name, 'startedAt': started,
                              'seconds': round(time.monotonic() - before, 3),
                              'status': status, 'runnerNetworkDelta': traffic}), file=output)
    return status if status >= 0 else 128 - status


if __name__ == '__main__':
    raise SystemExit(main())
