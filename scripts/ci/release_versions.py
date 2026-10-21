"""Canonical stable versions and the next patch's development prerelease."""
import re

VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-dev)?')
CHANNELS = ('finite', 'finite-dev')


def release_version(value):
    return isinstance(value, str) and len(value) <= 64 and VERSION.fullmatch(value) is not None


def stable_version(value):
    return release_version(value) and not value.endswith('-dev')


def prerelease(value):
    if not release_version(value):
        raise ValueError('Expected numeric MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-dev VERSION')
    return value.endswith('-dev')


def canonical_tag(channel, version):
    if channel not in CHANNELS:
        raise ValueError('Unsupported release channel')
    prerelease(version)
    return channel + '-' + version


def next_development(version):
    if not stable_version(version):
        raise ValueError('Only a stable release starts a development cycle')
    major, minor, patch = map(int, version.split('.'))
    development = f'{major}.{minor}.{patch + 1}-dev'
    if not release_version(development):
        raise ValueError('Next development version exceeds the supported version length')
    return development


def previous_stable(version):
    if not prerelease(version):
        raise ValueError('Expected a development prerelease')
    major, minor, patch = map(int, version[:-4].split('.'))
    return f'{major}.{minor}.{patch - 1}' if patch else None
