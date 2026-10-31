#!/usr/bin/env python3
"""Validate only the exact unpublished experiment in the existing hosted VM harness."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('experiment_prepare', Path(__file__).with_name('prepare.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def validate(root=ROOT):
    # Reuse the temporary internal PR allowlist; dispatch remains assembly-only.
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'pull_request':
        raise ValueError('Experimental VM validation requires the authorized hosted PR')
    revision = prepare.authorized_revision()
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip() != revision:
        raise ValueError('VM checkout differs from authorized experiment head')
    directory = root / '.bluebuild/containerfile'
    plan = json.loads((directory / 'plan.json').read_text())
    receipt = json.loads((directory / 'installed-provenance.json').read_text())
    profile = plan['profile']
    if profile not in prepare.PROFILES or plan['sourceRevision'] != revision:
        raise ValueError('VM plan differs from authorized experiment')
    image = receipt['imageId']
    if (not prepare.DIGEST.fullmatch(image)
            or any(receipt.get(k) != plan.get(k) for k in ('sourceRevision', 'profile', 'experimentIdentity'))
            or not plan['experimentIdentity'].startswith('containerfile-v1:')
            or receipt.get('foundationSource') != plan['foundationSource']):
        raise ValueError('VM provenance does not bind the experimental image')
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], cwd=root, text=True))[0]
    labels = info.get('Config', {}).get('Labels', {}) or {}
    expected = {'io.finite.production-eligible': 'false', 'io.finite.build-inputs': plan['experimentIdentity'],
                'org.opencontainers.image.revision': revision, 'io.finite.profile': profile,
                'org.opencontainers.image.base.digest': plan['baseDigest']}
    if info.get('Id') != image or any(labels.get(k) != v for k, v in expected.items()):
        raise ValueError('VM image identity differs from unpublished plan')
    (root / '.bluebuild' / (profile + '-image-ref.txt')).write_text(image + '\n')
    # PR jobs use a merge SHA in GITHUB_SHA although assembly explicitly checks
    # out the head. Bind harness receipts to the actual verified checkout.
    env = dict(os.environ, GITHUB_SHA=revision, SOURCE_REVISION=revision,
               BUILD_IDENTITY=plan['experimentIdentity'], PROFILE=profile)
    started = time.monotonic()
    result = subprocess.run(['bash', 'scripts/bluebuild/local-vm.sh', profile], cwd=root, env=env)
    outcome = {'schema': 1, 'sourceRevision': revision, 'imageId': image,
               'experimentIdentity': plan['experimentIdentity'], 'profile': profile,
               'authorizesPublication': False, 'phase': 'fresh', 'exitCode': result.returncode,
               'seconds': round(time.monotonic() - started, 3)}
    (directory / 'vm-result.json').write_text(json.dumps(outcome, indent=2) + '\n')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(validate())
