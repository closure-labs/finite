#!/usr/bin/env python3
"""Read native matched diagnostics after completion; keep adoption disabled."""
import argparse
import json
from pathlib import Path

from github_api import get_json
from release_transport_benchmark import collect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', required=True, type=int)
parser.add_argument('--output', default=Path('.bluebuild/release-transport-comparison.json'), type=Path)
args = parser.parse_args()
report = collect(args.run, get_json)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: value for key, value in report.items() if key not in ('samples', 'producers')}, indent=2))
