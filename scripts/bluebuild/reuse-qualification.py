#!/usr/bin/env python3
"""Reuse exact, authenticated qualification for at most 24 hours (opt-in)."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from github_api import GitHubReadError, bounded_metadata, get_metadata

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qualification_context', ROOT / 'scripts/bluebuild/qualification-context.py')
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)
REPOSITORY = 'closure-labs/finite'
ARCHIVE_LIMIT = 512 * 1024 * 1024
FILE_LIMIT = 4 * 1024 * 1024


class Unavailable(ValueError):
    """No compatible evidence: run fresh qualification."""


def github(path, paginated=False):
    collection = path.split('?')[0].rsplit('/', 1)[-1] if paginated else None
    return get_metadata('repos/' + REPOSITORY + '/' + path, collection=collection)


def metadata(run, jobs, artifact, profile):
    pattern = re.fullmatch(r'qualification-' + re.escape(profile) + r'-([1-9][0-9]*)-([1-9][0-9]*)', artifact.get('name', ''))
    if not pattern:
        raise ValueError('Invalid qualification artifact name')
    run_id, attempt = map(int, pattern.groups())
    matches = [job for job in jobs if job.get('name') == f'Publish ({profile}) / qualification / aggregate']
    if (run.get('id') != run_id or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or run.get('head_branch') != 'main' or run.get('event') not in ('push', 'workflow_dispatch', 'schedule')
            or run.get('path') != '.github/workflows/build.yml'
            or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', ''))):
        raise ValueError('Qualification producer is not one successful trusted main workflow')
    if not matches:
        raise Unavailable('Legacy qualification has no bound aggregate producer')
    if len(matches) != 1:
        raise ValueError('Qualification aggregate producer is ambiguous')
    job = matches[0]
    if (job.get('conclusion') != 'success' or job.get('status') != 'completed'
            or job.get('run_id') != run_id or job.get('run_attempt') != attempt
            or job.get('head_sha') != run['head_sha'] or type(job.get('id')) is not int):
        raise ValueError('Qualification aggregate did not succeed at the exact source and attempt')
    if artifact.get('expired') is True:
        raise Unavailable('Qualification artifact expired')
    if artifact.get('digest') is None:
        raise Unavailable('Legacy qualification has no authenticated archive digest')
    binding = artifact.get('workflow_run', {})
    if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= ARCHIVE_LIMIT
            or binding.get('id') != run_id or binding.get('head_sha') != run['head_sha']):
        raise ValueError('Qualification artifact has no immutable origin/archive binding')
    return job['id'], attempt


def extract(archive, artifact, directory, profile):
    archive.seek(0, 2)
    if archive.tell() != artifact['size_in_bytes'] or not 0 < archive.tell() <= ARCHIVE_LIMIT:
        raise ValueError('Qualification archive size mismatch')
    archive.seek(0)
    if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != artifact['digest']:
        raise ValueError('Qualification archive digest mismatch')
    archive.seek(0)
    required = {profile + '-acceptance.json', profile + '-desktop-acceptance.json'}
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) > 256 or sum(entry.file_size for entry in entries) > ARCHIVE_LIMIT:
            raise ValueError('Qualification archive is duplicate or oversized')
        if not required.issubset(names):
            raise Unavailable('Legacy qualification lacks complete bound evidence')
        for name in required:
            entry = zipped.getinfo(name)
            if (stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or entry.flag_bits & 1 or not 0 < entry.file_size <= FILE_LIMIT):
                raise ValueError('Qualification evidence is linked, encrypted or oversized')
            with zipped.open(entry) as stream:
                data = stream.read(FILE_LIMIT + 1)
            if len(data) != entry.file_size:
                raise ValueError('Qualification evidence exceeds declared size')
            (directory / name).write_bytes(data)


def require_age(acceptance, now=None):
    timestamp = datetime.fromisoformat(acceptance['qualifiedAt'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('Qualification timestamp lacks timezone')
    age = (now or datetime.now(timezone.utc)) - timestamp
    if age < timedelta(0):
        raise ValueError('Qualification evidence is from the future')
    if age > timedelta(hours=24):
        raise Unavailable('Qualification evidence is older than 24 hours')


def verify_reused_acceptance(acceptance, now=None, root=ROOT):
    """Recheck at aggregation/promotion; queued work cannot extend verdict age."""
    if acceptance.get('validationOnly') is True:
        raise ValueError('Diagnostic qualification cannot authorize publication or reuse')
    if acceptance.get('schema') != 2 or not acceptance.get('qualificationReuse'):
        raise ValueError('Acceptance is not a bound reused qualification')
    context = acceptance.get('qualificationContext', {})
    if (qualification.identity(context) != acceptance.get('qualificationContextSha256')
            or context.get('inputs') != qualification.source_inputs(root)):
        raise ValueError('Reused qualification differs from current installer/test inputs')
    require_age(acceptance, now)
    qualification.validate_certificate(root)


def validate(directory, profile, candidate, previous, source, build_identity, context, now=None):
    acceptance = json.loads(qualification.desktop.read(directory / (profile + '-acceptance.json')))
    if acceptance.get('validationOnly') is True:
        raise ValueError('Diagnostic qualification cannot authorize publication or reuse')
    if (acceptance.get('schema') != 2 or not acceptance.get('qualifiedIso')
            or not acceptance.get('qualificationContextSha256') or not acceptance.get('qualifiedAt')):
        raise Unavailable('Legacy evidence lacks exact ISO/test context binding')
    if (acceptance.get('candidate') != candidate or acceptance.get('previousDigest') != previous
            or acceptance.get('profile') != profile or acceptance.get('sourceRevision') != source
            or acceptance.get('buildIdentity') != build_identity
            or acceptance.get('qualificationContext') != context):
        raise Unavailable('Qualification candidate, predecessor or test context changed')
    if (acceptance.get('accepted') is not True or acceptance.get('secureBoot') is not True
            or acceptance.get('encryptedRoot') is not True
            or acceptance['qualificationContextSha256'] != qualification.identity(context)):
        raise ValueError('Qualification verdict/context binding is incomplete')
    require_age(acceptance, now)
    iso = acceptance['qualifiedIso']
    if (not re.fullmatch(r'finite(?:-dev)?\.iso', iso.get('name', ''))
            or any(not re.fullmatch('[0-9a-f]{64}', iso.get(key, '')) for key in ('sha256', 'installationSha256'))
            or not isinstance(iso.get('installer'), dict)):
        raise ValueError('Qualification ISO binding is incomplete')
    qualification.desktop.verify(directory, acceptance)
    return acceptance


def prefilter(directory, profile, candidate, previous, source, build_identity):
    """Reject definite static mismatches; returning never authorizes reuse.

    Called only after authenticating the producer and archive. Do not infer
    candidate identity from the producer's head SHA: resumed images can have an
    older source revision. The full runtime context and verdict are checked by
    validate() after this filter, even when all static fields match.
    """
    acceptance = json.loads(qualification.desktop.read(directory / (profile + '-acceptance.json')))
    if not isinstance(acceptance, dict):
        raise ValueError('Qualification evidence must be an object')
    if acceptance.get('validationOnly') is True:
        raise ValueError('Diagnostic qualification cannot authorize publication or reuse')
    if (acceptance.get('candidate') != candidate or acceptance.get('previousDigest') != previous
            or acceptance.get('profile') != profile or acceptance.get('sourceRevision') != source
            or acceptance.get('buildIdentity') != build_identity):
        raise Unavailable('Qualification candidate, predecessor or source identity changed')
    context = acceptance.get('qualificationContext')
    if not isinstance(context, dict) or context.get('inputs') != qualification.source_inputs():
        raise Unavailable('Qualification installer/test inputs changed or are missing')


def prepare_context():
    """Use the same pinned tools, smoke checks and interpreter as setup-vm-tools."""
    env = qualification.vm_tools.provision('nix')
    qualification.vm_tools.smoke(env)
    with tempfile.TemporaryDirectory(prefix='finite-qualification-context-') as temporary:
        directory = Path(temporary)
        subprocess.run(['python3', str(ROOT / 'scripts/bluebuild/qualification-context.py'),
                        'context', '--directory', str(directory)],
                       env=env, cwd=ROOT, check=True, timeout=90)
        return json.loads((directory / 'qualification-context.json').read_text())


@bounded_metadata
def reuse(profile, output, *, prepare_tools=False):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or not re.fullmatch('[0-9a-f]{40}', os.environ.get('GITHUB_SHA', ''))):
        raise ValueError('Qualification reuse requires the hosted main workflow')
    if (not re.fullmatch(r'finite(?:-dev)?', profile)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', os.environ.get('CANDIDATE_DIGEST', ''))
            or (os.environ.get('PREVIOUS_DIGEST') and not re.fullmatch(r'sha256:[0-9a-f]{64}', os.environ['PREVIOUS_DIGEST']))
            or not re.fullmatch('[0-9a-f]{40}', os.environ.get('SOURCE_REVISION', ''))
            or not re.fullmatch(r'v1:[0-9a-f]{64}', os.environ.get('BUILD_IDENTITY', ''))):
        raise ValueError('Qualification reuse requires exact profile/candidate/source identities')
    if output is None or output.exists() or output.is_symlink() or any(path.is_symlink() for path in output.absolute().parents):
        raise ValueError('Qualification reuse output must be new with no symlinked parents')
    context = None if prepare_tools else json.loads((Path('.bluebuild') / 'qualification-context.json').read_text())
    now = datetime.now(timezone.utc)
    candidate = 'ghcr.io/closure-labs/finite@' + os.environ['CANDIDATE_DIGEST']
    # Bounded lookup; the pilot targets recent exact candidate reruns.
    for page in range(1, 4):
        runs = github(f'actions/workflows/build.yml/runs?branch=main&status=success&per_page=100&page={page}')['workflow_runs']
        for run in runs:
            updated = datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00'))
            if now - updated > timedelta(hours=24):
                continue
            entries = [item for group in github(f'actions/runs/{run["id"]}/artifacts?per_page=100', True)
                       for item in group['artifacts']]
            pattern = re.compile(r'qualification-' + re.escape(profile) + '-' + str(run['id']) + r'-([1-9][0-9]*)$')
            artifacts = [item for item in entries if pattern.fullmatch(item.get('name', '')) and item.get('expired') is False]
            for artifact in sorted(artifacts, key=lambda item: int(pattern.fullmatch(item['name'])[1]), reverse=True):
                attempt = int(pattern.fullmatch(artifact['name'])[1])
                jobs = [item for group in github(f'actions/runs/{run["id"]}/attempts/{attempt}/jobs?per_page=100', True)
                        for item in group['jobs']]
                try:
                    job_id, attempt = metadata(run, jobs, artifact, profile)
                except Unavailable:
                    continue
                with tempfile.TemporaryDirectory(prefix='finite-qualification-') as temporary:
                    directory = Path(temporary)
                    with tempfile.TemporaryFile() as archive:
                        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                            stdout=archive, check=True, timeout=180,
                            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (ARCHIVE_LIMIT, ARCHIVE_LIMIT)))
                        try:
                            extract(archive, artifact, directory, profile)
                        except Unavailable:
                            continue
                    try:
                        if prepare_tools:
                            prefilter(directory, profile, candidate, os.environ.get('PREVIOUS_DIGEST', ''),
                                      os.environ['SOURCE_REVISION'], os.environ['BUILD_IDENTITY'])
                            if context is None:
                                context = prepare_context()
                        value = validate(directory, profile, candidate, os.environ.get('PREVIOUS_DIGEST', ''),
                            os.environ['SOURCE_REVISION'], os.environ['BUILD_IDENTITY'], context, datetime.now(timezone.utc))
                    except Unavailable:
                        continue
                    if value['revision'] != run['head_sha']:
                        raise ValueError('Qualification revision differs from authenticated workflow source')
                    # Preserve qualifiedAt: a reused verdict never refreshes its own age.
                    origin = {'run': run['id'], 'attempt': attempt, 'job': job_id,
                              'artifactId': artifact['id'], 'artifactSha256': artifact['digest'],
                              'qualificationRevision': value['revision']}
                    value['revision'] = os.environ['GITHUB_SHA']
                    value['qualificationReuse'] = origin
                    (directory / (profile + '-acceptance.json')).write_text(json.dumps(value, indent=2) + '\n')
                    output.mkdir(parents=True)
                    for path in directory.iterdir():
                        (output / path.name).write_bytes(path.read_bytes())
                    return origin
        if len(runs) < 100:
            break
    raise Unavailable('No fresh exact qualification artifact found')


@bounded_metadata
def prune_iso(profile, apply=False):
    """Keep at most two successful ISO generations per profile in the pilot."""
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('ISO retention requires the hosted main workflow')
    prefix = 'finite-qualified-iso-' + profile + '-'
    artifacts = [item for page in github('actions/artifacts?per_page=100', True) for item in page['artifacts']
                 if item.get('name', '').startswith(prefix) and item.get('expired') is False]
    successful = []
    current = int(os.environ['GITHUB_RUN_ID'])
    for artifact in sorted(artifacts, key=lambda item: item['created_at'], reverse=True):
        match = re.fullmatch(re.escape(prefix) + r'([1-9][0-9]*)-([1-9][0-9]*)', artifact['name'])
        if not match:
            continue
        run_id, attempt = map(int, match.groups())
        if run_id == current:
            successful.append(artifact)
            continue
        run = github(f'actions/runs/{run_id}')
        if (run.get('conclusion') == 'success' and run.get('head_branch') == 'main'
                and run.get('path') == '.github/workflows/build.yml'
                and run.get('head_repository', {}).get('full_name') == REPOSITORY):
            successful.append(artifact)
    for artifact in successful[2:]:
        print(('Deleting ' if apply else 'Would delete ') + artifact['name'])
        if not apply:
            continue
        subprocess.run(['gh', 'api', '--method', 'DELETE', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}'],
                       check=True, timeout=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-reused', type=Path)
    parser.add_argument('--prepare-context', action='store_true',
                        help='Provision pinned context tools only after authenticated static eligibility checks')
    args = parser.parse_args()
    try:
        if args.verify_reused:
            verify_reused_acceptance(json.loads(qualification.desktop.read(args.verify_reused)))
        else:
            print(json.dumps(reuse(args.profile, args.output, prepare_tools=args.prepare_context)))
        return 0
    except Unavailable as error:
        print(str(error))
        return 3
    except (GitHubReadError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Qualification reuse rejected: ' + str(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
