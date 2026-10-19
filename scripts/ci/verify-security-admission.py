#!/usr/bin/env python3
"""Independently verify native health and current admission before credentials or publication."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('publication_security_policy', ROOT / 'scripts/bluebuild/security-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory', required=True, type=Path)
parser.add_argument('--image', required=True)
args = parser.parse_args()
try:
    result = policy.verify(args.directory, args.image)
    print(json.dumps({'scannerStatus': result['status'], 'admission': result.get('admission')}))
except (ValueError, KeyError, TypeError, OSError) as error:
    print('Security admission denied: ' + str(error), file=sys.stderr)
    sys.exit(2)
