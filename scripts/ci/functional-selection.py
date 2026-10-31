#!/usr/bin/env python3
"""Fail-closed shadow selection. Does not control any current CI gate."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ALL = {'home-manager', 'homebrew', 'nix-lifecycle'}

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
            locked = data.get('locked')
            if (not isinstance(locked, dict) or not isinstance(locked.get('narHash'), str)
                    or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=', locked['narHash'])):
                raise ValueError('Dependency has no valid immutable content hash')
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
                known_source = all(v.get('type') == 'github' and v.get('owner') == 'closure-labs' and v.get('repo') == 'foundation'
                    for v in (versions['before'].get(path, {}), versions['after'].get(path, {})))
                if not known_source:
                    add(ALL, 'Foundation source identity changed/unknown')
                else:
                    # A filename diff cannot prove Nix export behavior. Until an
                    # evaluated export comparison is authenticated, fail closed.
                    add(ALL, 'Foundation exported behavior is opaque; source delta: '
                        + (', '.join(foundation_paths) if foundation_paths is not None else 'unavailable'))
            elif repo == 'home-manager' or path.split('/')[-1] == 'home-manager':
                def known_hm(value):
                    return ((value.get('type') == 'github' and value.get('owner') == 'nix-community'
                             and value.get('repo') == 'home-manager')
                            or (value.get('type') == 'tarball' and re.fullmatch(
                                r'https://api\.flakehub\.com/f/pinned/nix-community/home-manager/'
                                r'[0-9][A-Za-z0-9%+._-]*/[0-9a-f-]{36}/source\.tar\.gz', value.get('url', ''))))
                origins = [v[path] for v in versions.values() if path in v]
                known_boundary = path == 'foundation/home-manager' and all(path in v for v in versions.values())
                if known_boundary and origins and all(known_hm(value) for value in origins):
                    add({'home-manager'}, 'resolved Home Manager version: ' + path)
                else:
                    add(ALL, 'Home Manager source identity changed/unknown: ' + path)
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
        'suites': sorted(suites), 'reasons': reasons, 'resolvedInputs': versions,
        'foundationSourcePaths': foundation_paths}

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
