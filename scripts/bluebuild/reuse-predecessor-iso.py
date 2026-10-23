#!/usr/bin/env python3
"""Reuse authenticated pristine ISO bytes with unchanged generation inputs."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import zipfile
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reuse = load('predecessor_qualification_reuse', 'reuse-qualification.py')
release = load('predecessor_release_iso', 'release-evidence.py')
qualification = reuse.qualification
upstream_spec = importlib.util.spec_from_file_location('predecessor_registry', ROOT / 'scripts/ci/bluefin-upstream.py')
upstream = importlib.util.module_from_spec(upstream_spec)
upstream_spec.loader.exec_module(upstream)


def generation_inputs(inputs):
    # These two entry points never produce the published pristine candidate ISO:
    # local-vm.sh is restricted to PR/merge-group jobs, and this reader is called
    # only by the upgrade lane. Keep every other input (including unknown/new
    # helpers, executable modes, certificates and VM checks) conservative.
    # This projection must never be used for qualification receipt reuse.
    if not isinstance(inputs, dict):
        raise reuse.Unavailable('Predecessor ISO generation inputs are missing')
    return {path: value for path, value in inputs.items() if path not in (
        'scripts/bluebuild/local-vm.sh', 'scripts/bluebuild/reuse-predecessor-iso.py')}


def compatible(directory, profile, digest, inputs):
    value = json.loads(qualification.desktop.read(directory / (profile + '-acceptance.json')))
    if value.get('validationOnly') is True:
        raise ValueError('Diagnostic qualification cannot provide a retained predecessor ISO')
    if (value.get('schema') != 2 or not value.get('qualifiedIso')
            or value.get('candidate') != 'ghcr.io/closure-labs/finite@' + digest
            or value.get('profile') != profile):
        raise reuse.Unavailable('Predecessor ISO candidate or generation context differs')
    recorded = generation_inputs(value.get('qualificationContext', {}).get('inputs'))
    current = generation_inputs(inputs)
    if recorded != current:
        paths = sorted(path for path in recorded.keys() | current.keys()
                       if recorded.get(path) != current.get(path))
        raise reuse.Unavailable('Predecessor ISO generation inputs differ: ' + ', '.join(paths[:20]))
    if (value.get('accepted') is not True or value.get('secureBoot') is not True
            or value.get('encryptedRoot') is not True
            or qualification.identity(value['qualificationContext']) != value.get('qualificationContextSha256')):
        raise ValueError('Predecessor qualification has inconsistent acceptance/context')
    qualification.desktop.verify(directory, value)
    return value


def restore(profile, digest, output):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != reuse.REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)
            or not re.fullmatch(r'finite(?:-dev)?', profile)):
        raise ValueError('Predecessor reuse requires a hosted main immutable profile/digest')
    if output.exists() or output.is_symlink() or any(path.is_symlink() for path in output.absolute().parents):
        raise ValueError('Predecessor ISO destination must be new with no symlinked parents')
    inputs = qualification.source_inputs()
    runs = reuse.github('actions/workflows/build.yml/runs?branch=main&status=success&per_page=20')['workflow_runs']
    for run in runs:
        artifacts = [item for page in reuse.github(f'actions/runs/{run["id"]}/artifacts?per_page=100', True)
                     for item in page['artifacts']]
        pattern = re.compile(r'qualification-' + re.escape(profile) + '-' + str(run['id']) + r'-([1-9][0-9]*)$')
        matches = [item for item in artifacts if pattern.fullmatch(item.get('name', '')) and item.get('expired') is False]
        for artifact in sorted(matches, key=lambda item: int(pattern.fullmatch(item['name'])[1]), reverse=True):
            attempt = int(pattern.fullmatch(artifact['name'])[1])
            jobs = [item for page in reuse.github(f'actions/runs/{run["id"]}/attempts/{attempt}/jobs?per_page=100', True)
                    for item in page['jobs']]
            try:
                reuse.metadata(run, jobs, artifact, profile)
            except reuse.Unavailable:
                continue
            with tempfile.TemporaryDirectory(prefix='finite-predecessor-') as temporary:
                directory = Path(temporary)
                with tempfile.TemporaryFile() as archive:
                    subprocess.run(['gh', 'api', f'repos/{reuse.REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                        stdout=archive, check=True, timeout=180,
                        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (reuse.ARCHIVE_LIMIT, reuse.ARCHIVE_LIMIT)))
                    try:
                        reuse.extract(archive, artifact, directory, profile)
                    except reuse.Unavailable:
                        continue
                try:
                    value = compatible(directory, profile, digest, inputs)
                except reuse.Unavailable:
                    continue
                if value['revision'] != run['head_sha']:
                    raise ValueError('Predecessor qualification source differs from its producer')
                origin = value.get('qualifiedIsoOrigin', {'run': run['id'], 'attempt': attempt, 'revision': run['head_sha']})
                origin_run = run if origin['run'] == run['id'] else reuse.github('actions/runs/' + str(origin['run']))
                release.validate_run(origin_run, 'build.yml', origin['revision'])
                origin_artifacts = artifacts if origin['run'] == run['id'] else release.artifact_names(str(origin['run']))
                preserved = release.qualified_iso_artifact(origin_artifacts, profile, str(origin['run']), origin['attempt'])
                if preserved is None:
                    continue
                staging = directory / 'iso'
                staging.mkdir()
                release.authenticated_iso(preserved, origin_run, value, staging)
                # Current generation-input comparison includes all locks, hook, pinned
                # certificate and generation scripts. finiteRevision stays original.
                installation = json.loads((staging / 'installation.json').read_text())
                if (installation['image'] != value['candidate'] or installation['profile'] != profile
                        or installation['installer'] != value['qualifiedIso']['installer']):
                    raise ValueError('Predecessor ISO installer/image differs from qualified evidence')
                tag = installation['installationTag']
                if not re.fullmatch(r'ghcr.io/closure-labs/finite:i[0-9a-f]{16}', tag):
                    raise ValueError('Predecessor ISO has an invalid isolated installation tag')
                tag_info = upstream.inspect(tag, allow_missing=True)
                if tag_info is None:
                    continue
                if tag_info.get('Digest') != digest:
                    raise ValueError('Predecessor installation tag moved from its qualified digest')
                subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=staging, check=True, timeout=300)
                subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', 'cosign.pub', value['candidate']],
                               check=True, stdout=subprocess.DEVNULL, timeout=150)
                output.parent.mkdir(parents=True, exist_ok=True)
                # Copy by bounded streams; staging and the worktree may be on
                # different filesystems. No personalized ISO or VM state exists here.
                import shutil
                shutil.copytree(staging, output)
                (output / 'iso-reuse.json').write_text(json.dumps({'schema': 1, 'originRun': origin['run'],
                    'originAttempt': origin['attempt'], 'artifactSha256': preserved['digest'],
                    'image': value['candidate'], 'originalInstallationSha256': value['qualifiedIso']['installationSha256']}, indent=2) + '\n')
                return
    raise reuse.Unavailable('No compatible retained predecessor ISO found')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--digest', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        restore(args.profile, args.digest, args.output)
        return 0
    except reuse.Unavailable as error:
        print(str(error))
        return 3
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Predecessor ISO reuse rejected: ' + str(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
