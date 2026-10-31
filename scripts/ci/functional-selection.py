#!/usr/bin/env python3
"""Fail-closed shadow selection. Does not control any current CI gate."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ALL = {'home-manager', 'homebrew', 'nix-lifecycle'}
HM_FOUNDATION = {'modules/aspects/base/browser.nix', 'modules/aspects/base/desktop.nix',
    'modules/aspects/base/home.nix', 'modules/aspects/base/shell.nix'}
BREW_FOUNDATION = {'modules/aspects/base/homebrew.nix', 'modules/aspects/base/brew-packages.json',
    'modules/finite-brew-bootstrap', 'modules/finite-brew-migration-status'}

def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], timeout=30)

def snapshot(lock):
    """Resolve exported input paths, including follows; names alone are not IDs."""
    nodes = lock['nodes']
    root = lock['root']
    result = {}
    def follow(reference, resolving=()):
        if isinstance(reference, str):
            if reference not in nodes: raise ValueError('Missing input node')
            return reference
        if not isinstance(reference, list) or not reference or tuple(reference) in resolving:
            raise ValueError('Invalid/cyclic follows')
        current = root
        for part in reference:
            current = follow(nodes[current]['inputs'][part], (*resolving, tuple(reference)))
        return current
    def walk(node, path, ancestors):
        if len(path) > 30: raise ValueError('Input graph depth exceeded')
        if node in ancestors: return
        for name, reference in sorted(nodes[node].get('inputs', {}).items()):
            target = follow(reference)
            key = (*path, name)
            data = nodes[target]
            # Record exact immutable versions and hashes for reviewers.
            if not isinstance(data.get('locked'), dict): raise ValueError('Unlocked dependency')
            result['/'.join(key)] = data['locked']
            walk(target, key, (*ancestors, node))
    walk(root, (), ())
    return result

def select(paths, before, after, foundation_paths=None, full=False):
    suites, reasons = set(), []
    def add(chosen, reason):
        suites.update(chosen)
        reasons.append({'suites': sorted(chosen), 'reason': reason})
    if full: add(ALL, 'explicit manual full-suite option')
    versions = {'before': {}, 'after': {}}
    try:
        versions = {'before': snapshot(before), 'after': snapshot(after)}
        changed = [p for p in sorted(versions['before'].keys() | versions['after'].keys())
                   if versions['before'].get(p) != versions['after'].get(p)]
        for path in changed:
            entry = versions['after'].get(path, versions['before'].get(path, {}))
            repo = entry.get('repo', '')
            if path == 'foundation':
                if foundation_paths is None:
                    add(ALL, 'Foundation source delta unavailable/opaque')
                else:
                    for source in foundation_paths:
                        if source in HM_FOUNDATION:
                            add({'home-manager'}, 'Foundation HM export: ' + source)
                        elif source in BREW_FOUNDATION:
                            add({'home-manager', 'homebrew'}, 'Foundation brew/activation boundary: ' + source)
                        elif source == 'flake.lock':
                            # Finite's expanded lock resolves transitive exported versions below.
                            continue
                        elif source.startswith(('docs/', 'tests/')) or source in ('README.md', 'CHANGELOG.md', 'LICENSE'):
                            continue
                        else:
                            add(ALL, 'Foundation shared/unknown export: ' + source)
            elif repo == 'home-manager' or path.split('/')[-1] == 'home-manager':
                add({'home-manager'}, 'resolved Home Manager version: ' + path)
            elif path == 'nixpkgs-weekly' or path.startswith(('devenv/', 'gen/')):
                # These are tooling, but no exclusion is proven yet.
                add(ALL, 'unreviewed tooling/export impact: ' + path)
            elif repo == 'nixpkgs' or 'nixpkgs' in path.split('/')[-1]:
                add(ALL, 'nixpkgs can change HM and shared brew/bootstrap helper dependencies: ' + path)
            else:
                add(ALL, 'unknown changed input/export: ' + path)
        for path in paths:
            if path == 'flake.lock' or path == 'sources/foundation.json': continue
            if path.startswith(('docs/', 'tests/')) or path in ('README.md', 'CHANGELOG.md', 'LICENSE'): continue
            if path.startswith(('scripts/home/', 'templates/')) or path in ('lib/home-manager-flake-module.nix', 'lib/render-home-scaffold.nix'):
                add({'home-manager'}, 'Finite HM export: ' + path)
            elif path == 'sources/determinate-nix.json':
                add({'home-manager', 'nix-lifecycle'}, 'Nix runtime version affects HM execution: ' + path)
            else:
                add(ALL, 'base image, shared first-boot/service, selector or unknown boundary: ' + path)
        if 'sources/foundation.json' in paths and 'foundation' not in changed:
            add(ALL, 'Foundation metadata changed without matching resolved input')
    except (KeyError, TypeError, ValueError, RecursionError):
        add(ALL, 'malformed/incomplete input graph; fail closed')
    return {'schema': 1, 'kind': 'finite-functional-selection-shadow', 'advisory': True,
        'authorizesPublication': False, 'bootability': 'always-independent', 'manualFullSuite': full,
        'suites': sorted(suites), 'reasons': reasons, 'resolvedInputs': versions}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--foundation-repository', type=Path)
    parser.add_argument('--full-suite', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if not all(re.fullmatch('[0-9a-f]{40}', rev) for rev in (args.base, args.head)):
            raise ValueError('Exact commits required')
        before, after = [json.loads(git('.', 'show', rev + ':flake.lock')) for rev in (args.base, args.head)]
        paths = git('.', 'diff', '--no-renames', '--name-only', '-z', args.base, args.head).decode().strip('\0').split('\0')
        foundation_paths = None
        old, new = snapshot(before)['foundation'], snapshot(after)['foundation']
        if old != new and args.foundation_repository:
            if any(v.get('owner') != 'closure-labs' or v.get('repo') != 'foundation' or not re.fullmatch('[0-9a-f]{40}', v.get('rev', '')) for v in (old, new)):
                raise ValueError('Unexpected Foundation source')
            foundation_paths = git(args.foundation_repository, 'diff', '--no-renames', '--name-only', '-z', old['rev'], new['rev']).decode().strip('\0').split('\0')
        value = select([p for p in paths if p], before, after, foundation_paths, args.full_suite)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        value = select([], {}, {}, full=args.full_suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + '\n')

if __name__ == '__main__': main()
