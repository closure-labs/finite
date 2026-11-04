#!/usr/bin/env python3
"""Read-only candidate VM observations with explicit headless coverage limits."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

LIMIT = 2 * 1024 * 1024
ERROR_ROW_LIMIT = 512
PROCESS_STATES = frozenset('RSDZTtWXxKPI')
DEAD_STATES = frozenset('ZXx')


class ProcessObservationError(ValueError):
    def __init__(self, number, row):
        super().__init__('Malformed or unlabelled candidate process observation')
        # comm contains process names, never command arguments. Bound the row
        # before retaining it so a collection failure remains actionable.
        self.details = {'stage': 'processes', 'rowNumber': number,
                        'row': row[:ERROR_ROW_LIMIT], 'rowLength': len(row),
                        'truncated': len(row) > ERROR_ROW_LIMIT}


def command(args):
    with tempfile.TemporaryFile() as output:
        subprocess.run(args, stdout=output, check=True, timeout=30)
        output.seek(0, 2)
        if output.tell() > LIMIT:
            raise ValueError('Guest observations exceed their output bound')
        output.seek(0)
        return output.read().decode('utf-8')


def observations(enforcement, kernel_enforcement, permissive, processes, listeners, profile, *, process_format='legacy'):
    if process_format not in ('legacy', 'state-threads'):
        raise ValueError('Unknown process observation format')
    if enforcement.strip() != 'Enforcing' or kernel_enforcement.strip() != '1':
        raise ValueError('Candidate SELinux is not enforcing in userspace and kernel')
    permissive_types = sorted(set(re.findall(r'\b[a-zA-Z0-9_]+_t\b', permissive)))
    if 'sshd_t' in permissive_types:
        raise ValueError('SSH fixture domain must enforce SELinux')
    rows = []
    seen = set()
    for number, line in enumerate(processes.splitlines(), 1):
        fields = line.split(None, 4 if process_format == 'state-threads' else 2)
        if (len(fields) != (5 if process_format == 'state-threads' else 3)
                or not fields[1].isascii() or not fields[1].isdigit()):
            raise ProcessObservationError(number, line)
        row = {'pid': int(fields[1]), 'context': fields[0], 'command': fields[-1]}
        labelled = re.fullmatch(r'[^\s:]+:[^\s:]+:[A-Za-z0-9_]+_t:[^\s]+', fields[0])
        if process_format == 'state-threads':
            if (not 0 < row['pid'] <= 2**31 - 1 or row['pid'] in seen
                    or fields[2] not in PROCESS_STATES or not fields[3].isascii()
                    or not fields[3].isdigit() or not 0 < int(fields[3]) <= 2**31 - 1):
                raise ProcessObservationError(number, line)
            row.update(state=fields[2], nlwp=int(fields[3]))
            # A zombie group leader can still have live threads. Grant no
            # exception unless the state is explicitly Z and only it remains.
            exited = row['state'] == 'Z' and row['nlwp'] == 1 and row['context'] in ('-', '?')
            if not labelled and not exited:
                raise ProcessObservationError(number, line)
        elif not labelled:
            # Legacy receipts contain no state/thread proof: keep their strict
            # label handling and never infer an exception from comm text.
            raise ProcessObservationError(number, line)
        seen.add(row['pid'])
        rows.append(row)
    live = [row for row in rows if row.get('state') not in DEAD_STATES]
    if (not rows or len(rows) > 8192 or not any(row['pid'] == 1 for row in live)
            or not any(row['command'] == 'sshd' and row['context'].split(':')[2] == 'sshd_t' for row in live)):
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
    # Historical labels are observed only on an installed upgrade predecessor.
    if profile not in ('finite', 'finite-dev', 'bluefin-generic', 'bluefin-dx-generic'):
        raise ValueError('Unknown guest profile')
    return {'schema': 2 if process_format == 'state-threads' else 1, 'status': 'pass', 'profile': profile,
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
                              command(['ps', '-e', '-o', 'label=,pid=,state=,nlwp=,comm=']),
                              command(['ss', '-H', '-lntup']),
                              Path('/usr/share/finite/build-profile').read_text().strip(),
                              process_format='state-threads')
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = {'schema': 1, 'status': 'error', 'error': str(error),
                  'physicalHardwareAssessed': False}
        if isinstance(error, ProcessObservationError):
            result['details'] = error.details
        print(json.dumps(result))
        return 1


if __name__ == '__main__':
    sys.exit(main())
