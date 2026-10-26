#!/usr/bin/env python3
"""Export only declared nonsecret CI switches after scoped SecretSpec resolution."""
import argparse
import json
import os
from pathlib import Path

OPTIONS = ('FINITE_OPTIMIZED_CACHES', 'FINITE_CACHIX_WRITER', 'FINITE_REUSE_INVENTORY',
           'FINITE_GRYPE_DB_CACHE', 'FINITE_QUALIFICATION_REUSE', 'FINITE_QUALIFIED_ISO_PRESERVATION')
ISO_CHANNELS_OPTION = 'FINITE_QUALIFIED_ISO_CHANNELS'
SOURCE_PROOF_OPTION = 'FINITE_SOURCE_PROOF_REUSE'
CHANNEL_PROFILES = {'finite': 'finite', 'finite-dev': 'finite-dev'}


def iso_channels(value):
    """Normalize an explicit channel allowlist before exporting it to job env."""
    value = value or 'finite'
    if value == 'all':
        return tuple(sorted(CHANNEL_PROFILES))
    channels = tuple(item.strip() for item in value.split(','))
    if (not channels or len(channels) != len(set(channels))
            or any(channel not in CHANNEL_PROFILES for channel in channels)):
        raise ValueError('Expected supported channels or all for ' + ISO_CHANNELS_OPTION)
    return tuple(sorted(channels))


def options(env):
    result = {}
    for key in OPTIONS:
        value = env.get(key, 'false') or 'false'
        if value not in ('true', 'false'):
            raise ValueError('Expected true or false for ' + key)
        result[key] = value
    result[ISO_CHANNELS_OPTION] = ','.join(iso_channels(env.get(ISO_CHANNELS_OPTION)))
    mode = env.get(SOURCE_PROOF_OPTION) or 'off'
    if mode not in ('off', 'shadow', 'enabled'):
        raise ValueError('Expected off, shadow or enabled for ' + SOURCE_PROOF_OPTION)
    result[SOURCE_PROOF_OPTION] = mode
    return result


def iso_preservation_enabled(channel_or_profile, environ=None):
    if not isinstance(channel_or_profile, str):
        raise ValueError('ISO preservation requires one supported channel or profile')
    profiles = {profile: channel for channel, profile in CHANNEL_PROFILES.items()}
    channel = profiles.get(channel_or_profile, channel_or_profile)
    if channel not in CHANNEL_PROFILES:
        raise ValueError('ISO preservation requires one supported channel or profile')
    resolved = options(os.environ if environ is None else environ)
    return (resolved['FINITE_QUALIFIED_ISO_PRESERVATION'] == 'true'
            and channel in resolved[ISO_CHANNELS_OPTION].split(','))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--github-env', action='store_true')
    parser.add_argument('--iso-preservation', metavar='CHANNEL_OR_PROFILE')
    args = parser.parse_args()
    if args.iso_preservation:
        if args.github_env:
            parser.error('Select either GitHub environment export or ISO scope lookup')
        print(str(iso_preservation_enabled(args.iso_preservation)).lower())
        return
    result = options(os.environ)
    if args.github_env:
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise ValueError('GitHub export is hosted-only')
        with Path(os.environ['GITHUB_ENV']).open('a') as output:
            output.write(''.join(key + '=' + value + '\n' for key, value in result.items()))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
