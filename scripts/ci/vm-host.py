#!/usr/bin/env python3
"""Check KVM before expensive qualification work and retain bounded host evidence."""
import argparse
from datetime import datetime, timezone
import errno
import fcntl
import json
import os
from pathlib import Path
import platform
import runpy
import stat


def probe(device=Path('/dev/kvm')):
    # Linux's stable KVM API: create and close an empty VM, without a vCPU,
    # guest RAM, firmware or guest execution. Existence alone is insufficient.
    result = {'usable': False, 'apiVersion': None, 'emptyVmCreated': False,
              'stage': 'device', 'error': None}
    try:
        if not stat.S_ISCHR(device.stat().st_mode):
            result['error'] = 'not-character-device'
            return result
        result['stage'] = 'open'
        descriptor = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        try:
            result['stage'] = 'api-version'
            result['apiVersion'] = fcntl.ioctl(descriptor, 0xAE00, 0)
            if result['apiVersion'] != 12:
                result['error'] = 'unsupported-api-version'
                return result
            result['stage'] = 'create-empty-vm'
            vm = fcntl.ioctl(descriptor, 0xAE01, 0)
            os.close(vm)
            result['emptyVmCreated'] = True
        finally:
            os.close(descriptor)
        result.update(usable=True, stage='complete')
    except OSError as error:
        result['error'] = errno.errorcode.get(error.errno, 'unknown-os-error')
    return result


def capacity():
    result = {'effectiveCpuCount': None, 'effectiveMemoryBytes': None,
              'cpuModel': None, 'error': None}
    try:
        detect = runpy.run_path(str(Path(__file__).with_name('nix-resources.py')))['detect']
        result['effectiveCpuCount'], result['effectiveMemoryBytes'] = detect()
    except (OSError, ValueError, StopIteration) as error:
        # Capacity is observation, not a new resource eligibility threshold.
        result['error'] = type(error).__name__
    try:
        with Path('/proc/cpuinfo').open() as stream:
            lines = stream.read(65536).splitlines()
        result['cpuModel'] = next((line.partition(':')[2].strip()[:256] for line in lines
                                   if line.startswith('model name')), None)
    except OSError:
        pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    kvm = probe()
    record = {'schema': 1, 'kind': 'finite-vm-host', 'authorizesPublication': False,
              'observedAt': datetime.now(timezone.utc).isoformat(),
              'repository': os.environ.get('GITHUB_REPOSITORY'),
              'runId': os.environ.get('GITHUB_RUN_ID'),
              'runAttempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'revision': os.environ.get('GITHUB_SHA'),
              'sourceRevision': os.environ.get('SOURCE_REVISION'),
              'candidateDigest': os.environ.get('CANDIDATE_DIGEST'),
              'buildIdentity': os.environ.get('BUILD_IDENTITY'),
              'profile': os.environ.get('PROFILE'), 'phase': os.environ.get('PHASE'),
              'runner': {name: os.environ.get(name) for name in
                         ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')},
              'host': {'kernel': platform.release(), 'architecture': platform.machine(),
                       **capacity()},
              'expectedGuest': {'cpus': 2, 'memoryMiB': 4096, 'machine': 'q35',
                                'smm': True, 'accelerator': 'kvm'},
              'kvm': kvm}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print('Qualification KVM preflight: ' + json.dumps(kvm, sort_keys=True))
    return 0 if kvm['usable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
