#!/usr/bin/env python3
"""Materialize the one reviewed 393-ref baseline without fetching moving refs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finding_id_packets as packets
import history_snapshot

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / '.github/security/history-baseline-41338989009.json'
BASELINE_DIGEST = '9ef55a680a8438eca877801d299578dcbc22083fefc08aff0f97538c475d7f25'
REPOSITORY = 'https://github.com/closure-labs/finite.git'


def load_baseline():
    with BASELINE.open('rb') as stream:
        raw = stream.read(8 * 1024**2 + 1)
    if len(raw) > 8 * 1024**2 or hashlib.sha256(raw).hexdigest() != BASELINE_DIGEST:
        raise ValueError('Frozen baseline digest differs')
    value = packets.decision_controller.decision_packets.decode_json(raw)
    scanner = value['scanner']
    if (value['schema'] != 1 or value['repository'] != 'closure-labs/finite'
            or value['runId'] != '41338989009' or value['runAttempt'] != '1'
            or scanner['version'] != '8.30.1' or scanner['officialArchiveSha256'] != history_snapshot.ARCHIVE_SHA256
            or scanner['config'].encode() != history_snapshot.CONFIG or scanner['logOptions'] != history_snapshot.OPTIONS
            or scanner['configSha256'] != hashlib.sha256(history_snapshot.CONFIG).hexdigest()
            or scanner['defaultRules'] is not True or scanner['inlineAllows'] is not False
            or scanner['exceptionPolicy'] != 'byte-identical-main-canonical-finding-ids-v1'):
        raise ValueError('Unsupported baseline scanner configuration')
    return value


def prepare(candidate, value):
    refs = value['refs']
    if (candidate.exists() or not 0 < len(refs) <= history_snapshot.MAX_REFS
            or len({r['name'] for r in refs}) != len(refs)
            or not re.fullmatch('[a-f0-9]{40}', value['sourceRevision'])):
        raise ValueError('Frozen subject must be new and complete')
    for ref in refs:
        if (not isinstance(ref['name'], str) or not ref['name'].startswith('refs/')
                or len(ref['name']) > 4096 or any(ord(c) <= 32 for c in ref['name'])
                or not re.fullmatch('[a-f0-9]{40}', ref['object'])
                or ref['type'] not in ('commit', 'tag', 'tree', 'blob')):
            raise ValueError('Invalid frozen ref')
        subprocess.run(['git', 'check-ref-format', ref['name']], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    candidate.mkdir(mode=0o700)
    packets.git(candidate, 'init', '-q')
    wanted = sorted({r['object'] for r in refs} | {value['sourceRevision']})
    # Explicit object IDs only. No branch/tag/PR enumeration, depth truncation,
    # substitution of a new ref, credentials, alternate cache or fallback scan.
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    subprocess.run(['git', '-c', 'credential.helper=', '-c', 'core.hooksPath=/dev/null', '-C', str(candidate),
                    'fetch', '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules', REPOSITORY, *wanted],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, env=env)
    commands = ''.join(f"create {r['name']} {r['object']}\n" for r in refs)
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(candidate), 'update-ref', '--stdin'],
                   input=commands.encode(), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    # Detach HEAD without checking out/executing any historical source files.
    packets.git(candidate, 'update-ref', '--no-deref', 'HEAD', value['sourceRevision'])
    history_snapshot.check(candidate, value)
    if packets.git(candidate, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise ValueError('Frozen history is incomplete')


def check_inputs(candidate, ignores):
    value = load_baseline()
    history_snapshot.check(candidate, value)
    if hashlib.sha256(ignores.read_bytes()).hexdigest() != value['scanner']['exceptionSha256']:
        raise ValueError('First-pass exception policy differs from baseline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--check-inputs', type=Path)
    args = parser.parse_args()
    if args.check_inputs:
        check_inputs(args.candidate, args.check_inputs)
    else:
        prepare(args.candidate, load_baseline())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Unable to materialize or verify the exact frozen history baseline.', file=sys.stderr)
        raise SystemExit(1)
