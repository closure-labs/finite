"""Validate bounded optional Foundation observations; grants no authority."""
from datetime import datetime
import json
import math

STAGES = frozenset(('initialization', 'profile-validation', 'home-manager-realisation',
                    'brew-provisioning', 'brew-policy-evaluation', 'brew-bootstrap',
                    'commit-and-activation', 'activation', 'rollback-activation'))


def decode(raw):
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError('Duplicate Foundation timing field')
        return value
    return validate(json.loads(raw, object_pairs_hook=unique))


def validate(value):
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'kind', 'authorizesPublication', 'stage', 'startedAt', 'seconds', 'outcome', 'status'}
            or type(value['schema']) is not int or value['schema'] != 1
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
    return dict(value)
