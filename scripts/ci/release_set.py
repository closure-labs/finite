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
from urllib.parse import quote

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
            derived_assets=None, evidence_validator=None, phase='publish'):
    """Reconcile remote tags/assets, stage both drafts, then publish both.

    client journal reads return (document-or-None, CAS-version). journal writes
    must reject stale versions. All methods must fail on ambiguous API errors.
    Partial publication is durable and retried without overwriting remote assets.
    """
    if phase not in ('publish', 'stage-publication', 'commit-publication'):
        raise ValueError('Invalid publication phase')
    staging = phase != 'commit-publication'
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

    checkpoint('staging' if staging else 'publishing')
    try:
        for channel in CHANNELS:
            checkpoint('staging' if staging else 'publishing')
            entry = document['payload']['channels'][channel]
            revision = document['payload']['sourceRevision']
            target = client.tag_target(entry['tag'])
            if target is None and staging:
                client.create_tag(entry['tag'], revision)
                target = client.tag_target(entry['tag'])
            if target != revision:
                raise ValueError('Existing tag points at a different revision: ' + entry['tag'])
            release = client.get_release(entry['tag'])
            if release is None and staging:
                client.create_draft(entry['tag'], revision, identity, prerelease=prerelease(document['payload']['version']))
                release = client.get_release(entry['tag'])
            if release is None or release['payloadDigest'] != identity:
                raise ValueError('Release belongs to another payload: ' + entry['tag'])
            if release.get('prerelease') is not prerelease(document['payload']['version']):
                raise ValueError('Remote release type differs from the approved version')
            expected = expected_assets[channel]
            if staging:
                for name, digest in expected.items():
                    stage_asset(client, entry['tag'], revision, identity, name, digest,
                                Path(asset_roots[channel]) / name, expected, checkpoint)
            verify_assets(client.assets(release['id']), expected)
            journal['channels'][channel] = {'releaseId': release['id'],
                                            'state': 'staged' if release['draft'] else 'published'}
            checkpoint('staging' if staging else 'publishing')
        checkpoint('staged' if staging else 'publishing')
        if phase == 'stage-publication':
            return journal
        # Both complete inventories were checked before any public boundary.
        for channel in CHANNELS:
            checkpoint('publishing')
            evidence_validator(channel, Path(asset_roots[channel]),
                               document['payload']['channels'][channel]['assets'], derived_assets[channel])
            entry = document['payload']['channels'][channel]
            release = client.get_release(entry['tag'])
            if (client.tag_target(entry['tag']) != document['payload']['sourceRevision']
                    or release is None or release['payloadDigest'] != identity
                    or release.get('prerelease') is not prerelease(document['payload']['version'])):
                raise ValueError('Release changed since staging')
            verify_assets(client.assets(release['id']), expected_assets[channel])
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


def verify_assets(assets, expected):
    if set(assets) - set(expected):
        raise ValueError('Unexpected remote release assets; inspect the draft without overwriting assets')
    for name, asset in assets.items():
        if asset['state'] != 'uploaded' or asset['digest'] != expected[name]:
            raise ValueError('Remote asset hash mismatch or incomplete upload: ' + name + '; inspect the owned draft')
    if set(assets) != set(expected):
        raise ValueError('Release asset inventory is incomplete; run stage-publication')


def stage_asset(client, tag, revision, identity, name, digest, path, expected, checkpoint):
    """Three single writes, each preceded by reconciliation under the CAS lease.

    subprocess.run waits for (and kills on timeout) the uploader before we read
    state again. Manual concurrent asset editing is unsupported under this lease.
    """
    writes, reconciliations, last_error = 0, 0, None
    while reconciliations < 12:
        reconciliations += 1
        checkpoint('staging')
        release = client.get_release(tag)
        if (release is None or release['payloadDigest'] != identity
                or client.tag_target(tag) != revision):
            raise ValueError('Release ownership or source tag changed: ' + tag)
        assets = client.assets(release['id'])
        if set(assets) - set(expected):
            raise ValueError('Unexpected remote release assets; preserve and inspect the draft')
        for other, item in assets.items():
            if other != name and not (item['state'] == 'starter' and item['size'] == 0 and item['digest'] is None):
                if item['state'] != 'uploaded' or item['digest'] != expected[other]:
                    raise ValueError('Remote asset hash mismatch: ' + other)
        asset = assets.get(name)
        if asset is not None:
            if asset['state'] == 'uploaded' and asset['digest'] == digest:
                return
            placeholder = asset['state'] == 'starter' and asset['size'] == 0 and asset['digest'] is None
            if not release['draft'] or not placeholder:
                raise ValueError('Remote asset hash mismatch or unsafe failed upload: ' + name + '; preserve and inspect asset ' + str(asset['id']))
            # Re-read both the draft and the individual asset immediately before
            # deletion. A changed object is reconciled, never deleted as stale.
            current_release = client.get_release(tag)
            current_asset = client.get_asset(asset['id'])
            if (current_release != release or current_asset != asset
                    or client.tag_target(tag) != revision):
                continue
            client.delete_asset(asset['id'])
            continue
        if not release['draft']:
            raise ValueError('Published release is incomplete; refusing mutation')
        if writes == 3:
            raise RuntimeError('Upload failed after three reconciled attempts: ' + name) from last_error
        writes += 1
        try:
            client.upload(release['id'], path)
        except (RuntimeError, subprocess.SubprocessError) as error:
            last_error = error
        # Even a successful response is followed by a complete remote read.
    raise ValueError('Release asset kept changing; inspect draft before retry: ' + name)


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
                record = self.asset_record(asset)
                if record['name'] in assets:
                    raise ValueError('Duplicate remote asset name')
                assets[record['name']] = record
            if len(batch) < 100:
                return assets
        raise ValueError('Asset lookup exceeded bound')

    @staticmethod
    def asset_record(asset):
        digest = asset.get('digest')
        if (type(asset.get('id')) is not int or asset['id'] <= 0
                or not isinstance(asset.get('name'), str)
                or type(asset.get('size')) is not int or asset['size'] < 0
                or asset.get('state') not in ('starter', 'uploaded')
                or (digest is not None and not re.fullmatch(r'sha256:[0-9a-f]{64}', digest))):
            raise ValueError('Remote asset lacks valid identity, state, size or digest')
        return {key: asset[key] for key in ('id', 'name', 'state', 'size')} | {
            'digest': digest[7:] if digest else None}

    def get_asset(self, asset_id):
        item = self.api('releases/assets/' + str(asset_id), missing=True)
        return self.asset_record(item) if item is not None else None

    def delete_asset(self, asset_id):
        self.api('releases/assets/' + str(asset_id), 'DELETE')

    def upload(self, release_id, path):
        # curl streams the file with retries explicitly disabled. Keep the token
        # out of argv and let the executor reconcile every ambiguous POST.
        token = self.environment.get('GH_TOKEN')
        if not token or any(char in token for char in '\r\n'):
            raise ValueError('Release upload requires a valid scoped token')
        url = (f'https://uploads.github.com/repos/{self.repository}/releases/{release_id}/assets'
               + '?name=' + quote(path.name, safe=''))
        config = 'header = ' + json.dumps('Authorization: Bearer ' + token) + '\n'
        subprocess.run(['curl', '--disable', '--config', '-', '--fail', '--silent', '--show-error',
                        '--retry', '0', '--max-time', '300', '--request', 'POST',
                        '--header', 'Content-Type: application/octet-stream',
                        '--upload-file', str(path), '--output', os.devnull, url],
                       input=config, text=True, check=True, timeout=300, env=self.environment)

    def publish(self, release_id, *, prerelease=False):
        data = {'draft': False, 'prerelease': prerelease}
        if prerelease:
            data['make_latest'] = 'false'
        self.api('releases/' + str(release_id), 'PATCH', data)
