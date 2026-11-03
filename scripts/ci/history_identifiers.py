#!/usr/bin/env python3
"""Compile verified public identifiers into native Gitleaks AND allowances."""
from collections import defaultdict
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finding_id_packets as packets
import history_finding_ids

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


def source_identifier(candidate, fingerprint, item, blobs, packet_lines):
    commit, path, rule, number = FINGERPRINT.fullmatch(fingerprint).groups()
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
    if not line.isascii() or digest(line.encode()) != item['lineSha256']:
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
    return line, identifier


def native_config(candidate, policy, *, require_complete=False):
    """Use upstream rule/commit/path/whole-line AND semantics, never a file ignore.

    Validate source bytes before scanning, so one native pass can decide the
    verdict. An exception cannot match an added credential on that line: its
    entire source line, immutable commit, path and rule must all match.
    """
    reachable = set(packets.git(candidate, 'rev-list', '--all',
        f'--max-count={history_finding_ids.MAX_COMMITS + 1}').decode('ascii').splitlines())
    if len(reachable) > history_finding_ids.MAX_COMMITS:
        raise Invalid('history-limit')
    groups, blobs, packet_lines = defaultdict(set), {}, {}
    used = 0
    for fingerprint, item in sorted(policy.items()):
        commit, path, rule, _ = FINGERPRINT.fullmatch(fingerprint).groups()
        if commit not in reachable:
            if require_complete:
                raise Invalid('incomplete-frozen-baseline')
            continue  # --all cannot scan commits outside this exact ref closure.
        line, _ = source_identifier(candidate, fingerprint, item, blobs, packet_lines)
        groups[rule, path, commit].add(line)
        used += 1
    lines = ['[extend]', 'useDefault = true']
    for rule in sorted({key[0] for key in groups}):
        lines.extend(['[[rules]]', 'id = ' + json.dumps(rule)])
        for _, path, commit in sorted(key for key in groups if key[0] == rule):
            lines.extend(['[[rules.allowlists]]', 'condition = "AND"', 'regexTarget = "line"',
                'commits = [' + json.dumps(commit) + ']',
                'paths = [' + json.dumps('^' + re.escape(path) + '$') + ']',
                'regexes = ' + json.dumps([r'\A\n?' + re.escape(line) + r'\z'
                    for line in sorted(groups[rule, path, commit])])])
    return ('\n'.join(lines) + '\n').encode(), {
        'verifiedExactIdentifierCount': used,
        'unreachableCatalogEntryCount': len(policy) - used,
        'ruleCommitPathGroups': len(groups)}
