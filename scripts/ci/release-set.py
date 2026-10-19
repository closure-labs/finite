#!/usr/bin/env python3
"""Prepare a two-image official release set; execution is controller-only.

A trusted controller must authenticate producer evidence and fresh maintainer
release authorization before calling release_set.execute(). A user-supplied hash
is deliberately not exposed as a standalone publication command.
"""
import argparse
import json
from pathlib import Path
from release_set import payload_digest, prepare

parser = argparse.ArgumentParser(description=__doc__)
sub = parser.add_subparsers(dest='command', required=True)
p = sub.add_parser('prepare')
p.add_argument('--payload', required=True, type=Path)
p.add_argument('--evidence', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
doc = prepare(json.loads(args.payload.read_text()), json.loads(args.evidence.read_text()))
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(doc, sort_keys=True, indent=2) + '\n')
print(payload_digest(doc))
