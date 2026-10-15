#!/usr/bin/env python3
"""Select an explicit manual channel without relaxing validation or publication."""
import json
import os
import re
import sys

from impact import PROFILES

ACTIVE_PROFILES = {'finite', 'finite-dev'}

CHANNELS = {channel: profile for profile, channel in PROFILES.items() if profile in ACTIVE_PROFILES}


def validate_diagnostic(enabled, event_name, target, reconcile, run, digest, repository, ref):
    if type(enabled) is not bool:
        raise ValueError('Diagnostic security must be a boolean')
    if not enabled:
        return
    if (event_name != 'workflow_dispatch' or target not in CHANNELS or reconcile or run or digest
            or repository != 'closure-labs/finite' or not ref.startswith('refs/heads/')
            or ref == 'refs/heads/main'):
        raise ValueError('Diagnostic security requires one explicit unpublished validation branch channel')


def validate_resume(event_name, target, reconcile, run, digest, repository, ref):
    if not run and not digest:
        return
    if (not isinstance(run, str) or not re.fullmatch(r'[1-9][0-9]*', run)
            or not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)
            or event_name != 'workflow_dispatch' or target not in CHANNELS or reconcile
            or repository != 'closure-labs/finite' or ref != 'refs/heads/main'):
        raise ValueError('Resume requires a trusted main manual channel, origin run and immutable digest')


def select(event_name, target, reconcile):
    if not isinstance(target, str) or target not in {'automatic', *CHANNELS}:
        raise ValueError('Unknown release target; choose automatic or a supported channel')
    if type(reconcile) is not bool:
        raise ValueError('Reconcile must be a boolean')
    if target == 'automatic':
        return None
    if event_name != 'workflow_dispatch':
        raise ValueError('Explicit release targets require workflow_dispatch')
    if reconcile:
        raise ValueError('Choose either an explicit release target or reconciliation')
    # All Nix/runtime checks still run. With no revision diff to compare, select
    # the requested profile directly instead of invoking payload comparison.
    return {'checks': True, 'nix': False, 'profiles': [CHANNELS[target]]}


def main():
    reconcile = os.environ.get('RECONCILE', 'false')
    if reconcile not in {'true', 'false'}:
        raise ValueError('Reconcile must be true or false')
    target = os.environ.get('RELEASE_TARGET', 'automatic')
    diagnostic = os.environ.get('DIAGNOSTIC_SECURITY', 'false')
    if diagnostic not in {'true', 'false'}:
        raise ValueError('Diagnostic security must be true or false')
    validate_diagnostic(diagnostic == 'true', os.environ['GITHUB_EVENT_NAME'], target,
                        reconcile == 'true', os.environ.get('RESUME_RUN', ''),
                        os.environ.get('RESUME_DIGEST', ''), os.environ.get('GITHUB_REPOSITORY', ''),
                        os.environ.get('GITHUB_REF', ''))
    plan = select(os.environ['GITHUB_EVENT_NAME'], target, reconcile == 'true')
    validate_resume(os.environ['GITHUB_EVENT_NAME'], target, reconcile == 'true',
                    os.environ.get('RESUME_RUN', ''), os.environ.get('RESUME_DIGEST', ''),
                    os.environ.get('GITHUB_REPOSITORY', ''), os.environ.get('GITHUB_REF', ''))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('selected=' + str(plan is not None).lower(), file=output)
        if plan is not None:
            for name, value in plan.items():
                print(name + '=' + json.dumps(value, separators=(',', ':')), file=output)
    if plan is not None:
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('### Explicit manual channel selection\n\n')
            summary.write(f'Channel: {target}; profile: {plan["profiles"][0]}.\n\n')
            summary.write('All source/runtime checks remain required. Trusted main publication '
                          'also requires candidate security, isolated signing and boot qualification. '
                          'Other refs validate only.\n')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, ValueError, OSError) as error:
        sys.exit(f'Release selection failed: {error}')
