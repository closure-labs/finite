"""Read-only release readiness; evidence and human approval remain separate gates."""
import base64
import json
import re
from pathlib import Path

from github_api import get_json
from security_decisions import canonical_hash, load_json

REPOSITORY = 'closure-labs/finite'
PREFIX = 'repos/' + REPOSITORY
CHANNELS = ('finite', 'finite-dev')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def stable_version(value):
    return isinstance(value, str) and VERSION.fullmatch(value) is not None


def release_status(version, api=get_json, bot=None):
    if not stable_version(version):
        return {'state': 'development', 'reason': 'Development VERSION; choose a numeric MAJOR.MINOR.PATCH to release.'}
    releases = [api(PREFIX + '/releases/tags/' + channel + '-' + version, missing=True) for channel in CHANNELS]
    if all(release is not None and release.get('draft') is False for release in releases):
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
            files = api(PREFIX + f'/pulls/{number}/files?per_page=100')
            if not isinstance(files, list) or len(files) != pull.get('changed_files') or len(files) >= 100:
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
    return {'state': 'unprepared', 'reason': 'Numeric version has no published products or pending paired proposal.'}


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
