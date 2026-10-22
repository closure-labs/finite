"""Read-only release readiness; evidence and human approval remain separate gates."""
import base64
import json
import re
from pathlib import Path

from github_api import get_json
from security_decisions import canonical_hash, load_json
from release_versions import prerelease, release_version, stable_version

REPOSITORY = 'closure-labs/finite'
PREFIX = 'repos/' + REPOSITORY
CHANNELS = ('finite', 'finite-dev')


def published_stable_pair(version, api=get_json):
    """Discover a completed stable pair; this never authorizes product publication."""
    if not stable_version(version):
        return False
    revisions = []
    for channel in CHANNELS:
        tag = channel + '-' + version
        release = api(PREFIX + '/releases/tags/' + tag, missing=True)
        if (release is None or release.get('draft') is not False or release.get('prerelease') is not False
                or release.get('tag_name') != tag or not release.get('published_at')):
            return False
        names = {asset['name'] for asset in release.get('assets', [])}
        if not {'SHA256SUMS', 'SHA256SUMS.bundle.json'} <= names:
            return False
        reference = api(PREFIX + '/git/ref/tags/' + tag, missing=True)
        if reference is None:
            return False
        obj = reference['object']
        for _ in range(5):
            if obj.get('type') == 'commit':
                break
            if obj.get('type') != 'tag' or not re.fullmatch('[0-9a-f]{40}', obj.get('sha', '')):
                raise ValueError('Stable release tag has invalid identity')
            obj = api(PREFIX + '/git/tags/' + obj['sha'])['object']
        if obj.get('type') != 'commit' or not re.fullmatch('[0-9a-f]{40}', obj.get('sha', '')):
            raise ValueError('Stable release tag does not resolve to a commit')
        revisions.append(obj['sha'])
    if len(set(revisions)) != 1:
        raise ValueError('Stable releases identify different source revisions')
    return True


def prerelease_base(version, api=get_json):
    """Require the latest earlier stable patch, including incomplete claims.

    A reserved development version can be skipped without publishing a stable
    version of those bytes. Never skip an incomplete newer stable pair instead.
    """
    if not prerelease(version):
        raise ValueError('Expected a development prerelease')
    major, minor, patch = map(int, version[:-4].split('.'))
    candidates = set()

    def consider(tag):
        for channel in CHANNELS:
            prefix = channel + '-'
            if not tag.startswith(prefix) or not stable_version(tag[len(prefix):]):
                continue
            candidate = tuple(map(int, tag[len(prefix):].split('.')))
            if candidate[:2] == (major, minor) and candidate[2] < patch:
                candidates.add(candidate)

    # Read tokens may not see drafts. The publisher reserves canonical tags
    # before creating drafts, so include tag-only and hidden-draft claims too.
    for channel in CHANNELS:
        refs = api(PREFIX + f'/git/matching-refs/tags/{channel}-{major}.{minor}.')
        if (not isinstance(refs, list) or len(refs) > 1000
                or any(not isinstance(ref, dict) or not isinstance(ref.get('ref'), str)
                       or not ref['ref'].startswith('refs/tags/') for ref in refs)):
            raise ValueError('Invalid bounded stable tag inventory')
        for ref in refs:
            consider(ref['ref'][len('refs/tags/'):])
    for page in range(1, 11):
        releases = api(PREFIX + f'/releases?per_page=100&page={page}')
        if (not isinstance(releases, list) or len(releases) > 100
                or any(not isinstance(item, dict) or not isinstance(item.get('tag_name'), str)
                       for item in releases)):
            raise ValueError('Invalid stable release inventory')
        for item in releases:
            consider(item['tag_name'])
        if len(releases) < 100:
            break
    else:
        raise ValueError('Stable release inventory exceeds bounded pagination')
    if not candidates:
        return None
    baseline = '.'.join(map(str, max(candidates)))
    return baseline if published_stable_pair(baseline, api) else None


def release_status(version, api=get_json, bot=None):
    if not release_version(version):
        return {'state': 'development', 'reason': 'Unsupported VERSION; expected numeric MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-dev.'}
    releases = [api(PREFIX + '/releases/tags/' + channel + '-' + version, missing=True) for channel in CHANNELS]
    if all(release is not None and release.get('draft') is False for release in releases):
        if any(release.get('prerelease', False) != prerelease(version) for release in releases):
            return {'state': 'recovery', 'reason': 'Published release type differs from VERSION; reconcile the original products.'}
        return {'state': 'published', 'reason': 'Both release pages already exist; existing products are immutable.'}
    if any(release is not None for release in releases):
        return {'state': 'recovery', 'reason': 'Existing draft or partial paired release; use approved publication recovery.'}
    # Tags without releases also belong to recovery, never to new products.
    if any(api(PREFIX + '/git/ref/tags/' + channel + '-' + version, missing=True) is not None for channel in CHANNELS):
        return {'state': 'recovery', 'reason': 'Version already has a tag; reconcile the original approved products.'}
    decisions = Path(__file__).resolve().parents[2] / 'automation/decisions/releases'
    for path in sorted(decisions.glob('*.json')):
        proposal = load_json(path)
        if proposal.get('kind') == 'release-set' and proposal.get('payload', {}).get('version') == version:
            if path.stem != canonical_hash(proposal):
                raise ValueError('Release decision filename does not match its content')
            return {'state': 'recorded', 'reason': 'Recorded paired release decision awaits authenticated publication.',
                    'proposalHash': path.stem, 'sourceRevision': proposal['payload']['sourceRevision']}
    if bot:
        pulls = api(PREFIX + '/pulls?state=open&base=main&per_page=100')
        if not isinstance(pulls, list) or len(pulls) >= 100:
            raise ValueError('Release proposal inventory is incomplete')
        for pull in pulls:
            if (pull.get('user', {}).get('login') != bot or pull.get('user', {}).get('type') != 'Bot'
                    or not pull.get('title', '').startswith('Review release-set ')):
                continue
            number, head = pull.get('number'), pull.get('head', {}).get('sha', '')
            if type(number) is not int or not re.fullmatch('[0-9a-f]{40}', head):
                raise ValueError('Invalid release proposal provenance')
            # The list-pulls response has no changed_files count. Authenticate
            # the live PR before checking completeness of its file inventory.
            live = api(PREFIX + f'/pulls/{number}')
            if live.get('state') != 'open' or live.get('base', {}).get('ref') != 'main':
                continue
            if (live.get('head', {}).get('sha') != head or live.get('user', {}).get('login') != bot
                    or live.get('user', {}).get('type') != 'Bot'):
                raise ValueError('Release proposal changed during discovery')
            files = api(PREFIX + f'/pulls/{number}/files?per_page=100')
            if (not isinstance(files, list) or type(live.get('changed_files')) is not int
                    or len(files) != live['changed_files'] or len(files) >= 100):
                raise ValueError('Incomplete release proposal files')
            for entry in files:
                path = entry.get('filename', '')
                if not re.fullmatch(r'automation/decisions/releases/[0-9a-f]{64}\.json', path):
                    continue
                blob = api(PREFIX + '/contents/' + path + '?ref=' + head)
                if (blob.get('encoding') != 'base64' or type(blob.get('size')) is not int
                        or not 0 < blob['size'] <= 8 * 1024 * 1024):
                    raise ValueError('Invalid release proposal blob')
                raw = base64.b64decode(blob['content'].replace('\n', ''), validate=True)
                if len(raw) != blob['size']:
                    raise ValueError('Release proposal size mismatch')
                proposal = json.loads(raw)
                if proposal.get('kind') == 'release-set' and proposal.get('payload', {}).get('version') == version:
                    return {'state': 'review', 'reason': f'Paired release proposal #{number} awaits review or execution.',
                            'pullRequest': number, 'sourceRevision': proposal['payload']['sourceRevision']}
    if prerelease(version) and not prerelease_base(version, api):
        return {'state': 'waiting-stable', 'reason': 'Development prerelease waits for the latest earlier stable paired release.'}
    return {'state': 'unprepared', 'reason': 'Version has no published products or pending paired proposal.'}


def eligible_build(run, jobs, artifacts, revision):
    if (run.get('path') != '.github/workflows/build.yml' or run.get('head_sha') != revision
            or run.get('head_branch') != 'main' or run.get('status') != 'completed'
            or run.get('conclusion') != 'success' or run.get('event') not in ('push', 'schedule', 'workflow_dispatch')
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or type(run.get('id')) is not int or type(run.get('run_attempt')) is not int):
        return False
    # These names and artifact identities are discovery only; preparation still
    # authenticates the complete native evidence and exact product bytes.
    success = {job['name'] for job in jobs if job.get('conclusion') == 'success'}
    for channel in CHANNELS:
        if not {f'Publish ({channel}) / qualification / aggregate', f'Publish ({channel}) / promote'} <= success:
            return False
        name = f'finite-qualified-iso-{channel}-{run["id"]}-{run["run_attempt"]}'
        if not any(item.get('name') == name and item.get('expired') is False for item in artifacts):
            return False
    return True


def root_version(root=None):
    return ((root or Path(__file__).resolve().parents[2]) / 'VERSION').read_text().strip()
