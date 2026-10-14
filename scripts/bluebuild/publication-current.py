#!/usr/bin/env python3
"""Reject obsolete publication work using the final promotion ancestry rules."""
import argparse
import importlib.util
import json
import os
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('current_publication', Path(__file__).with_name('publication.py'))
publication = importlib.util.module_from_spec(SPEC)
exec(compile(Path(SPEC.origin).read_bytes(), SPEC.origin, 'exec'), publication.__dict__)


def require_current(revision):
    if not isinstance(revision, str) or not publication.SHA.fullmatch(revision):
        raise ValueError('Publication requires an exact revision')
    reference = publication.github('git/ref/heads/main')
    obj = reference.get('object', {}) if isinstance(reference, dict) else {}
    current = obj.get('sha') if isinstance(obj, dict) else None
    if (not isinstance(reference, dict) or not isinstance(obj, dict)
            or reference.get('ref') != 'refs/heads/main' or obj.get('type') != 'commit'
            or not isinstance(current, str) or not publication.SHA.fullmatch(current)):
        raise ValueError('Main reference is missing or malformed')
    if current != revision:
        if not publication.documentation_only_advance(revision, current):
            raise ValueError('Main changed release inputs; stop obsolete qualification work')
        if publication.github('git/ref/heads/main') != reference:
            raise ValueError('Main changed during publication preflight')
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default=os.environ.get('GITHUB_SHA'))
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    current = require_current(args.revision)
    if args.record:
        record = json.loads(args.record.read_text())
        if record.get('revision') != args.revision:
            raise ValueError('Publication record identifies another revision')
        publication.promotion_state(record)
    print('Publication remains eligible at main ' + current)


if __name__ == '__main__':
    main()
