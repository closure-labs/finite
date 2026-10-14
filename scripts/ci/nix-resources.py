#!/usr/bin/env python3
"""Choose bounded Nix concurrency from the CPU and RAM visible to this runner."""
import argparse
import json
import os
from pathlib import Path
import subprocess

GIB = 1024 ** 3


def budget(cpus, memory):
    if cpus < 1 or memory < 1:
        raise ValueError('CPU and memory capacity must be positive')
    # Reserve one GiB for the OS/daemon; allow three GiB per active builder.
    jobs = max(1, min(cpus, (memory - GIB) // (3 * GIB)))
    cores = max(1, cpus // jobs)
    evaluation = max(1, min(cpus, (memory - GIB) // (2 * GIB)))
    return {'max-jobs': jobs, 'cores': cores, 'eval-cores': evaluation}


def detect(proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    cpus = len(os.sched_getaffinity(0))
    memory = next(int(line.split()[1]) * 1024 for line in
                  (proc / 'meminfo').read_text().splitlines() if line.startswith('MemTotal:'))
    # Respect v2 limits on the current cgroup and its ancestors. Affinity
    # already accounts for cpusets; quota may impose a smaller CPU budget.
    directory = cgroup
    membership = proc / 'self/cgroup'
    if membership.exists():
        for line in membership.read_text().splitlines():
            if line.startswith('0::'):
                relative = line[3:].lstrip('/')
                if '..' not in Path(relative).parts:
                    directory = cgroup / relative
                break
    directories = [directory]
    while directories[-1] != cgroup:
        directories.append(directories[-1].parent)
    for directory in directories:
        cpu_limit = directory / 'cpu.max'
        if cpu_limit.exists():
            quota, period = cpu_limit.read_text().split()
            if quota != 'max':
                cpus = min(cpus, max(1, int(quota) // int(period)))
        memory_limit = directory / 'memory.max'
        if memory_limit.exists():
            value = memory_limit.read_text().strip()
            if value != 'max':
                memory = min(memory, int(value))
    return cpus, memory


def configuration(settings):
    return '\n'.join(f'{name} = {value}' for name, value in settings.items()) + '\nextra-experimental-features = parallel-eval\n'


def verify(settings, nix):
    # Print only selected settings; full config can contain GitHub access tokens.
    version = subprocess.check_output([nix, '--version'], text=True, timeout=15).strip()
    if 'Determinate' not in version:
        raise ValueError('Expected the installed Determinate Nix client')
    actual = json.loads(subprocess.check_output([nix, 'config', 'show', '--json'], text=True, timeout=15))
    for name, expected in settings.items():
        if actual.get(name, {}).get('value') != expected:
            raise ValueError(f'Nix did not apply {name}={expected}')
    if 'parallel-eval' not in actual.get('experimental-features', {}).get('value', []):
        raise ValueError('Parallel evaluation feature is not enabled')
    print(version)
    print(json.dumps(settings, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--nix', default='nix')
    args = parser.parse_args()
    cpus, memory = detect()
    settings = budget(cpus, memory)
    if args.verify:
        verify(settings, args.nix)
    elif args.config:
        print(configuration(settings), end='')
    else:
        output = os.environ['GITHUB_OUTPUT']
        with open(output, 'a') as stream:
            for name, value in settings.items():
                stream.write(f'{name}={value}\n')
        summary = f'Nix capacity: {cpus} CPUs, {memory // (1024 ** 2)} MiB RAM; ' + json.dumps(settings)
        print(summary)
        if path := os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(path, 'a') as stream:
                stream.write(summary + '\n')


if __name__ == '__main__':
    main()
