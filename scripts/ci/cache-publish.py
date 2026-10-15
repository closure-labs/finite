#!/usr/bin/env python3
"""Prepare selected allowlisted closures before exposing a write token."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
STORE = re.compile(r'/nix/store/[a-z0-9]{32}-[^/\s]+')
TOOLS = ('image-tools', 'scanner-tools', 'ci-repository-security-audit', 'ci-secrets-run')
MIB = 1024 ** 2
CREDENTIALS = ('CACHIX_AUTH_TOKEN', 'COSIGN_PRIVATE_KEY', 'MERGE_QUEUE_TOKEN',
               'GH_TOKEN', 'GITHUB_TOKEN', 'BB_PASSWORD')


def preparation_env():
    """Even push-time metadata checks must not inherit the writer credential."""
    return {key: value for key, value in os.environ.items() if key not in CREDENTIALS}


def boundary(env=os.environ):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_EVENT_NAME') != 'workflow_run'
            or not re.fullmatch(r'[0-9a-f]{40}', env.get('CACHE_SOURCE_REVISION', ''))):
        raise ValueError('Cache publishing requires a successful trusted main workflow')
    head = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT,
                                   env=preparation_env(), text=True, timeout=30).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', head) or head != env['CACHE_SOURCE_REVISION']:
        raise ValueError('Cache publishing checkout differs from its successful source revision')


def output(command):
    value = subprocess.check_output(command, cwd=ROOT, env=preparation_env(),
                                    text=True, timeout=3600).strip()
    if not STORE.fullmatch(value):
        raise ValueError('Expected exactly one store output')
    return value


def json_output(command):
    def unique(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError('Duplicate JSON metadata key')
            record[key] = value
        return record
    return json.loads(subprocess.check_output(command, cwd=ROOT, env=preparation_env(),
                                             text=True, timeout=3600), object_pairs_hook=unique)


def closure_sizes(paths):
    paths = list(paths)
    if not paths or len(paths) > 128 or any(not isinstance(path, str) or not STORE.fullmatch(path) for path in paths):
        raise ValueError('Invalid store roots')
    paths = sorted(set(paths))
    records = json_output(['nix', 'path-info', '--json', '--json-format', '1', '--closure-size', *paths])
    if not isinstance(records, dict) or set(records) != set(paths):
        raise ValueError('Closure metadata differs from requested roots')
    sizes = {}
    for path, record in records.items():
        size = record.get('closureSize') if isinstance(record, dict) else None
        if type(size) is not int or size < 0:
            raise ValueError('Invalid closure size')
        sizes[path] = size
    return sizes


def closure_size(path):
    return closure_sizes([path])[path]


class ToolIdentityError(ValueError):
    """Bounded shape diagnostics contain no arbitrary evaluator values or keys."""
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('Invalid or ambiguous tool identity: ' + json.dumps(diagnostics, sort_keys=True))


def identity_diagnostics(identities):
    diagnostics = {'metadataType': type(identities).__name__, 'tools': {}}
    if not isinstance(identities, dict):
        return diagnostics
    diagnostics.update(missingToolCount=len(set(TOOLS) - identities.keys()),
                       unexpectedToolCount=len(identities.keys() - set(TOOLS)))
    derivations, outputs = set(), set()
    for tool in TOOLS:
        if tool not in identities:
            continue
        identity = identities[tool]
        facts = {'recordType': type(identity).__name__, 'problems': []}
        diagnostics['tools'][tool] = facts
        if not isinstance(identity, dict):
            facts['problems'].append('record-not-object')
            if isinstance(identity, str):
                facts['stringLength'] = len(identity)
                facts['stringIsStorePath'] = bool(STORE.fullmatch(identity))
            continue
        facts['missingFieldCount'] = len({'drvPath', 'outputPath'} - identity.keys())
        facts['unexpectedFieldCount'] = len(identity.keys() - {'drvPath', 'outputPath'})
        if facts['missingFieldCount'] or facts['unexpectedFieldCount']:
            facts['problems'].append('unexpected-fields')
        for field, seen, is_derivation in (('drvPath', derivations, True), ('outputPath', outputs, False)):
            value = identity.get(field)
            path_facts = {'type': type(value).__name__}
            facts[field] = path_facts
            if isinstance(value, str):
                valid = bool(STORE.fullmatch(value)) and value.endswith('.drv') == is_derivation
                path_facts.update(length=len(value), validStorePath=valid, duplicate=value in seen)
                if valid and value not in seen:
                    seen.add(value)
                else:
                    facts['problems'].append(field + '-invalid-or-duplicate')
            else:
                facts['problems'].append(field + '-not-string')
    return diagnostics


def tool_identities():
    names = ' '.join(json.dumps(tool) for tool in TOOLS)
    # Nix's JSON serializer collapses *any* attrset containing outPath to that
    # attribute. Use an ordinary metadata key so drvPath survives serialization.
    # https://github.com/NixOS/nix/blob/2.35.2/src/libexpr/value-to-json.cc#L47-L55
    expression = ('tools: builtins.listToAttrs (builtins.map (name: { inherit name; '
                  'value = { drvPath = tools.${name}.drvPath; outputPath = tools.${name}.outPath; }; '
                  '}) [' + names + '])')
    identities = json_output(['nix', 'eval', '--file', 'lib/ci-tools.nix', '--json', '--apply', expression])
    diagnostics = identity_diagnostics(identities)
    if (not isinstance(identities, dict) or set(identities) != set(TOOLS)
            or any(facts['problems'] for facts in diagnostics['tools'].values())):
        raise ToolIdentityError(diagnostics)
    return identities


def batched_tools():
    identities = tool_identities()
    records = json_output(['nix', 'build', '--file', 'lib/ci-tools.nix', *TOOLS, '--no-link', '--json'])
    if not isinstance(records, list) or len(records) != len(TOOLS):
        raise ValueError('Build results differ from the declared tools')
    by_derivation = {}
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get('drvPath'), str)
                or record['drvPath'] in by_derivation):
            raise ValueError('Invalid or duplicate tool build result')
        by_derivation[record['drvPath']] = record.get('outputs')
    if set(by_derivation) != {identity['drvPath'] for identity in identities.values()}:
        raise ValueError('Build derivations differ from evaluated tools')
    roots = []
    for tool in TOOLS:
        identity = identities[tool]
        if by_derivation[identity['drvPath']] != {'out': identity['outputPath']}:
            raise ValueError('Build output differs from evaluated tool: ' + tool)
        roots.append({'kind': 'tool', 'name': tool, 'path': identity['outputPath']})
    return roots


def realize_roots(include_proofs=False, batch=True):
    """Credential-free realization shared by publishing and the hosted benchmark."""
    if any(os.environ.get(key) for key in CREDENTIALS):
        raise ValueError('Do not expose credentials during realization')
    roots = []
    if include_proofs:
        checks = output(['nix', 'build', '--accept-flake-config', '--no-update-lock-file', '--no-write-lock-file',
                         '--no-link', '--print-out-paths', '.#ci-checks'])
        for proof in sorted(Path(checks).iterdir()):
            roots.append({'kind': 'proof', 'name': proof.name, 'path': str(proof.resolve(strict=True))})
        if not roots:
            raise ValueError('Successful checks produced no proof outputs')
    if batch:
        roots.extend(batched_tools())
        sizes = closure_sizes([root['path'] for root in roots])
        for root in roots:
            root['bytes'] = sizes[root['path']]
    else:
        # Faithful legacy preparation: proof queries precede four serial builds.
        for root in roots:
            root['bytes'] = closure_size(root['path'])
        for tool in TOOLS:
            path = output(['nix', 'build', '--file', 'lib/ci-tools.nix', tool, '--no-link', '--print-out-paths'])
            roots.append({'kind': 'tool', 'name': tool, 'path': path, 'bytes': closure_size(path)})
    validate_roots(roots)
    return roots


def validate_roots(roots):
    if not isinstance(roots, list) or not 0 < len(roots) <= 128:
        raise ValueError('Invalid cache root count')
    seen = set()
    for root in roots:
        if not isinstance(root, dict) or set(root) != {'kind', 'name', 'path', 'bytes'}:
            raise ValueError('Invalid cache root fields')
        kind, name, path = root['kind'], root['name'], root['path']
        limit = MIB if kind == 'proof' else 2 * 1024 ** 3
        if (kind not in ('proof', 'tool') or not isinstance(name, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', name)
                or (kind == 'tool' and name not in TOOLS)
                or not isinstance(path, str) or not STORE.fullmatch(path) or path.endswith('.drv')
                or type(root['bytes']) is not int or not 0 <= root['bytes'] <= limit
                or (kind, name) in seen):
            raise ValueError('Invalid allowlisted cache root')
        seen.add((kind, name))


def prepare(destination, include_proofs=False):
    boundary()
    roots = realize_roots(include_proofs=include_proofs)
    destination.write_text(json.dumps({'schema': 1, 'revision': os.environ['CACHE_SOURCE_REVISION'],
                                      'cache': 'finite-os', 'roots': roots}, indent=2) + '\n')


def push(manifest):
    boundary()
    if not os.environ.get('CACHIX_AUTH_TOKEN'):
        raise ValueError('Cachix writer credential is unavailable')
    if manifest.is_symlink() or manifest.stat().st_size > MIB:
        raise ValueError('Invalid cache manifest')
    record = json.loads(manifest.read_text())
    if (record.get('schema') != 1 or record.get('revision') != os.environ['CACHE_SOURCE_REVISION']
            or record.get('cache') != 'finite-os'):
        raise ValueError('Cache manifest identifies another source or destination')
    roots = record.get('roots')
    validate_roots(roots)
    sizes = closure_sizes([root['path'] for root in roots])
    if any(sizes[root['path']] != root['bytes'] for root in roots):
        raise ValueError('Cache closure size changed after preparation')
    push_env = preparation_env()
    push_env['CACHIX_AUTH_TOKEN'] = os.environ['CACHIX_AUTH_TOKEN']
    subprocess.run(['cachix', 'push', '--omit-deriver', 'finite-os', *sorted(sizes)],
                   env=push_env, check=True, timeout=1800)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'push'))
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--include-proofs', action='store_true', help='Also realize and seed all successful check proofs')
    args = parser.parse_args()
    if args.mode == 'push':
        if args.include_proofs:
            parser.error('--include-proofs selects prepare roots only')
        push(args.manifest)
    else:
        prepare(args.manifest, include_proofs=args.include_proofs)


if __name__ == '__main__':
    main()
