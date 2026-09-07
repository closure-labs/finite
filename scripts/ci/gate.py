#!/usr/bin/env python3
"""Require success for selected jobs and explicit skips for unselected jobs."""
import json
import os

from impact import PROFILES


def failures(needs, publish):
    errors = []
    for job in ('impact', 'docs'):
        if needs[job]['result'] != 'success':
            errors.append(f'{job}: expected success, got {needs[job]["result"]}')
    # Dependent jobs cannot emit selections after a prerequisite failed.
    if errors:
        return errors
    outputs = needs['impact'].get('outputs', {})
    for name in ('checks', 'nix'):
        if outputs.get(name) not in ('true', 'false'):
            errors.append(f'Missing or invalid selection: {name}')
    checks = outputs.get('checks') == 'true'
    images = False
    if checks and needs['checks']['result'] != 'success':
        return [f"checks: expected success, got {needs['checks']['result']}"]
    try:
        explicit = json.loads(outputs['profiles'])
        if not isinstance(explicit, list) or not set(explicit) <= set(PROFILES):
            raise ValueError('Invalid explicit profiles')
        if checks:
            selection = needs['checks'].get('outputs', {})
            rows = json.loads(selection['matrix'])['include']
            selected = [row['profile'] for row in rows]
            if len(selected) != len(set(selected)) or any(row != {'profile': row['profile'], 'channel': PROFILES[row['profile']]} for row in rows):
                raise ValueError('Invalid image matrix')
            if not set(explicit) <= set(selected):
                raise ValueError('An explicit image input was skipped')
            images = bool(selected)
            if selection['images'] != str(images).lower():
                raise ValueError('Inconsistent image selection')
        elif explicit or outputs.get('nix') != 'false':
            raise ValueError('Image inputs require Nix/runtime checks')
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f'Missing or invalid image selection: {error}')
    expected = {
        'checks': checks,
        'images': images and not publish,
        'publish': images and publish,
    }
    for job, required in expected.items():
        wanted = 'success' if required else 'skipped'
        actual = needs[job]['result']
        if actual != wanted:
            errors.append(f'{job}: expected {wanted}, got {actual}')
    return errors


if __name__ == '__main__':
    errors = failures(json.loads(os.environ['NEEDS']), os.environ['TRUSTED_PUBLICATION'] == 'true')
    for error in errors:
        print(f'::error::{error}')
    raise SystemExit(bool(errors))
