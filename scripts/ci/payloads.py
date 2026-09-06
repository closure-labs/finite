#!/usr/bin/env python3
"""Refine the image matrix using Nix's evaluated payload dependencies."""
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode

from impact import PROFILES, NEXT, revisions


def evaluate(revision):
    repository = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()
    installable = 'git+' + Path(repository).as_uri() + '?' + urlencode({'rev': revision}) + '#packages.x86_64-linux'
    result = subprocess.run([
        'nix', 'eval', '--accept-flake-config', '--no-update-lock-file', '--no-write-lock-file',
        '--json', installable, '--apply',
        'p: { generic = p.image-payload.drvPath; next = p.image-payload-next.drvPath; }',
    ], check=True, stdout=subprocess.PIPE, text=True, timeout=300)
    identities = json.loads(result.stdout)
    if set(identities) != {'generic', 'next'} or any(
        not isinstance(value, str) or not re.fullmatch(r'/nix/store/[a-z0-9]{32}-.+\.drv', value)
        for value in identities.values()
    ):
        raise ValueError('Invalid payload derivation identities')
    return identities


def select(explicit, before, after):
    selected = set(explicit)
    if before['generic'] != after['generic']:
        selected.update(set(PROFILES) - NEXT)
    if before['next'] != after['next']:
        selected.update(NEXT)
    return sorted(selected)


def refine(plan, event_name, event, head, evaluator=evaluate):
    explicit = plan['profiles']
    if not plan['nix'] or set(explicit) == set(PROFILES):
        return explicit, None
    comparison = revisions(event_name, event)
    if comparison is None:
        raise ValueError('Missing comparison revisions')
    base = comparison[0]
    # Compare the current target with the actual assembled PR/queue revision.
    # GITHUB_SHA names the same checkout used by checks and image builds.
    if not re.fullmatch(r'[0-9a-f]{40,64}', head):
        raise ValueError('Invalid checkout revision')
    before, after = evaluator(base), evaluator(head)
    return select(explicit, before, after), {'base': base, 'head': head, 'before': before, 'after': after}


def main():
    evidence = None
    try:
        plan = {name: json.loads(value) for name, value in json.loads(os.environ['IMPACT']).items()}
        if not isinstance(plan['nix'], bool) or not isinstance(plan['profiles'], list) or not set(plan['profiles']) <= set(PROFILES):
            raise ValueError('Invalid initial selection')
        selected, evidence = refine(
            plan, os.environ['GITHUB_EVENT_NAME'],
            json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()), os.environ['GITHUB_SHA'],
        )
    except (KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f'::warning::Payload comparison unavailable; selecting all images ({type(error).__name__}).')
        selected = sorted(PROFILES)
    matrix = {'include': [{'profile': profile, 'channel': PROFILES[profile]} for profile in selected]}
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print(f'images={str(bool(selected)).lower()}', file=output)
        print('matrix=' + json.dumps(matrix, separators=(',', ':')), file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Image selection\n\n' + (', '.join(selected) or 'No image inputs changed.') + '\n')
        if evidence:
            summary.write('\nPayload dependency comparison:\n\n```json\n' + json.dumps(evidence, indent=2) + '\n```\n')


if __name__ == '__main__':
    main()
