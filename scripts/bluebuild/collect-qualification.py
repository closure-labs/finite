#!/usr/bin/env python3
"""Collect exact successful phase producers, including carried retry executions."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
from archive_read import archive_reader, chunks, members
from github_api import get_json
from workflow_costs import execution_key, inventory, timestamp

REPOSITORY = 'closure-labs/finite'
LIMIT = 512 * 1024**2


def positive(value):
    return type(value) is int and value > 0


def job_name(profile, phase, diagnostic=False):
    suffix = 'prepare' if phase == 'reused' else f'phase ({phase})'
    return ('qualification' if diagnostic else f'Publish ({profile}) / qualification') + ' / ' + suffix


def successful(job, run, attempt, profile, phase, diagnostic=False):
    required = ('Save authenticated reusable qualification',) if phase == 'reused' else (
        'Qualify immutable candidate phase', 'Save phase evidence')
    return (job.get('name') == job_name(profile, phase, diagnostic)
            and positive(job.get('id')) and job.get('run_id') == run['id']
            and job.get('run_attempt') == attempt and job.get('head_sha') == run['head_sha']
            and job.get('status') == 'completed' and job.get('conclusion') == 'success'
            and all(sum(step.get('name') == name and step.get('conclusion') == 'success'
                        for step in job.get('steps', [])) == 1 for name in required))


def artifact_binding(artifact, run, profile, phase, attempt, diagnostic=False):
    prefix = 'qualification-diagnostic' if diagnostic else 'qualification'
    name = (f'qualification-reused-{profile}-{run["id"]}-{attempt}' if phase == 'reused' else
            f'{prefix}-phase-{profile}-{phase}-{run["id"]}-{attempt}')
    binding = artifact.get('workflow_run', {})
    if (artifact.get('name') != name or not positive(artifact.get('id'))
            or artifact.get('expired') is not False or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= LIMIT
            or not isinstance(artifact.get('digest'), str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
            or binding.get('id') != run['id'] or binding.get('head_sha') != run['head_sha']):
        raise ValueError('Qualification phase artifact differs from its native producer')
    return artifact


def extract(archive, destination, profile, phase):
    with zipfile.ZipFile(archive) as zipped:
        for name, entry in members(zipped, max_files=512, max_bytes=LIMIT):
            allowed = ({profile + '-acceptance.json', profile + '-desktop-acceptance.json'} if phase == 'reused'
                       else {f'{profile}-{phase}-outcome.json', f'{phase}-qualification-context.json',
                             f'{profile}-{phase}-vm-host.json', f'{profile}-{phase}-stages.jsonl',
                             f'{profile}-{phase}-benchmark.json'})
            prefixes = () if phase == 'reused' else ('vm-' + phase + '/',
                'iso-candidate/' if phase == 'fresh' else 'iso-predecessor/')
            # The two producer ZIPs contain unrelated shared setup files. Only
            # the selected phase's namespace can enter the aggregate directory.
            if name not in allowed and not name.startswith(prefixes):
                continue
            if entry.file_size > 64 * 1024**2:
                raise ValueError('Qualification member exceeds its size bound')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                for chunk in chunks(zipped, entry):
                    output.write(chunk)
    required = (profile + '-acceptance.json' if phase == 'reused' else f'vm-{phase}/acceptance.json')
    if not (destination / required).is_file():
        raise ValueError('Successful phase lacks required acceptance evidence')
    if phase != 'reused':
        outcome = json.loads((destination / f'{profile}-{phase}-outcome.json').read_text())
        if outcome != {'outcome': 'success', 'phase': phase}:
            raise ValueError('Phase outcome does not record successful acceptance')


class Collector:
    def __init__(self, run_id, attempt, revision, profile, diagnostic=False, api=get_json):
        if (not positive(run_id) or type(attempt) is not int or not 1 <= attempt <= 20
                or not re.fullmatch(r'[0-9a-f]{40}', revision) or profile not in ('finite', 'finite-dev')):
            raise ValueError('Invalid bounded qualification collection identity')
        self.run_id, self.attempt, self.revision, self.profile = run_id, attempt, revision, profile
        self.diagnostic, self.api, self.attempts = diagnostic, api, {}
        self.run, self.jobs = self.native(attempt)
        self.artifacts = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts', limit=1000)

    def native(self, attempt):
        if attempt not in self.attempts:
            base = f'repos/{REPOSITORY}/actions/runs/{self.run_id}/attempts/{attempt}'
            run = self.api(base)
            path = '.github/workflows/' + ('benchmark-image-tools.yml' if self.diagnostic else 'build.yml')
            if (run.get('id') != self.run_id or run.get('run_attempt') != attempt
                    or run.get('head_sha') != self.revision or run.get('path') != path
                    or run.get('repository', {}).get('full_name') != REPOSITORY
                    or run.get('head_repository', {}).get('full_name') != REPOSITORY
                    or (self.diagnostic and (run.get('event') != 'workflow_dispatch' or run.get('head_branch') == 'main'))
                    or (not self.diagnostic and (run.get('head_branch') != 'main'
                        or run.get('event') not in ('push', 'schedule', 'workflow_dispatch')))):
                raise ValueError('Qualification run is not the exact trusted source/workflow')
            timestamp(run.get('run_started_at'))
            jobs = inventory(self.api, base + '/jobs', 'jobs', limit=1000)
            self.attempts[attempt] = run, jobs
        return self.attempts[attempt]

    def origin(self, phase):
        current = [j for j in self.jobs if type(j.get('run_attempt')) is int
                   and 1 <= j['run_attempt'] <= self.attempt
                   and successful(j, self.run, j['run_attempt'], self.profile, phase, self.diagnostic)]
        if len(current) != 1 or execution_key(current[0]) is None:
            raise ValueError('Current phase is not one successful identifiable execution')
        candidates = []
        for attempt in range(1, self.attempt + 1):
            run, jobs = self.native(attempt)
            for job in jobs:
                if (successful(job, run, attempt, self.profile, phase, self.diagnostic)
                        and execution_key(job) == execution_key(current[0])
                        and timestamp(job['started_at']) >= timestamp(run['run_started_at'])):
                    candidates.append((attempt, job))
        if len(candidates) != 1:
            raise ValueError('Qualification producing attempt is missing or ambiguous')
        attempt, job = candidates[0]
        prefix = 'qualification-diagnostic' if self.diagnostic else 'qualification'
        name = (f'qualification-reused-{self.profile}-{self.run_id}-{attempt}' if phase == 'reused' else
                f'{prefix}-phase-{self.profile}-{phase}-{self.run_id}-{attempt}')
        artifacts = [a for a in self.artifacts if a.get('name') == name]
        if len(artifacts) != 1:
            raise ValueError('Qualification producing artifact is missing or ambiguous')
        artifact = artifact_binding(artifacts[0], self.run, self.profile, phase, attempt, self.diagnostic)
        if not timestamp(job['started_at']) <= timestamp(artifact.get('created_at')) <= timestamp(job['completed_at']):
            raise ValueError('Phase artifact was not created during its successful producer job')
        origin = {'run': self.run_id, 'attempt': attempt, 'revision': self.revision, 'job': job['id'],
                  'artifactId': artifact['id'], 'artifactDigest': artifact['digest'], 'completedAt': job['completed_at']}
        return origin, artifact

    def collect(self, phases, destination, reader=archive_reader):
        origins = {}
        with tempfile.TemporaryDirectory(prefix='finite-qualification-phases-') as temporary:
            staged = Path(temporary)
            for phase in phases:
                origin, artifact = self.origin(phase)
                with reader(artifact, REPOSITORY) as archive:
                    extract(archive, staged, self.profile, phase)
                origins[phase] = origin
            # Publish files only after every required producer/ZIP succeeds.
            receipt_path = destination / 'qualification-phase-origins.json'
            if phases != ['reused'] and (receipt_path.exists() or receipt_path.is_symlink()):
                raise ValueError('Qualification origin receipt already exists')
            destination.mkdir(parents=True, exist_ok=True)
            for path in staged.rglob('*'):
                if path.is_file():
                    target = destination / path.relative_to(staged)
                    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
                        raise ValueError('Qualification collection refuses existing files or links')
            for path in staged.rglob('*'):
                if path.is_file():
                    target = destination / path.relative_to(staged)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            if phases != ['reused']:
                receipt = {'schema': 1, 'repository': REPOSITORY, 'run': self.run_id, 'attempt': self.attempt,
                           'revision': self.revision, 'profile': self.profile, 'validationOnly': self.diagnostic,
                           'phases': origins}
                target = destination / 'qualification-phase-origins.json'
                with target.open('x') as output:
                    json.dump(receipt, output, indent=2)
                    output.write('\n')
        return origins


def verify_fresh_origin(acceptance, build, api=get_json, reader=archive_reader):
    """Recovery independently checks a carried pristine ISO's original phase."""
    expected = {'run': build['id'], 'attempt': build['run_attempt'], 'revision': build['head_sha']}
    origins = acceptance.get('qualificationPhaseOrigins')
    if origins is None:
        if acceptance.get('qualifiedIsoOrigin') != expected:
            raise ValueError('Legacy ISO origin differs from its exact build attempt')
        return
    fresh = origins.get('fresh') if isinstance(origins, dict) else None
    if (not isinstance(fresh, dict) or fresh.get('run') != build['id'] or fresh.get('revision') != build['head_sha']
            or type(fresh.get('attempt')) is not int or not 1 <= fresh['attempt'] <= build['run_attempt']
            or not positive(fresh.get('job')) or not positive(fresh.get('artifactId'))
            or acceptance.get('qualifiedIsoOrigin') != {key: fresh[key] for key in ('run', 'attempt', 'revision')}):
        raise ValueError('ISO origin differs from its authenticated fresh phase')
    job = api(f'repos/{REPOSITORY}/actions/jobs/{fresh["job"]}')
    profile = acceptance['profile']
    if not successful(job, build, fresh['attempt'], profile, 'fresh') or execution_key(job) is None:
        raise ValueError('Original fresh phase did not succeed')
    if (fresh.get('completedAt') != job['completed_at']
            or timestamp(acceptance.get('qualifiedAt')) > timestamp(job['completed_at'])):
        raise ValueError('Recovery cannot extend the original fresh qualification time')
    artifact = api(f'repos/{REPOSITORY}/actions/artifacts/{fresh["artifactId"]}')
    artifact_binding(artifact, build, profile, 'fresh', fresh['attempt'])
    if not timestamp(job['started_at']) <= timestamp(artifact.get('created_at')) <= timestamp(job['completed_at']):
        raise ValueError('Original fresh artifact is outside its producer job interval')
    if artifact['digest'] != fresh.get('artifactDigest'):
        raise ValueError('Original fresh artifact differs from its receipt')
    with tempfile.TemporaryDirectory(prefix='finite-recovery-fresh-') as temporary:
        directory = Path(temporary)
        with reader(artifact, REPOSITORY) as archive:
            extract(archive, directory, profile, 'fresh')
        phase = json.loads((directory / 'vm-fresh/acceptance.json').read_text())
        if (phase.get('accepted') is not True or phase.get('secureBoot') is not True
                or phase.get('encryptedRoot') is not True or phase.get('validationOnly') is True
                or phase.get('profile') != profile or phase.get('source') != acceptance['candidate']
                or phase.get('iso') != acceptance['qualifiedIso']
                or phase.get('qualificationContext') != acceptance['qualificationContext']
                or phase.get('qualificationContextSha256') != acceptance['qualificationContextSha256']):
            raise ValueError('Recovered ISO/context differs from its original accepted fresh phase')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('.bluebuild'))
    parser.add_argument('--reused', action='store_true')
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Qualification collection requires hosted Finite execution')
    collector = Collector(int(os.environ['GITHUB_RUN_ID']), int(os.environ['GITHUB_RUN_ATTEMPT']),
                          os.environ['GITHUB_SHA'], os.environ['PROFILE'],
                          os.environ.get('FINITE_VALIDATION_ONLY') == 'true')
    phases = ['reused'] if args.reused else (['fresh', 'upgrade'] if os.environ.get('PREVIOUS_DIGEST') else ['fresh'])
    collector.collect(phases, args.directory)


if __name__ == '__main__':
    main()
