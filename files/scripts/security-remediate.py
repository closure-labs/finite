#!/usr/bin/env python3
"""Apply reviewed Fedora RPM security floors during the image build."""
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PROTECTED = ('kernel*', 'bootc*', 'rpm-ostree*', 'ostree*')
EVR = re.compile(r'[0-9]+:[A-Za-z0-9._+~^]+-[A-Za-z0-9._+~^]+')


def run(args):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE)
    if result.returncode:
        print(result.stdout, file=sys.stderr)
        result.check_returncode()
    return result.stdout.strip()


def protected(name):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in PROTECTED)


def load_policy(path):
    policy = json.loads(Path(path).read_text())
    if (set(policy) != {'schema', 'fedora', 'sourceImage', 'sourceRun', 'packages'}
            or type(policy['schema']) is not int or policy['schema'] != 1
            or type(policy['fedora']) is not int or policy['fedora'] != 44
            or type(policy['sourceRun']) is not int or policy['sourceRun'] <= 0
            or not re.fullmatch(r'ghcr\.io/closure-labs/finite@sha256:[a-f0-9]{64}', policy['sourceImage'])
            or not isinstance(policy['packages'], dict) or not policy['packages']):
        raise ValueError('Invalid security remediation policy')
    for name, entry in policy['packages'].items():
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.-]*', name) or protected(name)
                or not isinstance(entry, dict)
                or set(entry) != {'minimumEVR', 'advisories', 'source'}
                or not isinstance(entry['minimumEVR'], str) or not EVR.fullmatch(entry['minimumEVR'])
                or not entry['minimumEVR'].endswith('.fc44')
                or not isinstance(entry['advisories'], list) or not entry['advisories']
                or any(not isinstance(a, str) or not re.fullmatch(r'(?:CVE-\d{4}-\d+|FEDORA-\d{4}-[a-f0-9]+)', a) for a in entry['advisories'])
                or not isinstance(entry['source'], str)
                or not re.fullmatch(r'https://bodhi\.fedoraproject\.org/updates/FEDORA-\d{4}-[a-f0-9]+', entry['source'])):
            raise ValueError(f'Invalid security floor: {name}')
    return policy


def inventory(runner=None):
    runner = runner or run
    result = {}
    output = runner(['rpm', '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n'])
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) != 3:
            raise ValueError('Malformed RPM inventory record: ' + repr(line[:200]))
        name, evr, arch = fields
        # RPM's signing-key pseudo-package has no architecture. Preserve its
        # inventory record; it is not an installable remediation target.
        key_record = name == 'gpg-pubkey' and arch == '(none)'
        if not EVR.fullmatch(evr) or not (key_record or re.fullmatch(r'[A-Za-z0-9_]+', arch)):
            raise ValueError('Malformed RPM inventory record: ' + repr(line[:200]))
        result.setdefault(name, []).append((evr, arch))
    if not result:
        raise ValueError('Empty RPM inventory')
    return {name: sorted(values) for name, values in result.items()}


def compare(actual, floor):
    # Both strings are validated before interpolation into RPM's Lua evaluator.
    if not EVR.fullmatch(actual) or not EVR.fullmatch(floor):
        raise ValueError('Invalid RPM version')
    value = run(['rpm', '--eval', '%{lua:print(rpm.vercmp("' + actual + '", "' + floor + '"))}'])
    if value not in ('-1', '0', '1'):
        raise ValueError('RPM comparison failed')
    return int(value)


def remediate(policy):
    if run(['rpm', '--eval', '%{fedora}']) != str(policy['fedora']):
        raise ValueError('Security remediation requires the reviewed Fedora release')
    before = inventory()
    targets = {name: entry['minimumEVR'] for name, entry in policy['packages'].items() if name in before}
    outdated = {name: floor for name, floor in targets.items() if any(compare(evr, floor) < 0 for evr, _ in before[name])}
    if not outdated:
        print('Reviewed security RPM floors already satisfied; no repository access required')
        return
    # Fedora repositories only, including dependencies; retain upstream boot stack.
    run(['dnf5', '-y', '--refresh', '--disable-repo=*', '--enable-repo=fedora',
         '--enable-repo=updates', '--setopt=gpgcheck=1', '--setopt=*.gpgcheck=1',
         '--setopt=*.skip_if_unavailable=False', '--setopt=install_weak_deps=False',
         '--exclude=' + ','.join(PROTECTED), 'upgrade', '--no-allow-downgrade',
         *[f'{name} >= {floor}' for name, floor in sorted(outdated.items())]])
    after = inventory()
    if {n: v for n, v in before.items() if protected(n)} != {n: v for n, v in after.items() if protected(n)}:
        raise ValueError('Security transaction changed the protected boot stack')
    for name, floor in targets.items():
        if name not in after or any(compare(evr, floor) < 0 for evr, _ in after[name]):
            raise ValueError(f'Security floor not satisfied: {name} >= {floor}')
        if {arch for _, arch in before[name]} != {arch for _, arch in after[name]}:
            raise ValueError(f'Security transaction changed installed architectures: {name}')
    for name, entry in policy['packages'].items():
        if name in after and any(compare(evr, entry['minimumEVR']) < 0 for evr, _ in after[name]):
            raise ValueError(f'Security floor not satisfied for dependency: {name}')
    print('Reviewed security RPM floors satisfied')


if __name__ == '__main__':
    try:
        remediate(load_policy(Path(os.environ['CONFIG_DIRECTORY']) / 'scripts/security-remediation.json'))
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f'Security RPM remediation failed: {error}')
