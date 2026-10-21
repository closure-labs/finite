"""Immutable two-channel release plans and resumable, CAS-serialized publication.

The caller supplies approval only after its protected GitHub environment succeeds.
Remote state is reconciled on every retry; the journal is evidence, not authority.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from github_api import get_json
from release_versions import canonical_tag, prerelease

CHANNELS = ('finite', 'finite-dev')
HEX = re.compile(r'[0-9a-f]{64}')
REVISION = re.compile(r'[0-9a-f]{40}')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_payload(payload):
    if set(payload) != {'version', 'sourceRevision', 'channels'}:
        raise ValueError('Unexpected release payload fields')
    if not REVISION.fullmatch(payload['sourceRevision']):
        raise ValueError('Release requires exact source revision')
    if set(payload['channels']) != set(CHANNELS):
        raise ValueError('Release set must include both channels')
    for channel in CHANNELS:
        entry = payload['channels'][channel]
        if set(entry) != {'tag', 'imageDigest', 'isoSha256', 'assets'}:
            raise ValueError('Unexpected channel payload fields')
        if entry['tag'] != canonical_tag(channel, payload['version']):
            raise ValueError('Release tag differs from canonical version')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['imageDigest']):
            raise ValueError('Invalid image digest')
        if not HEX.fullmatch(entry['isoSha256']) or not entry['assets']:
            raise ValueError('Missing qualified ISO or release assets')
        for name, digest in entry['assets'].items():
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,199}', name)
                    or not HEX.fullmatch(digest)):
                raise ValueError('Unsafe asset name or invalid hash')
    return payload


def payload_digest(document):
    if document.get('schema') != 1 or set(document) != {'schema', 'payload', 'evidence'}:
        raise ValueError('Unsupported release-set envelope')
    return hashlib.sha256(canonical(validate_payload(document['payload']))).hexdigest()


def prepare(payload, evidence):
    document = {'schema': 1, 'payload': payload, 'evidence': evidence}
    payload_digest(document)
    validate_evidence(document)
    return document


def validate_evidence(document):
    """Require exact qualified receipts for both channels before any publication.

    Receipt authenticity and freshness are verified by the evidence-producing
    trusted job; this boundary checks the identities survive the artifact handoff.
    """
    payload = document['payload']
    if set(document['evidence']) != set(CHANNELS):
        raise ValueError('Both qualification receipts are required')
    for channel in CHANNELS:
        receipt = document['evidence'][channel]
        entry = payload['channels'][channel]
        expected = {'status': 'qualified', 'sourceRevision': payload['sourceRevision'],
                    'imageDigest': entry['imageDigest'], 'isoSha256': entry['isoSha256']}
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ValueError('Qualification receipt does not match release payload: ' + channel)


def execute(document, client, asset_roots, approved_digest, owner, now=time.time,
            derived_assets=None, evidence_validator=None):
    """Reconcile remote tags/assets, stage both drafts, then publish both.

    client journal reads return (document-or-None, CAS-version). journal writes
    must reject stale versions. All methods must fail on ambiguous API errors.
    Partial publication is durable and retried without overwriting remote assets.
    """
    identity = payload_digest(document)
    if approved_digest != identity:
        raise ValueError('Approval does not cover this immutable release payload')
    validate_evidence(document)
    if (not isinstance(derived_assets, dict) or set(derived_assets) != set(CHANNELS)
            or not callable(evidence_validator)):
        raise ValueError('Publication requires independently verified signed evidence for both channels')
    expected_assets = {}
    for channel in CHANNELS:
        derived = derived_assets[channel]
        if not isinstance(derived, dict) or not {'SHA256SUMS', 'SHA256SUMS.bundle.json'}.issubset(derived):
            raise ValueError('Signed checksums and verification bundle are required')
        core = document['payload']['channels'][channel]['assets']
        if set(core).intersection(derived):
            raise ValueError('Derived evidence cannot replace approved product bytes')
        for name, digest in derived.items():
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,199}', name) or not HEX.fullmatch(digest):
                raise ValueError('Unsafe derived evidence asset')
        expected_assets[channel] = {**core, **derived}
        evidence_validator(channel, Path(asset_roots[channel]), core, derived)
    if not owner or len(owner) > 200:
        raise ValueError('Execution owner is required')
    for channel in CHANNELS:
        for name, digest in expected_assets[channel].items():
            path = Path(asset_roots[channel]) / name
            if path.is_symlink() or not path.is_file() or sha256(path) != digest:
                raise ValueError('Missing or changed release asset: ' + channel + '/' + name)
    # Reserve a version across payload identities too: separate digest journals
    # alone cannot serialize two competing payloads claiming the same tags.
    client.reserve_version(document['payload']['version'], identity)
    journal, version = client.read_journal(identity)
    journal = journal or {'schema': 1, 'payloadDigest': identity, 'state': 'prepared', 'channels': {}}
    if journal.get('schema') != 1 or journal.get('payloadDigest') != identity:
        raise ValueError('Invalid execution journal')
    if journal.get('leaseUntil', 0) > now() and journal.get('owner') != owner:
        raise ValueError('Another executor holds the release-set lease')

    def checkpoint(state):
        nonlocal version
        journal.update(owner=owner, leaseUntil=now() + 900, state=state)
        version = client.write_journal(identity, journal, version)

    checkpoint('staging')
    try:
        for channel in CHANNELS:
            checkpoint('staging')
            entry = document['payload']['channels'][channel]
            revision = document['payload']['sourceRevision']
            target = client.tag_target(entry['tag'])
            if target is None:
                client.create_tag(entry['tag'], revision)
                target = client.tag_target(entry['tag'])
            if target != revision:
                raise ValueError('Existing tag points at a different revision: ' + entry['tag'])
            release = client.get_release(entry['tag'])
            if release is None:
                client.create_draft(entry['tag'], revision, identity, prerelease=prerelease(document['payload']['version']))
                release = client.get_release(entry['tag'])
            if release is None or release['payloadDigest'] != identity:
                raise ValueError('Release belongs to another payload: ' + entry['tag'])
            if release.get('prerelease') is not prerelease(document['payload']['version']):
                raise ValueError('Remote release type differs from the approved version')
            expected = expected_assets[channel]
            remote = client.assets(release['id'])
            if set(remote) - set(expected):
                raise ValueError('Unexpected remote release assets')
            for name, digest in expected.items():
                checkpoint('staging')
                if name in remote:
                    if remote[name] != digest:
                        raise ValueError('Remote asset hash mismatch: ' + name)
                elif release['draft']:
                    client.upload(release['id'], Path(asset_roots[channel]) / name)
                else:
                    raise ValueError('Published release is incomplete; refusing mutation')
            if client.assets(release['id']) != expected_assets[channel]:
                raise ValueError('Uploaded asset set does not match approved payload')
            journal['channels'][channel] = {'releaseId': release['id'],
                                            'state': 'staged' if release['draft'] else 'published'}
            checkpoint('staging')
        # Both images and their assets have been qualified and staged before here.
        for channel in CHANNELS:
            checkpoint('publishing')
            evidence_validator(channel, Path(asset_roots[channel]),
                               document['payload']['channels'][channel]['assets'], derived_assets[channel])
            entry = document['payload']['channels'][channel]
            release = client.get_release(entry['tag'])
            if (client.tag_target(entry['tag']) != document['payload']['sourceRevision']
                    or release['payloadDigest'] != identity or client.assets(release['id']) != expected_assets[channel]
                    or release.get('prerelease') is not prerelease(document['payload']['version'])):
                raise ValueError('Release changed since staging')
            if release['draft']:
                client.publish(release['id'], prerelease=prerelease(document['payload']['version']))
                published = client.get_release(entry['tag'])
                if (published is None or published['draft']
                        or published.get('prerelease') is not prerelease(document['payload']['version'])):
                    raise ValueError('Publication did not complete with the approved release type')
            journal['channels'][channel]['state'] = 'published'
            checkpoint('publishing')
        checkpoint('complete')
    except Exception:
        journal['state'] = 'partial' if any(v.get('state') == 'published' for v in journal['channels'].values()) else 'interrupted'
        raise
    finally:
        journal['leaseUntil'] = 0
        client.write_journal(identity, journal, version)
    return journal


class GitHubClient:
    """GitHub API adapter; journal persists on a dedicated CAS-protected branch."""
    def __init__(self, repository, journal_branch='automation/release-journal', token=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid repository')
        self.repository, self.branch = repository, journal_branch
        self.environment = {**os.environ, **({'GH_TOKEN': token} if token else {})}

    def api(self, endpoint, method='GET', data=None, missing=False):
        path = 'repos/' + self.repository + ('/' + endpoint if endpoint else '')
        if method == 'GET':
            return get_json(path, environment=self.environment, missing=missing)
        command = ['gh', 'api', path, '--method', method]
        if data is not None:
            command += ['--input', '-']
        result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, timeout=120, env=self.environment)
        if result.returncode:
            if missing and '(HTTP 404)' in result.stderr:
                return None
            raise RuntimeError('GitHub API failed: ' + endpoint + ': ' + result.stderr.strip())
        return json.loads(result.stdout) if result.stdout.strip() else None

    def reserve_version(self, version, identity):
        endpoint = 'contents/versions/' + version + '.json'
        existing = self.api(endpoint + '?ref=' + self.branch, missing=True)
        if existing is not None:
            if json.loads(base64.b64decode(existing['content'])).get('payloadDigest') != identity:
                raise ValueError('Release version already reserved by another payload')
            return
        self.ensure_journal_branch()
        try:
            self.api(endpoint, 'PUT', {'message': 'Reserve release ' + version, 'branch': self.branch,
                     'content': base64.b64encode(canonical({'schema': 1, 'payloadDigest': identity})).decode()})
        except RuntimeError:
            # A concurrent reservation may have won. Reconcile, never overwrite.
            existing = self.api(endpoint + '?ref=' + self.branch, missing=True)
            if existing is None or json.loads(base64.b64decode(existing['content'])).get('payloadDigest') != identity:
                raise

    def read_journal(self, identity):
        item = self.api('contents/releases/' + identity + '.json?ref=' + self.branch, missing=True)
        if item is None:
            return None, None
        return json.loads(base64.b64decode(item['content'])), item['sha']

    def ensure_journal_branch(self):
        if self.api('git/ref/heads/' + self.branch, missing=True) is None:
            repository = self.api('')
            head = self.api('git/ref/heads/' + repository['default_branch'])
            try:
                self.api('git/refs', 'POST', {'ref': 'refs/heads/' + self.branch, 'sha': head['object']['sha']})
            except RuntimeError:
                if self.api('git/ref/heads/' + self.branch, missing=True) is None:
                    raise
    def write_journal(self, identity, journal, version):
        self.ensure_journal_branch()
        data = {'message': 'Record release execution ' + identity, 'branch': self.branch,
                'content': base64.b64encode(canonical(journal)).decode()}
        if version:
            data['sha'] = version
        response = self.api('contents/releases/' + identity + '.json', 'PUT', data)
        return response['content']['sha']

    def tag_target(self, tag):
        ref = self.api('git/ref/tags/' + tag, missing=True)
        if ref is None:
            return None
        obj = ref['object']
        for _ in range(5):
            if obj['type'] == 'commit':
                return obj['sha']
            if obj['type'] != 'tag':
                break
            obj = self.api('git/tags/' + obj['sha'])['object']
        raise ValueError('Tag does not resolve to a commit')

    def create_tag(self, tag, revision):
        self.api('git/refs', 'POST', {'ref': 'refs/tags/' + tag, 'sha': revision})

    def get_release(self, tag):
        # Draft lookup via releases/tags is inconsistent before publication.
        for page in range(1, 101):
            releases = self.api('releases?per_page=100&page=' + str(page))
            found = [r for r in releases if r['tag_name'] == tag]
            if len(found) > 1:
                raise ValueError('Duplicate release tag')
            if found:
                item = found[0]
                match = re.search(r'<!-- finite-release-set:([0-9a-f]{64}) -->', item.get('body') or '')
                return {'id': item['id'], 'draft': item['draft'], 'prerelease': item['prerelease'],
                        'payloadDigest': match[1] if match else None}
            if len(releases) < 100:
                return None
        raise ValueError('Release lookup exceeded bound')

    def create_draft(self, tag, revision, identity, *, prerelease=False):
        data = {'tag_name': tag, 'target_commitish': revision,
                 'name': tag, 'draft': True, 'prerelease': prerelease,
                 'body': '<!-- finite-release-set:' + identity + ' -->'}
        if prerelease:
            data['make_latest'] = 'false'
        self.api('releases', 'POST', data)

    def assets(self, release_id):
        assets = {}
        for page in range(1, 101):
            batch = self.api(f'releases/{release_id}/assets?per_page=100&page={page}')
            for asset in batch:
                digest = asset.get('digest') or ''
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or asset['name'] in assets:
                    raise ValueError('Remote asset lacks unique authenticated SHA-256')
                assets[asset['name']] = digest[7:]
            if len(batch) < 100:
                return assets
        raise ValueError('Asset lookup exceeded bound')

    def upload(self, release_id, path):
        release = self.api('releases/' + str(release_id))
        subprocess.run(['gh', 'release', 'upload', release['tag_name'], str(path),
                        '--repo', self.repository], check=True, timeout=300, env=self.environment)

    def publish(self, release_id, *, prerelease=False):
        data = {'draft': False, 'prerelease': prerelease}
        if prerelease:
            data['make_latest'] = 'false'
        self.api('releases/' + str(release_id), 'PATCH', data)
