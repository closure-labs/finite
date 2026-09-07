#!/usr/bin/env python3
"""Record bounded stage timings without changing command output or exit status."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


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
            print(json.dumps({'stage': name, 'startedAt': started,
                              'seconds': round(time.monotonic() - before, 3),
                              'status': status, 'runnerNetworkDelta': traffic}), file=output)
    return status if status >= 0 else 128 - status


if __name__ == '__main__':
    raise SystemExit(main())
