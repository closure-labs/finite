#!/usr/bin/env python3
"""Check fresh scan findings against live GitHub-authenticated human decisions."""
import argparse
import json
import os
from pathlib import Path
import sys
from security_admission import ROOT, verify
from security_decisions import load_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scan', required=True, type=Path)
parser.add_argument('--profile', required=True, choices=['finite', 'finite-dev'])
parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
parser.add_argument('--bot-login', default=os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
parser.add_argument('--records-path', type=Path, default=ROOT / 'automation/decisions/security')
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
try:
    result = verify(load_json(args.scan), args.profile, args.repository, args.bot_login, args.records_path)
    code = 0 if result['status'] == 'covered' else 3
except Exception as error:
    result, code = {'schema': 1, 'status': 'technical-error', 'error': str(error)}, 2
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
sys.exit(code)
