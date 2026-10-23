"""Shared governed-path and exact Git-tree validation; grants no review authority."""
import re

SHA = re.compile(r'[0-9a-f]{40}')

GOVERNED_PREFIXES = ('scripts/ci/', 'scripts/bluebuild/', '.github/workflows/', '.github/actions/', 'automation/security/',
                     'automation/github/', 'automation/decisions/', 'lib/ci-applications/')
GOVERNED_FILES = {'flake.nix', 'flake.lock', 'cosign.pub', '.github/CODEOWNERS',
                  'lib/vm-tools.nix', 'lib/mk-pkgs.nix', 'lib/project-policy.nix', 'lib/secretspec.nix',
                  'sources/bluefin.pub', 'sources/bluefin-trust.json', 'sources/cosign-runtime.json',
                  'scripts/ci/verify-security-admission.py', 'scripts/ci/reconcile-decisions.py',
                  'scripts/ci/verify-attestation-subject.py', 'scripts/ci/inventory-evidence.py',
                  'secretspec.toml', 'sources/secretspec.json', 'lib/ci-tools.nix',
                  'scripts/ci/security_decisions.py', 'scripts/ci/security_admission.py',
                  'scripts/ci/security-admission.py', 'scripts/ci/decision_packets.py',
                  'scripts/ci/decision_controller.py', 'lib/bluebuild-checks.nix',
                  '.github/zizmor.yml', 'zizmor.yml', '.zizmor.yml', 'scripts/ci/decision-authority.py',
                  'scripts/ci/decision-check.py', 'scripts/ci/decision-controller.py',
                  'scripts/ci/approved-baseline.py', 'scripts/ci/reuse-candidate-security.py',
                  'scripts/ci/repository-security-audit.py', 'scripts/ci/legacy-release-boundary.py', 'scripts/ci/create-release-draft.sh'}


def governed(path):
    return (path in GOVERNED_FILES or path.startswith(GOVERNED_PREFIXES)
            or path.startswith('scripts/bluebuild/security')
            or path.startswith('scripts/bluebuild/publication')
            or path.startswith('scripts/bluebuild/release')
            or path.startswith('scripts/ci/release')
            or path.startswith('scripts/ci/prepare-release')
            or path.startswith('scripts/ci/decision-')
            or path.startswith('scripts/ci/decision_')
            or path.startswith('scripts/ci/execute-release')
            or path.startswith('lib/ci-'))


def tree(api, repository, sha):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError('Tree lookup requires immutable commit SHA')
    value = api(f'repos/{repository}/git/trees/{sha}?recursive=1')
    if not isinstance(value, dict) or value.get('truncated') is not False or not isinstance(value.get('tree'), list):
        raise ValueError('Cannot prove complete merge-group tree identity')
    entries = {}
    for item in value['tree']:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('Invalid tree response')
        if (not item['path'] or item['path'].startswith('/') or any(part in ('', '.', '..') for part in item['path'].split('/'))
                or (item.get('type'), item.get('mode')) not in {('tree', '040000'), ('blob', '100644'),
                    ('blob', '100755'), ('blob', '120000'), ('commit', '160000')}
                or not isinstance(item.get('sha'), str) or not SHA.fullmatch(item['sha'])):
            raise ValueError('Invalid tree entry identity')
        if item['path'] in entries:
            raise ValueError('Duplicate merge-group tree path')
        entries[item['path']] = (item.get('type'), item.get('mode'), item.get('sha'))
    return entries



def changed_paths(files, count):
    if type(count) is not int or not isinstance(files, list) or len(files) != count or not files:
        raise ValueError('Incomplete PR file inventory')
    paths = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('filename'), str):
            raise ValueError('Invalid changed-file inventory')
        paths.add(item['filename'])
        if item.get('previous_filename'):
            if not isinstance(item['previous_filename'], str):
                raise ValueError('Invalid renamed path')
            paths.add(item['previous_filename'])
    return paths


def compare(api, repository, target, head, paths):
    if not all(isinstance(sha, str) and SHA.fullmatch(sha) for sha in (target, head)):
        raise ValueError('Governed comparison requires immutable commit SHAs')
    sensitive = sorted(path for path in paths if governed(path))
    if target != head and sensitive:
        queued, reviewed = tree(api, repository, target), tree(api, repository, head)
        mismatches = [path for path in sensitive if queued.get(path) != reviewed.get(path)]
        if mismatches:
            raise ValueError('Merge-group governed content differs from approved PR head: '
                             + ', '.join(mismatches) + '. Rebase onto current main and obtain review of the new head.')
    return sensitive
