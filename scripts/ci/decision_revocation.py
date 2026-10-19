"""Propose a human revocation without requiring fresh scans or live old artifacts."""
from pathlib import Path
import re

import security_admission
from security_decisions import canonical_hash, load_json

ROOT = Path(__file__).resolve().parents[2]


def records(repository, directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Revocation requires an existing regular decision ledger')
    paths = sorted(directory.glob('*.json'))
    if len(paths) > 10000:
        raise ValueError('Revocation ledger exceeds record bound')
    result = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 8 * 1024**2:
            raise ValueError('Revocation parent must be a bounded regular record')
        proposal = load_json(path)
        security_admission.validate_proposal(proposal, repository)
        identity = canonical_hash(proposal)
        if path.name != identity + '.json':
            raise ValueError('Revocation parent filename does not bind its contents')
        result[identity] = proposal
    return result


def validate(proposal, repository, bot_login, records_path=ROOT / 'automation/decisions/security', github=None):
    payload = security_admission.validate_proposal(proposal, repository)
    if proposal['kind'] != 'security-revocation' or payload['disposition'] != 'revoked' or len(payload['supersedes']) != 1:
        raise ValueError('Revocation must explicitly target one complete accepted decision')
    ledger = records(repository, records_path)
    identity = payload['supersedes'][0]
    if identity not in ledger:
        raise ValueError('Revocation target is missing')
    parent = ledger[identity]
    if parent['payload']['disposition'] != 'accepted':
        raise ValueError('Revocation target must be accepted')
    for field in ('profiles', 'findings', 'packet'):
        if payload[field] != parent['payload'][field]:
            raise ValueError('Revocation cannot replace, narrow or expand the accepted snapshot')
    # The accepted parent must be the unique current leaf for every scope it
    # covers. Ignore this proposal itself if validating after it was merged.
    own = canonical_hash(proposal)
    for profile in payload['profiles']:
        relevant = {key for key, item in ledger.items() if profile in item['payload']['profiles'] and key != own}
        superseded = {key for item_id in relevant for key in ledger[item_id]['payload']['supersedes'] if key in relevant}
        if relevant - superseded != {identity}:
            raise ValueError('Revocation target is no longer the unique active accepted decision')
    authority = security_admission.authority
    authority.validate_context(repository, bot_login)
    number = authority.find_origin_pr(parent, repository, bot_login, github=github)
    # A departed approver cannot prevent a new maintainer from revoking their
    # retired authority. This is merge provenance, never a publication grant.
    return security_admission._historical_provenance(parent, number, repository, bot_login, github)


def create(decision_hash, rationale, repository, bot_login,
           records_path=ROOT / 'automation/decisions/security', github=None):
    if not isinstance(decision_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', decision_hash):
        raise ValueError('Revocation requires a canonical decision hash')
    ledger = records(repository, records_path)
    if decision_hash not in ledger:
        raise ValueError('Revocation target is missing')
    parent = ledger[decision_hash]
    proposal = {'schema': 1, 'kind': 'security-revocation',
                'payload': {**parent['payload'], 'disposition': 'revoked',
                            'supersedes': [decision_hash], 'rationale': rationale}}
    validate(proposal, repository, bot_login, records_path, github)
    return proposal
