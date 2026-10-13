#!/usr/bin/env python3
"""Read-only candidate VM observations with explicit headless coverage limits."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

LIMIT = 2 * 1024 * 1024


def command(args):
    with tempfile.TemporaryFile() as output:
        subprocess.run(args, stdout=output, check=True, timeout=30)
        output.seek(0, 2)
        if output.tell() > LIMIT:
            raise ValueError('Guest observations exceed their output bound')
        output.seek(0)
        return output.read().decode('utf-8')


def observations(enforcement, kernel_enforcement, permissive, processes, listeners, profile):
    if enforcement.strip() != 'Enforcing' or kernel_enforcement.strip() != '1':
        raise ValueError('Candidate SELinux is not enforcing in userspace and kernel')
    permissive_types = sorted(set(re.findall(r'\b[a-zA-Z0-9_]+_t\b', permissive)))
    if 'sshd_t' in permissive_types:
        raise ValueError('SSH fixture domain must enforce SELinux')
    rows = []
    for line in processes.splitlines():
        fields = line.split(None, 2)
        if (len(fields) != 3 or not fields[1].isascii() or not fields[1].isdigit()
                or not re.fullmatch(r'[^\s:]+:[^\s:]+:[A-Za-z0-9_]+_t:[^\s]+', fields[0])):
            raise ValueError('Malformed or unlabelled candidate process observation')
        rows.append({'pid': int(fields[1]), 'context': fields[0], 'command': fields[2]})
    if (not rows or len(rows) > 8192 or not any(row['pid'] == 1 for row in rows)
            or not any(row['command'] == 'sshd' and row['context'].split(':')[2] == 'sshd_t' for row in rows)):
        raise ValueError('Candidate process inventory lacks init or confined SSH fixture')
    sockets = []
    for line in listeners.splitlines():
        fields = line.split(None, 6)
        if len(fields) < 6 or fields[0] not in ('tcp', 'udp') or fields[1] not in ('LISTEN', 'UNCONN'):
            raise ValueError('Malformed candidate listener observation')
        sockets.append({'protocol': fields[0], 'state': fields[1], 'local': fields[4],
                        'peer': fields[5], 'owners': fields[6] if len(fields) == 7 else 'unknown'})
    if not sockets or len(sockets) > 4096:
        # SSH has just succeeded. An empty list is a collection fault, not proof
        # that the guest has no exposed services.
        raise ValueError('Candidate listener inventory is empty or excessive')
    if profile not in ('bluefin-generic', 'bluefin-next', 'bluefin-dx-generic', 'bluefin-dx-next'):
        raise ValueError('Unknown guest profile')
    return {'schema': 1, 'status': 'pass', 'profile': profile,
            'checks': {'selinuxEnforcing': True, 'permissiveDomainsCollected': True,
                       'processDomainsCollected': True, 'listenersCollected': True, 'sshConfined': True},
            'selinux': {'mode': 'Enforcing', 'kernelEnforce': 1, 'permissiveDomains': permissive_types},
            'processes': rows, 'listeners': sockets,
            'desktop': {'graphicalSession': 'not-assessed', 'hardware': 'not-assessed',
                        'rootlessIsolation': 'not-assessed', 'listenerReview': 'not-assessed'},
            'physicalHardwareAssessed': False,
            'limits': ['Process labels and enforcement do not prove application exploit mitigation.',
                       'Unconfined domains are retained, not described as confined.',
                       'The SSH listener is an acceptance fixture; actual desktop listeners require review.']}


def main():
    try:
        result = observations(command(['getenforce']), Path('/sys/fs/selinux/enforce').read_text(),
                              command(['semanage', 'permissive', '-l']),
                              command(['ps', '-e', '-o', 'label=,pid=,comm=']),
                              command(['ss', '-H', '-lntup']),
                              Path('/usr/share/finite/build-profile').read_text().strip())
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'schema': 1, 'status': 'error', 'error': str(error),
                          'physicalHardwareAssessed': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
