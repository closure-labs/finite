#!/usr/bin/env python3
"""Reuse authenticated hosted native bytes, reevaluating current policy and freshness."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import stat
import sys
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('reuse_publication', ROOT / 'scripts/bluebuild/publication.py')
publication = importlib.util.module_from_spec(SPEC)
# Match publication.py CLI loading: do not create a helper-only publication.pyc
# that the conservative build-input identity would treat as a new input.
exec(compile(Path(SPEC.origin).read_bytes(), SPEC.origin, 'exec'), publication.__dict__)
security = publication.security
MIB = 1024 * 1024
ARCHIVE_LIMIT = 512 * MIB
TOTAL_LIMIT = 768 * MIB
LIMITS = {name: 16 * MIB for name in (
    'image-manifest.json', 'platform-manifest.json', 'image-config.json', 'extraction.json',
    'extraction-manifest.json', 'extraction-layout.json', 'approved-baseline.json',
    'upstream-verification.json', 'database-coverage.json', 'coverage.json', 'security-result.json',
    'runner-resources.log', 'applicability-evidence.json', 'inventory-provenance.json',
    'inventory-origin.json', 'phase-timings.json')}
LIMITS.update({'sbom.syft.json': 256 * MIB, 'sbom.spdx.json': 256 * MIB,
               'vulnerabilities.json': 128 * MIB, 'rpm-file-evidence.json': 128 * MIB})
REQUIRED = {'sbom.syft.json', 'vulnerabilities.json', 'database-coverage.json', 'image-manifest.json',
            'image-config.json', 'extraction.json', 'approved-baseline.json', 'upstream-verification.json',
            'security-result.json'}


class Unavailable(ValueError):
    """No reusable artifact; a caller may run a fresh scan instead."""


def metadata(run, jobs, artifacts, profile, run_id):
    image_artifact, build_job = publication.origin_metadata(run, jobs, artifacts, profile, run_id)
    matches = [job for job in jobs if job.get('name') == f'Publish ({profile}) / security']
    if len(matches) != 1:
        raise ValueError('Reuse requires one exact original security job')
    job = matches[0]
    if (job.get('status') != 'completed' or job.get('conclusion') != 'success'
            or job.get('run_id') != run['id'] or job.get('run_attempt') != run['run_attempt']
            or job.get('head_sha') != run['head_sha'] or type(job.get('id')) is not int):
        raise ValueError('Original security job did not succeed at the exact source and attempt')
    name = f'security-{profile}-{run_id}-{run["run_attempt"]}'
    found = [entry for entry in artifacts if entry.get('name') == name]
    if not found:
        raise Unavailable('Original security artifact is unavailable')
    if len(found) != 1:
        raise ValueError('Original security artifact name is ambiguous')
    artifact = found[0]
    if artifact.get('expired') is True:
        raise Unavailable('Original security artifact has expired')
    binding = artifact.get('workflow_run', {})
    if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
            or not isinstance(artifact.get('digest'), str) or not publication.DIGEST.fullmatch(artifact['digest'])
            or type(artifact.get('size_in_bytes')) is not int or not 0 < artifact['size_in_bytes'] <= ARCHIVE_LIMIT
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha']):
        raise ValueError('Original security artifact lacks exact immutable run/archive binding')
    return artifact, image_artifact, build_job, job['id']


def extract(archive, artifact, directory):
    archive.seek(0, 2)
    if archive.tell() != artifact['size_in_bytes'] or not 0 < archive.tell() <= ARCHIVE_LIMIT:
        raise ValueError('Security archive size differs from GitHub metadata or exceeds bound')
    archive.seek(0)
    if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != artifact['digest']:
        raise ValueError('Security archive SHA256 differs from GitHub metadata')
    archive.seek(0)
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [entry.filename for entry in entries]
        if (len(names) != len(set(names)) or not REQUIRED.issubset(names) or len(names) > len(LIMITS)
                or sum(entry.file_size for entry in entries) > TOTAL_LIMIT):
            raise ValueError('Security archive has duplicate/missing/oversized native evidence')
        for entry in entries:
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (entry.filename not in LIMITS or entry.is_dir() or kind not in (0, stat.S_IFREG)
                    or entry.flag_bits & 1 or not 0 < entry.file_size <= LIMITS[entry.filename]):
                raise ValueError('Security archive contains unexpected paths, links or oversized evidence')
        for entry in entries:
            # Never extract archive paths. Every permitted name is a single fixed basename.
            remaining = entry.file_size
            with zipped.open(entry) as source, (directory / entry.filename).open('xb') as output:
                while chunk := source.read(min(MIB, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError('Security archive expanded beyond declared file size')
                    output.write(chunk)
            if remaining:
                raise ValueError('Security archive file size mismatch')


def read_json(path):
    if path.stat().st_size > 16 * MIB:
        raise ValueError('Security metadata exceeds its bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate security metadata key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def require_fresh(original, policy, now=None):
    now = now or datetime.now(timezone.utc)
    database = original['database']
    if database['status']['valid'] is not True:
        raise ValueError('Original scanner database is invalid')
    checks = [(original['scannedAt'], policy['maxEvidenceAgeHours'], 'scan'),
              (database['status']['built'], policy['maxDatabaseAgeHours'], 'database')]
    checks.extend((database['providers'][provider]['captured'], policy['maxDatabaseAgeHours'], provider)
                  for provider in policy['requiredProviders'])
    stale = []
    for value, hours, label in checks:
        if not isinstance(value, str):
            raise ValueError('Malformed original evidence timestamp')
        age = now - security.timestamp(value)
        if age < timedelta(0):
            raise ValueError('Original evidence timestamp is from the future')
        if age > timedelta(hours=hours):
            stale.append(label)
    # Inspect every timestamp before classifying expiration, so a stale scan
    # never masks a malformed/future provider timestamp.
    if stale:
        raise Unavailable('Original native freshness expired: ' + ', '.join(stale))


def revalidate(directory, image, profile, source, identity, policy_path):
    original = read_json(directory / 'security-result.json')
    if (original.get('schema') != 1 or type(original['schema']) is not int
            or original.get('status') != 'pass' or original.get('image') != image):
        raise ValueError('Original native result is not a passing exact candidate scan')
    baseline = read_json(directory / 'approved-baseline.json')
    if (baseline.get('image') != image or baseline.get('profile') != profile
            or baseline.get('sourceRevision') != source or baseline.get('buildIdentity') != identity):
        raise ValueError('Original native baseline differs from candidate profile/source/current identity')
    require_fresh(original, security.load_policy(policy_path))
    # This authenticates current publisher context, raw manifests and SBOM hash,
    # rechecks DB/scan freshness and reevaluates ALL findings under current policy.
    result = security.verify(directory, image, policy_path)
    if (result.get('status') != 'pass' or result.get('image') != image
            or result.get('scannedAt') != original.get('scannedAt')):
        raise ValueError('Current native verification did not pass for this immutable candidate')
    result['policySha256'] = security.file_sha256(policy_path)
    return original, result


def inspect_candidate(image):
    """Give only the registry read an explicit, private, short-lived auth file."""
    actor, token = os.environ.get('GITHUB_ACTOR', ''), os.environ.get('GH_TOKEN', '')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*(?:\[bot\])?', actor)
            or not token or len(token) > 65536 or any(character.isspace() for character in token)):
        raise ValueError('Candidate registry inspection requires the workflow actor and token')
    # Skopeo inspect documents REGISTRY_AUTH_FILE as its primary authfile override.
    # No runtime-dir fallback, credentials in argv, or evidence-directory storage.
    previous = os.environ.get('REGISTRY_AUTH_FILE')
    with tempfile.TemporaryDirectory(prefix='finite-registry-auth-') as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        path = directory / 'auth.json'
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            credential = base64.b64encode((actor + ':' + token).encode()).decode('ascii')
            json.dump({'auths': {'ghcr.io': {'auth': credential}}}, stream)
        try:
            os.environ['REGISTRY_AUTH_FILE'] = str(path)
            try:
                return publication.upstream.inspect(image)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
                # Remote error bodies are not trusted to omit credential data.
                raise ValueError('Authenticated candidate registry inspection failed') from None
        finally:
            if previous is None:
                os.environ.pop('REGISTRY_AUTH_FILE', None)
            else:
                os.environ['REGISTRY_AUTH_FILE'] = previous


def hosted():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != publication.REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_WORKFLOW_REF') != publication.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main'
            or not publication.SHA.fullmatch(os.environ.get('GITHUB_SHA', ''))):
        raise ValueError('Security reuse requires the hosted main manual Build Finite workflow')


def reuse(run_id, profile, digest, output):
    hosted()  # Before filesystem writes, API access or parsing native inventories.
    if (not re.fullmatch(r'[1-9][0-9]*', run_id) or profile not in security.PROFILES
            or not publication.DIGEST.fullmatch(digest)):
        raise ValueError('Reuse requires an exact origin run, supported profile and immutable digest')
    output = output.absolute()
    if output.exists() or output.is_symlink() or any(path.is_symlink() for path in output.parents):
        raise ValueError('Reuse output must be new and have no symlinked parents')
    run = publication.github('actions/runs/' + run_id)
    attempt = run.get('run_attempt')
    if type(attempt) is not int or attempt < 1:
        raise ValueError('Invalid original attempt')
    jobs = [item for page in publication.github(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100', True)
            for item in page['jobs']]
    artifacts = [item for page in publication.github(f'actions/runs/{run_id}/artifacts?per_page=100', True)
                 for item in page['artifacts']]
    artifact, image_artifact, build_job, security_job = metadata(run, jobs, artifacts, profile, run_id)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=30).strip()
    if head != os.environ['GITHUB_SHA']:
        raise ValueError('Reuse checkout differs from current workflow source')
    subprocess.run(['git', 'merge-base', '--is-ancestor', run['head_sha'], head], cwd=ROOT, check=True, timeout=30)
    recipe = publication.upstream.recipes(ROOT)[profile]
    identity = publication.upstream.image_identity(profile, ROOT)
    publication.upstream.verify(ROOT)
    files = publication.origin_files(image_artifact, profile)
    image = publication.upstream.REPOSITORY + '@' + digest
    publication.validate_candidate(profile, digest, run['head_sha'],
        json.loads(files[f'{profile}-publication.json']), files[f'{profile}-image-ref.txt'].decode(),
        inspect_candidate(image), recipe, identity)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.security-reuse-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'evidence'
        staging.mkdir()
        with tempfile.TemporaryFile() as archive:
            subprocess.run(['gh', 'api', f'repos/{publication.REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                stdout=archive, check=True, timeout=180,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (ARCHIVE_LIMIT, ARCHIVE_LIMIT)))
            extract(archive, artifact, staging)
        original, result = revalidate(staging, image, profile, run['head_sha'], identity,
                                      ROOT / 'automation/security/image-policy.json')
        # Keep original authenticated bytes and their hash alongside reevaluation.
        original_hash = security.file_sha256(staging / 'security-result.json')
        (staging / 'security-result.json').rename(staging / 'original-security-result.json')
        (staging / 'security-result.json').write_text(json.dumps(result, indent=2) + '\n')
        provenance = {'schema': 1, 'status': 'revalidated-native-evidence', 'image': image, 'profile': profile,
            'originRun': run['id'], 'originAttempt': attempt, 'originBuildJob': build_job, 'originSecurityJob': security_job,
            'artifactId': artifact['id'], 'artifactSha256': artifact['digest'], 'sourceRevision': run['head_sha'],
            'validationRevision': head, 'originalResultSha256': original_hash,
            'originalPolicySha256': original.get('policySha256'), 'currentPolicySha256': result['policySha256'],
            'originalScannedAt': original.get('scannedAt'), 'scannedAt': result['scannedAt'],
            'revalidatedAt': datetime.now(timezone.utc).isoformat(), 'newScanPerformed': False,
            'releaseEligibilityEstablished': False}
        (staging / 'reuse-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        staging.rename(output)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin-run', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--digest', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(reuse(args.origin_run, args.profile, args.digest, args.output)))
        return 0
    except Unavailable as error:
        print(str(error), file=sys.stderr)
        return 3
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Security reuse rejected: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
