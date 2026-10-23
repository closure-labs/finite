"""Bounded native stage receipts for read-only cost accounting."""
from contextlib import contextmanager
import json
import resource
import subprocess
import tempfile
import re
import zipfile

from archive_read import authenticate, chunks, members

MAX_ARCHIVE = 8 * 1024**2
MAX_RECEIPTS = 16


@contextmanager
def bounded_reader(artifact, repository):
    with tempfile.TemporaryFile() as archive:
        limit = artifact['size_in_bytes']
        subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, stderr=subprocess.PIPE, check=True, timeout=60,
                       preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)))
        authenticate(archive, artifact)
        yield archive


def join(run, artifacts, reader=bounded_reader):
    selected = [a for a in artifacts if re.fullmatch(
        r'(?:(?:image|security)-finite(?:-dev)?|qualification-phase-finite(?:-dev)?-(?:fresh|upgrade))-'
        + str(run['runId']) + r'-[1-9][0-9]*', a.get('name', ''))]
    run['receiptCoverage'] = {'selected': len(selected), 'read': 0, 'unavailable': [], 'unmatched': 0}
    if len(selected) > MAX_RECEIPTS:
        run['receiptCoverage']['unavailable'].append('receipt-count-bound')
        return
    seen = set()
    for artifact in selected:
        binding = artifact.get('workflow_run', {})
        if (binding.get('id') != run['runId'] or binding.get('head_sha') != run['sourceRevision']
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))):
            raise ValueError('Cost receipt artifact lacks native run/source binding')
        if artifact.get('expired') or not 0 < artifact.get('size_in_bytes', 0) <= MAX_ARCHIVE:
            run['receiptCoverage']['unavailable'].append('expired-or-size-bound')
            continue
        with reader(artifact, run['repository']) as archive:
            with zipfile.ZipFile(archive) as zipped:
                for name, entry in members(zipped, max_files=1024, max_bytes=MAX_ARCHIVE):
                    if name == 'phase-timings.json' and artifact['name'].startswith('security-'):
                        if entry.file_size > 65536:
                            raise ValueError('Oversized security phase receipt')
                        value = json.loads(b''.join(chunks(zipped, entry)))
                        lane = 'finite-dev' if '-finite-dev-' in artifact['name'] else 'finite'
                        candidates = [j for j in run['jobs'] if j['profile'] == lane and j['role'] == 'security'
                                      and str(j['runAttempt']) == artifact['name'].rsplit('-', 1)[1]]
                        reused = value.get('inventoryReused')
                        if len(candidates) == 1 and type(reused) is bool:
                            candidates[0]['inventoryReuse'] = {'eligible': True if reused else None,
                                'hit': True if reused else None, 'missReason': None, 'observedReused': reused}
                        continue
                    if name.endswith('/guest-timings.json'):
                        if entry.file_size > 16384:
                            raise ValueError('Oversized guest timing receipt')
                        value = json.loads(b''.join(chunks(zipped, entry)))
                        phase = 'upgrade' if '-upgrade-' in artifact['name'] else 'fresh'
                        lane = 'finite-dev' if '-finite-dev-' in artifact['name'] else 'finite'
                        candidates = [j for j in run['jobs'] if j['profile'] == lane
                                      and j['role'] == 'qualification-' + phase
                                      and str(j['runAttempt']) == artifact['name'].rsplit('-', 1)[1]]
                        if len(candidates) == 1 and value.get('schema') == 1 and len(value.get('stages', [])) <= 4:
                            for row in value['stages']:
                                if row.get('stage') not in ('startup-checks', 'homebrew-setup', 'predecessor-preparation', 'home-init') or type(row.get('seconds')) is not int or not 0 <= row['seconds'] <= 86400 or type(row.get('status')) is not int:
                                    raise ValueError('Invalid guest timing receipt')
                                candidates[0]['stages'].append({**row, 'nested': True})
                        continue
                    if not name.endswith(('-timings.jsonl', '-stages.jsonl')):
                        continue
                    if entry.file_size > 1024**2:
                        raise ValueError('Oversized stage receipt')
                    raw = b''.join(chunks(zipped, entry))
                    for line in raw.splitlines():
                        receipt = json.loads(line)
                        if receipt.get('kind') != 'finite-stage-timing' or receipt.get('schema') != 1:
                            raise ValueError('Unknown cost stage receipt schema')
                        if (receipt.get('repository') != run['repository']
                                or str(receipt.get('runId')) != str(run['runId'])
                                or receipt.get('revision') != run['sourceRevision']):
                            raise ValueError('Cost receipt differs from native producer')
                        candidates = [j for j in run['jobs'] if j['profile'] == receipt.get('profile')
                                      and str(j['runAttempt']) == str(receipt.get('runAttempt'))
                                      and (j['name'] == receipt.get('jobName') or
                                           receipt.get('jobName') == 'build' and j['role'] == 'build')]
                        if len(candidates) != 1:
                            run['receiptCoverage']['unmatched'] += 1
                            continue
                        job = candidates[0]
                        key = (job['jobId'], receipt.get('stage'), receipt.get('startedAt'))
                        if key in seen:
                            continue
                        seen.add(key)
                        elapsed = receipt.get('seconds')
                        if type(elapsed) not in (int, float) or not 0 <= elapsed <= 86400:
                            raise ValueError('Invalid receipt duration')
                        job.setdefault('stages', []).append(receipt)
                        job['candidateDigest'] = receipt.get('candidateDigest')
                        job['runner']['toolCohort'] = receipt.get('toolCohort')
                        job['runner']['imageVersion'] = receipt.get('runner', {}).get('ImageVersion')
                        if receipt.get('stage') == 'predecessor-iso-reuse':
                            status = receipt.get('status')
                            job['predecessorReuse'] = {'eligible': True,
                                'hit': status == 0 if status in (0, 3) else None,
                                'missReason': 'unavailable' if status == 3 else None}
        run['receiptCoverage']['read'] += 1
