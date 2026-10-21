#!/usr/bin/env python3
"""Retire per-channel release paths once unified human release decisions are active."""
import argparse
import base64
import json
import os
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
LEGACY_MODES = {'fixable-severity', 'upstream-maintained-risk', 'desktop-critical-only'}


def parse_policy(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate release policy key')
            result[key] = value
        return result
    policy = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(policy, dict) or type(policy.get('schema')) is not int or policy['schema'] != 1:
        raise ValueError('Unsupported release policy schema')
    mode = policy.get('mode', 'fixable-severity')
    if mode == 'maintainer-decision':
        raise ValueError('Per-channel release and recovery are retired; use Prepare two-image release approval, then Publish approved two-image release')
    if mode not in LEGACY_MODES:
        raise ValueError('Unknown release policy mode cannot authorize a legacy release')
    return mode


def require_legacy_policy(root=ROOT):
    path = root / 'automation/security/image-policy.json'
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 8 * 1024**2:
        raise ValueError('Release policy must be a bounded regular checked-out file')
    return parse_policy(path.read_text())


def require_current_legacy_policy():
    # A run keeps its original checkout after main changes. Consult current
    # main as data so an old policy checkout cannot bypass the cutover.
    if (os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Legacy release requires the trusted hosted main context')
    result = subprocess.run(['gh', 'api', '--method', 'GET',
                             'repos/closure-labs/finite/contents/automation/security/image-policy.json?ref=main'],
                            text=True, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError('Cannot authenticate current main release policy')
    document = json.loads(result.stdout)
    if (not isinstance(document, dict) or document.get('type') != 'file'
            or document.get('encoding') != 'base64' or type(document.get('size')) is not int
            or not 0 < document['size'] <= 8 * 1024**2 or not isinstance(document.get('content'), str)):
        raise ValueError('Current main release policy is not a bounded regular Git file')
    raw = base64.b64decode(document['content'].replace('\n', ''), validate=True)
    if len(raw) != document['size']:
        raise ValueError('Current main policy byte size differs from GitHub metadata')
    return parse_policy(raw)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        mode = require_legacy_policy()
        require_current_legacy_policy()
    except (ValueError, OSError, TypeError, subprocess.SubprocessError) as error:
        print('Legacy release denied: ' + str(error), file=sys.stderr)
        return 2
    print('Legacy release boundary verified for policy mode ' + mode)
    return 0


if __name__ == '__main__':
    sys.exit(main())
