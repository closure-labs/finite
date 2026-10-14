#!/usr/bin/env python3
"""Bound a VM upgrade and retain sanitized progress independently of shell cleanup."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import time

spec = importlib.util.spec_from_file_location('redactor', Path(__file__).with_name('redact-vm-logs.py'))
redactor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redactor)
DIAGNOSTICS = '''date -u; free -m; df -h / /var; cat /proc/net/dev;
for pid in $(pgrep -x bootc); do
  echo "bootc pid=$pid"; cat /proc/$pid/io; cat /proc/$pid/status | grep -E '^(State|VmRSS|Threads):';
done
'''


def supervise(state, evidence, secret, ssh, target, limit=1800, interval=60):
    cancelled = 0
    process = None
    def stop(signum, _frame):
        nonlocal cancelled
        cancelled = signum
    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    started = time.monotonic()
    try:
        redactor.snapshot_logs(state, secret, evidence)
        with (state / 'upgrade-transfer.log').open('wb') as output:
            # Both sides are bounded: SSH loss cannot leave an unbounded guest import.
            process = subprocess.Popen(ssh + ['sudo', 'timeout', '--signal=TERM', '--kill-after=10s',
                str(limit) + 's', 'bootc', 'switch', '--enforce-container-sigpolicy', target],
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            next_report = started
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if cancelled or elapsed >= limit:
                    break
                if time.monotonic() >= next_report:
                    with (state / 'upgrade-progress.log').open('ab') as progress:
                        progress.write(f'Upgrade elapsed {int(elapsed)}s; limit {limit}s\n'.encode())
                        progress.flush()
                        try:
                            subprocess.run(ssh + ['sudo', 'sh', '-c', shlex.quote(DIAGNOSTICS)],
                                           stdout=progress, stderr=subprocess.STDOUT, timeout=8)
                        except subprocess.TimeoutExpired:
                            progress.write(b'Guest diagnostic probe timed out; upgrade status unknown\n')
                    redactor.snapshot_logs(state, secret, evidence)
                    tail = (state / 'upgrade-transfer.log').read_bytes().replace(secret, b'[REDACTED]').decode(errors='replace').splitlines()[-3:]
                    print(f'VM upgrade: {int(elapsed)}s elapsed (limit {limit}s). ' + ' | '.join(tail), flush=True)
                    metrics = (state / 'upgrade-progress.log').read_bytes().replace(secret, b'[REDACTED]').decode(errors='replace').splitlines()[-18:]
                    for line in metrics:
                        print('VM upgrade metric: ' + line, flush=True)
                    next_report = time.monotonic() + interval
                time.sleep(0.2)
            result = 128 + cancelled if cancelled else process.poll()
            if result is None:
                result = 128 + cancelled if cancelled else 124
                print('VM upgrade cancelled' if cancelled else f'VM upgrade exceeded its {limit}-second limit', flush=True)
            (state / 'upgrade-outcome.json').write_text(json.dumps({'exitCode': result, 'elapsedSeconds': int(time.monotonic() - started), 'limitSeconds': limit}) + '\n')
            return result
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        redactor.snapshot_logs(state, secret, evidence)
        for sig, handler in old.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('key', type=Path)
    parser.add_argument('target')
    parser.add_argument('ssh', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.ssh or args.ssh[0] != 'ssh':
        parser.error('Expected SSH command')
    raise SystemExit(supervise(args.state, args.evidence, args.key.read_bytes().strip(), args.ssh, args.target))


if __name__ == '__main__':
    main()
