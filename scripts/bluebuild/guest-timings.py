#!/usr/bin/env python3
"""Retain only bounded structured guest stage markers while streaming output."""
import json
from pathlib import Path
import re
import sys

PATTERN = re.compile(r'FINITE_GUEST_STAGE (startup-checks|homebrew-setup|predecessor-preparation|home-init) ([0-9]+) ([0-9]+)\n')


def collect(stream, output, console=sys.stdout):
    rows = []
    for line in stream:
        match = PATTERN.fullmatch(line)
        if match:
            stage, seconds, status = match.groups()
            if any(row['stage'] == stage for row in rows) or int(status) > 255:
                raise ValueError('Duplicate or invalid guest timing')
            rows.append({'stage': stage, 'seconds': int(seconds), 'status': int(status)})
            output.write_text(json.dumps({'schema': 1, 'stages': rows}) + '\n')
        else:
            console.write(line)
            console.flush()
    return rows


if __name__ == '__main__':
    collect(sys.stdin, Path(sys.argv[1]))
