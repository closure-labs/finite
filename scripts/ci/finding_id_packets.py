"""Authenticate new finding-ID exceptions; never grants decision authority."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import decision_controller
import security_admission
from security_decisions import canonical_hash

ROOT = Path(__file__).resolve().parents[2]
PACKET = re.compile(r'automation/decisions/security/([0-9a-f]{64})\.json')
MAX_DOCUMENT = 2 * 1024**2
MAX_NATIVE = 2 * 768 * 1024**2 + MAX_DOCUMENT


def git(candidate, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(candidate), *args],
                                   stderr=subprocess.DEVNULL, timeout=30)


def proposal_lines(raw, path):
    if not PACKET.fullmatch(path) or len(raw) > MAX_DOCUMENT:
        raise ValueError('Invalid bounded security packet path')
    value = decision_controller.decision_packets.decode_json(raw)
    if (decision_controller.authority.proposal_path(value) != path or value['kind'] != 'security-findings'
            or raw != (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()):
        raise ValueError('Noncanonical security packet')
    security_admission.validate_proposal(value, decision_controller.REPOSITORY)
    marked = copy.deepcopy(value)
    markers = []
    for index, finding in enumerate(value['payload']['findings']):
        # Independently recompute the identity even though normalized validation
        # already round-trips it. Neither a field label nor plausible hex suffices.
        if finding['key'] != canonical_hash({k: finding[k] for k in ('profile', 'component', 'advisory', 'exposure')}):
            raise ValueError('Finding identity mismatch')
        marker = ('__FINITE_FINDING_ID_' + str(index)).ljust(64, '_')
        if len(marker) != 64 or marker.encode() in raw:
            raise ValueError('Ambiguous finding marker')
        marked['payload']['findings'][index]['key'] = marker
        markers.append((finding['key'], marker))
    rendered = json.dumps(marked, indent=2, allow_nan=False)
    text = raw.decode('utf-8')
    source_lines = text.splitlines()
    lines = []
    for key, marker in markers:
        quoted = json.dumps(marker)
        if rendered.count(quoted) != 1:
            raise ValueError('Ambiguous finding position')
        offset = rendered.index(quoted)
        line = text.count('\n', 0, offset) + 1
        if (text[offset:offset + 66] != json.dumps(key)
                or not re.fullmatch(r'        "key": "' + key + r'",?', source_lines[line - 1])):
            raise ValueError('Finding ID is not a standalone canonical field')
        lines.append(line)
    return value, lines


def authenticate_packet(value, base, candidate):
    source = value['payload']['packet']['producer']['headSha']
    # Producer must be in protected main history, not a candidate side commit.
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(candidate),
                    'merge-base', '--is-ancestor', source, base], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    # Existing validator authenticates OCI descriptor/layer bytes, canonical
    # request hash, live producer/source/run/attempt, both Actions ZIP digests,
    # exact native file inventories and reevaluated normalized finding ceilings.
    packets = decision_controller.decision_packets
    prior_bytes, prior_files = packets.MAX_BYTES, packets.MAX_FILES
    try:
        packets.MAX_BYTES, packets.MAX_FILES = MAX_NATIVE, 128
        decision_controller.validate_proposal_packet(value)
    finally:
        packets.MAX_BYTES, packets.MAX_FILES = prior_bytes, prior_files


def fingerprints(candidate, base, head):
    if (git(candidate, 'rev-parse', '--is-shallow-repository').decode().strip() != 'false'
            or git(candidate, 'rev-parse', 'HEAD').decode().strip() != head):
        raise ValueError('Candidate differs from declared head')
    changed = {}
    for commit in git(candidate, 'rev-list', '--full-history', base + '..' + head).decode().splitlines():
        parents = git(candidate, 'show', '-s', '--format=%P', commit).decode().split()
        paths = git(candidate, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                    '--diff-filter=AM', '--name-only', '-z', parents[0], commit, '--',
                    'automation/decisions/security') if parents else b''
        for name in paths.split(b'\0'):
            path = name.decode('utf-8')
            if not PACKET.fullmatch(path):
                continue
            # Existing protected-base packet semantics remain wholly unchanged.
            if git(candidate, 'ls-tree', base, '--', path):
                continue
            entry = git(candidate, 'ls-tree', commit, '--', path).split(b'\t', 1)[0].split()
            if len(entry) != 3 or entry[:2] != [b'100644', b'blob']:
                raise ValueError('New packet must be a regular Git blob')
            changed.setdefault(entry[2], {'path': path, 'commits': []})['commits'].append(commit)
    if len(changed) > 1:
        raise ValueError('New packet authentication is bounded to one immutable packet per range')
    result = set()
    for oid, item in changed.items():
        size = int(git(candidate, 'cat-file', '-s', oid.decode()))
        if not 0 < size <= MAX_DOCUMENT:
            raise ValueError('New packet exceeds document bound')
        raw = git(candidate, 'cat-file', 'blob', oid.decode())
        value, lines = proposal_lines(raw, item['path'])
        authenticate_packet(value, base, candidate)
        result.update(f'{commit}:{item["path"]}:generic-api-key:{line}'
                      for commit in item['commits'] for line in lines)
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Clear stale/partial output before any authentication. No payload is logged.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    base, head = os.environ['BASE_SHA'], os.environ['HEAD_SHA']
    expected_ref = 'main' if os.environ['EVENT_NAME'] == 'pull_request' else 'refs/heads/main'
    if (os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('BASE_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('BASE_REF') != expected_ref
            or os.environ['EVENT_NAME'] not in ('pull_request', 'merge_group')
            or not all(re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (base, head))
            or git(ROOT, 'rev-parse', 'HEAD').decode().strip() != base):
        raise ValueError('New packet verifier requires exact protected base tooling')
    values = fingerprints(args.candidate.resolve(), base, head)
    with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as output:
        output.write(''.join(value + '\n' for value in values))
    os.replace(output.name, args.output)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Unable to authenticate new finding-ID packet; no new exceptions granted.', file=sys.stderr)
        raise SystemExit(1)
