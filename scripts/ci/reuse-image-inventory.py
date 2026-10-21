#!/usr/bin/env python3
"""Fetch inventory bytes from a successful trusted native security job.

Exit 3 is a cache miss; exit 2 rejects malformed or unauthenticated evidence.
No vulnerability finding, database, freshness receipt or policy result is reused.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    # Match the CLI import path without adding build-identity input bytecode.
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


reuse = module('reuse_security', ROOT / 'scripts/ci/reuse-candidate-security.py')
inventory = module('inventory_evidence', ROOT / 'scripts/ci/inventory-evidence.py')
publication = reuse.publication


def github(path, paginated=False):
    """Retry bounded metadata GETs; authentication and invalid evidence stay fatal."""
    command = ['gh', 'api']
    if paginated:
        command.extend(['--paginate', '--slurp'])
    command.append('repos/' + publication.REPOSITORY + '/' + path)
    for attempt in range(3):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=35, check=True)
        except subprocess.CalledProcessError as error:
            # gh reports HTTP status in stderr; do not retry authorization,
            # missing artifacts, malformed JSON or failed evidence checks.
            status = re.search(r'HTTP ([0-9]{3})\b', error.stderr or '')
            if not status or int(status[1]) not in (408, 429, 500, 502, 503, 504):
                print('GitHub inventory metadata request failed: ' +
                      (status[0] if status else f'gh exit {error.returncode}'), file=sys.stderr)
                raise
            if attempt == 2:
                print('GitHub inventory metadata retry budget exhausted: ' + status[0], file=sys.stderr)
                raise
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
        else:
            return json.loads(result.stdout)
        delay = 2 ** (attempt + 1)
        print(f'GitHub inventory metadata transport failed; retry {attempt + 1}/2 in {delay}s', file=sys.stderr)
        time.sleep(delay)


def hosted():
    workflows = {'build.yml': {'workflow_dispatch', 'push', 'schedule'},
                 'image-security.yml': {'workflow_dispatch', 'schedule'},
                 'benchmark-security-reuse.yml': {'workflow_dispatch'},
                 'release.yml': {'workflow_dispatch'},
                 'release-set.yml': {'workflow_dispatch'}}
    workflow = os.environ.get('GITHUB_WORKFLOW_REF', '')
    prefix = publication.REPOSITORY + '/.github/workflows/'
    name = workflow.removeprefix(prefix).removesuffix('@refs/heads/main')
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != publication.REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or workflow != prefix + name + '@refs/heads/main' or name not in workflows
            or os.environ.get('GITHUB_EVENT_NAME') not in workflows[name]
            or not publication.SHA.fullmatch(os.environ.get('GITHUB_SHA', ''))):
        raise ValueError('Inventory reuse requires a trusted hosted main image consumer')


def native_inventory_health(result, policy):
    """Recognize healthy inventory producers without accepting their findings."""
    return result.get('status') == 'pass' or (
        policy.get('mode') == 'maintainer-decision' and result.get('mode') == 'maintainer-decision'
        and result.get('status') == 'complete' and result.get('scannerHealth') == 'healthy')


def inventory_source(record, run, profile, image):
    """Original build provenance only; a resumed transport is a safe cache miss."""
    if (not isinstance(record, dict) or record.get('profile') != profile
            or record.get('revision') != run.get('head_sha')
            or record.get('qualificationMode') != 'enforce' or record.get('publish') is not True):
        raise ValueError('Inventory producer build context differs from its run')
    source = record.get('sourceRevision', record.get('revision'))
    if not isinstance(source, str) or not publication.SHA.fullmatch(source):
        raise ValueError('Inventory source revision is malformed')
    if 'resumeOrigin' in record:
        origin = record['resumeOrigin']
        if (not isinstance(origin, dict) or origin.get('sourceRevision') != source
                or origin.get('digest') != image.split('@')[1]
                or type(origin.get('runId')) is not int or origin['runId'] < 1
                or type(origin.get('runAttempt')) is not int or origin['runAttempt'] < 1):
            raise ValueError('Inventory resume context has inconsistent original source/image identity')
        # origin_metadata intentionally authenticates original build steps;
        # resumed runs skip those steps. Do not infer that proof from JSON.
        raise inventory.Unavailable('Resumed transport has no independently authenticated original inventory chain; regenerate inventory')
    if source != run['head_sha']:
        raise ValueError('Original inventory source revision differs from its build run')
    return source


def retrieve(image, profile, output, origin_run=None):
    hosted()
    if not reuse.security.IMAGE.fullmatch(image) or profile not in reuse.security.PROFILES:
        raise ValueError('Inventory reuse requires an immutable image and supported profile')
    if origin_run is not None and not re.fullmatch(r'[1-9][0-9]*', origin_run):
        raise ValueError('Invalid explicit origin run')
    output = output.absolute()
    if ('..' in output.parts or output.exists()
            or any(part.is_symlink() for part in (output, *output.parents))):
        raise ValueError('Inventory output must be new with no symlinked parents')
    if origin_run:
        runs = [github('actions/runs/' + origin_run)]
    else:
        # Bounded discovery: never walk all history or download every SBOM.
        runs = github('actions/workflows/build.yml/runs?branch=main&status=completed&per_page=20')['workflow_runs']
    for run in runs:
        run_id = str(run['id'])
        attempt = run.get('run_attempt')
        if type(attempt) is not int or attempt < 1:
            raise ValueError('Invalid inventory producer attempt')
        artifacts = [item for page in github(f'actions/runs/{run_id}/artifacts?per_page=100', True)
                     for item in page['artifacts']]
        images = [item for item in artifacts if item.get('name') == f'image-{profile}-{run_id}-{attempt}']
        scans = [item for item in artifacts if item.get('name') == f'security-{profile}-{run_id}-{attempt}']
        if not images or not scans or any(item.get('expired') is True for item in (*images, *scans)):
            if origin_run:
                raise inventory.Unavailable('Original inventory artifacts are unavailable')
            continue
        if len(images) != 1 or len(scans) != 1:
            raise ValueError('Ambiguous inventory producer artifacts')
        # Authenticate this small archive before using its exact image reference
        # to choose the much larger native evidence archive.
        image_artifact = images[0]
        binding = image_artifact.get('workflow_run', {})
        if (type(image_artifact.get('id')) is not int or image_artifact['id'] < 1
                or image_artifact.get('expired') is not False
                or type(image_artifact.get('size_in_bytes')) is not int
                or not 0 < image_artifact['size_in_bytes'] <= 64 * 1024**2
                or not isinstance(image_artifact.get('digest'), str)
                or not publication.DIGEST.fullmatch(image_artifact['digest'])
                or binding.get('id') != run['id'] or binding.get('head_sha') != run.get('head_sha')):
            raise ValueError('Inventory image archive lacks immutable run binding')
        files = publication.origin_files(image_artifact, profile)
        if files[f'{profile}-image-ref.txt'].decode().strip() != image:
            if origin_run:
                raise inventory.Unavailable('Origin contains a different immutable image')
            continue
        record = json.loads(files[f'{profile}-publication.json'])
        try:
            source_revision = inventory_source(record, run, profile, image)
        except inventory.Unavailable:
            if origin_run:
                raise
            continue
        jobs = [item for page in github(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100', True)
                for item in page['jobs']]
        artifact, _, build_job, security_job = reuse.metadata(run, jobs, artifacts, profile, run_id)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix='.inventory-reuse-', dir=output.parent) as temporary:
                staging = Path(temporary) / 'evidence'
                staging.mkdir()
                with tempfile.TemporaryFile() as archive:
                    subprocess.run(['gh', 'api', f'repos/{publication.REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                                   stdout=archive, check=True, timeout=180,
                                   preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE,
                                       (reuse.ARCHIVE_LIMIT, reuse.ARCHIVE_LIMIT)))
                    reuse.extract(archive, artifact, staging)
                baseline = reuse.read_json(staging / 'approved-baseline.json')
                result = reuse.read_json(staging / 'security-result.json')
                policy = reuse.security.load_policy(ROOT / 'automation/security/image-policy.json')
                if (not native_inventory_health(result, policy) or result.get('image') != image
                        or baseline.get('image') != image or baseline.get('profile') != profile
                        or baseline.get('sourceRevision') != source_revision
                        or baseline.get('buildIdentity') != record.get('buildIdentity')):
                    raise ValueError('Native inventory producer does not match its immutable build')
                identity = inventory.verify(staging, image, reuse.security,
                                            policy.get('mode') in reuse.security.RISK_MODES)
                ready = Path(temporary) / 'inventory'
                ready.mkdir()
                inventory.copy(staging, ready, identity)
                origin = {'schema': 1, 'status': 'authenticated-inventory-only', 'image': image,
                          'profile': profile, 'originRun': run['id'], 'originAttempt': attempt,
                          'originBuildJob': build_job, 'originSecurityJob': security_job,
                          'artifactId': artifact['id'], 'artifactSha256': artifact['digest'],
                          'sourceRevision': run['head_sha'], 'validationRevision': os.environ['GITHUB_SHA'],
                          'authenticatedAt': datetime.now(timezone.utc).isoformat(),
                          'newScanRequired': True, 'releaseEligibilityEstablished': False}
                (ready / 'inventory-origin.json').write_text(json.dumps(origin, indent=2) + '\n')
                ready.rename(output)
                return origin
        except inventory.Unavailable:
            if origin_run:
                raise
            continue
    raise inventory.Unavailable('No compatible inventory in the bounded recent build history')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--origin-run')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    # Artifact parsing stays bounded independently of the scanner service.
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    try:
        print(json.dumps(retrieve(args.image, args.profile, args.output, args.origin_run)))
        return 0
    except (inventory.Unavailable, reuse.Unavailable) as error:
        print(str(error), file=sys.stderr)
        return 3
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Inventory reuse rejected: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
