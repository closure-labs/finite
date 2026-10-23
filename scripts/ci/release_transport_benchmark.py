"""Read-only matched complete-job assessment of diagnostic product transport."""
import json
import math
import statistics
import zipfile

from archive_read import archive_reader, chunks, members
from security_decisions import canonical_hash
from workflow_costs import inventory, seconds

REPOSITORY = 'closure-labs/finite'


def assess(samples):
    expected = {(phase, pair, mode) for phase, pair in [('cold', 1)] + [('warm', i) for i in range(1, 6)]
                for mode in ('legacy', 'receipt')}
    keyed = {}
    for sample in samples:
        if type(sample.get('completeJobSeconds')) not in (int, float) or not math.isfinite(sample['completeJobSeconds']) or sample['completeJobSeconds'] <= 0:
            raise ValueError('Transport job requires a finite positive complete duration')
        key = sample['phase'], sample['pair'], sample['mode']
        if key not in expected or key in keyed:
            raise ValueError('Unexpected or duplicate matched transport sample')
        keyed[key] = sample
    complete = set(keyed) == expected
    identity = {(s.get('reference'), s.get('inventorySha256'), s.get('revision')) for s in samples}
    correct = complete and len(identity) == 1 and all(all(v for v in row) for row in identity) and all(s['correctness'] and s['conclusion'] == 'success' for s in samples)
    matched = complete and all(keyed[(phase, pair, 'legacy')].get('imageVersion')
                  and keyed[(phase, pair, 'legacy')]['imageVersion'] == keyed[(phase, pair, 'receipt')].get('imageVersion')
                  and keyed[(phase, pair, 'legacy')].get('toolCohortSha256')
                  and keyed[(phase, pair, 'legacy')]['toolCohortSha256'] == keyed[(phase, pair, 'receipt')].get('toolCohortSha256')
                  for phase, pair in [('cold', 1)] + [('warm', i) for i in range(1, 6)]
                  if (phase, pair, 'legacy') in keyed and (phase, pair, 'receipt') in keyed)
    medians = {mode: statistics.median(s['completeJobSeconds'] for s in samples
                if s['mode'] == mode and s['phase'] == 'warm') if any(s['mode'] == mode and s['phase'] == 'warm' for s in samples) else None
               for mode in ('legacy', 'receipt')}
    delta = medians['legacy'] - medians['receipt'] if all(v is not None for v in medians.values()) else None
    cold = [keyed.get(('cold', 1, mode)) for mode in ('legacy', 'receipt')]
    cold_ratio = cold[1]['completeJobSeconds'] / cold[0]['completeJobSeconds'] if all(cold) and cold[0]['completeJobSeconds'] > 0 else None
    passed = bool(correct and matched and delta is not None and delta >= 30
                  and medians['legacy'] > 0 and delta / medians['legacy'] >= 0.10
                  and cold_ratio is not None and cold_ratio <= 1.10)
    return {'schema': 1, 'kind': 'finite-release-transport-comparison', 'authorizesPublication': False,
            'complete': complete, 'correctnessPassed': correct, 'matchedToolCohorts': matched,
            'warmCompleteJobMedians': medians, 'warmSecondsSaved': delta,
            'coldCostRatio': cold_ratio, 'performanceGatePassed': passed,
            'productionEnabled': False, 'adoption': 'retain-current-production-path',
            'samples': samples,
            'limitations': ['Native complete-job times include setup, seed work, hashing, artifact retention and local cleanup.',
                           'Producer complete-job occupancy is reported separately; it is not amortized away.',
                           'Cold means a fresh hosted runner; provider-side cache state remains unknown.',
                           'OCI retained storage and eventual registry cleanup require an explicit lifecycle observation before adoption.']}


def collect(run_id, api):
    run = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    if (run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('path') != '.github/workflows/benchmark-release-transport.yml'
            or run.get('event') != 'workflow_dispatch' or run.get('status') != 'completed'):
        raise ValueError('Comparison requires a completed native diagnostic consumer run')
    jobs = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{run["run_attempt"]}/jobs', 'jobs')
    artifacts = inventory(api, f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
    selected = [a for a in artifacts if a.get('name', '').startswith('release-transport-sample-')]
    if len(selected) > 12:
        raise ValueError('Comparison exceeds the twelve-sample bound; use one unretried matched run')
    samples = []
    for artifact in selected:
        if (artifact.get('expired') is not False or not 0 < artifact.get('size_in_bytes', 0) <= 1024**2
                or artifact.get('workflow_run', {}).get('id') != run_id
                or artifact['workflow_run'].get('head_sha') != run['head_sha']):
            raise ValueError('Invalid native transport sample artifact')
        with archive_reader(artifact, REPOSITORY) as archive:
            with zipfile.ZipFile(archive) as zipped:
                entries = list(members(zipped, max_files=2, max_bytes=1024**2))
                matching = [(name, e) for name, e in entries if name == 'transport-sample.json']
                if len(matching) != 1:
                    raise ValueError('Missing diagnostic transport sample')
                value = json.loads(b''.join(chunks(zipped, matching[0][1])))
        native = [j for j in jobs if j['name'] == value['jobName'] and j['run_id'] == run_id
                  and j['run_attempt'] == value['runAttempt'] and j['head_sha'] == value['revision']]
        if (value.get('runId') != run_id or value.get('revision') != run['head_sha'] or len(native) != 1
                or value.get('schema') != 1 or value.get('kind') != 'finite-release-transport-sample'):
            raise ValueError('Diagnostic sample differs from native job/source')
        job = native[0]
        samples.append({**value, 'jobId': job['id'], 'conclusion': job['conclusion'],
                        'completeJobSeconds': seconds(job['started_at'], job['completed_at']),
                        'nativeArtifact': {k: artifact[k] for k in ('id', 'digest', 'size_in_bytes')}})
    report = assess(samples)
    producers = {canonical_hash(s['producer']): s['producer'] for s in samples if 'producer' in s}
    report['producers'] = []
    for producer in producers.values():
        native = api(f'repos/{REPOSITORY}/actions/runs/{producer["runId"]}/attempts/{producer["runAttempt"]}')
        if native.get('head_sha') != producer['headSha'] or native.get('conclusion') != 'success':
            raise ValueError('Diagnostic producer changed or did not succeed')
        producer_jobs = inventory(api, f'repos/{REPOSITORY}/actions/runs/{producer["runId"]}/attempts/{producer["runAttempt"]}/jobs', 'jobs')
        costs = [seconds(j['started_at'], j['completed_at']) for j in producer_jobs if j.get('conclusion') != 'skipped']
        report['producers'].append({'producer': producer, 'runnerSeconds': sum(costs),
                                    'ociRetentionAndCleanup': 'requires-lifecycle-observation'})
    return report
