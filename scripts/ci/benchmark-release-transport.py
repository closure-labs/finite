#!/usr/bin/env python3
"""Create and measure new diagnostic products; never mutate release decisions."""
import argparse
import hashlib
import sys
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import decision_controller as controller
import decision_packets
import release_artifact
import release_origin
from security_decisions import canonical_hash, load_json

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('transport_execution', ROOT / 'scripts/ci/execute-release-set.py')
execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)
WORKFLOW = 'benchmark-release-transport.yml'
PACKET = Path('.bluebuild/diagnostic-packet')


def context():
    expected = f'{release_origin.REPOSITORY}/.github/workflows/{WORKFLOW}@' + os.environ.get('GITHUB_REF', '')
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != release_origin.REPOSITORY
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_WORKFLOW_REF') != expected):
        raise ValueError('Transport diagnostics require their native manual workflow')


def stage(reference):
    manifest = decision_packets.fetch(reference, PACKET)
    proposal = {'payload': load_json(PACKET / 'release-set.json')['payload']}
    execution.check_product(PACKET, proposal, manifest)
    # The diagnostic ZIP and OCI packet contain the exact original products.
    # The outer OCI producer changes; the approved product payload never does.
    (PACKET / 'decision-packet.json').unlink()


def persist(reference):
    producer = {'repository': release_origin.REPOSITORY, 'workflow': WORKFLOW,
                'runId': int(os.environ['GITHUB_RUN_ID']), 'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                'headSha': os.environ['GITHUB_SHA'], 'sourcePacket': reference, 'artifacts': []}
    artifact = release_artifact.bound_artifact(release_origin.REPOSITORY, producer['runId'], producer['runAttempt'],
                                              producer['headSha'], controller.collection, prefix='release-transport-packet')
    release_artifact.verify_archive(PACKET, artifact)
    producer['artifacts'] = [{k: artifact[k] for k in ('id', 'name', 'digest')}]
    packet = decision_packets.push(PACKET, producer)
    release_origin.write(PACKET, producer, artifact, packet, controller.collection,
                         Path('.bluebuild/release-set-origin.json'), diagnostic=True)
    Path('.bluebuild/diagnostic-reference.json').write_text(json.dumps(packet, indent=2) + '\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write('New diagnostic product packet: `' + packet['reference'] + '`\n')


def validate_products(directory, document):
    execution.payload_digest(document)
    execution.validate_evidence(document)
    if set(document['payload']['channels']) != {'finite', 'finite-dev'}:
        raise ValueError('Diagnostic must retain both profiles')
    # Match check_product's final approved-asset hash pass in both measured legs.
    for channel, product in document['payload']['channels'].items():
        for name, digest in product['assets'].items():
            path = directory / ('release-' + channel) / name
            if path.is_symlink() or not path.is_file() or execution.sha256(path) != digest:
                raise ValueError('Diagnostic approved asset hash mismatch')


def consume(reference, mode, phase, pair):
    Path('.bluebuild').mkdir(exist_ok=True)
    started = time.monotonic()
    result = {'schema': 1, 'kind': 'finite-release-transport-sample', 'authorizesPublication': False,
              'reference': reference, 'mode': mode, 'phase': phase, 'pair': pair,
              'runId': int(os.environ['GITHUB_RUN_ID']), 'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
              'revision': os.environ['GITHUB_SHA'], 'jobName': os.environ['FINITE_BENCHMARK_JOB'],
              'imageVersion': os.environ.get('ImageVersion'), 'correctness': False,
              'toolCohortSha256': canonical_hash({'flakeLock': hashlib.sha256((ROOT / 'flake.lock').read_bytes()).hexdigest(),
                  'python': sys.executable, 'oras': subprocess.check_output(['oras', 'version'], text=True)}),
              'setupAndRetention': 'Included in complete native job occupancy',
              'registryCacheState': 'unknown', 'startedAt': datetime.now(timezone.utc).isoformat()}
    try:
        # Both warm legs pay for the same seed. Cold means a fresh hosted runner;
        # neither condition claims control of registry/provider caches.
        rounds = ('seed', 'sample') if phase == 'warm' else ('sample',)
        for current in rounds:
            directory = Path('.bluebuild') / ('consumer-' + current)
            manifest = decision_packets.fetch(reference, directory)
            producer = manifest['producer']
            if producer.get('workflow') != WORKFLOW or producer.get('repository') != release_origin.REPOSITORY:
                raise ValueError('Benchmarks require a new native diagnostic packet')
            run_id, attempt = producer['runId'], producer['runAttempt']
            run = controller.api(f'repos/{release_origin.REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}')
            if (run.get('id') != run_id or run.get('run_attempt') != attempt or run.get('head_sha') != producer.get('headSha')
                    or run.get('path') != '.github/workflows/' + WORKFLOW or run.get('event') != 'workflow_dispatch'
                    or run.get('head_repository', {}).get('full_name') != release_origin.REPOSITORY
                    or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
                raise ValueError('Diagnostic producer must complete successfully first')
            artifact = release_artifact.bound_artifact(release_origin.REPOSITORY, run_id, attempt, producer['headSha'],
                                                       controller.collection, prefix='release-transport-packet')
            if producer.get('artifacts') != [{k: artifact[k] for k in ('id', 'name', 'digest')}]:
                raise ValueError('Diagnostic native artifact differs from immutable packet')
            if mode == 'receipt' and current == 'sample':
                if not release_origin.verify(directory, manifest, reference, artifact, controller.collection,
                                             controller.api, diagnostic=True):
                    raise ValueError('Diagnostic receipt required; no legacy fallback during measurement')
            else:
                release_artifact.verify_archive(directory, artifact, expected_files=manifest['files'])
            document = load_json(directory / 'release-set.json')
            validate_products(directory, document)
            result.update(inventorySha256=canonical_hash(manifest['files']), producer=producer,
                          productBytes=sum(f['size'] for f in manifest['files'].values()),
                          nativeArchiveBytes=artifact['size_in_bytes'])
            cleanup = time.monotonic()
            shutil.rmtree(directory)
            result[current + 'CleanupSeconds'] = time.monotonic() - cleanup
        result['correctness'] = True
    finally:
        for current in ('seed', 'sample'):
            directory = Path('.bluebuild') / ('consumer-' + current)
            if directory.exists():
                shutil.rmtree(directory)
        result['consumerSecondsIncludingCleanup'] = time.monotonic() - started
        Path('.bluebuild/transport-sample.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('stage', 'persist', 'consume'))
    parser.add_argument('--reference', required=True)
    parser.add_argument('--mode', choices=('legacy', 'receipt'), default='legacy')
    parser.add_argument('--phase', choices=('cold', 'warm'), default='cold')
    parser.add_argument('--pair', type=int, default=1)
    args = parser.parse_args()
    context()
    if not 1 <= args.pair <= 5:
        raise ValueError('Diagnostic pair must be 1..5')
    if args.command == 'stage': stage(args.reference)
    elif args.command == 'persist': persist(args.reference)
    else: consume(args.reference, args.mode, args.phase, args.pair)


if __name__ == '__main__':
    main()
