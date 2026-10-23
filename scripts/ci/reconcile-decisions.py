#!/usr/bin/env python3
"""Resume eligible retained candidates after a merged human decision, without waiting runners."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import decision_controller as controller
import decision_packets
from release_set import GitHubClient
from security_admission import verify
from security_decisions import canonical_hash, load_json


LEASE_SECONDS = 900


def build_inputs(profile, origin):
    """Expired or superseded retained artifacts require a fresh full build."""
    inputs = {'target': profile}
    if origin['workflow'].removeprefix('.github/workflows/') != 'build.yml':
        return inputs
    run_id = origin['runId']
    run = controller.api(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}')
    if (run.get('path', '').removeprefix('.github/workflows/') != 'build.yml'
            or run.get('head_repository', {}).get('full_name') != controller.REPOSITORY
            or run.get('head_branch') != 'main' or run.get('event') not in controller.PRODUCERS['build.yml']):
        raise ValueError('Resume origin is not a trusted main build')
    if (run.get('id') != run_id or run.get('head_sha') != origin['headSha']
            or run.get('run_attempt') != origin['runAttempt'] or run.get('status') != 'completed'):
        return inputs
    artifacts = controller.collection(f'repos/{controller.REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
    expected = {f'{kind}-{profile}-{run_id}-{origin["runAttempt"]}' for kind in ('image', 'security')}
    selected = [artifact for artifact in artifacts if artifact.get('name') in expected]
    if (len(selected) != len(expected) or {artifact.get('name') for artifact in selected} != expected
            or any(artifact.get('expired') is not False for artifact in selected)):
        return inputs
    inputs['resume_run'] = str(run_id)
    return inputs


def observed_dispatch(binding):
    title = 'Build Finite [decision:' + binding + ']'
    runs = controller.collection(f'repos/{controller.REPOSITORY}/actions/workflows/build.yml/runs?branch=main&event=workflow_dispatch', 'workflow_runs')
    matching = [run for run in runs if run.get('display_title') == title
                and run.get('event') == 'workflow_dispatch' and run.get('head_branch') == 'main'
                and run.get('head_repository', {}).get('full_name') == controller.REPOSITORY
                and run.get('path', '').removeprefix('.github/workflows/') == 'build.yml']
    if any(type(run.get('id')) is not int or run['id'] < 1 for run in matching):
        raise ValueError('Invalid observed decision dispatch')
    return max(matching, key=lambda run: run['id']) if matching else None


def publication_busy():
    """Do not replace another publisher in GitHub's single pending concurrency slot."""
    runs = controller.collection(f'repos/{controller.REPOSITORY}/actions/workflows/build.yml/runs?branch=main', 'workflow_runs')
    for run in runs:
        if (run.get('event') in controller.PRODUCERS['build.yml'] and run.get('head_branch') == 'main'
                and run.get('head_repository', {}).get('full_name') == controller.REPOSITORY
                and run.get('path', '').removeprefix('.github/workflows/') == 'build.yml'
                and run.get('status') != 'completed'):
            return True
    return False


def reconcile(now=time.time):
    controller.trusted_context()
    mode = load_json(controller.ROOT / 'automation/security/image-policy.json').get('mode', 'fixable-severity')
    if mode not in ('fixable-severity', 'upstream-maintained-risk', 'desktop-critical-only', 'maintainer-decision'):
        raise ValueError('Unknown checked-in image security policy mode')
    if mode != 'maintainer-decision':
        return [{'status': 'awaiting-policy-cutover', 'mode': mode}]
    bot = os.environ['FINITE_REVIEW_BOT_LOGIN']
    ledger = controller.ROOT / 'automation/decisions/security'
    if ledger.is_symlink():
        raise ValueError('Decision ledger must not be a symlink')
    paths = sorted(ledger.glob('*.json')) if ledger.exists() else []
    if len(paths) > 10000:
        raise ValueError('Decision reconciliation ledger exceeds bounded record count')
    records = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 8 * 1024**2:
            raise ValueError('Decision reconciliation requires bounded regular proposal files')
        proposal = load_json(path)
        identity = canonical_hash(proposal)
        if path.is_symlink() or path.name != identity + '.json' or identity in records:
            raise ValueError('Invalid immutable decision ledger identity')
        records[identity] = proposal
    journal = GitHubClient(controller.REPOSITORY, 'automation/decision-journal')
    actions = []
    for profile in controller.PROFILES:
        relevant = {key for key, p in records.items() if profile in p['payload']['profiles']}
        superseded = {parent for key in relevant for parent in records[key]['payload']['supersedes']}
        leaves = relevant - superseded
        if not leaves:
            continue
        if len(leaves) != 1:
            raise ValueError('Ambiguous decision leaves cannot trigger publication')
        identity = next(iter(leaves))
        proposal = records[identity]
        packet = proposal['payload']['packet']
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'packet'
            decision_packets.fetch(packet['reference'], directory, packet['sha256'])
            # Packets retain the original native bytes, including summaries
            # written before maintainer mode. Reconstruct the accepted snapshot
            # so its CVSS ceilings and related severities are preserved. This
            # historical clock selects build/rescan work only: publication
            # independently enforces fresh native evidence and live authority.
            native = directory / profile
            scanned = load_json(native / 'vulnerabilities.json')['descriptor']['timestamp']
            if not isinstance(scanned, str):
                raise ValueError('Decision snapshot requires a native scan timestamp')
            snapshot_time = datetime.fromisoformat(scanned.replace('Z', '+00:00'))
            if snapshot_time.tzinfo is None or snapshot_time > datetime.now(timezone.utc):
                raise ValueError('Decision snapshot requires an authenticated historical scan time')
            scan = controller.native_result(native, snapshot_time, snapshot_time, profile=profile)
            admission = verify(scan, profile, controller.REPOSITORY, bot)
        if admission['status'] != 'covered':
            actions.append({'profile': profile, 'status': admission['status']})
            continue
        if (not isinstance(admission.get('decision'), dict)
                or admission['decision'].get('proposalHash') != identity):
            raise ValueError('Reconciliation decision differs from authenticated active decision')
        request_id = canonical_hash({'decision': identity, 'profile': profile, 'image': scan['image']})
        state, version = journal.read_journal(request_id)
        origin = packet['producer']
        inputs = build_inputs(profile, origin)
        if 'resume_run' in inputs:
            # Existing trusted build/resume contracts reauthenticate ancestry,
            # image identity and native evidence; stale evidence is rescanned.
            inputs['resume_digest'] = scan['image'].split('@')[1]
        binding = canonical_hash({'request': request_id, 'inputs': inputs})
        if state:
            if (state.get('schema') != 1 or state.get('decision') != identity or state.get('profile') != profile
                    or state.get('status') not in ('claimed', 'dispatched') or not isinstance(state.get('inputs'), dict)
                    or state['inputs'].get('target') != profile
                    or set(state['inputs']) - {'target', 'resume_run', 'resume_digest'}
                    or ('binding' in state and state['binding'] != canonical_hash({'request': request_id, 'inputs': state['inputs']}))
                    or type(state.get('leaseUntil', 0)) not in (int, float)):
                raise ValueError('Invalid reconciliation journal')
            observed = observed_dispatch(state.get('binding', binding))
            if observed:
                if state.get('status') != 'dispatched' or state.get('observedRun') != observed['id'] or state.get('leaseUntil') != 0:
                    state.update(status='dispatched', observedRun=observed['id'], leaseUntil=0)
                    version = journal.write_journal(request_id, state, version)
                # A resume that failed after its inputs expired is retried once
                # as a new full build, with its own discoverable request marker.
                fallback = ('resume_run' in state['inputs'] and 'resume_run' not in inputs
                            and observed.get('status') == 'completed'
                            and observed.get('conclusion') in ('failure', 'cancelled'))
                if not fallback:
                    actions.append({'profile': profile, 'status': 'already-dispatched', 'run': observed['id']})
                    continue
            elif state.get('status') == 'dispatched':
                actions.append({'profile': profile, 'status': 'already-dispatched'})
                continue
            elif state.get('leaseUntil', 0) > now():
                actions.append({'profile': profile, 'status': 'dispatch-pending'})
                continue
        if publication_busy():
            actions.append({'profile': profile, 'status': 'publisher-busy'})
            continue
        claim = {'schema': 1, 'status': 'claimed', 'decision': identity, 'profile': profile,
                 'inputs': inputs, 'binding': binding, 'leaseUntil': now() + LEASE_SECONDS}
        # CAS establishes one dispatcher before a side effect. An ambiguous POST
        # or crash leaves a discoverable claim; a later invocation observes the
        # run marker before retrying an expired claim.
        version = journal.write_journal(request_id, claim, version)
        admission = verify(scan, profile, controller.REPOSITORY, bot)
        if (admission['status'] != 'covered' or not isinstance(admission.get('decision'), dict)
                or admission['decision'].get('proposalHash') != identity):
            raise ValueError('Decision authority changed before build dispatch')
        revision = os.environ.get('GITHUB_SHA', '')
        current = controller.api(f'repos/{controller.REPOSITORY}/git/ref/heads/main')
        if not re.fullmatch(r'[0-9a-f]{40}', revision) or current.get('object', {}).get('sha') != revision:
            raise ValueError('Main changed before decision build dispatch; reconcile the current revision')
        if publication_busy():
            actions.append({'profile': profile, 'status': 'publisher-busy'})
            continue
        inputs = {**inputs, 'decision_request': binding}
        controller.api(f'repos/{controller.REPOSITORY}/actions/workflows/build.yml/dispatches', 'POST',
                       {'ref': 'main', 'inputs': inputs})
        journal.write_journal(request_id, {**claim, 'status': 'dispatched', 'leaseUntil': 0}, version)
        actions.append({'profile': profile, 'status': 'dispatched'})
        # The workflow's hourly/completed-build reconciler handles the next
        # profile after this run. Multiple POSTs can replace queued publishers.
        break
    return actions


if __name__ == '__main__':
    try:
        print(json.dumps({'schema': 1, 'actions': reconcile()}))
    except Exception as error:
        print('Decision reconciliation failed: ' + str(error), file=sys.stderr)
        sys.exit(2)
