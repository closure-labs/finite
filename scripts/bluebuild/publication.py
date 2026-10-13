#!/usr/bin/env python3
"""Prepare isolated candidate tags and promote only a verified image digest."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

spec = importlib.util.spec_from_file_location('bluefin_upstream', Path(__file__).resolve().parents[1] / 'ci/bluefin-upstream.py')
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)
security_spec = importlib.util.spec_from_file_location('security_policy', Path(__file__).with_name('security-policy.py'))
security = importlib.util.module_from_spec(security_spec)
security_spec.loader.exec_module(security)
REPOSITORY = 'closure-labs/finite'
SHA = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def github(path, paginated=False):
    command = ['gh', 'api']
    if paginated:
        command.extend(['--paginate', '--slurp'])
    return json.loads(subprocess.check_output(
        [*command, 'repos/' + REPOSITORY + '/' + path], text=True, timeout=120))


def origin_metadata(run, jobs, artifacts, profile, run_id):
    """An unsuccessful security job does not erase a successful trusted build."""
    if (run.get('id') != int(run_id) or run.get('status') != 'completed'
            or run.get('conclusion') not in ('success', 'failure')
            or run.get('event') not in ('push', 'workflow_dispatch')
            or run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/build.yml'
            or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or not isinstance(run.get('head_sha'), str) or not SHA.fullmatch(run['head_sha'])
            or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1):
        raise ValueError('Resume origin must be a completed trusted main Build Finite push/manual run')
    image_job = f'Publish ({profile}) / build / build'
    required = ('Select checks', 'Documentation checks', 'Nix and runtime contracts', image_job)
    selected = {}
    for name in required:
        matches = [job for job in jobs if job.get('name') == name]
        if len(matches) != 1:
            raise ValueError('Resume origin is missing a unique required job: ' + name)
        job = matches[0]
        if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
                or job.get('head_sha') != run['head_sha'] or job.get('run_id') != run['id']
                or job.get('run_attempt') != run['run_attempt']):
            raise ValueError('Resume origin required job did not succeed at the selected attempt: ' + name)
        selected[name] = job
    for name in ('Prepare candidate publication', 'Build with BlueBuild', 'Verify assembled image', 'Save build evidence'):
        steps = [step for step in selected[image_job].get('steps', []) if step.get('name') == name]
        if len(steps) != 1 or steps[0].get('conclusion') != 'success':
            raise ValueError('Resume requires an original completed image build: ' + name)
    artifact_name = f'image-{profile}-{run_id}-{run["run_attempt"]}'
    matches = [entry for entry in artifacts if entry.get('name') == artifact_name]
    if len(matches) != 1:
        raise ValueError('Resume requires one exact origin artifact')
    artifact = matches[0]
    binding = artifact.get('workflow_run', {})
    if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
            or not isinstance(artifact.get('digest'), str)
            or not DIGEST.fullmatch(artifact['digest'])
            or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= 64 * 1024 * 1024
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha']):
        raise ValueError('Resume origin artifact lacks its immutable run/digest binding')
    return artifact, selected[image_job]['id']


def origin_files(artifact, profile):
    """Read only bounded named evidence files; never extract artifact paths."""
    names = (f'{profile}-publication.json', f'{profile}-image-ref.txt', f'{profile}.Containerfile')
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, check=True, timeout=180)
        archive.seek(0, 2)
        if not 0 < archive.tell() <= 64 * 1024 * 1024:
            raise ValueError('Origin artifact exceeds its archive bound')
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != artifact['digest']:
            raise ValueError('Origin artifact archive digest mismatch')
        archive.seek(0)
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            result = {}
            for name in names:
                matching = [entry for entry in entries if entry.filename == name]
                if len(matching) != 1 or not 0 < matching[0].file_size <= 4 * 1024 * 1024:
                    raise ValueError('Missing, duplicate or oversized origin evidence: ' + name)
                with zipped.open(matching[0]) as source:
                    result[name] = source.read(4 * 1024 * 1024 + 1)
                if len(result[name]) != matching[0].file_size:
                    raise ValueError('Origin evidence size mismatch')
            return result


def validate_candidate(profile, digest, source_revision, record, image_ref, info, recipe, identity):
    image = upstream.REPOSITORY + '@' + digest
    if (image_ref.strip() != image or record.get('publish') is not True
            or record.get('profile') != profile or record.get('revision') != source_revision
            or record.get('sourceRevision', source_revision) != source_revision
            or 'resumeOrigin' in record or record.get('buildIdentity') != identity
            or record.get('base') != recipe['base'] or record.get('digest') != recipe['digest']
            or record.get('tags') != recipe['tags'] or record.get('qualificationMode') != 'enforce'
            or info.get('Digest') != digest or info.get('Os') != 'linux' or info.get('Architecture') != 'amd64'):
        raise ValueError('Origin candidate does not match the requested digest and current runtime inputs')
    expected = {'io.finite.profile': profile, 'io.finite.build-inputs': identity,
                'org.opencontainers.image.revision': source_revision,
                'org.opencontainers.image.base.digest': recipe['digest'],
                'org.opencontainers.image.source': 'https://github.com/' + REPOSITORY}
    if any((info.get('Labels') or {}).get(key) != value for key, value in expected.items()):
        raise ValueError('Resume candidate labels do not match its trusted origin and current inputs')


def resume(profile, run_id, digest, root=upstream.ROOT):
    if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or not re.fullmatch(r'[1-9][0-9]*', run_id or '')
            or not DIGEST.fullmatch(digest or '')
            or not SHA.fullmatch(os.environ.get('GITHUB_SHA', ''))):
        raise ValueError('Resume requires a trusted main manual run and exact origin run/digest')
    run = github('actions/runs/' + run_id)
    attempt = run.get('run_attempt')
    if type(attempt) is not int or attempt < 1:
        raise ValueError('Invalid origin run attempt')
    jobs = [job for page in github(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100', True)
            for job in page['jobs']]
    artifacts = [entry for page in github(f'actions/runs/{run_id}/artifacts?per_page=100', True)
                 for entry in page['artifacts']]
    artifact, job_id = origin_metadata(run, jobs, artifacts, profile, run_id)
    source_revision = run['head_sha']
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=30).strip()
    if head != os.environ['GITHUB_SHA']:
        raise ValueError('Resume checkout differs from the current qualification revision')
    subprocess.run(['git', 'merge-base', '--is-ancestor', source_revision, head], cwd=root, check=True, timeout=30)
    recipe = upstream.recipes(root)[profile]
    identity = upstream.image_identity(profile, root)
    # Repeat publisher authentication here, independently of workflow ordering.
    upstream.verify(root)
    files = origin_files(artifact, profile)
    origin_record = json.loads(files[f'{profile}-publication.json'])
    image_ref = files[f'{profile}-image-ref.txt'].decode('utf-8')
    info = upstream.inspect(upstream.REPOSITORY + '@' + digest)
    validate_candidate(profile, digest, source_revision, origin_record, image_ref, info, recipe, identity)
    origin = {'runId': run['id'], 'runAttempt': attempt, 'jobId': job_id,
              'artifactId': artifact['id'], 'artifactDigest': artifact['digest'],
              'sourceRevision': source_revision, 'digest': digest}
    prepare(profile, True, root, source_revision=source_revision, resume_origin=origin)
    evidence = root / '.bluebuild'
    (evidence / f'{profile}.Containerfile').write_bytes(files[f'{profile}.Containerfile'])
    (evidence / f'{profile}-image-ref.txt').write_text(upstream.REPOSITORY + '@' + digest + '\n')
    (evidence / f'{profile}-resume-origin.json').write_text(json.dumps(origin, indent=2) + '\n')
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            print('digest=' + digest, file=stream)


def recovery_baseline(profile, published_digest, root):
    """Use a reviewed baseline only while its exact broken digest is published."""
    path = root / 'automation/qualification-recovery.json'
    if not path.exists():
        return published_digest, ''
    policy = json.loads(path.read_text())
    if (not isinstance(policy, dict) or set(policy) != {'schema', 'profiles'} or
            type(policy['schema']) is not int or policy['schema'] != 1 or not isinstance(policy['profiles'], dict)):
        raise ValueError('Invalid qualification recovery policy')
    for name, entry in policy['profiles'].items():
        if name not in upstream.PROFILES or not isinstance(entry, dict) or set(entry) != {'publishedDigest', 'baselineDigest', 'reason'}:
            raise ValueError('Invalid qualification recovery entry')
        replaced = upstream.digest(entry['publishedDigest'])
        baseline = upstream.digest(entry['baselineDigest'])
        if replaced == baseline or not isinstance(entry['reason'], str) or not entry['reason'].strip():
            raise ValueError('Recovery requires a distinct baseline and a reason')
    entry = policy['profiles'].get(profile)
    if entry and published_digest == entry['publishedDigest']:
        return entry['baselineDigest'], entry['reason']
    return published_digest, ''


def prepare(profile, publish, root=upstream.ROOT, source_revision=None, resume_origin=None):
    recipe = upstream.recipes(root)[profile]
    build_identity = upstream.image_identity(profile, root)
    mode = os.environ.get('FINITE_QUALIFICATION_MODE', 'enforce')
    if mode != 'enforce':
        raise ValueError('Boot qualification must be enforced')
    previous = upstream.inspect(upstream.REPOSITORY + ':' + recipe['tags'][0], allow_missing=True) if publish else None
    previous_digest = upstream.digest(previous['Digest']) if previous else ''
    if previous_digest:
        subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', str(root / 'cosign.pub'),
                        upstream.REPOSITORY + '@' + previous_digest],
                       check=True, stdout=subprocess.DEVNULL, timeout=150)
    published_digest = previous_digest
    previous_digest, recovery_reason = recovery_baseline(profile, published_digest, root)
    if recovery_reason:
        baseline = upstream.REPOSITORY + '@' + previous_digest
        subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', str(root / 'cosign.pub'), baseline],
                       check=True, stdout=subprocess.DEVNULL, timeout=150)
        if (upstream.inspect(baseline).get('Labels') or {}).get('io.finite.profile') != profile:
            raise ValueError('Recovery baseline belongs to a different profile')
    # Declared inputs cannot identify floating RPM/module contents. Every
    # published candidate must boot successfully, regardless of day or labels.
    qualify = publish
    evidence = root / '.bluebuild'
    evidence.mkdir(exist_ok=True)
    (evidence / f'{profile}-image-ref.txt').unlink(missing_ok=True)
    (evidence / f'{profile}-acceptance.json').unlink(missing_ok=True)
    # Publication workflows share finite-publication concurrency. A stable
    # candidate tag per profile also preserves BlueBuild's per-tag layer cache.
    candidate = f'candidate-{profile}'
    record = {**recipe, 'profile': profile, 'candidate': candidate,
              'revision': os.environ.get('GITHUB_SHA', 'local'), 'publish': publish,
              'sourceRevision': source_revision or os.environ.get('GITHUB_SHA', 'local'),
              'buildIdentity': build_identity, 'previousDigest': previous_digest,
              'publishedDigest': published_digest, 'recoveryReason': recovery_reason,
              'qualify': qualify, 'qualificationMode': mode}
    if resume_origin is not None:
        record['resumeOrigin'] = resume_origin
    (evidence / f'{profile}-publication.json').write_text(json.dumps(record, indent=2) + '\n')
    if publish and resume_origin is None:
        path = root / 'recipes' / f'{profile}.yml'
        content, count = re.subn(r'^alt-tags: \[[^\n]+\]$', 'alt-tags: [' + candidate + ']', path.read_text(), flags=re.M)
        if count != 1:
            raise ValueError('Expected one inline alt-tags field')
        path.write_text(content)
    if resume_origin is None:
        path = root / 'recipes' / f'{profile}.yml'
        content = path.read_text().replace('labels:\n', 'labels:\n  io.finite.build-inputs: "' + build_identity + '"\n', 1)
        path.write_text(content)
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            for name, value in {'qualify': str(qualify).lower(), 'previous': previous_digest,
                                'identity': build_identity, 'source_revision': record['sourceRevision']}.items():
                print(f'{name}={value}', file=stream)


def promotion_state(record):
    """Reject stale qualification before the first public tag mutation."""
    revision = record['revision']
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError('Promotion requires an exact qualification revision')
    current = github('git/ref/heads/main')
    reference = current.get('object', {}) if isinstance(current, dict) else {}
    if (not isinstance(current, dict) or not isinstance(reference, dict)
            or current.get('ref') != 'refs/heads/main'
            or reference.get('type') != 'commit' or reference.get('sha') != revision):
        raise ValueError('Main changed after qualification was prepared; requalify at the current revision')
    published = record['publishedDigest']
    if published != '':
        upstream.digest(published)
    current = upstream.inspect(upstream.REPOSITORY + ':' + record['tags'][0], allow_missing=True)
    observed = upstream.digest(current['Digest']) if current is not None else ''
    if observed != published:
        raise ValueError('Public channel changed after qualification was prepared')


def promote(profile, root=upstream.ROOT):
    evidence = root / '.bluebuild'
    record = json.loads((evidence / f'{profile}-publication.json').read_text())
    if not record['publish'] or record['profile'] != profile or record['tags'] != upstream.PROFILES[profile][1]:
        raise ValueError('Invalid publication record')
    if record['revision'] != os.environ['GITHUB_SHA']:
        raise ValueError('Publication record is from a different revision')
    baseline, reason = recovery_baseline(profile, record['publishedDigest'], root)
    if (record['previousDigest'] != baseline or record.get('recoveryReason') != reason or
            (reason and record.get('qualify') is not True)):
        raise ValueError('Publication record does not match the reviewed recovery baseline')
    # Build evidence is unsigned. Recheck scan policy and the registry signature
    # independently below; never resolve the mutable candidate tag again.
    image = (evidence / f'{profile}-image-ref.txt').read_text().strip()
    prefix = upstream.REPOSITORY + '@'
    if not image.startswith(prefix):
        raise ValueError('Verified image must belong to the Finite repository')
    expected = upstream.digest(image.removeprefix(prefix))
    source_revision = record.get('sourceRevision', record['revision'])
    if source_revision != record['revision']:
        origin = record.get('resumeOrigin', {})
        if origin.get('sourceRevision') != source_revision or origin.get('digest') != expected:
            raise ValueError('Publication lacks matching immutable resume provenance')
    if record['qualificationMode'] != 'enforce' or os.environ.get('FINITE_QUALIFICATION_MODE', 'enforce') != 'enforce':
        raise ValueError('Boot qualification must be enforced')
    acceptance_path = evidence / f'{profile}-acceptance.json'
    accepted = False
    if acceptance_path.exists():
        acceptance = json.loads(acceptance_path.read_text())
        accepted = all((acceptance.get('accepted') is True,
                        acceptance.get('candidate') == image,
                        acceptance.get('previousDigest') == record['previousDigest'],
                        acceptance.get('profile') == profile,
                        acceptance.get('revision') == record['revision'],
                        acceptance.get('sourceRevision', acceptance.get('revision')) == source_revision,
                        acceptance.get('buildIdentity') == record['buildIdentity'],
                        acceptance.get('secureBoot') is True,
                        acceptance.get('encryptedRoot') is True))
    if not accepted:
        raise ValueError('Candidate lacks matching successful encrypted Secure Boot qualification')
    security.verify(evidence / ('security-' + profile), image, root / 'automation/security/image-policy.json')
    subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', str(root / 'cosign.pub'), image],
                   check=True, stdout=subprocess.DEVNULL, timeout=150)
    # GitHub workflow concurrency serializes our publishers but does not freeze
    # main or prevent an administrator from updating a registry channel. Check
    # both after evidence validation, immediately before the first tag copy.
    promotion_state(record)
    for tag in record['tags']:
        target = upstream.REPOSITORY + ':' + tag
        subprocess.run(['skopeo', '--command-timeout', '90s', 'copy', '--retry-times', '3',
                        '--all', '--preserve-digests', 'docker://' + image, 'docker://' + target],
                       check=True, timeout=150)
        if upstream.inspect(target)['Digest'] != expected:
            raise RuntimeError(f'{target}: promoted digest does not match verified candidate')
    (evidence / f'{profile}-promoted.json').write_text(json.dumps(
        {**record, 'image': image, 'accepted': accepted}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'promote', 'resume'])
    parser.add_argument('profile', choices=upstream.PROFILES)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--run')
    parser.add_argument('--digest')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.profile, args.publish)
    elif args.command == 'resume':
        resume(args.profile, args.run, args.digest)
    else:
        promote(args.profile)


if __name__ == '__main__':
    main()
