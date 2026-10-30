#!/usr/bin/env python3
"""Retain only bounded structured guest stage markers while streaming output."""
import json
import gzip
import argparse
import importlib.util
import time
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
from foundation_timings import decode

PATTERN = re.compile(r'FINITE_GUEST_STAGE (startup-checks|homebrew-setup|predecessor-preparation|home-init) ([0-9]+) ([0-9]+)\n')
FOUNDATION = 'FOUNDATION_TIMING '


LINE_LIMIT = 16384
LOG_LIMIT = 256 * 1024 * 1024


class CompressedCapture:
    """Independent gzip members preserve a readable prefix even after cancellation."""
    def __init__(self, raw, limit=LOG_LIMIT):
        self.raw, self.limit = raw, limit
        self.bytes = self.input_bytes = 0
        self.error = None

    def write(self, chunk):
        self.input_bytes += len(chunk)
        if self.error or not chunk:
            return
        member = gzip.compress(chunk, compresslevel=6, mtime=0)
        if self.bytes + len(member) > self.limit:
            self.error = 'compressed-byte-budget'
            return
        self.raw.write(member)
        self.raw.flush()
        self.bytes += len(member)


def bounded_lines(stream, raw, secret):
    spec = importlib.util.spec_from_file_location('vm_redactor', Path(__file__).with_name('redact-vm-logs.py'))
    redactor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redactor)
    pending, overflow = b'', False
    for chunk in redactor.redacted_chunks(stream, secret):
        raw.write(chunk)
        for index, part in enumerate(chunk.split(b'\n')):
            if index:
                yield ('[oversized guest line omitted from console; see capture receipt]\n'
                       if overflow else pending.decode('utf-8', errors='replace') + '\n')
                pending, overflow = b'', False
            if len(pending) + len(part) > LINE_LIMIT:
                overflow = True
            if not overflow:
                pending += part
    if pending or overflow:
        yield ('[oversized guest line omitted from console; see capture receipt]\n'
               if overflow else pending.decode('utf-8', errors='replace'))


class BoundedConsole:
    def __init__(self, output, clock=time.monotonic):
        self.output, self.clock = output, clock
        self.remaining, self.tail, self.suppressed = 32768, '', 0
        self.last = clock()

    def write(self, line):
        if line.startswith('@nix '):
            try:
                value = json.loads(line[5:])
                if (isinstance(value, dict) and value.get('action') == 'msg'
                        and type(value.get('level')) is int and value['level'] <= 1
                        and isinstance(value.get('msg'), str)):
                    line = 'Nix diagnostic: ' + value['msg'][:8192] + '\n'
            except (ValueError, TypeError):
                pass
        if not line.startswith('@nix '):
            self.tail = (self.tail + line).encode()[-8192:].decode('utf-8', errors='ignore')
        if not line.startswith('@nix ') and len(line.encode()) <= self.remaining:
            self.output.write(line)
            self.remaining -= len(line.encode())
        else:
            self.suppressed += 1
        if self.clock() - self.last >= 30:
            self.output.write(f'Guest initialization continues; {self.suppressed} progress lines hidden from console.\n')
            self.last = self.clock()

    def flush(self):
        self.output.flush()

    def finish(self, rows):
        failed = not any(row['stage'] == 'home-init' and row['status'] == 0 for row in rows)
        if failed:
            self.output.write('Guest initialization failed or was incomplete; recent non-progress output:\n' + self.tail)
        self.output.write('Sanitized initializer output (completeness in home-init-log.json): home-init.log.gz in the VM evidence artifact.\n')
        self.output.flush()


def collect(stream, output, console=sys.stdout):
    rows = []
    foundation, rejected = [], 0
    def document():
        value = {'schema': 1, 'stages': rows}
        if foundation or rejected:
            value['foundation'] = {'schema': 1, 'stages': foundation, 'rejectedRecords': rejected}
        return json.dumps(value) + '\n'
    for line in stream:
        match = PATTERN.fullmatch(line)
        if match:
            stage, seconds, status = match.groups()
            if any(row['stage'] == stage for row in rows) or int(status) > 255:
                raise ValueError('Duplicate or invalid guest timing')
            rows.append({'stage': stage, 'seconds': int(seconds), 'status': int(status)})
            if isinstance(console, BoundedConsole):
                console.output.write(f'Guest stage {stage}: {seconds}s, exit {status}\n')
                console.flush()
            output.write_text(document())
        else:
            if line.startswith(FOUNDATION):
                try:
                    if len(line) > 1024:
                        raise ValueError('Oversized timing line')
                    record = decode(line[len(FOUNDATION):])
                    if any(row['stage'] == record['stage'] for row in foundation):
                        raise ValueError('Duplicate Foundation timing')
                    # Keep the complete guest receipt under its existing 16 KiB cap.
                    foundation.append(record)
                    if len(document().encode()) > 14336:
                        foundation.pop()
                        raise ValueError('Foundation timing envelope exceeds receipt budget')
                except (ValueError, TypeError):
                    rejected = min(rejected + 1, 1000000)
                try:
                    output.write_text(document())
                except OSError:
                    # Optional diagnostics must not replace the guest's status.
                    pass
            console.write(line)
            console.flush()
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--secret', type=Path)
    args = parser.parse_args()
    if bool(args.log) != bool(args.secret):
        parser.error('--log and --secret must be supplied together')
    if args.log:
        console = BoundedConsole(sys.stdout)
        rows, complete, capture = [], False, None
        try:
            with args.log.open('xb') as raw:
                args.log.chmod(0o600)
                capture = CompressedCapture(raw)
                rows = collect(bounded_lines(sys.stdin.buffer, capture, args.secret.read_bytes().strip()), args.output, console)
                complete = capture.error is None
        finally:
            args.log.with_name('home-init-log.json').write_text(json.dumps({
                'schema': 1, 'captureComplete': complete, 'authorizesPublication': False,
                'consoleByteBudget': 32768, 'compressedLogByteBudget': LOG_LIMIT,
                'compressedBytes': capture.bytes if capture else 0,
                'sanitizedBytesObserved': capture.input_bytes if capture else 0,
                'captureError': capture.error if capture else 'capture-not-started',
                'homeInitStatus': next((r['status'] for r in rows if r['stage'] == 'home-init'), None)}) + '\n')
            if capture and capture.error:
                print('Guest log capture incomplete: compressed storage budget exhausted; '
                      'guest status is reported separately.', file=sys.stderr)
            console.finish(rows)
    else:
        collect(sys.stdin, args.output)
