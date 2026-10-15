#!/usr/bin/env python3
"""Recover authenticated prepared assets on hosted runners; never rebuild images."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REPO = 'closure-labs/finite'
REPO_ID = 1293375784
META = 4 * 1024**2
ARCHIVE = 32 * 1024**3
EXPANDED = 64 * 1024**3
PREP_STEPS = ('Validate release request', 'Validate and collect qualified evidence',
              'Rescan the qualified immutable image before release', 'Record release artifact identity',
              'Save unsigned release assets', 'Save security evidence even when the release is blocked')
POLICY_INPUTS = ('flake.lock', 'lib/ci-shells.nix', 'lib/ci-tools.nix', 'lib/mk-pkgs.nix', 'lib/project-policy.nix',
                 'automation/security/image-policy.json', 'scripts/bluebuild/security-run.sh',
                 'scripts/bluebuild/security-scan.py', 'scripts/bluebuild/security-policy.py')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


EVIDENCE = module('recovery_evidence', ROOT / 'scripts/bluebuild/release-evidence.py')
REQUEST = module('recovery_request', ROOT / 'scripts/ci/release-request.py')
CONTEXT = module('recovery_context', ROOT / 'scripts/bluebuild/qualification-context.py')
POLICY = module('recovery_policy', ROOT / 'scripts/bluebuild/security-policy.py')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)


def read(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= META:
        raise ValueError('Missing, linked or oversized JSON receipt')
    return decode(path.read_bytes())


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def valid(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def positive(value):
    return type(value) is int and value > 0


def timestamp(value):
    if not valid(value, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'):
        raise ValueError('Missing canonical GitHub timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def fresh(value, now):
    if not 0 <= (now - timestamp(value)).total_seconds() <= 86400:
        raise ValueError('Prepared release or security scan is outside 24 hours')


def github(path, *, pages=False, budget=None):
    patterns = (r'actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*/jobs\?per_page=100|/artifacts\?per_page=100)?',
                r'compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}',
                r'contents/[A-Za-z0-9/._-]+\?ref=[0-9a-f]{40}',
                r'git/matching-refs/tags/finite-[a-z0-9.-]+',
                r'releases\?per_page=100&page=(?:[1-9]|10)')
    if not any(re.fullmatch(pattern, path) for pattern in patterns): raise ValueError('Unapproved read endpoint')
    with tempfile.TemporaryFile() as stream:
        result = subprocess.run(['gh', 'api', *(['--paginate', '--slurp'] if pages else []), 'repos/' + REPO + '/' + path],
            stdout=stream, stderr=subprocess.DEVNULL, check=False, timeout=180,
            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (META, META)))
        if not 0 < stream.tell() <= META: raise ValueError('Oversized or missing GitHub metadata')
        if budget is not None:
            budget['remaining'] -= stream.tell()
            if budget['remaining'] < 0: raise ValueError('Release listing exceeded total metadata budget')
        stream.seek(0); value = decode(stream.read(META + 1))
        if result.returncode: raise ValueError('Read-only GitHub metadata request failed')
        return value


def flatten(pages, key):
    if not isinstance(pages, list) or not 0 < len(pages) <= 10: raise ValueError('Invalid metadata pagination')
    result = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get(key), list) or len(page[key]) > 100:
            raise ValueError('Invalid metadata page')
        result += page[key]
    return result


def run_identity(run, number, workflow):
    if (not positive(number) or type(run.get('id')) is not int or run['id'] != number
            or not positive(run.get('run_attempt')) or run.get('head_branch') != 'main'
            or not valid(run.get('head_sha'), r'[0-9a-f]{40}')
            or run.get('path') != '.github/workflows/' + workflow
            or any(run.get(key, {}).get('full_name') != REPO or run[key].get('id') != REPO_ID
                   for key in ('repository', 'head_repository'))):
        raise ValueError('Producer run is not the exact same-repository main workflow')


def preparation(run, jobs, now):
    run_identity(run, run['id'], 'release.yml')
    if (run.get('event') != 'workflow_dispatch' or run.get('status') not in ('in_progress', 'waiting', 'completed')
            or (run['status'] == 'completed' and run.get('conclusion') not in ('failure', 'cancelled'))):
        raise ValueError('Recovery requires a prepared release awaiting or unsuccessful only in signing')
    fresh(run.get('created_at'), now)
    selected = [job for job in jobs if job.get('name') == 'release']
    if len(selected) != 1: raise ValueError('Ambiguous preparation job')
    prep = selected[0]
    for job in jobs:
        if (job.get('name') not in ('release', 'sign-release') or job.get('run_id') != run['id']
                or job.get('run_attempt') != run['run_attempt'] or job.get('head_sha') != run['head_sha']):
            raise ValueError('Unexpected or mismatched original workflow job')
    signers = [job for job in jobs if job.get('name') == 'sign-release']
    if len(signers) > 1: raise ValueError('Ambiguous original signer')
    if run.get('conclusion') == 'failure':
        if len(signers) != 1 or signers[0].get('conclusion') != 'failure':
            raise ValueError('Original failure was not isolated to the signer')
        failed = [step for step in signers[0].get('steps', []) if step.get('conclusion') == 'failure']
        if len(failed) != 1 or failed[0].get('name') != 'Create draft release with durable evidence':
            raise ValueError('Recovery only repairs the original draft-publication failure')
    if run.get('conclusion') == 'cancelled' and any(job.get('conclusion') not in ('success', 'cancelled', 'skipped') for job in jobs):
        raise ValueError('Cancelled original contains another failed job')
    if not positive(prep.get('id')) or prep.get('status') != 'completed' or prep.get('conclusion') != 'success':
        raise ValueError('Original preparation did not complete successfully')
    steps = []
    for name in PREP_STEPS:
        matches = [step for step in prep.get('steps', []) if step.get('name') == name]
        if len(matches) != 1 or matches[0].get('status') != 'completed' or matches[0].get('conclusion') != 'success':
            raise ValueError('Missing or failed original preparation step: ' + name)
        steps.append(matches[0])
    scan = next(step for step in steps if step['name'].startswith('Rescan '))
    fresh(scan.get('completed_at'), now)
    if timestamp(scan['completed_at']) > timestamp(prep.get('completed_at')): raise ValueError('Invalid scan/job sequencing')
    return prep, scan


def artifact(entries, name, run, now):
    selected = [entry for entry in entries if entry.get('name') == name]
    if len(selected) != 1: raise ValueError('Missing or ambiguous exact-attempt artifact')
    value = selected[0]; origin = value.get('workflow_run', {})
    if (not positive(value.get('id')) or value.get('expired') is not False
            or type(value.get('size_in_bytes')) is not int or not 0 < value['size_in_bytes'] <= ARCHIVE
            or not valid(value.get('digest'), r'sha256:[0-9a-f]{64}')
            or origin.get('id') != run['id'] or origin.get('head_sha') != run['head_sha']
            or origin.get('head_branch') != 'main'
            or origin.get('repository_id') != REPO_ID or origin.get('head_repository_id') != REPO_ID
            or timestamp(value.get('expires_at')) <= now):
        raise ValueError('Artifact lacks immutable bounded trusted producer binding')
    return value


def extract_archive(archive, destination, profile, *, recovery=False):
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError('Refuse linked extraction destination')
    destination.mkdir(parents=True, exist_ok=False)
    required = {'installation.json', 'signature.json', 'SHA256SUMS', 'provenance.json', 'acceptance.json',
                'publication.json', 'security-result.json', 'sbom.syft.json', 'vulnerabilities.json',
                profile + '-desktop-acceptance.json', profile + '.iso'}
    if recovery: required.add('release-recovery.json')
    bound_directory(archive)
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist(); names = [item.filename for item in entries]
        if (not 0 < len(entries) <= 256 or len(names) != len(set(names)) or not required.issubset(names)
                or sum(item.file_size for item in entries) > EXPANDED
                or [name for name in names if name.endswith('.iso')] != [profile + '.iso']):
            raise ValueError('Unexpected, duplicate, missing or oversized release archive contents')
        if shutil.disk_usage(destination).free < sum(item.file_size for item in entries) + 1024**3:
            raise ValueError('Insufficient free disk for declared extraction bytes and 1-GiB reserve')
        for item in entries:
            name = item.filename
            if (not valid(name, r'[A-Za-z0-9][A-Za-z0-9._+-]{0,199}')
                    or not (name in required or name.endswith(('.json', '.Containerfile')))
                    or name in ('SHA256SUMS.bundle.json', 'release-recovery-signing.json')
                    or (name == 'release-recovery.json' and not recovery)
                    or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG) or item.flag_bits & 1
                    or not 0 < item.file_size <= (ARCHIVE if name.endswith('.iso') else 512 * 1024**2)):
                raise ValueError('Unsafe release archive filename/type/size')
            remaining = item.file_size
            with zipped.open(item) as source, (destination / name).open('xb') as output:
                while chunk := source.read(min(1024**2, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0: raise ValueError('Archive expansion exceeded declared size')
                    output.write(chunk)
            if remaining: raise ValueError('Truncated release archive member')


def bound_directory(stream):
    # ZipFile allocates its central directory before infolist(). Bound that
    # allocation first, including ZIP64 archives produced for large ISO files.
    stream.seek(0, 2); length = stream.tell()
    stream.seek(max(0, length - 65557)); tail = stream.read(65557)
    index = tail.rfind(b'PK\x05\x06')
    if index < 0 or len(tail) - index < 22: raise ValueError('Missing ZIP end record')
    end = struct.unpack('<4s4H2LH', tail[index:index + 22])
    end_offset = length - len(tail) + index
    if index + 22 + end[-1] != len(tail) or end[1] or end[2]: raise ValueError('Unsupported ZIP comment/disks')
    entries, directory_size, directory_offset = end[4], end[5], end[6]
    boundary = end_offset
    if end_offset >= 20:
        stream.seek(end_offset - 20); locator = stream.read(20)
        if locator[:4] == b'PK\x06\x07':
            _, disk, offset, disks = struct.unpack('<4sLQL', locator)
            if disk or disks != 1 or not 0 <= offset <= end_offset - 76: raise ValueError('Invalid ZIP64 locator')
            stream.seek(offset); raw = stream.read(56)
            if len(raw) != 56: raise ValueError('Truncated ZIP64 directory')
            record = struct.unpack('<4sQ2H2L4Q', raw)
            if (record[0] != b'PK\x06\x06' or not 44 <= record[1] <= 4096
                    or offset + 12 + record[1] != end_offset - 20 or record[4] or record[5]
                    or record[6] != record[7]):
                raise ValueError('Invalid ZIP64 end record')
            entries, directory_size, directory_offset = record[7:10]
            boundary = offset
        elif end[3] != end[4]: raise ValueError('Split ZIP directory')
    if (not 0 < entries <= 256 or not 0 < directory_size <= 1024**2
            or directory_offset + directory_size > boundary):
        raise ValueError('ZIP central directory exceeds metadata/count bounds')
    stream.seek(0)


def download(value, destination, profile, *, recovery=False):
    with tempfile.TemporaryFile() as stream:
        subprocess.run(['gh', 'api', f'repos/{REPO}/actions/artifacts/{value["id"]}/zip'], stdout=stream,
            check=True, timeout=1800, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (ARCHIVE, ARCHIVE)))
        if stream.tell() != value['size_in_bytes']: raise ValueError('Archive byte size mismatch')
        stream.seek(0)
        if 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() != value['digest']:
            raise ValueError('Archive digest mismatch')
        stream.seek(0); extract_archive(stream, destination, profile, recovery=recovery)


def source_file(path, revision):
    value = github('contents/' + path + '?ref=' + revision)
    if (value.get('type') != 'file' or value.get('path') != path or value.get('encoding') != 'base64'
            or type(value.get('size')) is not int or not 0 < value['size'] <= META):
        raise ValueError('Original source input is not a bounded regular file')
    raw = base64.b64decode(''.join(value['content'].split()), validate=True)
    if len(raw) != value['size'] or hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != value.get('sha'):
        raise ValueError('Original source blob identity mismatch')
    return raw


def packet(directory, channel, source, original_run, *, inputs=None):
    profile = EVIDENCE.PROFILES[channel]
    installation, acceptance, publication, provenance, security = [read(directory / name) for name in
        ('installation.json', 'acceptance.json', 'publication.json', 'provenance.json', 'security-result.json')]
    image = EVIDENCE.validate_evidence(installation, acceptance, publication, channel, source, exact_iso=True)
    context = acceptance.get('qualificationContext', {})
    if (acceptance.get('schema') != 2 or acceptance.get('bootstrap') is not False
            or acceptance.get('validationOnly', False) is not False or acceptance.get('qualificationReuse')
            or acceptance.get('sourceRevision') != source or publication.get('sourceRevision') != source
            or context.get('schema') != 2 or context.get('platform') != 'linux/amd64'
            or context.get('inputs') != (CONTEXT.source_inputs() if inputs is None else inputs)
            or acceptance.get('qualificationContextSha256') != CONTEXT.identity(context)
            or provenance.get('schema') != 1 or provenance.get('revision') != source
            or provenance.get('sourceRevision') != source or provenance.get('image') != image
            or provenance.get('buildIdentity') != acceptance.get('buildIdentity')
            or provenance.get('qualification') != acceptance or provenance.get('installer') != installation['installer']
            or provenance.get('isoMatchesQualification') is not True
            or not valid(acceptance.get('buildIdentity'), r'v1:[0-9a-f]{64}')
            or not valid(acceptance.get('previousDigest'), r'sha256:[0-9a-f]{64}')
            or security.get('status') != 'pass' or security.get('image') != image
            or security.get('policySha256') != sha(ROOT / 'automation/security/image-policy.json')):
        raise ValueError('Prepared packet changed qualified source/context or lacks passing exact-image security')
    policy = POLICY.load_policy(ROOT / 'automation/security/image-policy.json')
    now = datetime.now(timezone.utc)
    POLICY.fresh(security['scannedAt'], min(24, policy['maxEvidenceAgeHours']), now, 'Recovered scan')
    database = security.get('database', {})
    if database.get('status', {}).get('valid') is not True or security.get('blocked') or security.get('releaseBlockers'):
        raise ValueError('Recovered security result has invalid database or release blockers')
    POLICY.fresh(database['status']['built'], policy['maxDatabaseAgeHours'], now, 'Recovered database')
    for provider in policy['requiredProviders']:
        POLICY.fresh(database['providers'][provider]['captured'], policy['maxDatabaseAgeHours'], now, 'Recovered ' + provider)
    build_url = provenance.get('buildRun', '')
    if not valid(build_url, r'https://github.com/closure-labs/finite/actions/runs/[1-9][0-9]*') or provenance.get('isoRun') != build_url:
        raise ValueError('Recovery requires the original preserved main-build ISO')
    build_number = int(build_url.rsplit('/', 1)[1])
    build = github('actions/runs/' + str(build_number)); run_identity(build, build_number, 'build.yml')
    if (build.get('status') != 'completed' or build.get('conclusion') != 'success' or build['head_sha'] != source
            or acceptance.get('qualifiedIsoOrigin') != {'run': build_number, 'attempt': build['run_attempt'], 'revision': source}):
        raise ValueError('Qualified original build/ISO producer did not succeed at exact source')
    iso = acceptance['qualifiedIso']
    if (iso.get('name') != profile + '.iso' or installation['installer'].get('finiteRevision') != source
            or sha(directory / iso['name']) != iso.get('sha256')
            or sha(directory / 'installation.json') != iso.get('installationSha256')):
        raise ValueError('Recovered pristine ISO or installation bytes differ from qualification')
    EVIDENCE.desktop.verify(directory, acceptance)
    policy_hashes = {}
    if source_file('VERSION', source).strip() != (ROOT / 'VERSION').read_bytes().strip():
        raise ValueError('Qualified source VERSION differs from current release version')
    for path in POLICY_INPUTS:
        raw = source_file(path, source)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != sha(ROOT / path): raise ValueError('Release policy/tool inputs drifted: ' + path)
        policy_hashes[path] = digest
    return {'candidate': image, 'profile': profile, 'sourceRevision': source, 'buildRun': build_number,
            'buildAttempt': build['run_attempt'], 'preparedRun': original_run,
            'buildIdentity': acceptance['buildIdentity'], 'qualificationContextSha256': acceptance['qualificationContextSha256'],
            'policyInputSha256': policy_hashes, 'qualifiedIso': iso, 'securityResult': security,
            'receiptSha256': {name: sha(directory / name) for name in ('provenance.json', 'acceptance.json',
                'publication.json', 'installation.json', profile + '-desktop-acceptance.json', 'security-result.json')}}


def unused_tag(tag):
    refs = github('git/matching-refs/tags/' + tag)
    if not isinstance(refs, list) or any(ref.get('ref') == 'refs/tags/' + tag for ref in refs):
        raise ValueError('Release requires a new unused exact tag')
    # The read token may see only published releases. The final publisher uses
    # its push-capable token for the authoritative draft-visible list check.
    budget = {'remaining': META}
    for page in range(1, 11):
        releases = github(f'releases?per_page=100&page={page}', budget=budget)
        if not isinstance(releases, list) or len(releases) > 100 or any(not isinstance(item, dict)
                or not isinstance(item.get('tag_name'), str) for item in releases):
            raise ValueError('Invalid bounded release listing')
        if any(item['tag_name'] == tag for item in releases):
            raise ValueError('An existing draft or published release already claims this tag')
        if len(releases) < 100: return
    raise ValueError('Release pagination budget exhausted before proving absence')


def hosted():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or not valid(os.environ.get('GITHUB_SHA'), r'[0-9a-f]{40}')):
        raise ValueError('Recovery executes only from reviewed same-repository manual main')


def prepare(args):
    hosted()
    if args.tag != REQUEST.canonical_tag(args.channel, (ROOT / 'VERSION').read_text().strip()):
        raise ValueError('Recovery requires the canonical current channel tag')
    unused_tag(args.tag)
    now = datetime.now(timezone.utc)
    run = github('actions/runs/' + str(args.prepared_run))
    run_identity(run, args.prepared_run, 'release.yml')
    jobs = flatten(github(f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', pages=True), 'jobs')
    prep, scan = preparation(run, jobs, now)
    compare = github('compare/' + run['head_sha'] + '...' + os.environ['GITHUB_SHA'])
    if compare.get('status') not in ('ahead', 'identical') or compare.get('merge_base_commit', {}).get('sha') != run['head_sha']:
        raise ValueError('Original qualified source is not an ancestor of recovery main')
    entries = flatten(github(f'actions/runs/{run["id"]}/artifacts?per_page=100', pages=True), 'artifacts')
    value = artifact(entries, f'unsigned-release-{run["id"]}-{run["run_attempt"]}', run, now)
    download(value, args.output, EVIDENCE.PROFILES[args.channel])
    receipt = packet(args.output, args.channel, run['head_sha'], run['id'])
    receipt.update(schema=1, channel=args.channel, tag=args.tag, preparedAttempt=run['run_attempt'],
        preparationJob=prep['id'], securityScanCompletedAt=scan['completed_at'],
        originalUnsignedArtifact={key: value[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run')},
        recoveryRun=int(os.environ['GITHUB_RUN_ID']), recoveryAttempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
        recoveryExecutionRevision=os.environ['GITHUB_SHA'])
    (args.output / 'release-recovery.json').write_text(json.dumps(receipt, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('source=' + run['head_sha'], file=output)


def signer(args):
    hosted()
    now = datetime.now(timezone.utc)
    run = github('actions/runs/' + os.environ['GITHUB_RUN_ID'])
    run_identity(run, int(os.environ['GITHUB_RUN_ID']), 'release-recovery.yml')
    if run.get('event') != 'workflow_dispatch' or run['head_sha'] != os.environ['GITHUB_SHA'] or run['run_attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('Signer current recovery run binding mismatch')
    entries = flatten(github(f'actions/runs/{run["id"]}/artifacts?per_page=100', pages=True), 'artifacts')
    value = artifact(entries, f'verified-unsigned-release-{run["id"]}-{run["run_attempt"]}', run, now)
    if (value['id'] != args.artifact_id or value['digest'] != args.artifact_digest
            or value['size_in_bytes'] != args.artifact_size):
        raise ValueError('Verified reupload differs from exact preparation upload outputs')
    download(value, args.output, EVIDENCE.PROFILES[args.channel], recovery=True)
    receipt = read(args.output / 'release-recovery.json')
    if (receipt.get('recoveryRun') != int(os.environ['GITHUB_RUN_ID'])
            or receipt.get('recoveryAttempt') != int(os.environ['GITHUB_RUN_ATTEMPT'])
            or receipt.get('recoveryExecutionRevision') != os.environ['GITHUB_SHA']
            or receipt.get('channel') != args.channel or receipt.get('tag') != args.tag
            or args.tag != REQUEST.canonical_tag(args.channel, (ROOT / 'VERSION').read_text().strip())):
        raise ValueError('Signer received another recovery execution/channel/tag')
    fresh(receipt.get('securityScanCompletedAt'), datetime.now(timezone.utc))
    actual = packet(args.output, args.channel, receipt['sourceRevision'], receipt['preparedRun'])
    if any(receipt.get(key) != value for key, value in actual.items()): raise ValueError('Verified recovery packet changed before signing')
    unused_tag(args.tag)
    (args.output / 'release-recovery-signing.json').write_text(json.dumps({'schema': 1,
        'verifiedUnsignedArtifact': {key: value[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run')},
        'recoveryExecutionRevision': os.environ['GITHUB_SHA'], 'sourceRevision': receipt['sourceRevision'],
        'recoveryRun': run['id'], 'recoveryAttempt': run['run_attempt'],
        'originalRecoveryReceiptSha256': sha(args.output / 'release-recovery.json')}, indent=2) + '\n')


def bind_upload(args):
    hosted()
    run = github('actions/runs/' + os.environ['GITHUB_RUN_ID'])
    run_identity(run, int(os.environ['GITHUB_RUN_ID']), 'release-recovery.yml')
    if run['head_sha'] != os.environ['GITHUB_SHA'] or run['run_attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('Upload current-run identity mismatch')
    entries = flatten(github(f'actions/runs/{run["id"]}/artifacts?per_page=100', pages=True), 'artifacts')
    value = artifact(entries, f'verified-unsigned-release-{run["id"]}-{run["run_attempt"]}', run, datetime.now(timezone.utc))
    expected_digest = args.artifact_digest if args.artifact_digest.startswith('sha256:') else 'sha256:' + args.artifact_digest
    if value['id'] != args.artifact_id or value['digest'] != expected_digest:
        raise ValueError('Current-run artifact differs from exact upload action outputs')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for name, key in (('artifact_id', 'id'), ('artifact_size', 'size_in_bytes'), ('artifact_digest', 'digest')):
            print(name + '=' + str(value[key]), file=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'bind-upload', 'verify-signer'))
    parser.add_argument('--channel', choices=EVIDENCE.PROFILES, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--prepared-run', type=int)
    parser.add_argument('--artifact-id', type=int)
    parser.add_argument('--artifact-size', type=int)
    parser.add_argument('--artifact-digest')
    parser.add_argument('--output', type=Path, default=Path('.bluebuild/release'))
    args = parser.parse_args()
    if args.operation == 'prepare':
        if not positive(args.prepared_run): parser.error('A positive prepared run is required')
        prepare(args)
    elif args.operation == 'bind-upload': bind_upload(args)
    else: signer(args)


if __name__ == '__main__': main()
