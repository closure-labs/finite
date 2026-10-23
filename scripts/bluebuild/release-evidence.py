#!/usr/bin/env python3
"""Assemble release evidence only from matching successful main-branch runs."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import shutil
import subprocess
import tempfile
import zipfile
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from github_api import get_json

desktop_spec = importlib.util.spec_from_file_location('desktop_qualification', Path(__file__).with_name('desktop-qualification.py'))
desktop = importlib.util.module_from_spec(desktop_spec)
desktop_spec.loader.exec_module(desktop)
options_spec = importlib.util.spec_from_file_location('release_ci_options', Path(__file__).resolve().parents[1] / 'ci/ci-options.py')
ci_options = importlib.util.module_from_spec(options_spec)
options_spec.loader.exec_module(ci_options)
REPOSITORY = 'closure-labs/finite'
PROFILES = {'finite': 'finite', 'finite-dev': 'finite-dev'}


def github(path):
    return get_json('repos/' + REPOSITORY + '/' + path)


def validate_run(run, workflow, revision):
    if (run['conclusion'] != 'success' or run['head_branch'] != 'main'
            or run['head_sha'] != revision or run['path'] != '.github/workflows/' + workflow
            or run['head_repository']['full_name'] != REPOSITORY):
        raise ValueError('Release evidence must come from successful matching main-branch runs')


def artifact(run_id, name, destination):
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', REPOSITORY,
                    '--name', name, '--dir', str(destination)], check=True, timeout=900)


def latest_artifact(artifacts, prefix):
    matches = [entry['name'] for entry in artifacts if not entry['expired']
               and re.fullmatch(re.escape(prefix) + r'[0-9]+', entry['name'])]
    if not matches:
        raise ValueError('Missing or expired release evidence: ' + prefix)
    return max(matches, key=lambda name: int(name.removeprefix(prefix)))


def artifact_names(run_id):
    pages = json.loads(subprocess.check_output(
        ['gh', 'api', '--paginate', '--slurp', f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100'],
        text=True, timeout=150))
    return [entry for page in pages for entry in page['artifacts']]


def validate_evidence(installation, acceptance, publication, channel, revision, *, exact_iso=False):
    if acceptance.get('validationOnly') is True:
        raise ValueError('Diagnostic qualification cannot authorize a release')
    profile = PROFILES[channel]
    image = installation['image']
    if not re.fullmatch(r'ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}', image):
        raise ValueError('Invalid release image')
    source_revision = publication.get('sourceRevision', revision)
    if (not re.fullmatch(r'[0-9a-f]{40}', source_revision)
            or acceptance.get('sourceRevision', revision) != source_revision):
        raise ValueError('Release evidence has inconsistent image source provenance')
    if not all((installation['profile'] == profile,
                installation['updateChannel'] == 'ghcr.io/closure-labs/finite:' + channel,
                acceptance['candidate'] == image, acceptance['profile'] == profile,
                acceptance['accepted'] is True, acceptance['secureBoot'] is True,
                acceptance.get('encryptedRoot') is True,
                acceptance['revision'] == revision,
                publication['revision'] == revision, publication['profile'] == profile,
                acceptance['buildIdentity'] == publication['buildIdentity'],
                acceptance['previousDigest'] == publication['previousDigest'],
                installation['installer']['finiteRevision'] == (acceptance['qualifiedIso']['installer']['finiteRevision'] if exact_iso else revision))):
        raise ValueError('Release evidence does not identify the same qualified candidate')
    if acceptance.get('qualifiedIso') and not exact_iso:
        expected = {key: value for key, value in acceptance['qualifiedIso']['installer'].items()
                    if key not in ('finiteRevision', 'localImageId')}
        actual = {key: value for key, value in installation['installer'].items()
                  if key not in ('finiteRevision', 'localImageId')}
        if actual != expected:
            raise ValueError('Regenerated release ISO changed the qualified installer context')
    if exact_iso and installation['installer'] != acceptance.get('qualifiedIso', {}).get('installer'):
        raise ValueError('Release installer differs from qualified pristine ISO')
    return image


def require_iso_fallback(channel, iso_run, environ=None):
    """Selected pilot channels require preserved bytes; others retain legacy ISO input."""
    if ci_options.iso_preservation_enabled(channel, environ):
        raise ValueError('ISO preservation pilot requires the exact qualified ISO artifact; qualify again if it expired')
    if not iso_run:
        raise ValueError('No preserved qualified ISO; enable preservation for this channel and qualify again, or supply an ISO run')


def qualified_iso_artifact(artifacts, profile, run_id, attempt):
    name = f'finite-qualified-iso-{profile}-{run_id}-{attempt}'
    matches = [entry for entry in artifacts if entry.get('name') == name and entry.get('expired') is False]
    if len(matches) > 1:
        raise ValueError('Qualified ISO artifact is ambiguous')
    return matches[0] if matches else None


def authenticated_iso(entry, run, acceptance, destination, *, download_timeout=1800):
    # Authenticate GitHub archive metadata before extracting only fixed names.
    if type(download_timeout) not in (int, float) or not 0 < download_timeout <= 1800:
        raise ValueError('Qualified ISO transfer requires a bounded positive timeout')
    maximum = 32 * 1024 * 1024 * 1024
    binding = entry.get('workflow_run', {})
    if (type(entry.get('id')) is not int or type(entry.get('size_in_bytes')) is not int
            or not 0 < entry['size_in_bytes'] <= maximum
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry.get('digest', ''))
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha']):
        raise ValueError('Qualified ISO archive lacks immutable trusted producer binding')
    iso = acceptance['qualifiedIso']
    names = {iso['name'], 'installation.json', 'signature.json', 'SHA256SUMS'}
    if not re.fullmatch(r'finite(?:-dev)?\.iso', iso['name']):
        raise ValueError('Invalid qualified ISO filename')
    with tempfile.TemporaryFile() as archive:
        try:
            subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{entry["id"]}/zip'],
                stdout=archive, check=True, timeout=download_timeout,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum)))
        except subprocess.TimeoutExpired:
            print(f'Qualified ISO artifact {entry["id"]} transfer timed out after {download_timeout}s: '
                  f'{os.fstat(archive.fileno()).st_size}/{entry["size_in_bytes"]} bytes received; '
                  'no archive members extracted', file=sys.stderr)
            raise
        archive.seek(0, 2)
        if archive.tell() != entry['size_in_bytes']:
            raise ValueError('Qualified ISO archive size differs from GitHub metadata')
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != entry['digest']:
            raise ValueError('Qualified ISO archive digest mismatch')
        archive.seek(0)
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if (len(entries) != len(names) or set(item.filename for item in entries) != names
                    or sum(item.file_size for item in entries) > maximum):
                raise ValueError('Qualified ISO archive has unexpected/duplicate/oversized contents')
            for item in entries:
                limit = maximum if item.filename == iso['name'] else 4 * 1024 * 1024
                if (stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG)
                        or item.flag_bits & 1 or not 0 < item.file_size <= limit):
                    raise ValueError('Qualified ISO archive has a link or invalid file size')
                remaining = item.file_size
                with zipped.open(item) as source, (destination / item.filename).open('xb') as output:
                    while chunk := source.read(min(1024 * 1024, remaining + 1)):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ValueError('Qualified ISO archive expanded past its declared size')
                        output.write(chunk)
                if remaining:
                    raise ValueError('Qualified ISO archive file size mismatch')
    if (qualification_sha(destination / iso['name']) != iso['sha256']
            or qualification_sha(destination / 'installation.json') != iso['installationSha256']):
        raise ValueError('Release ISO differs from the pristine bytes that passed VM qualification')


def qualification_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('channel', choices=PROFILES)
    parser.add_argument('iso_run')
    parser.add_argument('build_run')
    args = parser.parse_args()
    for run_id in (args.iso_run, args.build_run):
        if run_id and not run_id.isdecimal():
            raise ValueError('Invalid run ID')
    revision = os.environ['GITHUB_SHA']
    build_run = github('actions/runs/' + args.build_run)
    validate_run(build_run, 'build.yml', revision)
    profile = PROFILES[args.channel]
    build_artifacts = artifact_names(args.build_run)
    destination = Path('.bluebuild/release')
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        suffix = f'{profile}-{args.build_run}-'
        artifact(args.build_run, latest_artifact(build_artifacts, 'qualification-' + suffix), temporary / 'qualification')
        artifact(args.build_run, latest_artifact(build_artifacts, 'image-' + suffix), temporary / 'image')
        acceptance_path = temporary / 'qualification' / (profile + '-acceptance.json')
        publication_path = temporary / 'image' / (profile + '-publication.json')
        acceptance = json.loads(acceptance_path.read_text())
        publication = json.loads(publication_path.read_text())
        # Prefer the pristine ISO from the exact successful qualification attempt.
        reuse = acceptance.get('qualificationReuse', {})
        iso_origin = acceptance.get('qualifiedIsoOrigin', reuse)
        origin_id = str(iso_origin.get('run', args.build_run))
        origin_attempt = iso_origin.get('attempt')
        if origin_attempt is None:
            qualification_name = latest_artifact(build_artifacts, 'qualification-' + suffix)
            origin_attempt = int(qualification_name.rsplit('-', 1)[1])
        origin_run = build_run if origin_id == args.build_run else github('actions/runs/' + origin_id)
        origin_revision = iso_origin.get('revision', reuse.get('qualificationRevision', revision))
        validate_run(origin_run, 'build.yml', origin_revision)
        origin_artifacts = build_artifacts if origin_id == args.build_run else artifact_names(origin_id)
        preserved = qualified_iso_artifact(origin_artifacts, profile, origin_id, origin_attempt) if acceptance.get('qualifiedIso') else None
        exact_iso = preserved is not None
        if exact_iso:
            authenticated_iso(preserved, origin_run, acceptance, destination)
            iso_run = origin_run
        else:
            require_iso_fallback(args.channel, args.iso_run)
            iso_run = github('actions/runs/' + args.iso_run)
            validate_run(iso_run, 'iso.yml', revision)
            iso_artifacts = artifact_names(args.iso_run)
            artifact(args.iso_run, latest_artifact(iso_artifacts, f'finite-iso-{args.channel}-{args.iso_run}-'), destination)
        if acceptance.get('qualificationContext'):
            context_spec = importlib.util.spec_from_file_location('release_qualification_context', Path(__file__).with_name('qualification-context.py'))
            context_module = importlib.util.module_from_spec(context_spec)
            context_spec.loader.exec_module(context_module)
            if acceptance['qualificationContext'].get('inputs') != context_module.source_inputs():
                raise ValueError('Release checkout differs from the qualified installer/test implementation')
        installation = json.loads((destination / 'installation.json').read_text())
        image = validate_evidence(installation, acceptance, publication, args.channel, revision, exact_iso=exact_iso)
        desktop_path = desktop.verify(temporary / 'qualification', acceptance)
        shutil.copy2(desktop_path, destination / desktop_path.name)
        subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=destination, check=True, timeout=300)
        subprocess.run(['cosign', 'verify', '--new-bundle-format=false', '--key', 'cosign.pub', image], check=True, timeout=150)
        shutil.copy2(acceptance_path, destination / 'acceptance.json')
        shutil.copy2(publication_path, destination / 'publication.json')
        for path in (temporary / 'image').glob('*.Containerfile'):
            shutil.copy2(path, destination / path.name)
        provenance = {'schema': 1, 'image': image, 'revision': revision,
                      'sourceRevision': publication.get('sourceRevision', revision),
                      'buildIdentity': publication['buildIdentity'],
                      'buildRun': build_run['html_url'], 'isoRun': iso_run['html_url'],
                      'qualification': acceptance, 'installer': installation['installer'],
                      'isoMatchesQualification': exact_iso}
        (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            print('image=' + image, file=output)


if __name__ == '__main__':
    main()
