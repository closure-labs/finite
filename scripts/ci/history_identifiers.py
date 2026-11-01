#!/usr/bin/env python3
"""Validate reviewed exact fingerprints before giving them to upstream Gitleaks."""
from collections import Counter
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finding_id_packets as packets
from history_scan_summary import MAX_BYTES, MAX_FINDINGS

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / '.github/security'
SHAPES = {'standalone-json-public-identifier', 'standalone-python-public-key-constant',
          'standalone-recomputed-packet-key'}
KINDS = {'public-key-Git-blob', 'official-Rclone-pinned-public-key-list', 'public-Git-commit-object',
         'public-source-file-checksum', 'canonical-packet-finding-identity'}
HEX = re.compile('[a-f0-9]{64}')
FINGERPRINT = re.compile(r'([a-f0-9]{40}):([A-Za-z0-9_./-]+):(generic-api-key|sourcegraph-access-token):([1-9][0-9]*)')
JSON_LINE = re.compile(r'\s*"([^"\\\r\n]+)": "([A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})",?\s*')
PYTHON_LINE = re.compile(r'''\s*(KEY_SHA256|FINGERPRINT)\s*=\s*(['"])([A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})\2\s*''')


class Invalid(Exception):
    def __init__(self, reason):
        self.reason = reason


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, maximum):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise Invalid('size-limit')
    return raw


def load_policy(directory=DIRECTORY):
    raw = bounded(directory / 'history-identifiers.gitleaksignore', 256 * 1024)
    value = packets.decision_controller.decision_packets.decode_json(
        bounded(directory / 'history-identifiers.json', 1024 * 1024))
    if (type(value.get('schema')) is not int or value.get('schema') != 1 or value.get('version') != 'verified-history-identifiers-41338989009-v1'
            or value.get('fingerprintsDigest') != digest(raw)):
        raise Invalid('policy-binding')
    fps = raw.decode('ascii').splitlines()
    if len(fps) != 719 or len(set(fps)) != len(fps):
        raise Invalid('policy-inventory')
    bindings = value['bindings']
    for key, item in bindings.items():
        if (key != packets.canonical_hash(item) or item.get('kind') not in KINDS):
            raise Invalid('proof-binding')
    entries = value['exceptions']
    if not isinstance(entries, list) or len(entries) != len(fps):
        raise Invalid('policy-inventory')
    by_digest = {}
    for item in entries:
        if (not isinstance(item, dict) or item.get('shape') not in SHAPES
                or item.get('proofBinding') not in bindings
                or not all(isinstance(item.get(k), str) and HEX.fullmatch(item[k])
                           for k in ('fpDigest', 'blobSha256', 'lineSha256', 'identifierSha256'))
                or not re.fullmatch('[a-f0-9]{40}', item.get('blobGitSha1', ''))
                or item['fpDigest'] in by_digest):
            raise Invalid('policy-entry')
        by_digest[item['fpDigest']] = item
    result = {}
    for fp in fps:
        match = FINGERPRINT.fullmatch(fp)
        if (not match or '..' in match[2].split('/') or str(PurePosixPath(match[2])) != match[2]
                or match[2].startswith('/')):
            raise Invalid('policy-fingerprint')
        item = by_digest.get(digest(fp.encode()))
        if item is None:
            raise Invalid('policy-inventory')
        result[fp] = dict(item, binding=bindings[item['proofBinding']])
    return result, value


def reported_fingerprint(finding):
    commit, path, rule, line = (finding.get(k) for k in ('Commit', 'File', 'RuleID', 'StartLine'))
    if (not isinstance(commit, str) or not re.fullmatch('[a-f0-9]{40}', commit)
            or not isinstance(path, str) or not 0 < len(path) <= 4096
            or not isinstance(rule, str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,127}', rule)
            or type(line) is not int or line <= 0):
        raise Invalid('report-metadata')
    fp = f'{commit}:{path}:{rule}:{line}'
    if finding.get('Fingerprint') != fp:
        raise Invalid('report-fingerprint')
    return fp


def validate_match(candidate, finding, item, blobs, packet_lines):
    commit, path, rule, number = FINGERPRINT.fullmatch(finding['Fingerprint']).groups()
    number = int(number)
    if (commit, path) not in blobs:
        if len(blobs) >= 256:
            raise Invalid('document-limit')
        entry = packets.git(candidate, 'ls-tree', commit, '--', path).split(b'\t', 1)[0].split()
        if len(entry) != 3 or entry[:2] != [b'100644', b'blob']:
            raise Invalid('regular-blob-required')
        oid = entry[2].decode()
        size = int(packets.git(candidate, 'cat-file', '-s', oid))
        if not 0 < size <= packets.MAX_DOCUMENT:
            raise Invalid('document-limit')
        raw = packets.git(candidate, 'cat-file', 'blob', oid)
        blobs[commit, path] = raw, oid, digest(raw), raw.decode('utf-8').splitlines()
    raw, oid, blob_digest, lines = blobs[commit, path]
    if (oid != item['blobGitSha1'] or blob_digest != item['blobSha256'] or number > len(lines)):
        raise Invalid('blob-binding')
    line = lines[number - 1]
    if (not line.isascii() or digest(line.encode()) != item['lineSha256']
            or type(finding.get('EndLine')) is not int or finding.get('EndLine') != number):
        raise Invalid('line-binding')
    if item['shape'] == 'standalone-recomputed-packet-key':
        if (item['binding']['kind'] != 'canonical-packet-finding-identity' or rule != 'generic-api-key'
                or path != item['binding']['packetPath'] or oid != item['binding']['packetBlob']
                or blob_digest != item['binding']['packetDigest']):
            raise Invalid('packet-binding')
        if (oid, path) not in packet_lines:
            packet_lines[oid, path] = set(packets.proposal_lines(raw, path)[1])
        match = re.fullmatch(r'        "key": "([a-f0-9]{64})",?', line)
        if number not in packet_lines[oid, path] or not match:
            raise Invalid('standalone-line-required')
        identifier = match[1]
    elif item['shape'] == 'standalone-json-public-identifier':
        if item['binding']['kind'] == 'canonical-packet-finding-identity':
            raise Invalid('proof-binding')
        packets.decision_controller.decision_packets.decode_json(raw)
        match = JSON_LINE.fullmatch(line)
        if not match or (rule == 'sourcegraph-access-token' and
                         (match[1] != 'sourceRevision' or item['binding']['kind'] != 'public-Git-commit-object')):
            raise Invalid('standalone-line-required')
        identifier = match[2]
    else:
        match = PYTHON_LINE.fullmatch(line)
        if rule != 'generic-api-key' or not match or item['binding']['kind'] not in ('public-key-Git-blob', 'official-Rclone-pinned-public-key-list'):
            raise Invalid('standalone-line-required')
        ast.parse(raw)
        identifier = match[3]
    if digest(identifier.encode()) != item['identifierSha256']:
        raise Invalid('identifier-binding')
    start, end = finding.get('StartColumn'), finding.get('EndColumn')
    match = finding.get('Match')
    if (type(start) is not int or type(end) is not int or start < 1 or end < start
            or finding.get('Secret') != 'REDACTED' or not isinstance(match, str)
            or match.count('REDACTED') != 1):
        raise Invalid('match-span')
    source_match = match.replace('REDACTED', identifier)
    if source_match.count(identifier) != 1 or line.count(source_match) != 1:
        raise Invalid('match-span')
    offset = line.index(source_match)
    # v8.30.1 detect/location.go counts the preceding newline in columns
    # after a fragment's first line. Authenticate the exact unique source
    # substring independently; then require one of its two defined modes.
    column_mode = start - (offset + 1)
    if column_mode not in (0, 1) or end != offset + len(source_match) + column_mode:
        raise Invalid('match-span')



def verified(candidate, findings, policy, *, require_complete=False):
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise Invalid('report-limit')
    fps = [reported_fingerprint(row) for row in findings]
    counts = Counter(fps)
    if any(counts[fp] != 1 for fp in counts if fp in policy):
        raise Invalid('ambiguous-fingerprint')
    result, blobs, packet_lines = [], {}, {}
    for row, fp in zip(findings, fps):
        if fp in policy:
            validate_match(candidate, row, policy[fp], blobs, packet_lines)
            result.append(fp)
    if require_complete and set(result) != set(policy):
        raise Invalid('incomplete-frozen-baseline')
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--status', type=int, required=True)
    parser.add_argument('--base-ignores', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--require-complete-baseline', action='store_true')
    args = parser.parse_args()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    try:
        policy, value = load_policy()
        raw = bounded(args.report, MAX_BYTES)
        findings = packets.decision_controller.decision_packets.decode_json(raw)
        if args.status not in (0, 2) or bool(findings) != (args.status == 2):
            raise Invalid('scanner-status')
        matches = verified(args.candidate, findings, policy, require_complete=args.require_complete_baseline)
        base = bounded(args.base_ignores, 32 * 1024**2).decode('ascii').splitlines()
        for fp in base:
            match = FINGERPRINT.fullmatch(fp)
            if not match or match[3] != 'generic-api-key' or not packets.PACKET.fullmatch(match[2]):
                raise Invalid('base-exceptions')
        union = sorted(set(base) | set(matches))
        if len(union) > 100000:
            raise Invalid('fingerprint-limit')
        with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as stream:
            stream.write(''.join(fp + '\n' for fp in union))
        os.replace(stream.name, args.output)
        receipt = {'schema': 1, 'policy': value['version'], 'firstPassFindingCount': len(findings),
                   'verifiedExactIdentifierCount': len(matches), 'unclassifiedFindingCount': len(findings) - len(matches),
                   'firstPassReportDigest': digest(raw), 'catalogDigest': digest((DIRECTORY / 'history-identifiers.json').read_bytes()),
                   'reviewedFingerprintsDigest': value['fingerprintsDigest'],
                   'combinedExceptionDigest': digest(args.output.read_bytes()), 'requireCompleteBaseline': args.require_complete_baseline}
        args.receipt.write_text(json.dumps(receipt, sort_keys=True) + '\n')
        args.receipt.chmod(0o600)
    except Exception as error:
        reason = error.reason if isinstance(error, Invalid) else 'validation-error'
        args.receipt.write_text(json.dumps({'schema': 1, 'verdict': 'exception-validation-failed', 'reason': reason}) + '\n')
        args.receipt.chmod(0o600)
        print('Unable to verify historical identifier exceptions: ' + reason + '.', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
