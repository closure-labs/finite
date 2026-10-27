"""Authenticate independent publication before suppressing decision recovery.

All discovery is bounded and read-only. Missing or invalid proof is a miss; a
journal receipt is historical evidence and is never used as live authority.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import tempfile
import zipfile

import decision_controller as controller
import image_identity
from security_decisions import canonical_hash, load_json

REPOSITORY = controller.REPOSITORY
ARCHIVE_LIMIT = 64 * 1024**2
FILE_LIMIT = 4 * 1024**2


def artifact(entries, name, run, limit=ARCHIVE_LIMIT):
    matches = [entry for entry in entries if entry.get('name') == name]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous completion artifact')
    value = matches[0]
    if (value.get('expired') is not False or type(value.get('id')) is not int or value['id'] <= 0
            or type(value.get('size_in_bytes')) is not int or not 0 < value['size_in_bytes'] <= limit
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', value.get('digest', ''))
            or value.get('workflow_run', {}).get('id') != run['id']
            or value.get('workflow_run', {}).get('head_sha') != run['head_sha']):
        raise ValueError('Completion artifact lacks immutable native binding')
    return value


def download(value, extract):
    with tempfile.TemporaryFile() as archive:
        def restrict():
            resource.setrlimit(resource.RLIMIT_FSIZE, (value['size_in_bytes'], value['size_in_bytes']))
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{value["id"]}/zip'],
                       stdout=archive, check=True, timeout=300, preexec_fn=restrict)
        archive.seek(0, 2)
        if archive.tell() != value['size_in_bytes']:
            raise ValueError('Completion archive size mismatch')
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != value['digest']:
            raise ValueError('Completion archive hash mismatch')
        archive.seek(0)
        return extract(archive)


def documents(archive, names):
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if (len(entries) > 256 or len({e.filename for e in entries}) != len(entries)
                or sum(e.file_size for e in entries) > ARCHIVE_LIMIT):
            raise ValueError('Duplicate or oversized completion archive')
        result = {}
        for name in names:
            entry = zipped.getinfo(name)
            if (entry.flag_bits & 1 or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or not 0 < entry.file_size <= FILE_LIMIT):
                raise ValueError('Unsafe completion document')
            with zipped.open(entry) as stream:
                raw = stream.read(FILE_LIMIT + 1)
            if len(raw) != entry.file_size:
                raise ValueError('Completion document size mismatch')
            def unique(pairs):
                value = dict(pairs)
                if len(value) != len(pairs):
                    raise ValueError('Duplicate completion field')
                return value
            result[name] = json.loads(raw, object_pairs_hook=unique)
        return result


def ancestor(base, head):
    if not all(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (base, head)):
        raise ValueError('Invalid completion source')
    if base == head:
        return
    comparison = controller.api(f'repos/{REPOSITORY}/compare/{base}...{head}')
    if (comparison.get('status') != 'ahead' or comparison.get('base_commit', {}).get('sha') != base
            or comparison.get('merge_base_commit', {}).get('sha') != base):
        raise ValueError('Completion source is not a proven successor')


def successful_job(jobs, name, run):
    matches = [job for job in jobs if job.get('name') == name]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous publisher job')
    job = matches[0]
    if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
            or job.get('run_id') != run['id'] or job.get('run_attempt') != run['run_attempt']
            or job.get('head_sha') != run['head_sha'] or type(job.get('id')) is not int):
        raise ValueError('Publisher job did not succeed at the exact attempt')
    return job['id']


def current_build_identity(profile):
    """Use the production image-input contract from this exact trusted checkout.

    This runs only in the hosted controller, never to instrument user realization.
    Missing current proof retains recovery rather than trusting registry labels.
    """
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=controller.ROOT,
                                       text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    if checkout != os.environ.get('GITHUB_SHA'):
        raise ValueError('Completion checkout differs from the trusted current source')
    return image_identity.identity(profile, controller.ROOT)


def authenticate(profile, origin, native, decision, bot, run, current_identity):
    security = controller.module('completion_security', controller.ROOT / 'scripts/ci/reuse-candidate-security.py')
    qualification = controller.module('completion_qualification', controller.ROOT / 'scripts/bluebuild/reuse-qualification.py')
    publication = security.publication
    if (type(run.get('id')) is not int or run['id'] <= 0
            or type(run.get('run_attempt')) is not int or run['run_attempt'] <= 0
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or run.get('path') != '.github/workflows/build.yml' or run.get('head_branch') != 'main'
            or run.get('event') not in controller.PRODUCERS['build.yml']
            or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('head_repository', {}).get('full_name') != REPOSITORY):
        raise ValueError('Completion requires a trusted successful publisher')
    baseline = load_json(native / 'approved-baseline.json')
    identity = baseline.get('buildIdentity')
    if (baseline.get('profile') != profile or baseline.get('sourceRevision') != origin['headSha']
            or not isinstance(identity, str) or not re.fullmatch(r'v1:[0-9a-f]{64}', identity)
            or identity != current_identity):
        raise ValueError('Recovery packet lacks exact profile/build identity')
    prefix = f'repos/{REPOSITORY}/actions/runs/{run["id"]}'
    jobs = controller.collection(prefix + f'/attempts/{run["run_attempt"]}/jobs', 'jobs')
    job_ids = {kind: successful_job(jobs, f'Publish ({profile}) / {suffix}', run)
               for kind, suffix in (('promotion', 'promote'), ('qualification', 'qualification / aggregate'),
                                    ('security', 'security'), ('sign', 'sign'))}
    entries = controller.collection(prefix + '/artifacts', 'artifacts')
    suffix = f'{profile}-{run["id"]}-{run["run_attempt"]}'
    promotion = artifact(entries, 'promotion-' + suffix, run)
    qualified = artifact(entries, 'qualification-' + suffix, run, qualification.ARCHIVE_LIMIT)
    scanned = artifact(entries, 'security-' + suffix, run, security.ARCHIVE_LIMIT)
    promoted_name = profile + '-promoted.json'
    record = download(promotion, lambda stream: documents(stream, (promoted_name,)))[promoted_name]
    source, image = record.get('sourceRevision', record.get('revision')), record.get('image')
    tags = publication.upstream.PROFILES[profile][1]
    if (record.get('profile') != profile or record.get('buildIdentity') != identity
            or record.get('revision') != run['head_sha'] or record.get('tags') != tags
            or record.get('publish') is not True or record.get('accepted') is not True
            or record.get('qualificationMode') != 'enforce' or not isinstance(image, str)
            or not re.fullmatch(r'ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}', image)):
        raise ValueError('Promotion differs from recovery profile/build')
    ancestor(origin['headSha'], source)
    ancestor(source, run['head_sha'])
    ancestor(run['head_sha'], os.environ.get('GITHUB_SHA', ''))
    with tempfile.TemporaryDirectory(prefix='completion-') as temporary:
        directory = Path(temporary)
        download(qualified, lambda stream: qualification.extract(stream, qualified, directory, profile))
        acceptance = load_json(directory / (profile + '-acceptance.json'))
        context = acceptance.get('qualificationContext', {})
        if (context.get('inputs') != qualification.qualification.source_inputs(controller.ROOT)
                or acceptance.get('revision') != run['head_sha']):
            raise ValueError('Completion qualification inputs changed')
        qualification.validate(directory, profile, image, record.get('previousDigest'), source, identity, context)
        security_dir = directory / 'security'
        security_dir.mkdir()
        download(scanned, lambda stream: security.extract(stream, scanned, security_dir))
        original_scan, fresh = security.revalidate(security_dir, image, profile, source, identity,
                                      controller.ROOT / 'automation/security/image-policy.json')
        # Revalidate current human coverage explicitly; a stored admission is insufficient.
        from security_admission import verify
        admitted = verify(fresh, profile, REPOSITORY, bot)
        if admitted.get('status') != 'covered' or admitted.get('decision', {}).get('proposalHash') != decision:
            raise ValueError('Completion is not covered by the live recovery decision')
    subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', str(controller.ROOT / 'cosign.pub'), image],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=150)
    for tag in tags:
        if security.inspect_candidate(publication.upstream.REPOSITORY + ':' + tag).get('Digest') != image.split('@')[1]:
            raise ValueError('Completion public aliases are stale or partially promoted')
    # Signature/registry reads may take time; queued revocation or expiration
    # must not become a satisfaction receipt after the earlier admission check.
    security.require_fresh(original_scan, security.security.load_policy(
        controller.ROOT / 'automation/security/image-policy.json'))
    admitted = verify(fresh, profile, REPOSITORY, bot)
    if admitted.get('status') != 'covered' or admitted.get('decision', {}).get('proposalHash') != decision:
        raise ValueError('Completion authority changed before satisfaction')
    current = controller.api(f'repos/{REPOSITORY}/git/ref/heads/main')
    if current.get('object', {}).get('sha') != os.environ.get('GITHUB_SHA'):
        raise ValueError('Main changed before completion was recorded')
    return {'schema': 1, 'repository': REPOSITORY, 'workflow': 'build.yml', 'runId': run['id'],
            'runAttempt': run['run_attempt'], 'revision': run['head_sha'], 'sourceRevision': source,
            'profile': profile, 'buildIdentity': identity, 'currentBuildIdentity': current_identity,
            'currentRevision': os.environ['GITHUB_SHA'], 'image': image, 'decision': decision,
            'jobs': job_ids, 'artifacts': {kind: {'id': value['id'], 'sha256': value['digest']}
                for kind, value in (('promotion', promotion), ('qualification', qualified), ('security', scanned))},
            'promotionSha256': canonical_hash(record), 'aliases': tags}


def completion(profile, origin, native, decision, bot):
    """A bounded recent window; incomplete proof always retains normal recovery."""
    try:
        current_identity = current_build_identity(profile)
        result = controller.api(f'repos/{REPOSITORY}/actions/workflows/build.yml/runs?branch=main&status=success&per_page=10')
        runs = result.get('workflow_runs')
        if not isinstance(runs, list) or len(runs) > 10:
            return None
        for value in runs:
            try:
                # Reread native state instead of trusting the discovery listing.
                run = controller.api(f'repos/{REPOSITORY}/actions/runs/{value["id"]}')
                return authenticate(profile, origin, native, decision, bot, run, current_identity)
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile):
                continue
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError):
        pass
    return None
