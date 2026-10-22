#!/usr/bin/env python3
"""Resolve approved product bytes, rescan, sign, and publish a two-image release.

No code from an OCI packet is executed. Each phase uses trusted checkout code.
Signing is a separate phase so workflows can verify authority before exposing keys.
"""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import decision_controller as controller
import decision_packets
import release_artifact
import archive_read
from release_set import CHANNELS, GitHubClient, execute, payload_digest, sha256, validate_evidence
from security_decisions import canonical_hash, load_json

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def approved(proposal_hash, github=None):
    if not re.fullmatch(r'[0-9a-f]{64}', proposal_hash):
        raise ValueError('Invalid release proposal identity')
    proposal = load_json(ROOT / 'automation/decisions/releases' / (proposal_hash + '.json'))
    if canonical_hash(proposal) != proposal_hash or proposal.get('kind') != 'release-set':
        raise ValueError('Release proposal content differs from requested authority')
    authority = controller.authority
    repository, bot = controller.REPOSITORY, os.environ.get('FINITE_REVIEW_BOT_LOGIN')
    number = authority.find_origin_pr(proposal, repository, bot, github=github)
    receipt = authority.verify_proposal(proposal, number, repository, bot,
                                        require_merged=True, github=github)
    api = github or authority.github_api
    pull = api(f'repos/{repository}/pulls/{number}')
    references = re.findall(r'^Initial durable product packet: `(ghcr\.io/closure-labs/finite-decisions@sha256:[0-9a-f]{64})`\s*$',
                            pull.get('body') or '', re.MULTILINE)
    if len(references) != 1:
        raise ValueError('Approved release PR lacks one unambiguous initial packet reference')
    return proposal, receipt, references[0]


def check_product(packet, proposal, manifest, github=None, *, cached_archive=None):
    document = load_json(packet / 'release-set.json')
    if document.get('payload') != proposal['payload']:
        raise ValueError('Packet product bytes differ from approved release payload')
    payload_digest(document)
    validate_evidence(document)
    producer = manifest['producer']
    run_id = producer.get('runId')
    attempt = producer.get('runAttempt')
    if type(run_id) is not int or run_id <= 0 or type(attempt) is not int or attempt <= 0:
        raise ValueError('Invalid initial release packet producer')
    api = github or controller.api
    run = api(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}')
    if (producer.get('repository') != controller.REPOSITORY
            or producer.get('workflow') != 'release-set.yml'
            or producer.get('headSha') != document['payload']['sourceRevision']
            or run.get('head_sha') != producer['headSha'] or run.get('id') != run_id
            or run.get('run_attempt') != producer.get('runAttempt')
            or run.get('path') != '.github/workflows/release-set.yml'
            or run.get('head_repository', {}).get('full_name') != controller.REPOSITORY
            or run.get('head_branch') != 'main' or run.get('event') != 'workflow_dispatch'
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise ValueError('Product packet lacks a successful trusted release-set producer')
    artifact = release_artifact.bound_artifact(controller.REPOSITORY, run_id, attempt,
                                               producer['headSha'], controller.collection)
    binding = [{key: artifact[key] for key in ('id', 'name', 'digest')}]
    if producer.get('artifacts') != binding:
        raise ValueError('Initial product packet does not bind the actual uploaded artifact')
    release_artifact.verify_archive(packet, artifact, controller.REPOSITORY, manifest['files'], cached_archive=cached_archive)
    for channel in CHANNELS:
        directory = packet / ('release-' + channel)
        for name, digest in document['payload']['channels'][channel]['assets'].items():
            path = directory / name
            if path.is_symlink() or not path.is_file() or sha256(path) != digest:
                raise ValueError('Approved product asset mismatch: ' + name)
    return document



def check_signed_packet(packet, proposal, manifest, github=None):
    document = load_json(packet / 'release-set.json')
    if document.get('payload') != proposal['payload']:
        raise ValueError('Recovery packet differs from approved products')
    payload_digest(document)
    validate_evidence(document)
    producer = manifest['producer']
    api = github or controller.api
    run_id, attempt = producer.get('runId'), producer.get('runAttempt')
    if type(run_id) is not int or run_id <= 0 or type(attempt) is not int or attempt <= 0:
        raise ValueError('Invalid signed recovery producer')
    run = api(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}')
    if (producer.get('repository') != controller.REPOSITORY
            or producer.get('workflow') != 'publish-release-set.yml'
            or run.get('head_sha') != producer.get('headSha') or run.get('id') != run_id
            or run.get('run_attempt') != attempt or run.get('path') != '.github/workflows/publish-release-set.yml'
            or run.get('head_repository', {}).get('full_name') != controller.REPOSITORY
            or run.get('head_branch') != 'main' or run.get('event') != 'workflow_dispatch'
            or run.get('status') != 'completed'):
        raise ValueError('Recovery packet lacks a completed trusted publisher producer')
    jobs = controller.collection(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs', 'jobs')
    signers = [job for job in jobs if job.get('name') == 'sign' and job.get('conclusion') == 'success']
    if len(signers) != 1:
        raise ValueError('Recovery packet producer did not complete isolated signing')
    signed_inventory(packet, document)
    return document


def verify_scans(output, document):
    policy = module('release_execution_policy', ROOT / 'scripts/bluebuild/security-policy.py')
    configuration = policy.load_policy(ROOT / 'automation/security/image-policy.json')
    if configuration.get('mode') != 'maintainer-decision':
        raise ValueError('Release-set publication requires completed maintainer-decision cutover')
    receipts = {}
    for channel in CHANNELS:
        image = 'ghcr.io/closure-labs/finite@' + document['payload']['channels'][channel]['imageDigest']
        result = policy.verify(output / ('security-' + channel), image)
        if result.get('admission', {}).get('status') != 'covered':
            raise ValueError('Release findings lack current authenticated acceptance')
        receipts[channel] = result['admission']
    return receipts


def validate_signed(channel, directory, core, derived, document):
    for name, digest in {**core, **derived}.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError('Signed release bytes changed')
    if 'release-set.json' not in derived:
        raise ValueError('Signed evidence must bind the complete approved release payload')
    signed_document = load_json(directory / 'release-set.json')
    if signed_document.get('payload') != document['payload'] or payload_digest(signed_document) != payload_digest(document):
        raise ValueError('Signed release manifest belongs to a different approved payload')
    subprocess.run(['cosign', 'verify-blob', '--key', str(ROOT / 'cosign.pub'),
                    '--bundle', str(directory / 'SHA256SUMS.bundle.json'),
                    str(directory / 'SHA256SUMS')], check=True, timeout=150)
    rows = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]{0,199})', line)
        if match is None or match[2] in rows:
            raise ValueError('Invalid or duplicate signed checksum entry')
        rows[match[2]] = match[1]
    expected = {**core, **{k: v for k, v in derived.items() if k not in ('SHA256SUMS', 'SHA256SUMS.bundle.json')}}
    if rows != expected:
        raise ValueError('Signed checksums do not cover the exact approved products and evidence')


def signed_inventory(output, document):
    roots, derived = {}, {}
    for channel in CHANNELS:
        roots[channel] = output / 'signed' / channel
        core = document['payload']['channels'][channel]['assets']
        derived[channel] = {}
        for path in roots[channel].iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError('Signed release assets must be regular files')
            if path.name not in core:
                derived[channel][path.name] = sha256(path)
        validate_signed(channel, roots[channel], core, derived[channel], document)
    return roots, derived


def stage_signing(output, document, receipts):
    for channel in CHANNELS:
        destination = output / 'signed' / channel
        destination.mkdir(parents=True, exist_ok=False)
        for name in document['payload']['channels'][channel]['assets']:
            os.link(output / 'packet' / ('release-' + channel) / name, destination / name)
        for name in ('security-result.json', 'sbom.spdx.json'):
            shutil.copyfile(output / ('security-' + channel) / name, destination / name)
        (destination / 'release-set.json').write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
        (destination / 'security-admission.json').write_text(json.dumps(receipts[channel], sort_keys=True, indent=2) + '\n')


def compact_handoff(output, document):
    """Keep packet authentication evidence; carry product bytes only in signed/."""
    for channel in CHANNELS:
        for name in document['payload']['channels'][channel]['assets']:
            (output / 'packet' / ('release-' + channel) / name).unlink(missing_ok=True)
    recovered = output / 'packet/signed'
    if recovered.exists():
        shutil.rmtree(recovered)


def sign(output, document):
    if not os.environ.get('COSIGN_PRIVATE_KEY'):
        raise ValueError('Scoped signing credentials are unavailable')
    for channel in CHANNELS:
        directory = output / 'signed' / channel
        entries = {}
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unexpected signing asset')
            if path.name not in ('SHA256SUMS', 'SHA256SUMS.bundle.json'):
                entries[path.name] = sha256(path)
        if any(entries.get(name) != digest for name, digest in document['payload']['channels'][channel]['assets'].items()):
            raise ValueError('Signing assets differ from approved products')
        (directory / 'SHA256SUMS').write_text(''.join(digest + '  ' + name + '\n' for name, digest in sorted(entries.items())))
        subprocess.run(['cosign', 'sign-blob', '--yes', '--key', 'env://COSIGN_PRIVATE_KEY',
                        '--bundle', str(directory / 'SHA256SUMS.bundle.json'), str(directory / 'SHA256SUMS')],
                       check=True, timeout=150)
    signed_inventory(output, document)



def download_execution(output, signed=True, github=None):
    """Resolve the exact successful producing attempt instead of assuming retry attempt."""
    api = github or controller.api
    run_id, attempt = int(os.environ['GITHUB_RUN_ID']), int(os.environ['GITHUB_RUN_ATTEMPT'])
    run = api(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}')
    if (run.get('path') != '.github/workflows/publish-release-set.yml'
            or run.get('head_sha') != os.environ['GITHUB_SHA'] or run.get('head_branch') != 'main'
            or run.get('head_repository', {}).get('full_name') != controller.REPOSITORY):
        raise ValueError('Execution artifact is not from this trusted workflow run')
    prefix = ('signed-' if signed else '') + f'release-execution-{run_id}-'
    artifacts = controller.collection(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
    candidates = []
    for artifact in artifacts:
        name = artifact.get('name', '')
        if not re.fullmatch(re.escape(prefix) + r'[1-9][0-9]*', name) or artifact.get('expired') is not False:
            continue
        producing_attempt = int(name[len(prefix):])
        binding = artifact.get('workflow_run', {})
        if (producing_attempt > attempt or binding.get('id') != run_id
                or binding.get('head_sha') != os.environ['GITHUB_SHA']
                or type(artifact.get('id')) is not int or artifact['id'] <= 0
                or type(artifact.get('size_in_bytes')) is not int
                or not 0 < artifact['size_in_bytes'] <= 64 * 1024**3
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))):
            raise ValueError('Execution artifact lacks immutable same-run producer binding')
        candidates.append((producing_attempt, artifact))
    if not candidates:
        raise ValueError('No retained exact-byte execution artifact; use immutable signed recovery packet')
    latest = max(value[0] for value in candidates)
    choices = [artifact for producing_attempt, artifact in candidates if producing_attempt == latest]
    if len(choices) != 1:
        raise ValueError('Ambiguous execution artifact attempt')
    artifact = choices[0]
    with archive_read.archive_reader(artifact, controller.REPOSITORY) as archive:
        archive_read.extract(archive, output)
    return artifact



def proposal_from_push(github=None, event=None):
    if os.environ.get('GITHUB_EVENT_NAME') != 'push':
        raise ValueError('A release proposal hash is required for manual recovery')
    event = event if event is not None else load_json(os.environ['GITHUB_EVENT_PATH'])
    before, after = event.get('before', ''), os.environ.get('GITHUB_SHA', '')
    if (not re.fullmatch(r'[0-9a-f]{40}', before) or before == '0' * 40
            or not re.fullmatch(r'[0-9a-f]{40}', after)):
        raise ValueError('Automatic release requires an exact existing main push range')
    comparison = (github or controller.api)(f'repos/{controller.REPOSITORY}/compare/{before}...{after}')
    files = comparison.get('files')
    if comparison.get('status') != 'ahead' or not isinstance(files, list) or len(files) >= 300:
        raise ValueError('Cannot establish complete automatic release proposal diff')
    releases = [item for item in files if item.get('filename', '').startswith('automation/decisions/releases/')]
    if len(releases) != 1 or releases[0].get('status') != 'added':
        raise ValueError('Automatic release requires exactly one newly added decision')
    match = re.fullmatch(r'automation/decisions/releases/([0-9a-f]{64})\.json', releases[0]['filename'])
    if match is None:
        raise ValueError('Automatic release path is not a canonical decision identity')
    proposal = load_json(ROOT / releases[0]['filename'])
    if canonical_hash(proposal) != match[1] or proposal.get('kind') != 'release-set':
        raise ValueError('Automatic release proposal differs from its immutable ledger path')
    return match[1]


@contextmanager
def artifact_reader_credentials():
    token = os.environ.get('ARTIFACT_READ_TOKEN')
    if not token:
        raise ValueError('Staging requires the hosted read-only artifact token')
    previous = os.environ.get('GH_TOKEN')
    try:
        os.environ['GH_TOKEN'] = token
        yield
    finally:
        if previous is None:
            os.environ.pop('GH_TOKEN', None)
        else:
            os.environ['GH_TOKEN'] = previous


def materialize_products(output, proposal, reference, *, staged=False, retain_archive=False):
    if staged:
        if output.is_symlink() or not output.is_dir():
            raise ValueError('Staged execution directory is missing or unsafe')
    else:
        output.mkdir(parents=True, exist_ok=False)
    print('Release phase: authenticate ' + ('staged' if staged else 'downloaded') + ' OCI product packet', flush=True)
    manifest = decision_packets.fetch(reference, output / 'packet', existing=staged)
    recovered = manifest.get('producer', {}).get('workflow') == 'publish-release-set.yml'
    cached = output / 'transport' / 'original.zip' if staged or retain_archive else None
    if recovered:
        document = check_signed_packet(output / 'packet', proposal, manifest)
    else:
        if staged and (cached.is_symlink() or not cached.is_file()):
            raise ValueError('Staged original archive is missing or unsafe')
        print('Release phase: authenticate original Actions archive and every product member', flush=True)
        try:
            document = check_product(output / 'packet', proposal, manifest, cached_archive=cached)
        finally:
            if staged:
                cached.unlink(missing_ok=True)
    return document, recovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('identity', 'stage', 'prepare', 'download', 'check', 'sign', 'persist-signed', 'stage-publication', 'commit-publication', 'publish'))
    parser.add_argument('--proposal-hash', default='')
    parser.add_argument('--packet-ref', default='')
    parser.add_argument('--unsigned', action='store_true')
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--directory', type=Path, default=ROOT / '.bluebuild/release-execution')
    args = parser.parse_args()
    if args.staged and args.phase != 'prepare':
        parser.error('--staged is only valid for prepare')
    controller.trusted_context()
    if not args.proposal_hash:
        args.proposal_hash = proposal_from_push()
    output = args.directory
    # Sign runs only in a protected job immediately after a separate fresh check;
    # keys never enter the authority or scanner subprocesses.
    if args.phase == 'sign':
        document = load_json(output / 'release-set.json')
        proposal = load_json(ROOT / 'automation/decisions/releases' / (args.proposal_hash + '.json'))
        if canonical_hash(proposal) != args.proposal_hash or proposal['payload'] != document['payload']:
            raise ValueError('Signing product differs from reviewed payload')
        sign(output, document)
        return
    proposal, receipt, initial = approved(args.proposal_hash)
    if args.phase == 'identity':
        # Discovery only. Consumers still authenticate native artifact binding;
        # neither this metadata nor the monitor grants release authority.
        identity = {'schema': 1, 'proposalHash': args.proposal_hash,
                    'payloadDigest': canonical_hash(proposal['payload']), 'version': proposal['payload']['version'],
                    'repository': controller.REPOSITORY, 'workflow': 'publish-release-set.yml',
                    'runId': int(os.environ['GITHUB_RUN_ID']), 'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                    'headSha': os.environ['GITHUB_SHA']}
        path = ROOT / '.bluebuild/release-execution-identity.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(identity, sort_keys=True) + '\n')
        return
    if args.phase == 'download':
        with artifact_reader_credentials():
            download_execution(output, signed=not args.unsigned)
        return
    if args.phase == 'stage':
        # Human approval is checked above using the short-lived App token.
        # Large immutable reads use the job token, whose lifetime covers the job.
        with artifact_reader_credentials():
            document, _ = materialize_products(output, proposal, args.packet_ref or initial, retain_archive=True)
        (output / 'release-set.json').write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
        print('Release phase: product staging complete; obtain fresh authority credentials before scanning', flush=True)
    elif args.phase == 'prepare':
        if args.staged:
            document, recovered = materialize_products(output, proposal, args.packet_ref or initial, staged=True)
        else:
            with artifact_reader_credentials():
                document, recovered = materialize_products(output, proposal, args.packet_ref or initial)
        for channel in CHANNELS:
            print('Release phase: fresh security scan and current admission for ' + channel, flush=True)
            image = 'ghcr.io/closure-labs/finite@' + document['payload']['channels'][channel]['imageDigest']
            subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'), image,
                            str(output / ('security-' + channel))], check=True, timeout=3600)
        receipts = verify_scans(output, document)
        (output / 'release-set.json').write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
        if recovered:
            shutil.copytree(output / 'packet/signed', output / 'signed', copy_function=os.link)
        else:
            stage_signing(output, document, receipts)
        compact_handoff(output, document)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('recovered_signed=' + str(recovered).lower() + '\n')
                stream.write('proposal_hash=' + args.proposal_hash + '\n')
    else:
        document = load_json(output / 'release-set.json')
        if document['payload'] != proposal['payload']:
            raise ValueError('Execution payload differs from current human authority')
        validate_evidence(document)
        verify_scans(output, document)
        if args.phase == 'persist-signed':
            signed_inventory(output, document)
            with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
                packet = Path(temporary)
                shutil.copyfile(output / 'release-set.json', packet / 'release-set.json')
                shutil.copytree(output / 'signed', packet / 'signed', copy_function=os.link)
                producer = {'repository': controller.REPOSITORY, 'workflow': 'publish-release-set.yml',
                            'runId': int(os.environ['GITHUB_RUN_ID']),
                            'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                            'headSha': os.environ['GITHUB_SHA'], 'artifacts': []}
                reference = decision_packets.push(packet, producer)
                print(json.dumps(reference, sort_keys=True))
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                        summary.write('Signed exact-byte recovery packet: `' + reference['reference'] + '`\n')
        if args.phase in ('stage-publication', 'commit-publication', 'publish'):
            roots, derived = signed_inventory(output, document)
            client = GitHubClient(controller.REPOSITORY, token=os.environ['RELEASE_PUBLISH_TOKEN'])
            def publication_guard(channel, directory, core, evidence):
                # Large uploads can outlive an approval or evidence freshness.
                # Recheck live authority at each actual public release boundary.
                fresh, _, _ = approved(args.proposal_hash)
                if fresh['payload'] != document['payload']:
                    raise ValueError('Release authority changed during staging')
                verify_scans(output, document)
                validate_signed(channel, directory, core, evidence, document)
            result = execute(document, client, roots, payload_digest(document),
                             owner=os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'],
                             derived_assets=derived, evidence_validator=publication_guard, phase=args.phase)
            print(json.dumps(result, sort_keys=True))
    (output / 'release-authority.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
