#!/usr/bin/env python3
"""Stop a hosted native qualification command when host memory pressure is too high."""
import os
from pathlib import Path
import signal
import subprocess
import sys


def main(command):
    with subprocess.Popen(['nice', '-n', '19', *command], start_new_session=True) as process:
        try:
            while process.poll() is None:
                available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                                 if line.startswith('MemAvailable:'))
                if available < 3 * 1024**2:
                    print('Stopping native qualification because host memory fell below 3 GiB', file=sys.stderr)
                    return 1
                try:
                    return process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    continue
            return process.returncode
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
