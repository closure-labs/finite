#!/usr/bin/env python3
"""Emit only fixed historical-scan verdicts and aggregate counts, never findings."""
import argparse
import json
from pathlib import Path
import re

MAX_BYTES = 64 * 1024 * 1024
MAX_FINDINGS = 100000


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate key')
        result[key] = value
    return result


def summarize(status, report):
    result = {'schema': 1, 'verdict': 'scanner-error', 'findingCount': None,
              'genericApiKeyCount': None, 'otherRuleFindingCount': None,
              'distinctRuleCount': None, 'distinctCommitCount': None, 'distinctPathCount': None}
    if status not in (0, 2):
        result['verdict'] = 'timeout' if status == 124 else 'interrupted' if status in (137, 143) else (
            'scanner-error' if status == 1 else 'unexpected-exit')
        return result
    with report.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized report')
    findings = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite value')))
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS or bool(findings) != (status == 2):
        raise ValueError('Report contradicts scan status')
    rules, commits, paths = set(), set(), set()
    generic = 0
    for finding in findings:
        if (not isinstance(finding, dict) or not isinstance(finding.get('RuleID'), str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,127}', finding['RuleID'])
                or not isinstance(finding.get('Commit'), str)
                or not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', finding['Commit'])
                or not isinstance(finding.get('File'), str) or not 0 < len(finding['File']) <= 4096
                or type(finding.get('StartLine')) is not int or finding['StartLine'] <= 0):
            raise ValueError('Invalid report metadata')
        rules.add(finding['RuleID'])
        commits.add(finding['Commit'])
        paths.add(finding['File'])
        generic += finding['RuleID'] == 'generic-api-key'
    result.update(verdict='findings' if findings else 'clean', findingCount=len(findings),
                  genericApiKeyCount=generic, otherRuleFindingCount=len(findings) - generic,
                  distinctRuleCount=len(rules), distinctCommitCount=len(commits), distinctPathCount=len(paths))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', type=int, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = summarize(args.status, args.report)
    except (OSError, ValueError, TypeError, RecursionError):
        # Never print parser exceptions: report bytes and paths are untrusted.
        result = {'schema': 1, 'verdict': 'invalid-report', 'findingCount': None}
    print(json.dumps(result, sort_keys=True))
    return {'clean': 0, 'findings': 2, 'timeout': 124}.get(result['verdict'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
