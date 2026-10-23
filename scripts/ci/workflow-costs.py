#!/usr/bin/env python3
"""Collect the previous 14 days and, when specified, seven days after rollout."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from workflow_costs import collect, markdown, timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout', help='Immutable rollout UTC timestamp, e.g. 2026-10-23T12:00:00Z')
    parser.add_argument('--receipts', action='store_true', help='Join bounded authenticated native stage receipts')
    parser.add_argument('--output', type=Path, default=Path('.bluebuild/workflow-costs.json'))
    args = parser.parse_args()
    report = collect(rollout=timestamp(args.rollout) if args.rollout else None, receipts=args.receipts)
    report['collectionCompletedAt'] = datetime.now(timezone.utc).isoformat()
    report['collectorScriptSha256'] = hashlib.sha256(Path(__file__).with_name('workflow_costs.py').read_bytes()).hexdigest()
    report['collector'] = {key: os.environ.get(key) for key in ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID',
                           'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    content = markdown(report)
    args.output.with_suffix('.md').write_text(content)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(content)


if __name__ == '__main__':
    main()
