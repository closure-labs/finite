"""Protected default-branch decision proposals; no scan result grants human approval."""
import importlib.util
import html
from datetime import datetime, timezone
import resource
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from github_api import GitHubReadError, get_json
import decision_packets
from security_decisions import canonical_hash, load_json, normalize_findings, compare_findings, validate_normalized

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'closure-labs/finite'
PROFILES = ('finite', 'finite-dev')
PRODUCERS = {'build.yml': {'push', 'schedule', 'workflow_dispatch'},
             'image-security.yml': {'schedule', 'workflow_dispatch'},
             'release-set.yml': {'workflow_dispatch'}}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


authority = module('controller_authority', ROOT / 'scripts/ci/decision-authority.py')


def api(path, method='GET', payload=None):
    if method == 'GET':
        try:
            return get_json(path)
        except GitHubReadError as error:
            raise ValueError(str(error)) from error
    args = ['gh', 'api', '--method', method, path]
    if payload is not None:
        args += ['--input', '-']
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=90, check=False)
    if result.returncode:
        raise ValueError('GitHub decision API failed: ' + path.split('?')[0])
    return json.loads(result.stdout) if result.stdout else None


def collection(path, key=None):
    values = []
    for page in range(1, 11):
        result = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        items = result[key] if key else result
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError('Invalid bounded API collection')
        values.extend(items)
        if len(items) < 100:
            return values
    raise ValueError('Decision collection exceeds bounded pagination')


def producer(run_id, allowed=None):
    if type(run_id) is not int or run_id <= 0:
        raise ValueError('Invalid producer run ID')
    run = api(f'repos/{REPOSITORY}/actions/runs/{run_id}')
    workflow = run.get('path', '').removeprefix('.github/workflows/')
    if (workflow not in (allowed or PRODUCERS) or run.get('event') not in PRODUCERS[workflow]
            or run.get('head_branch') != 'main' or run.get('status') != 'completed'
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or not re.fullmatch(r'[0-9a-f]{40}', run.get('head_sha', ''))
            or type(run.get('run_attempt')) is not int or run['run_attempt'] < 1
            or run.get('id') != run_id):
        raise ValueError('Evidence producer is not a completed trusted main workflow')
    return {'repository': REPOSITORY, 'workflow': workflow, 'runId': run_id,
            'runAttempt': run['run_attempt'], 'headSha': run['head_sha'], 'artifacts': []}


def producer_window(origin):
    run = api(f'repos/{REPOSITORY}/actions/runs/{origin["runId"]}')
    if (run.get('id') != origin['runId'] or run.get('run_attempt') != origin['runAttempt']
            or run.get('head_sha') != origin['headSha'] or run.get('status') != 'completed'):
        raise ValueError('Producer changed while authenticating scan time')
    def timestamp(value):
        if not isinstance(value, str):
            raise ValueError('Producer timestamps are required')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Producer timestamp requires timezone')
        return parsed.astimezone(timezone.utc)
    start, end = timestamp(run.get('created_at')), timestamp(run.get('updated_at'))
    if start > end or end > datetime.now(timezone.utc):
        raise ValueError('Invalid authoritative producer time window')
    return start, end


def artifact_clock(artifact, window):
    value = artifact.get('created_at')
    if not isinstance(value, str):
        raise ValueError('Authenticated artifact upload timestamp is required')
    produced = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if produced.tzinfo is None or not window[0] <= produced <= window[1]:
        raise ValueError('Artifact upload is outside authenticated producer window')
    return produced


def native_observation_policy(policy, path):
    """Use cutover-identical observations without enabling admission or legacy AI waivers.

    Only native-health settings survive the projection. Legacy risk decisions may
    be stale or malformed and cannot classify, suppress or approve fresh findings.
    """
    source = load_json(path)
    legacy_fields = {'maxExceptionDays', 'blockedFixableSeverities', 'blockKnownExploited',
                     'exceptions', 'seriousAdvisories', 'reviewedDispositions', 'releaseBlockers',
                     'blockingBasis', 'confirmedDesktopRisks'}
    if (not isinstance(source, dict) or type(source.get('schema')) is not int or source['schema'] != 1
            or not isinstance(source.get('mode', 'fixable-severity'), str)
            or source.get('mode', 'fixable-severity') not in {'fixable-severity', *policy.RISK_MODES}
            or set(source) - (policy.DECISION_FIELDS | legacy_fields)):
        raise ValueError('Decision observations require a supported checked native-health policy')
    if source.get('mode') == policy.DECISION_MODE and set(source) != policy.DECISION_FIELDS:
        raise ValueError('Active maintainer policy must contain only native-health fields')
    required = policy.DECISION_FIELDS - {'mode'}
    if not required <= set(source):
        raise ValueError('Decision observations require every explicit native-health field')
    config = {key: source[key] for key in required}
    config['mode'] = policy.DECISION_MODE
    policy.validate_policy(config)
    return config


def native_result(directory, produced_at=None, not_before=None, profile=None):
    """Reevaluate original native bytes; a stored status is never a health receipt."""
    policy = module('controller_security_policy', ROOT / 'scripts/bluebuild/security-policy.py')
    original = load_json(directory / 'security-result.json')
    if original.get('status') not in ('pass', 'blocked', 'complete') or (original.get('status') == 'complete' and original.get('scannerHealth') != 'healthy'):
        raise ValueError('Producer did not complete a technically healthy native scan')
    image = original['image']
    config = native_observation_policy(policy, ROOT / 'automation/security/image-policy.json')
    manifests = policy.read_manifests(directory)
    baseline = policy.production_baseline(directory, image, config, manifests, policy.read_baseline(directory))
    if profile is not None and (not isinstance(baseline, dict) or baseline.get('profile') != profile):
        raise ValueError('Native image profile differs from the authenticated artifact channel')
    scan = load_json(directory / 'vulnerabilities.json')
    if produced_at is not None:
        scanned = policy.timestamp(scan['descriptor']['timestamp'])
        if not_before is None or not not_before <= scanned <= produced_at:
            raise ValueError('Scan timestamp is outside authenticated run/upload window')
    return policy.evaluate(load_json(directory / 'sbom.syft.json'),
                           scan, image, config, now=produced_at,
                           database_coverage=load_json(directory / 'database-coverage.json'),
                           manifests=manifests, approved_baseline=baseline)


class ConsolidationRequired(ValueError):
    def __init__(self, origin):
        super().__init__('A single-profile producer needs a complete two-profile scan')
        self.origin = origin


class NoImageWork(ValueError):
    def __init__(self, origin):
        super().__init__('Trusted build intentionally skipped image production')
        self.origin = origin


def skipped_image_work(origin):
    """Prove this exact build attempt selected no images; absent archives alone cannot."""
    jobs = collection(f'repos/{REPOSITORY}/actions/runs/{origin["runId"]}/attempts/{origin["runAttempt"]}/jobs', 'jobs')
    by_name = {}
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get('name'), str)
                or job['name'] in by_name or job.get('run_id') != origin['runId']
                or job.get('run_attempt') != origin['runAttempt'] or job.get('head_sha') != origin['headSha']
                or job.get('status') != 'completed' or job.get('conclusion') not in ('success', 'skipped')):
            raise ValueError('Cannot authenticate successful no-image build job inventory')
        by_name[job['name']] = job
    skipped = {'Validate (${{ matrix.profile }})', 'Publish (${{ matrix.profile }})'}
    if any(name.startswith(('Publish (', 'Validate (')) and name not in skipped for name in by_name):
        return False
    return (all(by_name.get(name, {}).get('conclusion') == 'skipped' for name in skipped)
            and all(by_name.get(name, {}).get('conclusion') == 'success'
                    for name in ('Select checks', 'Documentation checks', 'CI gate')))


def artifacts_for(origin, artifacts, profiles=PROFILES):
    """Require both profile archives from the exact trusted run and attempt."""
    result = {}
    seen = set()
    for profile in profiles:
        prefix = 'security' if origin['workflow'] == 'build.yml' else 'published-security'
        name = f'{prefix}-{profile}-{origin["runId"]}-{origin["runAttempt"]}'
        selected = [a for a in artifacts if isinstance(a, dict) and a.get('name') == name]
        if len(selected) != 1:
            raise ValueError('Both exact profile scan artifacts are required')
        artifact = selected[0]
        if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
                or artifact['id'] < 1 or artifact['id'] in seen
                or artifact.get('workflow_run', {}).get('id') != origin['runId']
                or artifact.get('workflow_run', {}).get('head_sha') != origin['headSha']
                or type(artifact.get('size_in_bytes')) is not int
                or not 0 < artifact['size_in_bytes'] <= 512 * 1024**2
                or not isinstance(artifact.get('digest'), str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])):
            raise ValueError('Scan artifact lacks exact immutable producer binding')
        seen.add(artifact['id'])
        result[profile] = artifact
    return result


def extract_artifact(artifact, target):
    reuse = module('controller_reuse_security', ROOT / 'scripts/ci/reuse-candidate-security.py')
    target.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryFile() as archive:
        def restrict_archive():
            resource.setrlimit(resource.RLIMIT_FSIZE, (artifact['size_in_bytes'], artifact['size_in_bytes']))
        subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
                       stdout=archive, check=True, timeout=300, preexec_fn=restrict_archive)
        archive.seek(0)
        # This checks the downloaded ZIP size and SHA256 against GitHub, then
        # extracts only fixed regular native filenames with expansion bounds.
        reuse.extract(archive, artifact, target)


def collect(run_id, directory):
    """Authenticate both same-attempt artifact bytes before proposing a decision."""
    origin = producer(run_id, {'build.yml', 'image-security.yml'})
    artifacts = collection(f'repos/{REPOSITORY}/actions/runs/{run_id}/artifacts', 'artifacts')
    if (origin['workflow'] == 'build.yml'
            and not any(isinstance(a, dict) and isinstance(a.get('name'), str)
                        and a['name'].startswith('security-') for a in artifacts)
            and skipped_image_work(origin)):
        raise NoImageWork(origin)
    expected = {profile: f'security-{profile}-{run_id}-{origin["runAttempt"]}' for profile in PROFILES}
    present = [profile for profile, name in expected.items()
               if sum(isinstance(a, dict) and a.get('name') == name for a in artifacts) == 1]
    missing = [profile for profile, name in expected.items()
               if not any(isinstance(a, dict) and a.get('name') == name for a in artifacts)]
    if origin['workflow'] == 'build.yml' and len(present) == 1 and len(missing) == 1:
        raise ConsolidationRequired(origin)
    selected = artifacts_for(origin, artifacts)
    window = producer_window(origin)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    findings = []
    for profile, artifact in selected.items():
        target = directory / profile
        extract_artifact(artifact, target)
        if has_reused_evidence(target):
            # Current health and live authority may cover reused bytes. They
            # cannot establish a new historical producer-time approval packet.
            result = native_result(target, profile=profile)
        else:
            result = native_result(target, artifact_clock(artifact, window), window[0], profile=profile)
        findings.extend(normalize_findings(result, profile))
        origin['artifacts'].append({k: artifact[k] for k in ('id', 'name', 'digest')})
    return origin, findings


def has_reused_evidence(directory):
    # Presence is only a conservative refresh signal, never authority.
    return any((Path(directory) / name).exists() for name in
               ('original-security-result.json', 'reuse-provenance.json'))


def request_fresh_scans(origin):
    """Uncovered reused bytes need a fresh two-profile snapshot, not an inferred chain."""
    trusted_context()
    require_live_authority_rule()
    live = producer(origin['runId'], {'build.yml'})
    if any(live[key] != origin[key] for key in ('repository', 'workflow', 'runId', 'runAttempt', 'headSha')):
        raise ValueError('Producer changed before fresh consolidated scan request')
    # Omitting resume inputs runs the native scanners for both channels. This
    # new run produces no security-reuse metadata, so it cannot recurse here.
    api(f'repos/{REPOSITORY}/actions/workflows/build.yml/dispatches', 'POST',
        {'ref': 'main', 'inputs': {'target': 'automatic', 'reconcile': 'false'}})
    return {'schema': 1, 'status': 'fresh-scans-required', 'sourceRun': live['runId'],
            'requestedProfiles': list(PROFILES), 'authorizesPublication': False}


def decision_ids():
    import security_admission
    directory = ROOT / 'automation/decisions/security'
    if directory.is_symlink():
        raise ValueError('Decision ledger cannot be a symlink')
    paths = sorted(directory.glob('*.json')) if directory.exists() else []
    if len(paths) > 10000:
        raise ValueError('Decision ledger exceeds record bound')
    result = []
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024**2:
            raise ValueError('Decision record must be a bounded regular file')
        proposal = load_json(path)
        security_admission.validate_proposal(proposal, REPOSITORY)
        identity = canonical_hash(proposal)
        if path.name != identity + '.json':
            raise ValueError('Decision record filename differs from canonical identity')
        result.append(identity)
    return result


def current_admission(directory):
    """Never create another approval request when live authority covers both scans."""
    import security_admission
    bot = os.environ.get('FINITE_REVIEW_BOT_LOGIN')
    authority.validate_context(REPOSITORY, bot)
    result = {}
    for profile in PROFILES:
        # This is a newly collected scan; publication-style current freshness
        # applies here. The PR check separately supports historical snapshots.
        native = native_result(Path(directory) / profile, profile=profile)
        try:
            result[profile] = security_admission.verify(native, profile, REPOSITORY, bot)
        except security_admission.authority.HumanDecisionRequired as error:
            # Lost/dismissed authorization needs a new human decision. API,
            # integrity and configuration errors must continue to fail closed.
            result[profile] = {'status': 'review-required', 'reason': str(error)}
    return result


def pending_proposal(findings, supersedes):
    """Deduplicate requests only; an unmerged PR never authorizes publication."""
    bot = os.environ.get('FINITE_REVIEW_BOT_LOGIN')
    authority.validate_context(REPOSITORY, bot)
    validate_normalized(findings)
    pulls = collection(f'repos/{REPOSITORY}/pulls?state=open&base=main')
    for pull in pulls:
        if (not isinstance(pull, dict) or pull.get('user', {}).get('type') != 'Bot'
                or pull['user'].get('login') != bot or pull.get('state') != 'open'
                or pull.get('base', {}).get('ref') != 'main'
                or pull.get('head', {}).get('repo', {}).get('full_name') != REPOSITORY):
            continue
        number, head = pull.get('number'), pull.get('head', {}).get('sha')
        if type(number) is not int or not isinstance(head, str) or not re.fullmatch(r'[0-9a-f]{40}', head):
            raise ValueError('Invalid pending proposal PR identity')
        files = collection(f'repos/{REPOSITORY}/pulls/{number}/files')
        if len(files) != 1 or files[0].get('status') != 'added':
            continue
        path = files[0].get('filename', '')
        if not re.fullmatch(r'automation/decisions/security/[0-9a-f]{64}\.json', path):
            continue
        proposal = authority.document_at(api, REPOSITORY, path, head)
        if authority.proposal_path(proposal) != path or proposal['kind'] != 'security-findings':
            continue
        payload = proposal['payload']
        if (payload.get('profiles') != list(PROFILES) or payload.get('disposition') != 'accepted'
                or not isinstance(payload.get('supersedes'), list)
                or not set(supersedes).issubset(payload['supersedes'])):
            continue
        comparison = compare_findings(findings, payload.get('findings'))
        if not comparison['new'] and not comparison['worsened']:
            return {'status': 'pending-review', 'pullRequest': pull.get('html_url'),
                    'proposalHash': canonical_hash(proposal), 'authorizesPublication': False}
    return None


def request_consolidation(origin):
    """One full build after a proven single-profile run; never retry a failed full build."""
    trusted_context()
    require_live_authority_rule()
    live = producer(origin['runId'], {'build.yml'})
    if any(live[key] != origin[key] for key in ('repository', 'workflow', 'runId', 'runAttempt', 'headSha')):
        raise ValueError('Single-profile producer changed before consolidation')
    jobs = collection(f'repos/{REPOSITORY}/actions/runs/{live["runId"]}/attempts/{live["runAttempt"]}/jobs', 'jobs')
    intended = set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get('name'), str):
            raise ValueError('Invalid intended-profile job inventory')
        match = re.match(r'^Publish \(([^)]+)\) / ', job['name'])
        if match:
            if (match[1] not in PROFILES or job.get('run_id') != live['runId']
                    or job.get('run_attempt') != live['runAttempt'] or job.get('head_sha') != live['headSha']):
                raise ValueError('Publication job has ambiguous source/attempt identity')
            intended.add(match[1])
    if len(intended) != 1:
        raise ValueError('Missing profile evidence is a technical failure of a full build, not a consolidation request')
    profile = next(iter(intended))
    builds = [j for j in jobs if j['name'] == f'Publish ({profile}) / build / build']
    scans = [j for j in jobs if j['name'] == f'Publish ({profile}) / security']
    if (len(builds) != 1 or builds[0].get('status') != 'completed' or builds[0].get('conclusion') != 'success'
            or len(scans) != 1 or scans[0].get('status') != 'completed'):
        raise ValueError('Single-profile build/scan did not complete and cannot request consolidation')
    artifacts = collection(f'repos/{REPOSITORY}/actions/runs/{live["runId"]}/artifacts', 'artifacts')
    selected = artifacts_for(live, artifacts, (profile,))
    window = producer_window(live)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / profile
        artifact = selected[profile]
        extract_artifact(artifact, directory)
        native = (native_result(directory, profile=profile) if has_reused_evidence(directory) else
                  native_result(directory, artifact_clock(artifact, window), window[0], profile=profile))
        normalize_findings(native, profile)
        import security_admission
        try:
            admission = security_admission.verify(native, profile, REPOSITORY,
                                                  os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
        except security_admission.authority.HumanDecisionRequired:
            admission = {'status': 'review-required'}
        if admission.get('status') == 'covered':
            return {'schema': 1, 'status': 'covered', 'profiles': [profile], 'proposalRequired': False}
    # Manual automatic selection has no revision comparison, and therefore
    # selects both profiles. Any subsequent missing scan has both intended
    # jobs and fails the single-profile predicate above, stopping recursion.
    api(f'repos/{REPOSITORY}/actions/workflows/build.yml/dispatches', 'POST',
        {'ref': 'main', 'inputs': {'target': 'automatic', 'reconcile': 'false'}})
    return {'schema': 1, 'status': 'consolidation-required', 'sourceRun': live['runId'],
            'requestedProfiles': list(PROFILES)}


def validate_proposal_packet(proposal):
    """New security proposals bind complete observations to live producer provenance."""
    if proposal.get('kind') == 'release-set':
        # Release core identity is independently validated; evidence refresh is separate.
        import release_set
        release_set.validate_payload(proposal['payload'])
        return
    import security_admission
    security_admission.validate_proposal(proposal, REPOSITORY)
    if proposal.get('kind') == 'security-revocation':
        import decision_revocation
        decision_revocation.validate(proposal, REPOSITORY, os.environ.get('FINITE_REVIEW_BOT_LOGIN'),
                                     ROOT / 'automation/decisions/security', github=api)
        return
    payload = proposal['payload']
    if (set(payload) != {'profiles', 'findings', 'disposition', 'supersedes', 'packet', 'rationale'}
            or payload['profiles'] != list(PROFILES) or payload['disposition'] not in ('accepted', 'rejected', 'revoked')
            or not isinstance(payload['rationale'], str) or not payload['rationale'].strip()
            or not isinstance(payload['supersedes'], list)
            or any(not re.fullmatch(r'[0-9a-f]{64}', p) for p in payload['supersedes'])):
        raise ValueError('Unsupported complete security decision proposal')
    packet = payload['packet']
    live = producer(packet['producer']['runId'], {'build.yml', 'image-security.yml'})
    for key in ('repository', 'workflow', 'runId', 'runAttempt', 'headSha'):
        if live[key] != packet['producer'][key]:
            raise ValueError('Proposal producer identity changed')
    artifacts = collection(f'repos/{REPOSITORY}/actions/runs/{live["runId"]}/artifacts', 'artifacts')
    selected = artifacts_for(live, artifacts)
    window = producer_window(live)
    exact = [{key: artifact[key] for key in ('id', 'name', 'digest')}
             for artifact in selected.values()]
    if packet['producer']['artifacts'] != exact:
        raise ValueError('Proposal must bind both exact unexpired profile artifacts')
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / 'packet'
        manifest = decision_packets.fetch(packet['reference'], directory, packet['sha256'])
        if manifest['producer'] != packet['producer']:
            raise ValueError('Packet producer differs from proposal')
        current = []
        for profile, artifact in selected.items():
            original = Path(temporary) / ('authenticated-' + profile)
            extract_artifact(artifact, original)
            native = directory / profile
            if decision_packets.inventory(native) != decision_packets.inventory(original):
                raise ValueError('Packet native bytes differ from authenticated Actions archive')
            current.extend(normalize_findings(native_result(original, artifact_clock(artifact, window), window[0], profile=profile), profile))
        # Extra root/member files cannot smuggle alternative evidence or profiles.
        expected_files = {f'{profile}/{name}': item for profile in PROFILES
                          for name, item in decision_packets.inventory(directory / profile).items()}
        if manifest['files'] != expected_files:
            raise ValueError('Security packet contains unexpected profile or root evidence')
        if canonical_hash(current) != canonical_hash(payload['findings']):
            raise ValueError('Proposed risk ceilings differ from authenticated native evidence')


def trusted_context():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Decision mutation requires the protected default branch')


def require_live_authority_rule():
    """Never autoqueue a decision until the required check is bound to our App."""
    configured = os.environ.get('FINITE_REVIEW_APP_ID', '')
    if not re.fullmatch(r'[1-9][0-9]*', configured):
        raise ValueError('Configured numeric review App ID is required before proposing')
    app_id = int(configured)
    rules = api(f'repos/{REPOSITORY}/rules/branches/main')
    if not isinstance(rules, list):
        raise ValueError('Cannot inspect effective main rules')
    required = [rule for rule in rules if isinstance(rule, dict) and rule.get('type') == 'required_status_checks']
    bound = any(any(check.get('context') == 'Maintainer decision authority'
                    and check.get('integration_id') == app_id
                    for check in rule.get('parameters', {}).get('required_status_checks', []))
                for rule in required)
    queues = [rule.get('parameters', {}) for rule in rules if isinstance(rule, dict) and rule.get('type') == 'merge_queue']
    if not bound or not queues or any(queue.get('max_entries_to_build') != 1
                                      or queue.get('max_entries_to_merge') != 1 for queue in queues):
        raise ValueError('Main requires the configured App authority check and single-PR merge queue before proposing')
    return app_id


def safe_markdown(value):
    # Render untrusted scan/rationale text inertly; prevent HTML, tables,
    # new commands on their own line, mentions, links and code delimiters.
    value = html.escape(str(value), quote=True).replace('\r', ' ').replace('\n', ' ')
    return value.replace('|', '&#124;').replace('`', '&#96;').replace('@', '&#64;').replace('[', '&#91;').replace(']', '&#93;')


def summary(proposal):
    payload = proposal['payload']
    lines = ['Super Admin team decision required. Approve this exact PR head to authorize the proposed scope.',
             '', 'Proposal SHA256: `' + canonical_hash(proposal) + '`', '']
    if proposal['kind'] == 'release-set':
        lines += ['Official version: ' + payload['version'], '',
                  '| Channel | Immutable image | Qualified ISO SHA256 |', '| --- | --- | --- |']
        for profile in PROFILES:
            entry = payload['channels'][profile]
            lines.append(f'| {profile} | `{entry["imageDigest"]}` | `{entry["isoSha256"]}` |')
    else:
        priorities = {'Critical': 0, 'High': 1, 'Unknown': 2, 'Medium': 3, 'Low': 4, 'Negligible': 5}
        lines += ['Proposed disposition: **' + payload['disposition'] + '**', '', safe_markdown(payload['rationale'][:4000]), '',
                  f'Total normalized findings: {len(payload["findings"])}. All severities require review.', '',
                  '| Profile | Findings by severity |', '| --- | --- |']
        for profile in PROFILES:
            counts = {}
            for finding in payload['findings']:
                if finding['profile'] == profile:
                    counts[finding['severity']] = counts.get(finding['severity'], 0) + 1
            description = ', '.join(f'{severity}: {counts[severity]}' for severity in sorted(counts, key=priorities.get))
            lines.append('| ' + profile + ' | ' + (description or '0') + ' |')
        lines += ['', '| Profile | Vulnerability | Severity | CVSS | Known exploited | Component |',
                  '| --- | --- | --- | --- | --- | --- |']
        prioritized = sorted(payload['findings'], key=lambda f: (
            not f['knownExploited'], priorities[f['severity']], f['profile'], f['advisory'], f['component']))
        displayed = 0
        for finding in prioritized[:150]:
            advisory = finding['advisory']
            link = f'[{advisory}](https://nvd.nist.gov/vuln/detail/{advisory})' if re.fullmatch(r'CVE-[0-9]{4}-[0-9]+', advisory) else safe_markdown(advisory)
            if re.fullmatch(r'GHSA-[a-z0-9-]+', advisory):
                link = f'[{advisory}](https://github.com/advisories/{advisory})'
            component = safe_markdown(finding['component'][:240])
            score = str(finding['cvss']) if finding['cvss'] is not None else 'Unknown'
            exploited = 'Yes' if finding['knownExploited'] else 'No'
            row = f'| {safe_markdown(finding["profile"])} | {link} | {safe_markdown(finding["severity"])} | {score} | {exploited} | {component} |'
            if sum(len(line) + 1 for line in lines) + len(row) > 50000:
                break
            lines.append(row)
            displayed += 1
        lines += ['', f'Showing {displayed} of {len(payload["findings"])} findings, prioritizing known exploitation, Critical and High severity.',
                  'The Files changed tab and immutable scan packet contain the complete findings.',
                  '', 'Full hash-bound scan packet: `' + payload['packet']['reference'] + '`']
    lines += ['', 'Approval is persistent until changed or revoked. Scanner errors and missing coverage cannot be accepted.',
              'A new PR head invalidates previous approval. Only current closure-labs/super-admins members with maintain/admin access count; bots and AI review labels cannot approve this decision.']
    return '\n'.join(lines)


def release_scan_summary(directory):
    """Keep the release reviewer informed without granting vulnerability acceptance."""
    findings = load_json(Path(directory) / 'findings.json')
    validate_normalized(findings)
    if any(f['profile'] not in PROFILES for f in findings):
        raise ValueError('Release scan findings identify an unsupported profile')
    lines = ['', 'Native scan snapshot (risk acceptance is verified separately):', '',
             '| Profile | Findings by severity |', '| --- | --- |']
    for profile in PROFILES:
        counts = {}
        for finding in findings:
            if finding['profile'] == profile:
                counts[finding['severity']] = counts.get(finding['severity'], 0) + 1
        lines.append('| ' + profile + ' | ' + (', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) or '0') + ' |')
    advisories = sorted({f['advisory'] for f in findings})
    links = []
    for advisory in advisories[:150]:
        if re.fullmatch(r'CVE-[0-9]{4}-[0-9]+', advisory):
            links.append(f'[{advisory}](https://nvd.nist.gov/vuln/detail/{advisory})')
        elif re.fullmatch(r'GHSA-[a-z0-9-]+', advisory):
            links.append(f'[{advisory}](https://github.com/advisories/{advisory})')
        else:
            links.append(safe_markdown(advisory))
    if links:
        lines += ['', ', '.join(links)]
    lines += ['', 'The immutable packet contains the complete findings, components, versions and locations.']
    return '\n'.join(lines)


def proposal_branch(proposal, path, branch):
    """Recover a branch left by an interrupted PR creation without overwriting it."""
    from release_set import GitHubClient
    existing = GitHubClient(REPOSITORY).api('git/ref/heads/' + branch, missing=True)
    if existing is not None:
        head = existing.get('object', {}).get('sha', '')
        if (not re.fullmatch(r'[0-9a-f]{40}', head)
                or canonical_hash(authority.document_at(api, REPOSITORY, path, head)) != canonical_hash(proposal)):
            raise ValueError('Existing proposal branch differs from immutable decision')
        return
    main = api(f'repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']
    base = api(f'repos/{REPOSITORY}/git/commits/{main}')
    tree = api(f'repos/{REPOSITORY}/git/trees', 'POST', {'base_tree': base['tree']['sha'],
               'tree': [{'path': path, 'mode': '100644', 'type': 'blob',
                         'content': json.dumps(proposal, indent=2) + '\n'}]})
    commit = api(f'repos/{REPOSITORY}/git/commits', 'POST',
                 {'message': 'review: maintainer decision ' + canonical_hash(proposal)[:12], 'tree': tree['sha'], 'parents': [main]})
    api(f'repos/{REPOSITORY}/git/refs', 'POST', {'ref': 'refs/heads/' + branch, 'sha': commit['sha']})


def cutover_scope(config, head, main):
    """A recovered cutover branch may change only the fixed regular policy file."""
    path = 'automation/security/image-policy.json'
    if not isinstance(head, str) or not re.fullmatch(r'[0-9a-f]{40}', head):
        raise ValueError('Cutover branch lacks immutable head identity')
    comparison = api(f'repos/{REPOSITORY}/compare/{main}...{head}')
    files = comparison.get('files') if isinstance(comparison, dict) else None
    total = comparison.get('total_commits') if isinstance(comparison, dict) else None
    if (not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict) or files[0].get('filename') != path
            or files[0].get('status') != 'modified' or files[0].get('previous_filename')
            or type(total) is not int or not 1 <= total <= 100
            or not isinstance(comparison.get('commits'), list) or len(comparison['commits']) != total):
        raise ValueError('Cutover branch must contain only the fixed policy change with complete comparison evidence')
    tree = api(f'repos/{REPOSITORY}/git/trees/{head}?recursive=1')
    if not isinstance(tree, dict) or tree.get('truncated') is not False or not isinstance(tree.get('tree'), list):
        raise ValueError('Cutover branch requires a complete Git tree')
    matching = [entry for entry in tree['tree'] if isinstance(entry, dict) and entry.get('path') == path]
    if len(matching) != 1 or matching[0].get('type') != 'blob' or matching[0].get('mode') != '100644':
        raise ValueError('Cutover policy must be one regular nonexecutable Git file')
    if canonical_hash(authority.document_at(api, REPOSITORY, path, head)) != canonical_hash(config):
        raise ValueError('Cutover branch policy differs from exact generated native-health configuration')


def propose_cutover(run_id, directory):
    """Create only a human-reviewable policy activation PR after both images are covered."""
    trusted_context()
    require_live_authority_rule()
    bot = os.environ.get('FINITE_REVIEW_BOT_LOGIN')
    authority.validate_context(REPOSITORY, bot)
    if type(run_id) is not int or run_id < 1:
        raise ValueError('Cutover requires a positive trusted producer run')
    path = 'automation/security/image-policy.json'
    source = load_json(ROOT / path)
    policy = module('cutover_native_policy', ROOT / 'scripts/bluebuild/security-policy.py')
    config = native_observation_policy(policy, ROOT / path)
    if source.get('mode') == policy.DECISION_MODE:
        return {'status': 'already-active', 'policyChanged': False}
    collect(run_id, Path(directory))
    def require_covered():
        admissions = current_admission(directory)
        if set(admissions) != set(PROFILES) or any(admissions[p].get('status') != 'covered' for p in PROFILES):
            raise ValueError('Cutover requires current healthy scans and live human-covered admission for both profiles')
    require_covered()
    main = api(f'repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']
    if canonical_hash(authority.document_at(api, REPOSITORY, path, main)) != canonical_hash(source):
        raise ValueError('Current main policy changed; reassess cutover from a fresh trusted checkout')
    branch = 'automation/maintainer-policy-cutover-' + canonical_hash(config)
    pulls = collection(f'repos/{REPOSITORY}/pulls?state=all&head=closure-labs:{branch}')
    from release_set import GitHubClient
    existing = GitHubClient(REPOSITORY).api('git/ref/heads/' + branch, missing=True)
    head = existing.get('object', {}).get('sha') if existing is not None else None
    if existing is not None:
        cutover_scope(config, head, main)
    if pulls:
        if len(pulls) != 1:
            raise ValueError('Cutover branch has ambiguous pull request provenance')
        pull = api(f'repos/{REPOSITORY}/pulls/{pulls[0]["number"]}')
        files = collection(f'repos/{REPOSITORY}/pulls/{pull["number"]}/files')
        if (pull.get('state') != 'open' or pull.get('user', {}).get('type') != 'Bot'
                or pull['user'].get('login') != bot or pull.get('base', {}).get('ref') != 'main'
                or pull.get('base', {}).get('repo', {}).get('full_name') != REPOSITORY
                or pull.get('head', {}).get('repo', {}).get('full_name') != REPOSITORY
                or pull.get('head', {}).get('sha') != head or existing is None
                or pull.get('changed_files') != 1 or len(files) != 1 or not isinstance(files[0], dict) or files[0].get('filename') != path
                or files[0].get('status') != 'modified' or files[0].get('previous_filename')):
            raise ValueError('Existing cutover PR differs from the exact bot-authored single-policy proposal')
        require_covered()
    else:
        # Inventory and live human authority may change while inspecting branch/PR
        # state. Recheck immediately before the first repository mutation.
        require_covered()
        if existing is None:
            base = api(f'repos/{REPOSITORY}/git/commits/{main}')
            tree = api(f'repos/{REPOSITORY}/git/trees', 'POST', {'base_tree': base['tree']['sha'],
                       'tree': [{'path': path, 'mode': '100644', 'type': 'blob',
                                 'content': json.dumps(config, indent=2) + '\n'}]})
            commit = api(f'repos/{REPOSITORY}/git/commits', 'POST',
                         {'message': 'security: propose human decision policy activation', 'tree': tree['sha'], 'parents': [main]})
            head = commit['sha']
            api(f'repos/{REPOSITORY}/git/refs', 'POST', {'ref': 'refs/heads/' + branch, 'sha': head})
        pull = api(f'repos/{REPOSITORY}/pulls', 'POST', {
            'title': 'Activate maintainer security decisions', 'head': branch, 'base': 'main', 'draft': True,
            'body': 'Both profiles have authenticated, current native scans covered by existing human decisions. '
                    'Producer: https://github.com/' + REPOSITORY + '/actions/runs/' + str(run_id) + '\n\n'
                    'This PR changes only the image policy to native-health fields and maintainer-decision mode. '
                    'A current human member of closure-labs/super-admins with maintain/admin access must approve this exact PR head. '
                    'This proposal grants no approval and does not remove release environment reviewers.'})
        if (pull.get('user', {}).get('type') != 'Bot' or pull['user'].get('login') != bot
                or pull.get('head', {}).get('sha') != head
                or pull.get('head', {}).get('repo', {}).get('full_name') != REPOSITORY
                or pull.get('base', {}).get('ref') != 'main'
                or pull.get('base', {}).get('repo', {}).get('full_name') != REPOSITORY):
            raise ValueError('Cutover proposal was not authored by the configured App at the expected repository head')
    if pull.get('draft'):
        subprocess.run(['gh', 'pr', 'ready', str(pull['number']), '--repo', REPOSITORY], check=True, timeout=60)
    subprocess.run(['gh', 'pr', 'merge', str(pull['number']), '--auto', '--merge', '--match-head-commit', head, '--repo', REPOSITORY], check=True, timeout=60)
    return {'status': 'pending-review', 'pullRequest': pull['html_url'], 'policyChanged': False,
            'authorizesPublication': False, 'profiles': list(PROFILES)}

def propose(proposal, packet_directory=None):
    trusted_context()
    require_live_authority_rule()
    bot = os.environ.get('FINITE_REVIEW_BOT_LOGIN')
    authority.validate_context(REPOSITORY, bot)
    path = authority.proposal_path(proposal)
    if proposal['kind'] != 'release-set':
        validate_proposal_packet(proposal)
    else:
        validate_proposal_packet(proposal)
        # Durable product bytes are separate from the immutable approval identity.
        if packet_directory is None:
            raise ValueError('Release proposal requires durable product evidence')
        origin = {'repository': REPOSITORY, 'workflow': 'release-set.yml',
                  'runId': int(os.environ['GITHUB_RUN_ID']),
                  'runAttempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'headSha': os.environ['GITHUB_SHA'], 'artifacts': []}
        import release_artifact
        original = release_artifact.bound_artifact(REPOSITORY, origin['runId'], origin['runAttempt'], origin['headSha'], collection)
        release_artifact.verify_archive(packet_directory, original, REPOSITORY)
        origin['artifacts'] = [{key: original[key] for key in ('id', 'name', 'digest')}]
        reference = decision_packets.push(packet_directory, origin)
    identity = canonical_hash(proposal)
    branch = 'automation/decision-' + identity
    existing = collection(f'repos/{REPOSITORY}/pulls?state=all&head=closure-labs:{branch}')
    if existing:
        if len(existing) != 1 or existing[0].get('user', {}).get('login') != bot:
            raise ValueError('Decision branch has unexpected PR provenance')
        return existing[0]['html_url']
    body = summary(proposal)
    if proposal['kind'] == 'release-set':
        body += release_scan_summary(packet_directory)
        body += '\n\nInitial durable product packet: `' + reference['reference'] + '`\n'
    if len(body) > 60000:
        raise ValueError('Decision review summary exceeds GitHub body bound')
    proposal_branch(proposal, path, branch)
    pull = api(f'repos/{REPOSITORY}/pulls', 'POST', {'title': 'Review ' + proposal['kind'] + ' ' + identity[:12],
               'head': branch, 'base': 'main', 'draft': True, 'body': body})
    if pull.get('user', {}).get('login') != bot or pull.get('user', {}).get('type') != 'Bot':
        raise ValueError('Decision PR was not authored by configured App')
    subprocess.run(['gh', 'pr', 'ready', str(pull['number']), '--repo', REPOSITORY], check=True, timeout=60)
    # Required App-origin check holds the queue until an eligible human approves.
    subprocess.run(['gh', 'pr', 'merge', str(pull['number']), '--auto', '--merge', '--repo', REPOSITORY], check=True, timeout=60)
    return pull['html_url']
