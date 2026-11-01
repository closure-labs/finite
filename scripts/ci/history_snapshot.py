#!/usr/bin/env python3
"""Bind a historical scan to exact public refs and fixed scanner configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finding_id_packets as packets

ARCHIVE_SHA256 = '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'
OPTIONS = ['--all', '--full-history', '--diff-merges=first-parent', '--text', '--no-ext-diff', '--no-textconv']
CONFIG = b'[extend]\nuseDefault = true\n'
MAX_REFS = 20000
SHA = re.compile('[a-f0-9]{40}')


def refs(candidate):
    rows = packets.git(candidate, 'for-each-ref', '--format=%(refname)%00%(objectname)%00%(objecttype)').decode().splitlines()
    if len(rows) > MAX_REFS:
        raise ValueError('Ref budget exhausted')
    result = []
    for row in rows:
        name, oid, kind = row.split('\0')
        if (not name.startswith('refs/') or len(name) > 4096 or any(ord(c) < 32 for c in name)
                or not SHA.fullmatch(oid) or kind not in ('commit', 'tag', 'tree', 'blob')):
            raise ValueError('Invalid public Git ref metadata')
        result.append({'name': name, 'object': oid, 'type': kind})
    return result


def snapshot(candidate, source, config, ignores, run, attempt, tooling=None):
    if (not SHA.fullmatch(source) or packets.git(candidate, 'rev-parse', 'HEAD').decode().strip() != source
            or packets.git(candidate, 'rev-parse', '--is-shallow-repository').strip() != b'false'
            or config.read_bytes() != CONFIG or not re.fullmatch('[1-9][0-9]{0,19}', run)
            or not re.fullmatch('[1-9][0-9]{0,19}', attempt)):
        raise ValueError('Invalid immutable history scan context')
    raw = ignores.read_bytes()
    if len(raw) > 32 * 1024**2:
        raise ValueError('Exception metadata exceeds bound')
    return {'schema': 1, 'repository': 'closure-labs/finite', 'sourceRevision': source,
            'runId': run, 'runAttempt': attempt, 'toolingRevision': tooling or source, 'refs': refs(candidate),
            'scanner': {'version': '8.30.1', 'officialArchiveSha256': ARCHIVE_SHA256,
                        'config': CONFIG.decode(), 'configSha256': hashlib.sha256(CONFIG).hexdigest(),
                        'logOptions': OPTIONS, 'defaultRules': True, 'inlineAllows': False,
                        'exceptionPolicy': 'byte-identical-main-canonical-finding-ids-v1',
                        'exceptionSha256': hashlib.sha256(raw).hexdigest(),
                        'exceptionFingerprintCount': len(raw.splitlines())}}


def check(candidate, value):
    if (packets.git(candidate, 'rev-parse', 'HEAD').decode().strip() != value['sourceRevision']
            or refs(candidate) != value['refs']):
        raise ValueError('Refs or source moved during historical scan')


def provenance_counts(candidate, findings):
    # Categories are observations, never exceptions or acceptance authority.
    result = {'canonicalPacketIdWithoutMainException': 0, 'unclassifiedGenericKey': 0,
              'otherDefaultRule': 0}
    cache = {}
    for finding in findings:
        if finding['RuleID'] != 'generic-api-key':
            result['otherDefaultRule'] += 1
            continue
        commit, path = finding['Commit'], finding['File']
        category = 'unclassifiedGenericKey'
        if packets.PACKET.fullmatch(path):
            key = commit, path
            if key not in cache:
                if len(cache) >= 256:
                    raise ValueError('Provenance document budget exhausted')
                lines = []
                entry = packets.git(candidate, 'ls-tree', commit, '--', path).split(b'\t', 1)[0].split()
                if len(entry) == 3 and entry[:2] == [b'100644', b'blob']:
                    size = int(packets.git(candidate, 'cat-file', '-s', entry[2].decode()))
                    if 0 < size <= packets.MAX_DOCUMENT:
                        try:
                            _, lines = packets.proposal_lines(packets.git(candidate, 'cat-file', 'blob', entry[2].decode()), path)
                        except (ValueError, TypeError, KeyError, RecursionError):
                            pass
                cache[key] = set(lines)
            if finding['StartLine'] in cache[key]:
                category = 'canonicalPacketIdWithoutMainException'
        result[category] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--source')
    parser.add_argument('--frozen', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--ignores', type=Path)
    args = parser.parse_args()
    if args.check:
        raw = args.manifest.read_bytes()
        if len(raw) > 8 * 1024**2:
            raise ValueError('Oversized ref manifest')
        value = packets.decision_controller.decision_packets.decode_json(raw)
        check(args.candidate, value)
    else:
        value = snapshot(args.candidate, args.source or os.environ['GITHUB_SHA'], args.config, args.ignores,
                         os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'], os.environ['GITHUB_SHA'])
        if args.frozen:
            import history_frozen_refs
            history_frozen_refs.check_inputs(args.candidate, args.ignores)
            value['referenceBaseline'] = {'runId': '41338989009', 'runAttempt': '1',
                                          'manifestSha256': history_frozen_refs.BASELINE_DIGEST}
        rendered = json.dumps(value, indent=2) + '\n'
        if len(rendered.encode()) > 8 * 1024**2:
            raise ValueError('Ref manifest exceeds bound')
        args.manifest.write_text(rendered)
        args.manifest.chmod(0o600)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Unable to bind historical scan refs and configuration.', file=sys.stderr)
        raise SystemExit(1)
