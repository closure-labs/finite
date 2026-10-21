#!/usr/bin/env python3
"""Stage a reviewable next-development PR only after a complete stable pair."""
import argparse
import os
from pathlib import Path
import re
import subprocess

from github_api import get_json
from release_readiness import PREFIX, published_stable_pair
from release_versions import next_development, stable_version


def development_changelog(changelog, stable, development):
    if (len(re.findall(r'^## \[Unreleased\]$', changelog, re.MULTILINE)) != 1
            or len(re.findall(r'^## \[' + re.escape(stable) + r'\][^\n]*$', changelog, re.MULTILINE)) != 1):
        raise ValueError('Post-release cycle requires one Unreleased and one stable changelog entry')
    if re.search(r'^## \[' + re.escape(development) + r'\]', changelog, re.MULTILINE):
        raise ValueError('The next development prerelease already has a changelog entry')
    start = changelog.index('## [Unreleased]') + len('## [Unreleased]')
    end = re.search(r'^## \[', changelog[start:], re.MULTILINE)
    if end is None:
        raise ValueError('Missing versioned changelog entry')
    end = start + end.start()
    pending = changelog[start:end].strip()
    pending = re.sub(r'^Development version: `[^`]+`\. The next stable release is [^\n]+\.\n?', '',
                     pending, flags=re.MULTILINE).strip()
    note = f'Development version: `{development}`. The next stable release is {development[:-4]}.'
    entry = f'## [{development}]\n\n### Changed\n\n- Start the next development cycle after the successful `{stable}` stable pair.\n\n'
    return (changelog[:start] + '\n\n' + note + ('\n\n' + pending if pending else '')
            + '\n\n' + entry + changelog[end:])


def stage(root, revision, api=get_json):
    version = (root / 'VERSION').read_text().strip()
    # Published prereleases never start another cycle.
    if not stable_version(version):
        return None
    if not published_stable_pair(version, api):
        return None
    if api(PREFIX + '/git/ref/heads/main')['object']['sha'] != revision:
        raise ValueError('Main advanced; defer the next development PR to reconciliation')
    development = next_development(version)
    changelog = development_changelog((root / 'CHANGELOG.md').read_text(), version, development)
    (root / 'VERSION').write_text(development + '\n')
    (root / 'CHANGELOG.md').write_text(changelog)
    return {'stable': version, 'development': development}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('workflow_run', 'schedule', 'workflow_dispatch')):
        raise ValueError('Post-release preparation requires trusted hosted main')
    revision = os.environ.get('GITHUB_SHA', '')
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
    if not re.fullmatch('[0-9a-f]{40}', revision) or checkout != revision:
        raise ValueError('Post-release checkout differs from trusted main revision')
    result = stage(Path.cwd(), revision)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('changed=' + str(result is not None).lower(), file=output)
        if result:
            print('stable=' + result['stable'], file=output)
            print('development=' + result['development'], file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Next development cycle\n\n')
        summary.write(('Both stable products are published. Proposing `' + result['development']
                       + '` for review; image qualification and release approval follow its merge.\n')
                      if result else 'No completed stable pair requires a development version PR.\n')


if __name__ == '__main__':
    main()
