"""Read-only matched complete-job assessment of diagnostic product transport."""
from collections import Counter
import json
import math
import re
import statistics
import zipfile

from archive_read import chunks, members
from cost_receipts import bounded_reader
from security_decisions import canonical_hash
from workflow_costs import inventory, seconds

REPOSITORY = 'closure-labs/finite'
PAIRS = [('cold', 1)] + [('warm', i) for i in range(1, 6)]
EXPECTED = {(phase, pair, mode) for phase, pair in PAIRS for mode in ('legacy', 'receipt')}


def assess(samples):
    keyed = {}
    for sample in samples:
        if type(sample.get('completeJobSeconds')) not in (int, float) or not math.isfinite(sample['completeJobSeconds']) or sample['completeJobSeconds'] <= 0:
            raise ValueError('Transport job requires a finite positive complete duration')
        key = sample['phase'], sample['pair'], sample['mode']
        if key not in EXPECTED or key in keyed:
            raise ValueError('Unexpected or duplicate matched transport sample')
        keyed[key] = sample
    complete = set(keyed) == EXPECTED
    identity = {(s.get('reference'), s.get('inventorySha256'), s.get('revision')) for s in samples}
    identity_consistent = bool(len(identity) == 1 and all(all(v for v in row) for row in identity)) if samples else None
    verified = sum(s['correctness'] is True and s['conclusion'] == 'success' for s in samples)
    correct = complete and identity_consistent is True and verified == len(samples)
    comparisons = []
    for phase, pair in PAIRS:
        legs = {mode: keyed.get((phase, pair, mode), {}) for mode in ('legacy', 'receipt')}
        images = {mode: leg.get('imageVersion') for mode, leg in legs.items()}
        tools = {mode: leg.get('toolCohortSha256') for mode, leg in legs.items()}
        comparisons.append({'phase': phase, 'pair': pair,
                            'missingModes': [mode for mode, leg in legs.items() if not leg],
                            'imageVersions': images, 'toolCohorts': tools,
                            'runnerImagesMatched': (images['legacy'] == images['receipt']) if all(images.values()) else None,
                            'toolsMatched': (tools['legacy'] == tools['receipt']) if all(tools.values()) else None})
    matched = complete and all(p['runnerImagesMatched'] is True and p['toolsMatched'] is True for p in comparisons)
    medians = {mode: statistics.median(s['completeJobSeconds'] for s in samples
                if s['mode'] == mode and s['phase'] == 'warm') if any(s['mode'] == mode and s['phase'] == 'warm' for s in samples) else None
               for mode in ('legacy', 'receipt')}
    delta = medians['legacy'] - medians['receipt'] if all(v is not None for v in medians.values()) else None
    cold = [keyed.get(('cold', 1, mode)) for mode in ('legacy', 'receipt')]
    cold_ratio = cold[1]['completeJobSeconds'] / cold[0]['completeJobSeconds'] if all(cold) and cold[0]['completeJobSeconds'] > 0 else None
    failures = []
    if not complete:
        failures.append('incomplete-sample-set')
    if samples and (identity_consistent is False or verified != len(samples)):
        failures.append('failed-or-inconsistent-samples')
    if any(not p['missingModes'] and (p['runnerImagesMatched'] is False or p['toolsMatched'] is False) for p in comparisons):
        failures.append('runner-image-or-tool-cohort-mismatch')
    if any(not p['missingModes'] and (p['runnerImagesMatched'] is None or p['toolsMatched'] is None) for p in comparisons):
        failures.append('unknown-runner-image-or-tool-cohort')
    if complete:
        if delta is None or delta < 30:
            failures.append('warm-median-minimum-seconds')
        if delta is None or medians['legacy'] <= 0 or delta / medians['legacy'] < 0.10:
            failures.append('warm-median-minimum-relative')
    if cold_ratio is not None and cold_ratio > 1.10:
        failures.append('cold-cost-regression')
    passed = bool(correct and matched and not failures)
    return {'schema': 1, 'kind': 'finite-release-transport-comparison', 'authorizesPublication': False,
            'complete': complete, 'correctnessPassed': correct, 'matchedToolCohorts': matched,
            'warmCompleteJobMedians': medians, 'warmSecondsSaved': delta,
            'coldCostRatio': cold_ratio, 'performanceGatePassed': passed,
            'productionEnabled': False, 'adoption': 'retain-current-production-path',
            'pairComparisons': comparisons, 'gateFailures': failures,
            'verifiedSampleCount': verified, 'failedSampleCount': len(samples) - verified,
            'productIdentityConsistent': identity_consistent,
            'samples': samples,
            'limitations': ['Native complete-job times include setup, seed work, hashing, artifact retention and local cleanup.',
                           'Producer complete-job occupancy is reported separately; it is not amortized away.',
                           'Known native runner seconds are a subtotal when native job durations are unknown.',
                           'Missing or unscored samples retain native job cost and never count as fast successful samples.',
                           'Cold means a fresh hosted runner; provider-side cache state remains unknown.',
                           'OCI retained storage and eventual registry cleanup require an explicit lifecycle observation before adoption.']}


def native_jobs(run, jobs):
    """Keep every native job's cost even when it produced no sample."""
    unique = {}
    for job in jobs:
        if (type(job.get('id')) is not int or job['id'] <= 0 or job.get('run_id') != run['id']
                or job.get('run_attempt') != run['run_attempt'] or job.get('head_sha') != run['head_sha']):
            raise ValueError('Diagnostic job differs from its native run/attempt/source')
        if job['id'] in unique and job != unique[job['id']]:
            raise ValueError('Conflicting duplicate native diagnostic job')
        unique[job['id']] = job
    rows = []
    for job in unique.values():
        elapsed, issue = None, None
        try:
            if job.get('status') != 'completed':
                issue = 'unfinished-native-job'
            else:
                elapsed = 0 if job.get('conclusion') == 'skipped' else seconds(job.get('started_at'), job.get('completed_at'))
        except (ValueError, TypeError):
            issue = 'missing-or-invalid-native-timestamps'
        rows.append({'jobId': job['id'], 'name': job['name'], 'status': job['status'],
                     'conclusion': job.get('conclusion'), 'runnerSeconds': elapsed, 'timingIssue': issue})
    return list(unique.values()), rows


def collect(run_id, api, *, reader=bounded_reader):
    run = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    if (run.get('id') != run_id or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or not re.fullmatch('[0-9a-f]{40}', run.get('head_sha', ''))
            or run.get('path') != '.github/workflows/benchmark-release-transport.yml'
            or run.get('event') != 'workflow_dispatch' or run.get('status') != 'completed'
            or type(run.get('run_attempt')) is not int or run['run_attempt'] != 1):
        raise ValueError('Comparison requires one completed unretried native diagnostic consumer run')
    jobs, accounting = native_jobs(run, inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/attempts/1/jobs', 'jobs', limit=100))
    consumers = {}
    for job in jobs:
        match = re.fullmatch(r'consumer-(cold|warm)-([1-5])-(legacy|receipt)', job['name'])
        if not match:
            continue
        key = match[1], int(match[2]), match[3]
        if key not in EXPECTED or key in consumers:
            raise ValueError('Unexpected or ambiguous native consumer job')
        consumers[key] = job
    if not consumers:
        raise ValueError('Comparison requires native consumer jobs')
    artifacts = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts', limit=100)
    selected = [a for a in artifacts if a.get('name', '').startswith('release-transport-sample-')]
    if len(selected) > 12:
        raise ValueError('Comparison exceeds the twelve-sample bound; use one unretried matched run')
    samples, unscored, seen = [], [], set()
    for artifact in selected:
        match = re.fullmatch(r'release-transport-sample-(cold|warm)-([1-5])-(legacy|receipt)-' + str(run_id) + '-1', artifact['name'])
        key = (match[1], int(match[2]), match[3]) if match else None
        if key not in consumers or key in seen:
            raise ValueError('Missing, duplicate or mismatched native sample job')
        seen.add(key)
        job = consumers[key]
        if (artifact.get('expired') is not False or type(artifact.get('size_in_bytes')) is not int
                or not 0 < artifact['size_in_bytes'] <= 1024**2
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
                or artifact.get('workflow_run', {}).get('id') != run_id
                or artifact['workflow_run'].get('head_sha') != run['head_sha']):
            raise ValueError('Invalid native transport sample artifact')
        with reader(artifact, REPOSITORY) as archive:
            with zipfile.ZipFile(archive) as zipped:
                entries = list(members(zipped, max_files=2, max_bytes=1024**2))
                matching = [(name, e) for name, e in entries if name == 'transport-sample.json']
                if not matching and job.get('conclusion') != 'success':
                    unscored.append({'jobId': job['id'], 'nativeArtifact': artifact,
                                     'reason': 'failed-job-without-sample-member'})
                    continue
                if len(matching) != 1:
                    raise ValueError('Missing diagnostic transport sample')
                value = json.loads(b''.join(chunks(zipped, matching[0][1])))
        if (not isinstance(value, dict) or type(value.get('runId')) is not int or value['runId'] != run_id
                or value.get('revision') != run['head_sha']
                or value.get('jobName') != job['name'] or value.get('runAttempt') != 1
                or type(value.get('runAttempt')) is not int or type(value.get('pair')) is not int
                or (value.get('phase'), value.get('pair'), value.get('mode')) != key
                or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('kind') != 'finite-release-transport-sample'):
            raise ValueError('Diagnostic sample differs from native job/source')
        elapsed = next(j['runnerSeconds'] for j in accounting if j['jobId'] == job['id'])
        sample = {**value, 'jobId': job['id'], 'conclusion': job['conclusion'],
                  'completeJobSeconds': elapsed,
                  'nativeArtifact': {k: artifact[k] for k in ('id', 'digest', 'size_in_bytes')}}
        if elapsed is None or elapsed <= 0:
            unscored.append({**sample, 'reason': 'missing-or-nonpositive-native-duration'})
        else:
            samples.append(sample)
    report = assess(samples)
    report.update(nativeRun={'id': run_id, 'attempt': 1, 'revision': run['head_sha'],
                             'conclusion': run.get('conclusion')},
                  nativeJobs=accounting, knownRunnerSeconds=sum(j['runnerSeconds'] or 0 for j in accounting),
                  nativeJobConclusions=dict(Counter(j['conclusion'] or j['status'] for j in accounting)),
                  unknownDurationJobs=[j['jobId'] for j in accounting if j['runnerSeconds'] is None],
                  missingSampleJobs=[j['id'] for key, j in consumers.items() if key not in seen],
                  missingNativeJobs=[{'phase': phase, 'pair': pair, 'mode': mode}
                                     for phase, pair, mode in sorted(EXPECTED - set(consumers))],
                  unscoredSamples=unscored)
    if run.get('conclusion') != 'success':
        report['gateFailures'].append('native-run-failed')
    if report['unknownDurationJobs']:
        report['gateFailures'].append('incomplete-native-job-costs')
    report['performanceGatePassed'] = report['performanceGatePassed'] and not report['gateFailures']
    producers = {canonical_hash(s['producer']): s['producer'] for s in samples if 'producer' in s}
    report['producers'] = []
    for producer in producers.values():
        if (producer.get('repository') != REPOSITORY or producer.get('workflow') != 'benchmark-release-transport.yml'
                or type(producer.get('runId')) is not int or producer['runId'] <= 0
                or type(producer.get('runAttempt')) is not int or producer['runAttempt'] <= 0):
            raise ValueError('Invalid diagnostic producer identity')
        native = api(f'repos/{REPOSITORY}/actions/runs/{producer["runId"]}/attempts/{producer["runAttempt"]}')
        if (native.get('id') != producer['runId'] or native.get('run_attempt') != producer['runAttempt']
                or native.get('head_sha') != producer['headSha'] or native.get('conclusion') != 'success'
                or native.get('status') != 'completed' or native.get('event') != 'workflow_dispatch'
                or native.get('path') != '.github/workflows/benchmark-release-transport.yml'
                or native.get('repository', {}).get('full_name') != REPOSITORY):
            raise ValueError('Diagnostic producer changed or did not succeed')
        producer_jobs, producer_costs = native_jobs(native, inventory(api, f'repos/{REPOSITORY}/actions/runs/{producer["runId"]}/attempts/{producer["runAttempt"]}/jobs', 'jobs', limit=100))
        successful = [j for j in producer_jobs if j['name'] == 'producer' and j.get('status') == 'completed'
                      and j.get('conclusion') == 'success']
        if len(successful) != 1:
            raise ValueError('Diagnostic producer job did not succeed')
        unknown = [j['jobId'] for j in producer_costs if j['runnerSeconds'] is None]
        report['producers'].append({'producer': producer,
                                    'runnerSeconds': None if unknown else sum(j['runnerSeconds'] for j in producer_costs),
                                    'nativeJobs': producer_costs, 'unknownDurationJobs': unknown,
                                    'ociRetentionAndCleanup': 'requires-lifecycle-observation'})
    report['producerCostCoverage'] = ('unknown-without-sample-producer' if not producers else
                                     'incomplete-native-producer-costs' if any(p['unknownDurationJobs'] for p in report['producers']) else
                                     'verified-from-samples')
    if report['producerCostCoverage'] != 'verified-from-samples':
        report['gateFailures'].append(report['producerCostCoverage'])
        report['performanceGatePassed'] = False
    return report
