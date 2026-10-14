#!/usr/bin/env python3
"""Select CI work conservatively from the event's complete Git diff."""
import json
import os
from pathlib import Path
import re
import subprocess

PROFILES = {
    'bluefin-generic': 'finite',
    'bluefin-next': 'finite-next',
    'bluefin-dx-generic': 'finite-dev',
    'bluefin-dx-next': 'finite-dev-next',
}
NEXT = {'bluefin-next', 'bluefin-dx-next'}
GENERIC = set(PROFILES) - NEXT
# These files qualify an existing immutable image; they are not filesystem
# inputs. Keep source/security checks while reusing already validated builds.
QUALIFICATION_ONLY = {
    'scripts/ci/reuse-candidate-security.py',
    'automation/security/image-policy.json',
    'scripts/ci/approved-baseline.py', 'scripts/ci/security-remediation-diff.py',
    'scripts/ci/bluefin-upstream.py', 'scripts/ci/impact.py', 'scripts/ci/image_identity.py',
    'scripts/bluebuild/security-policy.py', 'scripts/bluebuild/security-scan.py',
    'scripts/bluebuild/security-run.sh', 'scripts/bluebuild/audit-published.sh',
    'scripts/bluebuild/publication.py',
    '.github/workflows/publication.yml', '.github/workflows/image-security.yml',
    '.github/workflows/build.yml', 'scripts/ci/release-selection.py',
    'scripts/ci/remediation-preflight.py', 'scripts/ci/applicability-evidence.py',
    'scripts/ci/native-evidence-summary.py',
    'scripts/ci/diagnose-built-candidate.sh', 'scripts/ci/rpm-file-evidence.py',
    'scripts/ci/extraction-layout-smoke.py',
    'scripts/ci/freerdp-reference-evidence.py',
    'scripts/ci/podman-reference-evidence.py',
    'scripts/ci/httpd-reference-evidence.py',
    'scripts/ci/go-consumer-reference.py',
    'scripts/ci/rclone-compatibility.py',
    'scripts/bluebuild/desktop-qualification.py',
    'scripts/bluebuild/check-vm-desktop.py',
    'scripts/bluebuild/vm-acceptance.sh', 'scripts/bluebuild/qualify.sh',
    'scripts/bluebuild/vm-upgrade.py', 'scripts/bluebuild/redact-vm-logs.py',
    'scripts/bluebuild/release-evidence.py', '.github/workflows/qualification.yml',
}


def classify(paths):
    checks, nix = not paths, False
    profiles = set(PROFILES) if not paths else set()
    for path in paths:
        if path in {'README.md', 'CHANGELOG.md', 'LICENSE', 'LICENSE.md', '.great_cto/tasks.md'} or path.startswith('docs/'):
            continue
        checks = True
        if path in QUALIFICATION_ONLY:
            continue
        if path.startswith('automation/security/') or path in {'sources/bluefin-trust.json', 'sources/bluefin.pub'}:
            profiles.update(PROFILES)
            continue
        if path.startswith(('tests/', 'automation/')):
            continue
        if path in {
            'devenv.lock', 'scripts/ci/http-get.py',
            '.github/workflows/update-bluefin.yml', '.github/workflows/upstream-health.yml',
            '.github/workflows/repository-security.yml', '.github/workflows/doppler-pilot.yml',
            '.github/dependabot.yml', '.github/workflows/update-home-release.yml',
            '.github/workflows/update-flake-lock.yml', '.github/workflows/update-determinate-nix.yml',
            '.github/workflows/queue-dependabot.yml',
            '.github/workflows/update-kernel.yml', '.github/workflows/release.yml',
            'scripts/ci/kernel-update.py',
            '.github/workflows/desktop-security-evidence.yml',
            'scripts/ci/go-binary-evidence.go', 'scripts/ci/go-binary-evidence_test.go',
            'scripts/ci/go-desktop-evidence.py',
            'scripts/ci/local-candidate-evidence.py',
        }:
            continue
        if path.startswith(('lib/', 'modules/', 'templates/')) or path in {
            'flake.nix', 'flake.lock', 'VERSION', 'sources/determinate-nix.json', 'sources/kernel-next.json',
            'sources/kernel-policy.json', 'sources/fedora-45.pub',
        }:
            nix = True
        elif path in {f'recipes/{profile}.yml' for profile in PROFILES}:
            profiles.add(Path(path).stem)
        elif path in {'recipes/shared/next.yml', 'files/scripts/kernel-next.sh'}:
            profiles.update(NEXT)
        elif path in {'files/scripts/kernel-generic-security.py',
                      'files/security/kernel-generic.json', 'files/security/fedora-44.pub'}:
            profiles.update(GENERIC)
        else:
            profiles.update(PROFILES)
    return {'checks': checks, 'nix': nix, 'profiles': sorted(profiles)}


def revisions(event_name, event):
    if event_name == 'pull_request':
        base = event['pull_request']['base']['sha']
        head = event['pull_request']['head']['sha']
        separator = '...'
    elif event_name == 'merge_group':
        base, head = event['merge_group']['base_sha'], event['merge_group']['head_sha']
        separator = '..'
    elif event_name == 'push':
        base, head = event['before'], event['after']
        separator = '..'
    else:
        return None
    if any(not re.fullmatch(r'[0-9a-f]{40,64}', sha) or set(sha) == {'0'} for sha in (base, head)):
        return None
    return base, head, separator


def changed_paths(event_name, event):
    comparison = revisions(event_name, event)
    if comparison is None:
        return None
    base, head, separator = comparison
    result = subprocess.run(
        ['git', 'diff', '--no-renames', '--name-only', '-z', base + separator + head],
        check=True, stdout=subprocess.PIPE,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b'\0') if path]


def main():
    try:
        paths = changed_paths(os.environ['GITHUB_EVENT_NAME'], json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
        plan = classify(paths or [])
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'::warning::Change detection unavailable; running full validation ({type(error).__name__}).')
        plan = classify([])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for name, value in plan.items():
            print(f'{name}={json.dumps(value, separators=(",", ":"))}', file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Selected checks\n\nDocumentation checks run for every change.\n\n')
        summary.write(f'- Nix/runtime checks: {"run" if plan["checks"] else "skip"}\n')
        summary.write(f'- Compare Nix payloads: {"yes" if plan["nix"] else "no"}\n')
        summary.write(f'- Images selected by paths: {", ".join(plan["profiles"]) or "none"}\n')


if __name__ == '__main__':
    main()
