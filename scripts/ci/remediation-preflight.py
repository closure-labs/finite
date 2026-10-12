#!/usr/bin/env python3
"""Read Fedora repository availability; never install packages or claim scan clearance."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('remediation', ROOT / 'files/scripts/security-remediate.py')
remediation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remediation)
OBSERVE = ('python3-anyio', 'python3-msgpack', 'rclone', 'yq', 'podman', 'buildah', 'skopeo',
           'cosign', 'tailscale', 'gum', 'glow', 'toolbox', 'restic', 'containerd', 'runc', 'ipp-usb', 'uupd')
FEDORA_IMAGE = 'registry.fedoraproject.org/fedora@sha256:1ff9eb02e4e2d7fb1175becac7139b2960c4fdcccedce81c86ec25b98ef3124d'
FORMAT = '%{name}\t%{evr}\t%{arch}\t%{repoid}\t%{full_nevra}\n'


def run(args):
    return subprocess.check_output(args, text=True, timeout=600).strip()


def command(names):
    return ['dnf5', '--refresh', '--disable-repo=*', '--enable-repo=fedora', '--enable-repo=updates',
            '--setopt=gpgcheck=1', '--setopt=*.gpgcheck=1', '--setopt=*.skip_if_unavailable=False',
            'repoquery', '--available', '--arch=x86_64,noarch', '--queryformat', FORMAT, *sorted(names)]


def parse(output, names):
    packages = {name: [] for name in names}
    for line in output.splitlines():
        name, evr, arch, repository, nevra = line.split('\t')
        if ':' not in evr:
            evr = '0:' + evr
        if (name not in packages or not remediation.EVR.fullmatch(evr) or
                arch not in ('x86_64', 'noarch') or repository not in ('fedora', 'updates') or
                nevra != f'{name}-{evr}.{arch}'):
            raise ValueError('Unexpected Fedora repository query record')
        record = {'evr': evr, 'arch': arch, 'repository': repository, 'nevra': nevra}
        if record not in packages[name]:
            packages[name].append(record)
    return packages


def compare(actual, floor, runner):
    if not remediation.EVR.fullmatch(actual) or not remediation.EVR.fullmatch(floor):
        raise ValueError('Invalid RPM version')
    value = runner(['rpm', '--eval', '%{lua:print(rpm.vercmp("' + actual + '", "' + floor + '"))}'])
    if value not in ('-1', '0', '1'):
        raise ValueError('RPM comparison failed')
    return int(value)


def load_prerequisites(path):
    policy = json.loads(path.read_text())
    if (set(policy) != {'schema', 'fedora', 'sourceImage', 'packages'} or
            type(policy['schema']) is not int or policy['schema'] != 1 or
            type(policy['fedora']) is not int or policy['fedora'] != 44 or
            not re.fullmatch(r'ghcr\.io/closure-labs/finite@sha256:[a-f0-9]{64}', policy['sourceImage']) or
            not isinstance(policy['packages'], dict) or not policy['packages']):
        raise ValueError('Invalid scan-readiness prerequisites')
    for name, entry in policy['packages'].items():
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]*', name) or
                set(entry) != {'component', 'minimumUpstreamVersion', 'advisories'} or
                not isinstance(entry['component'], str) or not entry['component'].startswith('pkg:') or
                not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', entry['minimumUpstreamVersion']) or
                not isinstance(entry['advisories'], list) or not entry['advisories'] or
                any(not re.fullmatch(r'GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}', item)
                    for item in entry['advisories'])):
            raise ValueError('Invalid scan prerequisite for ' + name)
    return policy


def upstream_meets(evr, minimum, runner):
    if not remediation.EVR.fullmatch(evr) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', minimum):
        raise ValueError('Invalid upstream comparison')
    # Fedora epochs and release rebuilds cannot satisfy an upstream version fix.
    # RPM's comparator still handles version segments and prerelease markers.
    version = evr.split(':', 1)[1].rsplit('-', 1)[0]
    return compare('0:' + version + '-0', '0:' + minimum + '-0', runner) >= 0


def probe(policy, prerequisites, runner=None):
    runner = runner or run
    names = set(policy['packages']) | set(OBSERVE) | set(prerequisites['packages'])
    packages = parse(runner(command(names)), names)
    findings = []
    for name in sorted(names):
        floor = policy['packages'].get(name, {}).get('minimumEVR')
        records = packages[name]
        for record in records:
            record['meetsFloor'] = compare(record['evr'], floor, runner) >= 0 if floor else None
        status = ('missing' if not records else 'outdated' if floor and not any(
                  record['meetsFloor'] for record in records) else 'available')
        findings.append({'name': name, 'minimumEVR': floor, 'status': status,
                         'scannerResolution': 'unknown', 'available': records})
    floors_available = all(row['status'] == 'available' for row in findings if row['minimumEVR'])
    prerequisite_rows = []
    for name, entry in sorted(prerequisites['packages'].items()):
        records = [{**record, 'meetsUpstreamMinimum': upstream_meets(record['evr'], entry['minimumUpstreamVersion'], runner)}
                   for record in packages[name]]
        status = 'missing' if not records else 'available' if any(row['meetsUpstreamMinimum'] for row in records) else 'outdated'
        prerequisite_rows.append({'name': name, **entry, 'status': status, 'available': records, 'scannerResolution': 'unknown'})
    prerequisite_ready = all(row['status'] == 'available' for row in prerequisite_rows)
    ready = floors_available and prerequisite_ready
    return {'schema': 1, 'status': 'available' if ready else 'blocked',
            'queriedAt': datetime.now(timezone.utc).isoformat(), 'fedora': policy['fedora'],
            'sourceImage': policy['sourceImage'], 'architectures': ['x86_64', 'noarch'],
            'scannerResolution': 'unknown', 'findings': findings,
            'packageFloorsAvailable': floors_available, 'prerequisiteReady': prerequisite_ready,
            'prerequisites': prerequisite_rows,
            'limits': 'Metadata availability only; no RPM payload signature or transaction verification, '
                      'no installation, no multilib solver proof, and no new image vulnerability scan. '
                      'Even available prerequisites are not a passing security scan or proof of embedded fixes.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=ROOT / 'files/scripts/security-remediation.json')
    parser.add_argument('--prerequisites', type=Path, default=ROOT / 'scripts/ci/remediation-prerequisites.json')
    parser.add_argument('--container', required=True, help='Already-running pinned Fedora container ID or name')
    args = parser.parse_args(argv)
    report = {'schema': 1, 'status': 'error', 'scannerResolution': 'unknown'}
    code = 2
    try:
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise ValueError('Repository preflight is hosted-only')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', args.container):
            raise ValueError('Invalid Fedora container identifier')
        details = json.loads(run(['docker', 'inspect', args.container]))
        if (len(details) != 1 or details[0]['Config']['Image'] != FEDORA_IMAGE or
                details[0]['State']['Running'] is not True):
            raise ValueError('Preflight requires the exact pinned running Fedora container')
        runner = lambda command: run(['docker', 'exec', args.container, *command])
        release = dict(line.split('=', 1) for line in runner(['cat', '/etc/os-release']).splitlines()
                       if '=' in line and not line.startswith('#'))
        if (shlex.split(release.get('ID', '')) != ['fedora'] or
                shlex.split(release.get('VERSION_ID', '')) != ['44']):
            raise ValueError('Preflight requires Fedora 44')
        installed = remediation.inventory(runner)
        policy = remediation.load_policy(args.policy)
        prerequisites = load_prerequisites(args.prerequisites)
        if prerequisites['sourceImage'] != policy['sourceImage'] or prerequisites['fedora'] != policy['fedora']:
            raise ValueError('Prerequisites do not match the reviewed remediation baseline')
        report = probe(policy, prerequisites, runner)
        report['containerImage'] = FEDORA_IMAGE
        report['inventoryPackages'] = sum(len(records) for records in installed.values())
        report['inventoryParser'] = 'passed'
        report['rpmVersion'] = runner(['rpm', '--version'])
        report['dnfVersion'] = runner(['dnf5', '--version'])
        code = 0 if report['status'] == 'available' else 1
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        report.update(status='error', error=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
