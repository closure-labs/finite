#!/usr/bin/env python3
"""Select CI work conservatively from the event's complete Git diff."""
import json
import os
from pathlib import Path
import re
import subprocess

PROFILES = {
    'bluefin-generic': 'bluefin-generic',
    'bluefin-next': 'next',
    'bluefin-dx-generic': 'bluefin-dx-generic',
    'bluefin-dx-next': 'dev-next',
}
NEXT = {'bluefin-next', 'bluefin-dx-next'}


def classify(paths):
    checks, nix = not paths, False
    profiles = set(PROFILES) if not paths else set()
    for path in paths:
        if path in {'README.md', 'CHANGELOG.md', 'LICENSE', 'LICENSE.md'} or path.startswith('docs/'):
            continue
        checks = True
        if path.startswith(('tests/', 'automation/')):
            continue
        if path in {
            '.github/dependabot.yml', '.github/workflows/iso.yml',
            '.github/workflows/vm-acceptance.yml', '.github/workflows/update-home-release.yml',
            '.github/workflows/update-flake-lock.yml', '.github/workflows/update-determinate-nix.yml',
            '.github/workflows/queue-dependabot.yml',
        }:
            continue
        if path.startswith(('lib/', 'modules/', 'templates/')) or path in {
            'flake.nix', 'flake.lock', 'VERSION', 'sources/determinate-nix.json', 'sources/kernel-next.json',
        }:
            nix = True
        elif path in {f'recipes/{profile}.yml' for profile in PROFILES}:
            profiles.add(Path(path).stem)
        elif path in {'recipes/shared/next.yml', 'files/scripts/kernel-next.sh'}:
            profiles.update(NEXT)
        else:
            profiles.update(PROFILES)
    return {'checks': checks, 'nix': nix, 'profiles': sorted(profiles)}


def revisions(event_name, event):
    if event_name == 'pull_request':
        base = event['pull_request']['base']['sha']
        head = event['pull_request']['head']['sha']
        separator = '...'
    elif event_name == 'merge_group':
        base, head = event['merge_group']['base_sha'], event['merge_group']['head_sha']
        separator = '..'
    elif event_name == 'push':
        base, head = event['before'], event['after']
        separator = '..'
    else:
        return None
    if any(not re.fullmatch(r'[0-9a-f]{40,64}', sha) or set(sha) == {'0'} for sha in (base, head)):
        return None
    return base, head, separator


def changed_paths(event_name, event):
    comparison = revisions(event_name, event)
    if comparison is None:
        return None
    base, head, separator = comparison
    result = subprocess.run(
        ['git', 'diff', '--no-renames', '--name-only', '-z', base + separator + head],
        check=True, stdout=subprocess.PIPE,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b'\0') if path]


def main():
    try:
        paths = changed_paths(os.environ['GITHUB_EVENT_NAME'], json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
        plan = classify(paths or [])
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'::warning::Change detection unavailable; running full validation ({type(error).__name__}).')
        plan = classify([])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for name, value in plan.items():
            print(f'{name}={json.dumps(value, separators=(",", ":"))}', file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Selected checks\n\nDocumentation checks run for every change.\n\n')
        summary.write(f'- Nix/runtime checks: {"run" if plan["checks"] else "skip"}\n')
        summary.write(f'- Compare Nix payloads: {"yes" if plan["nix"] else "no"}\n')
        summary.write(f'- Images selected by paths: {", ".join(plan["profiles"]) or "none"}\n')


if __name__ == '__main__':
    main()
