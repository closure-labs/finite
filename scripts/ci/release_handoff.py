"""Small signing requests authenticated by a successful native preparation job.

Preparation verifies the original native archive and approved product hashes.
The isolated signer receives only evidence and approved hashes. Publication
fetches the immutable original OCI products and checks every signed hash again.
"""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import decision_packets
from security_decisions import canonical_hash, load_json

MAX_BYTES = 2 * 1024**3
REPOSITORY = 'closure-labs/finite'
WORKFLOW = '.github/workflows/publish-release-set.yml'
CHANNELS = ('finite', 'finite-dev')


def producer():
    return {'repository': REPOSITORY, 'workflow': 'publish-release-set.yml',
            'runId': int(os.environ['GITHUB_RUN_ID']),
            'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'headSha': os.environ['GITHUB_SHA']}


def native_preparation(identity, api, collection, *, job_name='prepare'):
    if (not isinstance(identity, dict) or set(identity) != {'repository', 'workflow', 'runId', 'runAttempt', 'headSha'}
            or identity['repository'] != REPOSITORY or identity['workflow'] != 'publish-release-set.yml'
            or type(identity['runId']) is not int or identity['runId'] <= 0
            or type(identity['runAttempt']) is not int or identity['runAttempt'] <= 0
            or not isinstance(identity['headSha'], str) or not re.fullmatch(r'[0-9a-f]{40}', identity['headSha'])):
        raise ValueError('Invalid signing preparation identity')
    endpoint = f'repos/{REPOSITORY}/actions/runs/{identity["runId"]}/attempts/{identity["runAttempt"]}'
    run = api(endpoint)
    if (run.get('id') != identity['runId'] or run.get('run_attempt') != identity['runAttempt']
            or run.get('head_sha') != identity['headSha'] or run.get('path') != WORKFLOW
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or run.get('head_branch') != 'main' or run.get('event') not in ('push', 'workflow_dispatch')):
        raise ValueError('Signing request lacks trusted native preparation')
    jobs = collection(endpoint + '/jobs', 'jobs')
    prepared = [job for job in jobs if job.get('name') == job_name]
    if (len(prepared) != 1 or prepared[0].get('status') != 'completed'
            or prepared[0].get('conclusion') != 'success'
            or prepared[0].get('run_id') != identity['runId']
            or prepared[0].get('run_attempt') != identity['runAttempt']
            or prepared[0].get('head_sha') != identity['headSha']):
        raise ValueError('Signing request requires one successful exact native preparation job')


def inventory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Unsafe signing evidence directory')
    files, total = {}, 0
    for path in directory.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Unsafe signing evidence member')
        if path.is_file():
            name = decision_packets.safe_name(path.relative_to(directory).as_posix())
            total += path.stat().st_size
            if total > MAX_BYTES or len(files) >= decision_packets.MAX_FILES:
                raise ValueError('Signing evidence exceeds 2 GiB or file count limit')
            files[name] = {'size': path.stat().st_size, 'sha256': decision_packets.file_hash(path)}
    return files


def create(output, destination, proposal, reference):
    """Called by the trusted prepare job only after product and scan validation."""
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(output / 'release-set.json', destination / 'release-set.json')
    for channel in CHANNELS:
        shutil.copytree(output / ('security-' + channel), destination / ('security-' + channel), symlinks=True)
        target = destination / 'signed' / channel
        target.mkdir(parents=True)
        core = proposal['payload']['channels'][channel]['assets']
        for path in (output / 'signed' / channel).iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unsafe signing request member')
            if path.name not in core:
                shutil.copyfile(path, target / path.name)
    record = {'schema': 1, 'proposalHash': canonical_hash(proposal),
              'payloadDigest': canonical_hash(proposal['payload']),
              'productReference': reference, 'preparation': producer()}
    (destination / 'handoff.json').write_text(json.dumps(record, sort_keys=True) + '\n')
    validate(destination, proposal, reference)
    inventory(destination)


def validate(output, proposal, reference):
    record = load_json(output / 'handoff.json')
    if (not isinstance(record, dict)
            or set(record) != {'schema', 'proposalHash', 'payloadDigest', 'productReference', 'preparation'}
            or type(record['schema']) is not int or record['schema'] != 1
            or record['proposalHash'] != canonical_hash(proposal)
            or record['payloadDigest'] != canonical_hash(proposal['payload'])
            or record['productReference'] != reference or not decision_packets.REFERENCE.fullmatch(reference)
            or load_json(output / 'release-set.json').get('payload') != proposal['payload']):
        raise ValueError('Signing request differs from approved products or original packet')
    for channel in CHANNELS:
        core = proposal['payload']['channels'][channel]['assets']
        directory = output / 'signed' / channel
        if any((directory / name).exists() or (directory / name).is_symlink() for name in core):
            raise ValueError('Signing request must contain metadata only')
        required = {'release-set.json', 'security-result.json', 'sbom.spdx.json', 'security-admission.json'}
        names = {path.name for path in directory.iterdir()}
        if not required <= names or names - required - {'SHA256SUMS', 'SHA256SUMS.bundle.json'}:
            raise ValueError('Unexpected signing metadata inventory')
    inventory(output)
    return record


def hydrate(output, proposal, reference, *, api, collection, verify_signed, cached_packet=None):
    """Use original immutable products; never rebuild or sign product bytes."""
    record = validate(output, proposal, reference)
    native_preparation(record['preparation'], api, collection)
    document = load_json(output / 'release-set.json')
    verify_signed(output, document, metadata_only=True)
    context = tempfile.TemporaryDirectory(dir=output.parent) if cached_packet is None else nullcontext(None)
    with context as temporary:
        packet = Path(temporary) / 'products' if cached_packet is None else cached_packet
        decision_packets.fetch(reference, packet, existing=packet.exists())
        if load_json(packet / 'release-set.json').get('payload') != proposal['payload']:
            raise ValueError('Immutable original packet differs from approved products')
        for channel in CHANNELS:
            for name, digest in proposal['payload']['channels'][channel]['assets'].items():
                path = packet / ('release-' + channel) / name
                if path.is_symlink() or not path.is_file() or decision_packets.file_hash(path) != digest:
                    raise ValueError('Original product differs from signed approved hash: ' + name)
                os.link(path, output / 'signed' / channel / name)
    verify_signed(output, document)
