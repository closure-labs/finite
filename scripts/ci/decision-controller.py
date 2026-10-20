#!/usr/bin/env python3
"""Create reviewable, bot-authored decisions from authenticated hosted evidence."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

import decision_controller as controller
import decision_packets
from security_decisions import load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('collect', 'propose', 'revoke', 'propose-cutover'))
    parser.add_argument('--run', type=int)
    parser.add_argument('--kind', choices=('security-findings', 'security-revocation', 'release-set'))
    parser.add_argument('--packet-directory', type=Path, default=Path('.bluebuild/decision-packet'))
    parser.add_argument('--disposition', choices=('accepted', 'rejected'), default='accepted')
    parser.add_argument('--rationale')
    parser.add_argument('--decision-hash')
    parser.add_argument('--proposal', type=Path)
    args = parser.parse_args()
    controller.trusted_context()
    if args.command == 'propose-cutover':
        if (args.run is None or args.kind is not None or args.proposal is not None
                or args.decision_hash is not None or args.rationale is not None or args.disposition != 'accepted'):
            raise ValueError('Cutover accepts only a producer run and local native-evidence directory')
        print(json.dumps(controller.propose_cutover(args.run, args.packet_directory)))
        return
    if args.command == 'revoke':
        import decision_revocation
        proposal = decision_revocation.create(args.decision_hash, args.rationale, controller.REPOSITORY,
                                              os.environ.get('FINITE_REVIEW_BOT_LOGIN'),
                                              controller.ROOT / 'automation/decisions/security', github=controller.api)
        print(json.dumps({'pullRequest': controller.propose(proposal)}))
        return
    if args.command == 'collect':
        if args.disposition == 'rejected' and (not args.rationale or not args.rationale.strip()):
            raise ValueError('An explicit rejection rationale is required')
        try:
            origin, findings = controller.collect(args.run, args.packet_directory)
        except controller.NoImageWork as skipped:
            print(json.dumps({'schema': 1, 'status': 'no-image-work', 'sourceRun': skipped.origin['runId'],
                              'proposalRequired': False, 'authorizesPublication': False}))
            return
        except controller.ConsolidationRequired as required:
            print(json.dumps(controller.request_consolidation(required.origin)))
            return
        if args.disposition == 'accepted':
            admission = controller.current_admission(args.packet_directory)
            if all(result['status'] == 'covered' for result in admission.values()):
                print(json.dumps({'status': 'covered', 'profiles': list(controller.PROFILES), 'proposalRequired': False}))
                return
        if any(controller.has_reused_evidence(args.packet_directory / profile) for profile in controller.PROFILES):
            print(json.dumps(controller.request_fresh_scans(origin)))
            return
        # Every current profile leaf must be explicitly superseded by this full snapshot.
        prior = controller.decision_ids()
        pending = controller.pending_proposal(findings, prior) if args.disposition == 'accepted' else None
        if pending:
            print(json.dumps(pending))
            return
        packet = decision_packets.push(args.packet_directory, origin)
        proposal = {'schema': 1, 'kind': 'security-findings', 'payload': {
            'profiles': list(controller.PROFILES), 'findings': findings, 'disposition': args.disposition,
            'supersedes': prior, 'packet': packet,
            'rationale': args.rationale or 'Proposed acceptance of the complete native scan snapshot. A human maintainer must assess exposure and approve this PR.'}}
    else:
        proposal = load_json(args.proposal)
        if proposal['kind'] != args.kind:
            raise ValueError('Proposal kind mismatch')
    print(json.dumps({'pullRequest': controller.propose(proposal, args.packet_directory)}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Decision controller failed: ' + str(error), file=sys.stderr)
        sys.exit(2)
