#!/usr/bin/env python3
"""Predeclare and report native installer trials; never authorize publication."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import quote, unquote

from archive_read import archive_reader, members, chunks
from github_api import get_json
from workflow_costs import inventory, observe

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'closure-labs/finite'
PROFILES = ('finite', 'finite-dev')
MODES = ('default', 'zstd')
PAIRS = ('cold-1', *(f'warm-{i}' for i in range(1, 6)))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


controls = load('installer_controls', 'scripts/bluebuild/benchmark-controls.py')
provenance = load('installer_provenance', 'scripts/bluebuild/installer-provenance.py')
desktop = load('installer_desktop', 'scripts/bluebuild/desktop-qualification.py')


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Oversized benchmark document')
    return json.loads(path.read_bytes())


def require_runner_release(image, api=None):
    if not controls.matches(r'[0-9]{8}\.[0-9]+\.[0-9]+', image):
        raise ValueError('Invalid declared Ubuntu runner image')
    # ImageVersion appends a build component to the runner-images release tag.
    tag = 'ubuntu24/' + image.rsplit('.', 1)[0]
    value = (api or get_json)('repos/actions/runner-images/releases/tags/' + quote(tag, safe=''))
    if (not isinstance(value, dict) or value.get('tag_name') != tag
            or type(value.get('id')) is not int or value['id'] <= 0
            or not isinstance(value.get('published_at'), str)):
        raise ValueError('Runner release metadata has no exact published origin')
    if value.get('draft') is not False or value.get('prerelease') is not False:
        raise ValueError('Runner image deployment is incomplete or unknown; do not create benchmark samples')
    published = datetime.fromisoformat(value['published_at'].replace('Z', '+00:00'))
    if published.tzinfo is None:
        raise ValueError('Runner release timestamp lacks a timezone')
    return {'repository': 'actions/runner-images', 'tag': tag, 'releaseId': value['id'],
            'publishedAt': value['published_at'], 'draft': False, 'prerelease': False,
            'checkedAt': datetime.now(timezone.utc).isoformat()}


def validate_plan(plan):
    if (plan.get('schema') != 1 or plan.get('authorizesPublication') is not False
            or plan.get('repository') != REPOSITORY
            or not re.fullmatch('[0-9a-f]{40}', plan.get('head', ''))
            or set(plan.get('profiles', {})) != set(PROFILES)
            or plan.get('pairs') != list(PAIRS)):
        raise ValueError('Incomplete predeclared installer benchmark plan')
    created = datetime.fromisoformat(plan['createdAt'])
    if created.tzinfo is None:
        raise ValueError('Benchmark plan requires a timezone')
    for profile in PROFILES:
        entry = plan['profiles'][profile]
        controls.controls(json.dumps({
            'schema': 1, 'planSha256': sha(plan), 'pair': 'cold-1', 'temperature': 'cold',
            'runnerImage': plan['runnerImage'], 'runtimeCohorts': entry['runtimeCohorts']}),
            {'FINITE_VALIDATION_ONLY': 'true'})
        inputs = entry['inputs']
        if (set(inputs) != {'CANDIDATE_DIGEST', 'PREVIOUS_DIGEST', 'BUILD_IDENTITY', 'SOURCE_REVISION'}
                or not all(re.fullmatch('sha256:[0-9a-f]{64}', inputs[k])
                           for k in ('CANDIDATE_DIGEST', 'PREVIOUS_DIGEST'))
                or not re.fullmatch('v1:[0-9a-f]{64}', inputs['BUILD_IDENTITY'])
                or not re.fullmatch('[0-9a-f]{40}', inputs['SOURCE_REVISION'])):
            raise ValueError('Benchmark plan requires frozen immutable product identities')
    return plan


def parse_runner_header(raw):
    # Restrict parsing to the runner's startup section, before any workflow
    # command can print lookalike image metadata into the job log.
    marker = b'##[group]GITHUB_TOKEN Permissions'
    boundary = raw.find(marker)
    if boundary < 0:
        raise ValueError('Incomplete native runner startup header')
    raw = raw[:boundary + len(marker)]
    lines = [re.sub(r'^\d{4}-\d\d-\d\dT[0-9:.]+Z ', '', line)
             for line in raw.decode('utf-8-sig').splitlines()]
    if not lines or not lines[0].startswith('Current runner version: '):
        raise ValueError('Missing native runner startup header')
    boundary = lines.index('##[group]GITHUB_TOKEN Permissions')
    startup = lines[:boundary]
    if ('Prepare workflow directory' in startup or any(line.startswith('##[group]Run ') for line in startup)):
        raise ValueError('Runner metadata appeared after workflow preparation')
    if startup.count('##[group]Runner Image') != 1:
        raise ValueError('Missing or ambiguous native runner image')
    start = startup.index('##[group]Runner Image') + 1
    end = startup.index('##[endgroup]', start)
    fields = {}
    for line in startup[start:end]:
        key, separator, value = line.partition(': ')
        if separator:
            if key in fields:
                raise ValueError('Duplicate native runner image metadata')
            fields[key] = value
    version = fields.get('Version', '')
    if fields.get('Image') != 'ubuntu-24.04' or not re.fullmatch(r'[0-9]{8}\.[0-9]+\.[0-9]+', version):
        raise ValueError('Unknown native Ubuntu runner image')
    tag = 'ubuntu24/' + version.rsplit('.', 1)[0]
    release = fields.get('Image Release', '')
    if unquote(release) != 'https://github.com/actions/runner-images/releases/tag/' + tag:
        raise ValueError('Native runner release differs from its version')
    return {'image': fields['Image'], 'version': version, 'release': release}


def native_runner_image(job_id):
    if type(job_id) is not int or job_id < 1:
        raise ValueError('Native runner lookup requires a job ID')
    # Only successful native samples reach this lookup. Eight MiB/30 seconds
    # bounds each log read; transport and size failures leave the cohort unknown.
    with tempfile.TemporaryFile() as log:
        maximum = 8 * 1024**2
        subprocess.run(['gh', 'api', '--allow-escape-sequences',
                        f'repos/{REPOSITORY}/actions/jobs/{job_id}/logs'],
                       stdout=log, stderr=subprocess.PIPE, check=True, timeout=30,
                       preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum)))
        log.seek(0)
        value = parse_runner_header(log.read(65536))
        log.seek(0)
        return {**value, 'jobId': job_id, 'source': 'native-job-startup-log',
                'logSha256': hashlib.file_digest(log, 'sha256').hexdigest()}


def native_sample(run_id, plan, api=get_json):
    native = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    if (native.get('id') != run_id or native.get('head_sha') != plan['head']
            or native.get('repository', {}).get('full_name') != REPOSITORY
            or native.get('event') != 'workflow_dispatch'
            or native.get('head_branch') == 'main'
            or native.get('path') != '.github/workflows/benchmark-image-tools.yml'
            or datetime.fromisoformat(native['created_at'].replace('Z', '+00:00')) <=
               datetime.fromisoformat(plan['createdAt'])):
        raise ValueError('Native run is outside the predeclared diagnostic plan')
    cost = observe(native, api, datetime.now(timezone.utc))
    result = {'runId': run_id, 'native': cost, 'eligible': False, 'reasons': [],
              'knownRunnerSeconds': sum(j['runnerSeconds'] or 0 for j in cost['jobs']),
              'unknownDurationJobs': [j['jobId'] for j in cost['jobs'] if j['runnerSeconds'] is None]}
    if result['unknownDurationJobs']:
        result['reasons'].append('Native job duration remains unknown')
    if native['run_attempt'] != 1 or native['status'] != 'completed' or native['conclusion'] != 'success':
        result['reasons'].append('Run is incomplete, failed, cancelled or retried; cost retained')
        return result
    try:
        artifacts = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
        documents, hashes = {}, {}
        selected = [a for a in artifacts if a['name'].startswith('qualification-diagnostic-')]
        if len(selected) > 6:
            raise ValueError('Oversized diagnostic artifact inventory')
        for artifact in selected:
            origin = artifact.get('workflow_run', {})
            if (origin.get('id') != run_id or origin.get('head_sha') != plan['head']
                    or artifact['expired'] or not 0 < artifact['size_in_bytes'] <= 16 * 1024 * 1024):
                raise ValueError('Invalid native diagnostic artifact origin')
            with archive_reader(artifact, REPOSITORY) as archive, zipfile.ZipFile(archive) as zipped:
                for name, member in members(zipped, max_files=1024, max_bytes=64 * 1024 * 1024):
                    if not name.endswith(('-acceptance.json', '-benchmark.json', '-stages.jsonl', 'nix-setup.json')):
                        continue
                    if member.file_size > 4 * 1024 * 1024:
                        raise ValueError('Oversized diagnostic receipt')
                    raw = b''.join(chunks(zipped, member))
                    key = artifact['name'] + '/' + name
                    if key in documents:
                        raise ValueError('Duplicate diagnostic receipt')
                    hashes[key] = hashlib.sha256(raw).hexdigest()
                    documents[key] = [json.loads(line) for line in raw.splitlines()] if name.endswith('.jsonl') else json.loads(raw)
        result['receiptSha256'] = hashes
        native_images = {}
        for job in cost['jobs']:
            if job['name'] not in ('qualification / phase (fresh)', 'qualification / phase (upgrade)'):
                continue
            try:
                native_images[job['jobId']] = native_runner_image(job['jobId'])
            except (ValueError, OSError, subprocess.SubprocessError):
                native_images[job['jobId']] = None
        result.update(verify_documents(plan, native, cost, documents, hashes, native_images))
    except (ValueError, KeyError, TypeError, StopIteration, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        result['eligible'] = False
        result['reasons'].append('Producer receipt verification failed: ' + type(error).__name__)
    return result


def verify_documents(plan, native, cost, documents, hashes, native_images=None):
    run_id = native['id']
    profile_entries = [(p, f'qualification-diagnostic-{p}-{run_id}-1/') for p in PROFILES]
    profile, prefix = next((p, prefix) for p, prefix in profile_entries if prefix + p + '-acceptance.json' in documents)
    accepted = documents[prefix + profile + '-acceptance.json']
    entry = plan['profiles'][profile]; inputs = entry['inputs']
    if (accepted.get('schema') != 2 or accepted.get('revision') != plan['head']
            or accepted.get('profile') != profile or accepted.get('sourceRevision') != inputs['SOURCE_REVISION']
            or accepted.get('buildIdentity') != inputs['BUILD_IDENTITY']
            or accepted.get('candidate') != 'ghcr.io/closure-labs/finite@' + inputs['CANDIDATE_DIGEST']
            or accepted.get('previousDigest') != inputs['PREVIOUS_DIGEST']
            or any(accepted.get(k) is not True for k in ('accepted', 'validationOnly', 'secureBoot', 'encryptedRoot'))
            or accepted.get('bootstrap') is not False
            or sha(accepted['qualificationContext']) != accepted['qualificationContextSha256']):
        raise ValueError('Acceptance is not bound to the declared immutable inputs')
    desktop_key = prefix + profile + '-desktop-acceptance.json'
    desktop.validate(documents[desktop_key], accepted)
    if hashes[desktop_key] != accepted['vmSecurityEvidence']['sha256']:
        raise ValueError('Desktop acceptance differs from its raw hash binding')
    reasons, phase_results, benchmark_values, modes = [], [], [], []
    for phase in ('fresh', 'upgrade'):
        phase_prefix = f'qualification-diagnostic-phase-{profile}-{phase}-{run_id}-1/'
        control = documents[phase_prefix + f'{profile}-{phase}-benchmark.json']
        if (control.get('schema') != 1 or control.get('authorizesPublication') is not False
                or control.get('repository') != REPOSITORY or control.get('revision') != plan['head']
                or control.get('runId') != run_id or control.get('runAttempt') != 1
                or control.get('profile') != profile or control.get('phase') != phase
                or control.get('inputs') != inputs or control.get('mode') not in MODES):
            raise ValueError('Diagnostic control has a forged or mismatched origin')
        value = control['controls']; benchmark_values.append(value); modes.append(control['mode'])
        controls.controls(json.dumps(value), {'FINITE_VALIDATION_ONLY': 'true'})
        if (value['planSha256'] != sha(plan) or value['runtimeCohorts'] != entry['runtimeCohorts']
                or value['runnerImage'] != plan['runnerImage']):
            raise ValueError('Diagnostic control differs from its predeclared plan')
        phase_acceptance = documents[phase_prefix + f'vm-{phase}/acceptance.json']
        expected_image = 'ghcr.io/closure-labs/finite@' + inputs['CANDIDATE_DIGEST' if phase == 'fresh' else 'PREVIOUS_DIGEST']
        if (phase_acceptance.get('source') != expected_image or phase_acceptance.get('profile') != profile
                or (phase == 'upgrade' and phase_acceptance.get('target') != accepted['candidate'])
                or any(phase_acceptance.get(k) is not True for k in ('accepted', 'secureBoot', 'encryptedRoot', 'validationOnly'))
                or phase_acceptance.get('qualificationContext') != accepted['qualificationContext']
                or sha(phase_acceptance['qualificationContext']) != phase_acceptance.get('qualificationContextSha256')):
            raise ValueError('Phase acceptance differs from the authenticated aggregate')
        iso = phase_acceptance['iso']
        if type(iso['sizeBytes']) is not int or iso['sizeBytes'] <= 0 or (phase == 'fresh' and iso != accepted['qualifiedIso']):
            raise ValueError('Pristine ISO size or aggregate binding differs')
        runtime = provenance.validate(iso['installer']['runtimeProvenance'])
        if (runtime['cohortSha256'] != value['runtimeCohorts'][phase]
                or runtime['repositoryMetadata'] is None or runtime['repositoryConfiguration'] is None):
            reasons.append(phase + ': unknown or mismatched runtime RPM/repository cohort')
        expected_codec = 'xz' if control['mode'] == 'default' else 'zstd'
        if runtime['compression']['type'] != expected_codec:
            raise ValueError('Runtime codec differs from its declared arm')
        if control['mode'] == 'zstd' and runtime['compression']['args'] != ['-Xcompression-level', '15']:
            raise ValueError('Unreviewed runtime compression arguments')
        rows = documents[phase_prefix + f'{profile}-{phase}-stages.jsonl']
        cohorts = []
        if {r.get('stage') for r in rows} != {'installer-prepare', 'image-acquisition', 'iso-build', 'vm-acceptance'} or len(rows) != 4:
            reasons.append(phase + ': incomplete or duplicate stage timings')
        for row in rows:
            if (row.get('schema') != 1 or row.get('authorizesPublication') is not False
                    or row.get('repository') != REPOSITORY or row.get('revision') != plan['head']
                    or int(row.get('runId', 0)) != run_id or int(row.get('runAttempt', 0)) != 1
                    or row.get('profile') != profile or row.get('phase') != phase
                    or row.get('buildIdentity') != inputs['BUILD_IDENTITY']
                    or row.get('candidateDigest') != inputs['CANDIDATE_DIGEST']
                    or row.get('sourceRevision') != inputs['SOURCE_REVISION']):
                raise ValueError('Timing receipt differs from its native origin')
            if row['runner'].get('ImageVersion') != plan['runnerImage'] or row.get('status') != 0:
                reasons.append(phase + ': runner or stage outcome mismatch')
            cohorts.append(row['toolCohort'])
        if not rows or any(c != cohorts[0] for c in cohorts) or not all(cohorts[0].values()):
            reasons.append(phase + ': missing or inconsistent tool cohort')
        setup = documents[phase_prefix + 'nix-setup.json']
        if (setup.get('schema') != 1 or setup.get('kind') != 'finite-nix-observation'
                or int(setup.get('runId', 0)) != run_id or int(setup.get('runAttempt', 0)) != 1
                or setup.get('repository') != REPOSITORY or setup.get('revision') != plan['head']
                or setup.get('authorizesPublication') is not False or setup.get('status') != 'success'):
            raise ValueError('Invalid Nix setup observation origin or status')
        cache = setup.get('cache') or {}
        if value['temperature'] == 'warm' and (cache.get('STORE_HIT') != 'true' or not cache.get('STORE_KEY')):
            reasons.append(phase + ': warm requires an observed exact cache hit; unknown is not a hit')
        if value['temperature'] == 'cold' and any(cache.get(k) for k in ('STORE_KEY', 'SOURCE_KEY', 'STORE_HIT', 'SOURCE_HIT')):
            reasons.append(phase + ': cold unexpectedly restored an Actions cache')
        job = next(j for j in cost['jobs'] if j['name'] == f'qualification / phase ({phase})')
        if job['conclusion'] != 'success' or job['runnerSeconds'] is None:
            reasons.append(phase + ': missing successful complete native phase job')
        native_image = (native_images or {}).get(job['jobId'])
        if (not isinstance(native_image, dict) or native_image.get('jobId') != job['jobId']
                or native_image.get('image') != 'ubuntu-24.04' or native_image.get('version') != plan['runnerImage']):
            reasons.append(phase + ': unknown or mismatched native runner startup image')
        phase_results.append({'phase': phase, 'jobId': job['jobId'], 'runnerSeconds': job['runnerSeconds'],
            'nativeRunnerImage': native_image,
            'isoBytes': iso['sizeBytes'], 'runtimeCohort': runtime['cohortSha256'],
            'toolCohort': cohorts[0] if cohorts else None,
            'cacheKey': cache.get('STORE_KEY'), 'qualificationContext': phase_acceptance['qualificationContext']})
    if benchmark_values[0] != benchmark_values[1] or modes[0] != modes[1]:
        raise ValueError('Qualification phases used different benchmark controls')
    return {'eligible': not reasons and all(j['runnerSeconds'] is not None for j in cost['jobs']), 'reasons': reasons, 'profile': profile,
            'mode': control['mode'], 'pair': value['pair'], 'temperature': value['temperature'],
            'correctnessPassed': True, 'phases': phase_results}


def compare(plan, samples):
    validate_plan(plan)
    seen = set(); groups = {}; decisions = []
    unassigned = any(not s.get('profile') or not s.get('pair') for s in samples)
    for sample in samples:
        if type(sample['runId']) is not int or sample['runId'] in seen:
            raise ValueError('Native jobs cannot be charged twice through duplicate runs')
        seen.add(sample['runId'])
        if sample.get('profile') and sample.get('pair'):
            key = (sample['profile'], sample['pair'], sample['mode'])
            if key in groups:
                raise ValueError('Selective replacements or duplicate benchmark arms are forbidden')
            groups[key] = sample
    for profile in PROFILES:
        costs = {mode: [] for mode in MODES}; complete = not unassigned; reasons = ['Failed or unassigned native work cannot be replaced'] if unassigned else []
        cold = None
        phase_costs = {phase: {mode: [] for mode in MODES} for phase in ('fresh','upgrade')}
        for pair in PAIRS:
            arms = [groups.get((profile, pair, mode)) for mode in MODES]
            if not all(arm and arm['eligible'] for arm in arms):
                complete = False; reasons.append(pair + ': incomplete or ineligible pair'); continue
            default, zstd = arms
            matched = True
            for a, b in zip(default['phases'], zstd['phases'], strict=True):
                ac, bc = dict(a['qualificationContext']), dict(b['qualificationContext'])
                ac.pop('installerCompression', None); bc.pop('installerCompression', None)
                if (a['phase'] != b['phase'] or ac != bc or a['toolCohort'] != b['toolCohort']
                        or a['runtimeCohort'] != b['runtimeCohort'] or a['cacheKey'] != b['cacheKey']):
                    matched = False
                if pair == 'cold-1' and b['runnerSeconds'] > a['runnerSeconds'] * 1.1:
                    reasons.append('cold phase exceeds 10 percent regression')
                    matched = False
            if not matched:
                complete = False; reasons.append(pair + ': cohort or cold phase gate failed'); continue
            if pair == 'cold-1':
                cold = zstd['knownRunnerSeconds'] <= default['knownRunnerSeconds'] * 1.1
            else:
                for mode, arm in zip(MODES, arms, strict=True):
                    costs[mode].append(arm['knownRunnerSeconds'])
                    for phase in arm['phases']:
                        phase_costs[phase['phase']][mode].append(phase['runnerSeconds'])
        medians = {mode: statistics.median(values) if len(values) == 5 else None for mode, values in costs.items()}
        warm = (medians['default'] is not None and medians['zstd'] is not None
                and medians['default'] - medians['zstd'] >= 30
                and medians['zstd'] <= medians['default'] * .9)
        phase_medians = {phase: {mode: statistics.median(values) if len(values) == 5 else None
            for mode, values in modes.items()} for phase, modes in phase_costs.items()}
        phase_warm = all(v['default'] is not None and v['zstd'] is not None
            and v['default'] - v['zstd'] >= 30 and v['zstd'] <= v['default'] * .9
            for v in phase_medians.values())
        warm = warm and phase_warm
        decisions.append({'profile': profile, 'complete': complete, 'warmPairs': len(costs['default']),
            'wholeWorkflowWarmMedianSeconds': medians, 'phaseWarmMedianSeconds': phase_medians, 'coldGatePassed': cold,
            'warmGatePassed': warm, 'performanceGatePassed': complete and cold is True and warm,
            'reasons': reasons})
    return {'schema': 1, 'authorizesPublication': False, 'planSha256': sha(plan),
        'samples': samples, 'decisions': decisions,
        'knownRunnerSeconds': sum(s['knownRunnerSeconds'] for s in samples),
        'performanceGatePassed': all(d['performanceGatePassed'] for d in decisions),
        # Runtime/transfer/storage adoption remains an independent review.
        'adopted': False, 'actualRegistryStorageAndDeletionCost': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    create = sub.add_parser('plan')
    create.add_argument('--head', required=True)
    create.add_argument('--runner-image', required=True)
    create.add_argument('--products', type=Path, required=True, help='Authenticated pilot request with frozen product records')
    create.add_argument('--cohorts', type=Path, required=True, help='Profile to fresh/upgrade runtime-cohort hashes')
    create.add_argument('--output', type=Path, required=True)
    report = sub.add_parser('report')
    report.add_argument('--plan', type=Path, required=True)
    report.add_argument('--runs', type=Path, required=True, help='JSON list of all native run IDs, including failed work')
    report.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'plan':
        if args.output.exists():
            raise ValueError('Refusing to overwrite a frozen installer benchmark plan')
        products, cohorts = read(args.products), read(args.cohorts)
        profiles = {}
        for profile in PROFILES:
            value = next(r['inputs'] for r in products['records'] if r['profile'] == profile)
            profiles[profile] = {'inputs': dict(zip(
                ('CANDIDATE_DIGEST', 'PREVIOUS_DIGEST', 'BUILD_IDENTITY', 'SOURCE_REVISION'),
                (value[k] for k in ('digest', 'previous', 'identity', 'source_revision')), strict=True)),
                'runtimeCohorts': cohorts[profile]}
        plan = {'schema': 1, 'repository': REPOSITORY, 'authorizesPublication': False,
            'createdAt': datetime.now(timezone.utc).isoformat(), 'head': args.head,
            'runnerImage': args.runner_image, 'profiles': profiles, 'pairs': list(PAIRS),
            'warmDefinition': 'Exact authenticated Nix checks snapshot hit. Runtime DNF and unseeded guest remain fresh. Restore, setup and cleanup are charged.',
            'replacementPolicy': 'No replacements; retain failed and mismatched native work.'}
        validate_plan(plan)
        plan['runnerRelease'] = require_runner_release(args.runner_image)
        # An exclusive create also protects a plan created during the lookup.
        with args.output.open('x') as output:
            output.write(json.dumps(plan, indent=2) + '\n')
        return
    plan = validate_plan(read(args.plan)); runs = read(args.runs)
    if not isinstance(runs, list) or len(runs) > 24 or any(type(r) is not int or r <= 0 for r in runs) or len(set(runs)) != len(runs):
        raise ValueError('Expected at most 24 distinct predeclared native runs')
    # Refuse a selected subset that drops slower, failed or interrupted work.
    endpoint = (f'repos/{REPOSITORY}/actions/workflows/benchmark-image-tools.yml/runs'
                f'?head_sha={plan["head"]}&event=workflow_dispatch&created=' + quote('>=' + plan['createdAt']))
    native = inventory(get_json, endpoint, 'workflow_runs', limit=100)
    if {r['id'] for r in native} != set(runs):
        raise ValueError('Run list omits or adds native work since the plan was frozen')
    samples = [native_sample(run, plan) for run in runs]
    args.output.write_text(json.dumps(compare(plan, samples), indent=2) + '\n')


if __name__ == '__main__':
    main()
