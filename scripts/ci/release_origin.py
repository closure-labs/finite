"""Versioned native producer evidence for release transport, never approval."""
import json
from pathlib import Path
import re
import zipfile

from archive_read import archive_reader, chunks, members
import decision_packets
from security_decisions import canonical_hash

REPOSITORY = 'closure-labs/finite'
MAX_RECEIPT = 1024**2


def artifact_name(producer):
    prefix = 'release-transport-origin' if producer.get('workflow') == 'benchmark-release-transport.yml' else 'release-set-origin'
    return f'{prefix}-{producer["runId"]}-{producer["runAttempt"]}'


def receipt(directory, producer, artifact, packet, job_id):
    """Called only after strict ZIP authentication and successful OCI persistence."""
    files = decision_packets.inventory(directory)
    expected = {'schema': 1, 'producer': producer, 'files': files}
    if packet.get('sha256') != canonical_hash(expected) or packet.get('producer') != producer:
        raise ValueError('Origin receipt packet differs from verified producer/inventory')
    if not decision_packets.REFERENCE.fullmatch(packet.get('reference', '')):
        raise ValueError('Origin receipt requires immutable OCI reference')
    if type(job_id) is not int or job_id <= 0:
        raise ValueError('Origin receipt requires the native producing job')
    return {'schema': 1, 'kind': 'finite-release-product-origin', 'authorizesPublication': False,
            'producer': producer, 'jobId': job_id,
            'sourceRevision': json.loads((Path(directory) / 'release-set.json').read_text())['payload']['sourceRevision'],
            'artifact': {key: artifact[key] for key in ('id', 'name', 'digest', 'size_in_bytes')},
            'packet': {'reference': packet['reference'], 'sha256': packet['sha256']}, 'files': files}


def write(directory, producer, artifact, packet, collection, output, *, diagnostic=False):
    jobs = collection(f'repos/{REPOSITORY}/actions/runs/{producer["runId"]}/attempts/{producer["runAttempt"]}/jobs', 'jobs')
    matches = [j for j in jobs if j.get('name') == ('producer' if diagnostic else 'prepare') and j.get('run_id') == producer['runId']
               and j.get('run_attempt') == producer['runAttempt'] and j.get('head_sha') == producer['headSha']
               and j.get('status') == 'in_progress']
    if len(matches) != 1:
        raise ValueError('Origin receipt must be emitted by the native preparing job')
    value = receipt(directory, producer, artifact, packet, matches[0]['id'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    return value


def verify(directory, manifest, reference, artifact, collection, api, *, cached_archive=None, diagnostic=False):
    """Return false only for an absent legacy receipt; invalid evidence fails closed."""
    producer = manifest['producer']
    run_id, attempt = producer['runId'], producer['runAttempt']
    workflow = 'benchmark-release-transport.yml' if diagnostic else 'release-set.yml'
    if (producer.get('repository') != REPOSITORY or producer.get('workflow') != workflow
            or type(run_id) is not int or run_id <= 0 or type(attempt) is not int or attempt <= 0
            or not re.fullmatch('[0-9a-f]{40}', producer.get('headSha', ''))):
        raise ValueError('Invalid origin producer')
    entries = collection(f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
    matches = [a for a in entries if a.get('name') == artifact_name(producer)]
    if not matches:
        return False
    if len(matches) != 1:
        raise ValueError('Ambiguous origin receipt')
    native = matches[0]
    binding = native.get('workflow_run', {})
    if (native.get('expired') is not False or type(native.get('id')) is not int
            or native['id'] <= 0 or type(native.get('size_in_bytes')) is not int
            or not 0 < native['size_in_bytes'] <= MAX_RECEIPT
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', native.get('digest', ''))
            or binding.get('id') != run_id or binding.get('head_sha') != producer['headSha']):
        raise ValueError('Invalid native origin artifact binding')
    run = api(f'repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}')
    if (run.get('id') != run_id or run.get('run_attempt') != attempt
            or run.get('head_sha') != producer['headSha'] or (not diagnostic and run.get('head_branch') != 'main')
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or run.get('path') != '.github/workflows/' + workflow
            or run.get('event') != 'workflow_dispatch' or run.get('status') != 'completed'
            or run.get('conclusion') != 'success'):
        raise ValueError('Origin producer did not complete the trusted workflow')
    with archive_reader(native, REPOSITORY, cached_archive) as archive:
        with zipfile.ZipFile(archive) as zipped:
            entries = list(members(zipped, max_files=1, max_bytes=MAX_RECEIPT))
            if len(entries) != 1 or entries[0][0] != 'release-set-origin.json':
                raise ValueError('Origin artifact must contain exactly one versioned receipt')
            value = decision_packets.decode_json(b''.join(chunks(zipped, entries[0][1])))
    if not isinstance(value, dict) or set(value) != {'schema', 'kind', 'authorizesPublication', 'producer',
                                                  'jobId', 'sourceRevision', 'artifact', 'packet', 'files'}:
        raise ValueError('Invalid origin receipt schema')
    jobs = collection(f'repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs', 'jobs')
    matching = [j for j in jobs if j.get('id') == value['jobId'] and j.get('name') == ('producer' if diagnostic else 'prepare')
                and j.get('run_id') == run_id and j.get('run_attempt') == attempt
                and j.get('head_sha') == producer['headSha'] and j.get('status') == 'completed'
                and j.get('conclusion') == 'success'
                and all(any(s.get('name') == name and s.get('conclusion') == 'success'
                            for s in j.get('steps', [])) for name in
                        (('Persist authenticated diagnostic packet', 'Retain native diagnostic origin') if diagnostic else
                         ('Propose the single official release approval', 'Retain native release product origin')))]
    packet_identity = canonical_hash({'schema': 1, 'producer': producer, 'files': manifest['files']})
    if (type(value['schema']) is not int or value['schema'] != 1
            or value['kind'] != 'finite-release-product-origin' or value['authorizesPublication'] is not False
            or type(value['jobId']) is not int or value['jobId'] <= 0
            or value['producer'] != producer
            or value['sourceRevision'] != (json.loads((Path(directory) / 'release-set.json').read_text())['payload']['sourceRevision'] if diagnostic else producer['headSha'])
            or value['artifact'] != {key: artifact[key] for key in ('id', 'name', 'digest', 'size_in_bytes')}
            or value['packet'] != {'reference': reference, 'sha256': packet_identity}
            or value['files'] != manifest['files'] or len(matching) != 1):
        raise ValueError('Origin receipt differs from native producer or immutable products')
    # OCI fetch already checks these. Recheck when renewing credentials with staged products.
    files = {}
    directory = Path(directory)
    for path in directory.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('Unsafe staged origin product')
        if path.is_file() and path.relative_to(directory).as_posix() != 'decision-packet.json':
            name = decision_packets.safe_name(path.relative_to(directory).as_posix())
            files[name] = {'sha256': decision_packets.file_hash(path), 'size': path.stat().st_size}
    if files != value['files']:
        raise ValueError('Origin products changed after OCI transport')
    return True
