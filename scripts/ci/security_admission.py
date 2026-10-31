"""Resolve authenticated human decision chains before admitting image findings.

Local proposal JSON supplies candidates only. The active decision must pass live
GitHub authority checks; superseded ancestors require immutable merge provenance.
"""
import importlib.util
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
import re

from security_decisions import TechnicalError, canonical_hash, evaluate, load_json, validate_normalized

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('security_admission_authority', Path(__file__).with_name('decision-authority.py'))
authority = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authority)
PROFILES = {'finite', 'finite-dev'}
HEX = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')


def positive(value):
    return (type(value) is int and value > 0) or (isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value))


def validate_packet(packet, repository):
    if not isinstance(packet, dict) or set(packet) != {'reference', 'sha256', 'producer'}:
        raise TechnicalError('Decision requires a content-addressed packet and producer')
    if (not isinstance(packet['reference'], str)
            or not re.fullmatch(r'ghcr\.io/' + re.escape(repository) + r'-decisions@sha256:[0-9a-f]{64}', packet['reference'])
            or not isinstance(packet['sha256'], str) or not HEX.fullmatch(packet['sha256'])):
        raise TechnicalError('Invalid immutable decision packet identity')
    producer = packet['producer']
    if not isinstance(producer, dict) or set(producer) != {'repository', 'workflow', 'runId', 'runAttempt', 'headSha', 'artifacts'}:
        raise TechnicalError('Invalid decision packet producer fields')
    if (producer['repository'] != repository or not isinstance(producer['workflow'], str)
            or not re.fullmatch(r'(?:\.github/workflows/)?[a-z0-9-]+\.yml', producer['workflow'])
            or not positive(producer['runId']) or not positive(producer['runAttempt'])
            or not isinstance(producer['headSha'], str) or not SHA.fullmatch(producer['headSha'])):
        raise TechnicalError('Invalid decision packet trusted producer identity')
    artifacts = producer['artifacts']
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 100:
        raise TechnicalError('Decision packet lacks bounded producer artifacts')
    identities = set()
    for artifact in artifacts:
        if (not isinstance(artifact, dict) or set(artifact) != {'id', 'name', 'digest'}
                or not positive(artifact['id']) or not isinstance(artifact['name'], str)
                or not artifact['name'] or len(artifact['name']) > 250
                or not isinstance(artifact['digest'], str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
                or str(artifact['id']) in identities):
            raise TechnicalError('Invalid decision packet artifact binding')
        identities.add(str(artifact['id']))
    return packet


def validate_proposal(proposal, repository):
    authority.proposal_path(proposal)
    if proposal['kind'] not in ('security-findings', 'security-revocation'):
        raise TechnicalError('Non-security decision in security ledger')
    payload = proposal['payload']
    if set(payload) != {'profiles', 'findings', 'disposition', 'supersedes', 'packet', 'rationale'}:
        raise TechnicalError('Unsupported security decision payload fields')
    profiles = payload['profiles']
    if (not isinstance(profiles, list) or not profiles or any(p not in PROFILES for p in profiles)
            or len(profiles) != len(set(profiles))):
        raise TechnicalError('Decision profiles must be explicit and unique')
    findings = validate_normalized(payload['findings'])
    if any(finding['profile'] not in profiles for finding in findings):
        raise TechnicalError('Decision findings do not match declared profiles')
    if payload['disposition'] not in ('accepted', 'rejected', 'revoked'):
        raise TechnicalError('Decision requires an explicit human disposition')
    if (proposal['kind'] == 'security-revocation') != (payload['disposition'] == 'revoked'):
        raise TechnicalError('Revocation kind and disposition disagree')
    parents = payload['supersedes']
    if (not isinstance(parents, list) or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in parents)
            or len(parents) != len(set(parents))):
        raise TechnicalError('Invalid explicit supersession identities')
    if payload['disposition'] == 'revoked' and not parents:
        raise TechnicalError('Revocation must explicitly identify accepted authority')
    if not isinstance(payload['rationale'], str) or not payload['rationale'].strip() or len(payload['rationale']) > 20000:
        raise TechnicalError('Human decision rationale is required')
    validate_packet(payload['packet'], repository)
    return payload



def _historical_provenance(proposal, number, repository, bot_login, github=None):
    """Authenticate retired ancestry without granting current acceptance authority.

    A later live-authorized decision may supersede a former maintainer's decision.
    This receipt never authorizes publication and deliberately has no reviewer.
    """
    api = github or authority.github_api
    path = authority.proposal_path(proposal)
    identity = canonical_hash(proposal)
    endpoint = f'repos/{repository}/pulls/{number}'
    pull = api(endpoint)
    if not isinstance(pull, dict):
        raise TechnicalError('Invalid historical decision PR')
    head, merge = pull.get('head', {}).get('sha', ''), pull.get('merge_commit_sha', '')
    if (pull.get('number') != number or pull.get('merged') is not True
            or pull.get('state') != 'closed'
            or not (pull.get('user', {}).get('type') == 'User'
                    or (pull.get('user', {}).get('type') == 'Bot' and pull['user'].get('login') == bot_login))
            or pull.get('base', {}).get('repo', {}).get('full_name') != repository
            or pull.get('head', {}).get('repo', {}).get('full_name') != repository
            or pull.get('base', {}).get('ref') != 'main'
            or not isinstance(head, str) or not SHA.fullmatch(head)
            or not isinstance(merge, str) or not SHA.fullmatch(merge)):
        raise TechnicalError('Historical decision lacks same-repository merged proposal provenance')
    files = authority.collection(api, endpoint + '/files')
    if (not files or len(files) != pull.get('changed_files')
            or any(not isinstance(item, dict) or item.get('filename') != path
                   or item.get('status') not in ('added', 'modified') for item in files)):
        raise TechnicalError('Historical decision changed unexpected files')
    main = api(f'repos/{repository}/git/ref/heads/main')
    current = main.get('object', {}).get('sha', '') if isinstance(main, dict) else ''
    if not isinstance(current, str) or not SHA.fullmatch(current):
        raise TechnicalError('Cannot establish historical decision main ancestry')
    comparison = api(f'repos/{repository}/compare/{merge}...{current}')
    if not isinstance(comparison, dict) or comparison.get('status') not in ('ahead', 'identical'):
        raise TechnicalError('Historical merge is not on current main')
    for revision in (head, merge, current):
        if canonical_hash(authority.document_at(api, repository, path, revision)) != identity:
            raise TechnicalError('Historical decision differs from immutable proposal merge')
    latest = api(endpoint)
    if (latest.get('head', {}).get('sha') != head or latest.get('merged') is not True
            or latest.get('merge_commit_sha') != merge):
        raise TechnicalError('Historical proposal changed during provenance validation')
    return {'schema': 1, 'status': 'superseded-provenance', 'repository': repository,
            'proposalHash': identity, 'path': path, 'pullRequest': number,
            'reviewedHead': head, 'mergeCommit': merge}



def live_ledger(records, repository, github=None):
    """Authenticate a complete current-main inventory, never a checkout's subset."""
    api = github or authority.github_api
    ref = api(f'repos/{repository}/git/ref/heads/main')
    head = ref.get('object', {}).get('sha') if isinstance(ref, dict) else None
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise TechnicalError('Current main ledger lacks immutable revision')
    tree = api(f'repos/{repository}/git/trees/{head}?recursive=1')
    if (not isinstance(tree, dict) or tree.get('truncated') is not False
            or not isinstance(tree.get('tree'), list) or len(tree['tree']) > 100000):
        raise TechnicalError('Current main ledger requires a complete bounded Git tree')
    prefix = 'automation/decisions/security'
    inventory = {}
    seen = set()
    for entry in tree['tree']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise TechnicalError('Malformed current main Git tree entry')
        path = entry['path']
        if path in seen:
            raise TechnicalError('Duplicate current main Git tree path')
        seen.add(path)
        if path in ('automation', 'automation/decisions', prefix):
            if entry.get('type') != 'tree' or entry.get('mode') != '040000':
                raise TechnicalError('Security ledger parent must be a regular Git tree')
        elif path.startswith(prefix + '/'):
            name = path[len(prefix) + 1:]
            if (not re.fullmatch(r'[0-9a-f]{64}\.json', name)
                    or entry.get('type') != 'blob' or entry.get('mode') != '100644'
                    or not isinstance(entry.get('sha'), str) or not SHA.fullmatch(entry['sha'])
                    or type(entry.get('size')) is not int or not 0 < entry['size'] <= 8 * 1024 * 1024):
                raise TechnicalError('Current main ledger contains a noncanonical or nonregular security record')
            inventory[name[:-5]] = entry
    if len(inventory) > 10000 or set(inventory) != set(records):
        raise TechnicalError('Local security ledger differs from complete current main inventory')
    for identity, entry in inventory.items():
        record = records[identity]
        if entry['sha'] == record['blobSha'] and record.get('sourcePath') is not None:
            authority.seed_tree_document(repository, entry['path'], head, entry, record['sourcePath'])
        if entry['sha'] != record['blobSha']:
            # Formatting-only changes are harmless; canonical content still must
            # equal the filename and the independently validated local proposal.
            document = authority.document_at(api, repository, entry['path'], head)
            if canonical_hash(document) != identity:
                raise TechnicalError('Current main security record differs from canonical local identity')
    return inventory


def historical_batch(records, identities, repository, bot_login, github=None, workers=1):
    """Read-only provenance only; never returns current acceptance authority."""
    if type(workers) is not int or workers not in (1, 4):
        raise TechnicalError('Historical provenance requires one or four read workers')
    def historical(identity):
        proposal = records[identity]['proposal']
        number = authority.find_origin_pr(proposal, repository, bot_login, github=github)
        return _historical_provenance(proposal, number, repository, bot_login, github)
    if workers == 1 or len(identities) < 2:
        return {identity: historical(identity) for identity in identities}
    # Context copies share only bounded immutable bytes, protected by its lock.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [(identity, pool.submit(copy_context().run, historical, identity)) for identity in identities]
        try:
            return {identity: future.result() for identity, future in pending}
        except BaseException:
            for _, future in pending:
                future.cancel()
            raise


def _verify(scan_result, profile, repository, bot_login,
           records_path=ROOT / 'automation/decisions/security', github=None, *, historical_workers=1):
    """Return covered/review-required/rejected/revoked and fresh authority receipts.

    Packet authenticity is established by the required App check before a human
    approves the proposal. Runtime verifies the immutable approved reference and
    live PR/reviewer authority; historical Actions artifacts need not remain live.
    Branching chains are intentionally ambiguous instead of selecting by clocks.
    """
    if profile not in PROFILES:
        raise TechnicalError('Unsupported publication profile')
    if type(historical_workers) is not int or historical_workers not in (1, 4):
        raise TechnicalError('Historical provenance requires one or four read workers')
    authority.validate_context(repository, bot_login)
    # Validate the scan before any decision can waive an infrastructure failure.
    initial = evaluate(scan_result, profile)
    path = Path(records_path)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise TechnicalError('Security decision ledger must be a regular directory')
    candidates = sorted(path.glob('*.json')) if path.exists() else []
    if len(candidates) > 10000:
        raise TechnicalError('Security decision ledger exceeds bounded record count')
    records = {}
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 8 * 1024 * 1024:
            raise TechnicalError('Security decision record is not a bounded regular file')
        proposal = load_json(candidate)
        payload = validate_proposal(proposal, repository)
        identity = canonical_hash(proposal)
        if candidate.name != identity + '.json' or identity in records:
            raise TechnicalError('Security ledger filename does not match canonical proposal')
        raw = candidate.read_bytes()
        blob_sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        records[identity] = {'proposal': proposal, 'payload': payload, 'blobSha': blob_sha, 'sourcePath': candidate}
    live_ledger(records, repository, github)
    relevant = {key for key, value in records.items() if profile in value['payload']['profiles']}
    if not relevant:
        live_ledger(records, repository, github)
        return {**initial, 'authority': None, 'decision': None}
    superseded = {parent for identity in relevant for parent in records[identity]['payload']['supersedes']
                  if parent in relevant}
    leaves = relevant - superseded
    if len(leaves) != 1:
        raise TechnicalError('Multiple unrelated live decisions require explicit human supersession')
    active = next(iter(leaves))
    receipts, order = {}, []
    visiting, visited = set(), set()

    def validate_chain(identity):
        if identity in visiting:
            raise TechnicalError('Security decision supersession cycle')
        if identity in visited:
            return
        if identity not in records:
            raise TechnicalError('Superseded security decision is missing from ledger')
        visiting.add(identity)
        record = records[identity]
        parents = record['payload']['supersedes']
        for parent in parents:
            validate_chain(parent)
            if not set(record['payload']['profiles']).intersection(records[parent]['payload']['profiles']):
                raise TechnicalError('Decision supersedes an unrelated profile')
        if record['payload']['disposition'] == 'revoked':
            if len(parents) != 1 or records[parents[0]]['payload']['disposition'] != 'accepted':
                raise TechnicalError('Revocation does not explicitly target an accepted decision')
            parent_payload = records[parents[0]]['payload']
            if any(record['payload'][field] != parent_payload[field] for field in ('profiles', 'findings', 'packet')):
                raise TechnicalError('Revocation differs from the complete accepted snapshot')
        visiting.remove(identity)
        visited.add(identity)
        order.append(identity)

    for identity in sorted(relevant):
        validate_chain(identity)

    ancestors = [identity for identity in order if identity != active]
    receipts.update(historical_batch(records, ancestors, repository, bot_login, github, historical_workers))
    number = authority.find_origin_pr(records[active]['proposal'], repository, bot_login, github=github)
    receipts[active] = authority.verify_proposal(records[active]['proposal'], number, repository,
                                                bot_login, require_merged=True, github=github)
    identity = active
    payload = records[identity]['payload']
    disposition = payload['disposition']
    accepted = [finding for finding in payload['findings'] if finding['profile'] == profile]
    result = evaluate(scan_result, profile, accepted if disposition == 'accepted' else None,
                      revoked=disposition == 'revoked')
    if disposition == 'rejected':
        result['status'] = 'rejected'
    live_ledger(records, repository, github)
    return {**result, 'authority': receipts[identity],
            'authorityChain': [receipts[key] for key in sorted(receipts)],
            'decision': {'proposalHash': identity, 'disposition': disposition,
                         'packet': payload['packet']}}


def verify(scan_result, profile, repository, bot_login,
           records_path=ROOT / 'automation/decisions/security', github=None, *, historical_workers=1):
    # A single admission operation shares only cryptographically bound bytes.
    # Main, complete ledger inventory, PRs, reviews and live roles are still read.
    with authority.immutable_documents():
        return _verify(scan_result, profile, repository, bot_login, records_path, github,
                       historical_workers=historical_workers)
