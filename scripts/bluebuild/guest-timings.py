#!/usr/bin/env python3
"""Retain only bounded structured guest stage markers while streaming output."""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
from foundation_timings import decode

PATTERN = re.compile(r'FINITE_GUEST_STAGE (startup-checks|homebrew-setup|predecessor-preparation|home-init) ([0-9]+) ([0-9]+)\n')
FOUNDATION = 'FOUNDATION_TIMING '


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
    collect(sys.stdin, Path(sys.argv[1]))
