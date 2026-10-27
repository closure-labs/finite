"""Validate bounded optional Foundation observations; grants no authority."""
from datetime import datetime
import json
import math

STAGES = frozenset(('initialization', 'profile-validation', 'home-manager-realisation',
                    'brew-provisioning', 'brew-policy-evaluation', 'brew-bootstrap',
                    'commit-and-activation', 'activation', 'rollback-activation',
                    'preparation', 'bluefin-readiness', 'bluefin-stock-install', 'bluefin-postcheck',
                    'bluefin-bundle', 'nix-activities', 'resource-client', 'resource-nix-daemon',
                    'resource-determinate-daemon', 'service-startup', 'flatpak-work'))


def decode(raw):
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError('Duplicate Foundation timing field')
        return value
    return validate(json.loads(raw, object_pairs_hook=unique))


def validate(value):
    version = value.get('schema') if isinstance(value, dict) else None
    fields = {
            'schema', 'kind', 'authorizesPublication', 'stage', 'startedAt', 'seconds', 'outcome', 'status'}
    if (not isinstance(value, dict) or set(value) != fields | ({'details'} if version == 2 else set())
            or type(version) is not int or version not in (1, 2)
            or value['kind'] != 'foundation-stage-timing' or value['authorizesPublication'] is not False
            or not isinstance(value['stage'], str) or value['stage'] not in STAGES
            or type(value['seconds']) not in (int, float) or not 0 <= value['seconds'] <= 86400
            or not math.isfinite(value['seconds'])
            or value['outcome'] not in ('success', 'error')
            or value['status'] is not None and (type(value['status']) is not int or not -255 <= value['status'] <= 255)
            or value['outcome'] == 'success' and value['status'] != 0
            or value['outcome'] == 'error' and value['status'] == 0):
        raise ValueError('Invalid Foundation timing observation')
    try:
        if not isinstance(value['startedAt'], str) or len(value['startedAt']) > 64:
            raise ValueError('Invalid timestamp')
        if datetime.fromisoformat(value['startedAt'].replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Missing timezone')
    except ValueError as error:
        raise ValueError('Invalid Foundation timing timestamp') from error
    if version == 2:
        validate_details(value['stage'], value['details'])
    if len(json.dumps(value, separators=(',', ':')).encode()) > 1000:
        raise ValueError('Oversized Foundation timing record')
    return dict(value)


def validate_details(stage, details):
    def integer(value, maximum=2**63 - 1):
        return type(value) is int and 0 <= value <= maximum
    def elapsed(value):
        return value is None or (type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 86400)
    if not isinstance(details, dict):
        raise ValueError('Invalid Foundation detail object')
    if stage == 'nix-activities':
        valid = (set(details) == {'logger', 'evaluation', 'builds', 'substitutions', 'buildSeconds',
                                  'substitutionSeconds', 'overlapSeconds', 'incomplete', 'rejectedRecords'}
                 and details['logger'] == 'nix-internal-json-v1' and details['evaluation'] == 'unknown'
                 and integer(details['builds'], 4096) and integer(details['substitutions'], 4096)
                 and details['builds'] + details['substitutions'] <= 4096
                 and all(elapsed(details[key]) for key in ('buildSeconds', 'substitutionSeconds', 'overlapSeconds'))
                 and type(details['incomplete']) is bool and integer(details['rejectedRecords'], 1000000))
        if valid:
            values = [details[key] for key in ('buildSeconds', 'substitutionSeconds', 'overlapSeconds')]
            valid = (all(value is None for value in values) or
                     all(value is not None for value in values) and values[2] <= min(values[:2])
                     and not details['incomplete'])
    elif stage in ('resource-client', 'resource-nix-daemon', 'resource-determinate-daemon'):
        valid = (set(details) == {'scope', 'memoryCurrentBytes', 'memoryPeakBytes', 'cpuUsageUsec', 'available'}
                 and details['scope'] == ('client' if stage == 'resource-client' else 'shared-daemon')
                 and type(details['available']) is bool
                 and all(details[key] is None or integer(details[key])
                         for key in ('memoryCurrentBytes', 'memoryPeakBytes', 'cpuUsageUsec')))
        if valid and not details['available']:
            valid = all(details[key] is None for key in ('memoryCurrentBytes', 'memoryPeakBytes', 'cpuUsageUsec'))
    elif stage == 'bluefin-bundle':
        import re
        valid = (set(details) == {'brewfileSha256', 'cache', 'closurePinned'}
                 and isinstance(details['brewfileSha256'], str)
                 and re.fullmatch(r'[0-9a-f]{64}', details['brewfileSha256']) is not None
                 and details['cache'] in ('present', 'absent', 'unknown') and details['closurePinned'] is False)
    else:
        valid = False
    if not valid:
        raise ValueError('Invalid Foundation stage details')
