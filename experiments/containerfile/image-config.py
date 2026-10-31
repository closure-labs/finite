#!/usr/bin/env python3
"""Small explicit equivalents of the recipe's file/identity/signing operations."""
import json
from pathlib import Path
import shutil
import subprocess
import sys


def payload(ctx, root=Path('/')):
    plan = json.loads((ctx / 'plan.json').read_text())
    for entry in plan['copies']:
        if entry == {'source': 'system', 'destination': '/'}:
            continue  # cp -a already installed this tree, including symlinks.
        source = ctx / 'files' / entry['source']
        target = root / entry['destination'].lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            subprocess.run(['cp', '-a', str(source) + '/.', str(target)], check=True)
            (target / '.gitkeep').unlink(missing_ok=True)
        else:
            shutil.copy2(source, target)


def identity(ctx, root=Path('/')):
    plan = json.loads((ctx / 'plan.json').read_text())
    release = root / 'etc/os-release'
    values = plan['osRelease']
    existing = release.read_text().splitlines()
    seen = set()
    lines = []
    for line in existing:
        key = line.split('=', 1)[0]
        if key in values:
            lines.append(key + '=' + json.dumps(values[key]))
            seen.add(key)
        else:
            lines.append(line)
    lines.extend(key + '=' + json.dumps(value) for key, value in values.items() if key not in seen)
    release.write_text('\n'.join(lines) + '\n')
    containers = root / 'etc/containers'
    (containers / 'registries.d').mkdir(parents=True, exist_ok=True)
    key = root / 'etc/pki/containers/finite.pub'
    key.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ctx / 'cosign.pub', key)
    policy_path = containers / 'policy.json'
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    if policy is not None and not isinstance(policy, dict):
        raise ValueError('Invalid inherited signature policy')
    if policy is None or (policy.get('default') or [{}])[0].get('type') == 'insecureAcceptAnything':
        policy = json.loads((ctx / 'experiment/signing-policy.json').read_text())
    if not isinstance(policy, dict) or not isinstance(policy.get('transports'), dict):
        raise ValueError('Invalid inherited signature policy')
    policy['transports'].setdefault('docker', {})['ghcr.io/closure-labs/finite'] = [{
        'type': 'sigstoreSigned', 'keyPath': '/etc/pki/containers/finite.pub',
        'signedIdentity': {'type': 'matchRepository'}}]
    policy_path.write_text(json.dumps(policy, indent=2) + '\n')
    (containers / 'registries.d/closure-labs-finite.yaml').write_text(
        'docker:\n  ghcr.io/closure-labs/finite:\n    use-sigstore-attachments: true\n')


if __name__ == '__main__':
    {'payload': payload, 'identity': identity}[sys.argv[1]](Path(sys.argv[2]))
