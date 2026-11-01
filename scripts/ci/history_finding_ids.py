#!/usr/bin/env python3
"""Write standard Gitleaks fingerprints only for unchanged main packet ID lines."""
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finding_id_packets as packets

PREFIX = 'automation/decisions/security'
MAX_COMMITS = 20000
MAX_FINGERPRINTS = 100000
SHA = re.compile(r'[0-9a-f]{40}')


def entry(candidate, revision, path):
    fields = packets.git(candidate, 'ls-tree', revision, '--', path).split(b'\t', 1)[0].split()
    return fields[2] if len(fields) == 3 and fields[:2] == [b'100644', b'blob'] else None


def fingerprints(candidate, anchor):
    # The caller is the protected-main workflow, not PR tooling. Never import
    # modules or configuration from any historical/ref checkout.
    if (not SHA.fullmatch(anchor)
            or packets.git(candidate, 'rev-parse', 'HEAD').decode().strip() != anchor
            or packets.git(candidate, 'rev-parse', '--is-shallow-repository').strip() != b'false'):
        raise ValueError('Historical exceptions require the exact full main checkout')
    history = packets.git(candidate, 'rev-list', '--all', '--parents', '--full-history').decode().splitlines()
    if len(history) > MAX_COMMITS:
        raise ValueError('Historical commit budget exhausted')
    trusted, result = {}, set()
    for record in history:
        revisions = record.split()
        if not revisions or not all(SHA.fullmatch(value) for value in revisions):
            raise ValueError('Invalid Git history')
        commit, parents = revisions[0], revisions[1:]
        # Match the scanner's first-parent merge DIFF without restricting its
        # traversal: every parent/ref is still in both rev-list and Gitleaks.
        args = ['diff-tree', '--no-commit-id', '--name-only', '-r', '-z', '--no-renames', '--diff-filter=AM']
        args += [parents[0], commit] if parents else ['--root', commit]
        for raw_path in packets.git(candidate, *args, '--', PREFIX).split(b'\0'):
            path = raw_path.decode('utf-8')
            if not packets.PACKET.fullmatch(path):
                continue
            if path not in trusted:
                oid, lines = entry(candidate, anchor, path), []
                if oid is not None:
                    size = int(packets.git(candidate, 'cat-file', '-s', oid.decode()))
                    if 0 < size <= packets.MAX_DOCUMENT:
                        try:
                            _, lines = packets.proposal_lines(packets.git(candidate, 'cat-file', 'blob', oid.decode()), path)
                        except (ValueError, TypeError, KeyError, RecursionError):
                            pass  # Invalid/unrecognized packets retain their complete scan.
                trusted[path] = oid, lines
            oid, lines = trusted[path]
            # A plausible key/hash, old filename or reviewed ancestor is not
            # enough: the WHOLE historical blob must equal this main blob.
            if oid is not None and lines and entry(candidate, commit, path) == oid:
                result.update(f'{commit}:{path}:generic-api-key:{line}' for line in lines)
                if len(result) > MAX_FINGERPRINTS:
                    raise ValueError('Historical fingerprint budget exhausted')
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--anchor', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)  # No stale receipt can survive an error.
    values = fingerprints(args.candidate.resolve(), args.anchor)
    with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as stream:
        stream.write(''.join(value + '\n' for value in values))
    os.replace(stream.name, args.output)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Unable to validate historical packet IDs; no audit receipt granted.', file=sys.stderr)
        raise SystemExit(1)
