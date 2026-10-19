#!/usr/bin/env python3
"""Small fixtures authenticate reuse without downloading or parsing actual inventories."""
from copy import deepcopy
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('reuse', ROOT / 'scripts/ci/reuse-candidate-security.py')
reuse = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reuse)
PROFILE = 'finite'
SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
IMAGE = 'ghcr.io/closure-labs/finite@' + DIGEST
IDENTITY = 'v1:' + 'c' * 64
STAMP = datetime.now(timezone.utc).isoformat()


def environment():
    return {'GITHUB_ACTOR': 'fixture-user', 'GH_TOKEN': 'fixture-token', 'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': SHA,
        'GITHUB_WORKFLOW_REF': 'closure-labs/finite/.github/workflows/build.yml@refs/heads/main'}


class Reuse(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 123, 'run_attempt': 2, 'status': 'completed', 'conclusion': 'failure',
            'event': 'workflow_dispatch', 'head_branch': 'main', 'path': '.github/workflows/build.yml',
            'repository': {'full_name': 'closure-labs/finite'},
            'head_repository': {'full_name': 'closure-labs/finite'}, 'head_sha': SHA}
        names = ['Select checks', 'Documentation checks', 'Nix and runtime contracts',
                 f'Publish ({PROFILE}) / build / build', f'Publish ({PROFILE}) / security']
        self.jobs = [{'id': i + 1, 'name': name, 'status': 'completed', 'conclusion': 'success',
                      'head_sha': SHA, 'run_id': 123, 'run_attempt': 2} for i, name in enumerate(names)]
        self.jobs[3]['steps'] = [{'name': name, 'conclusion': 'success'} for name in (
            'Prepare candidate publication', 'Build with BlueBuild', 'Verify assembled image', 'Save build evidence')]
        self.artifacts = [{'id': i + 10, 'name': f'{kind}-{PROFILE}-123-2', 'expired': False,
            'digest': 'sha256:' + 'd' * 64, 'size_in_bytes': 1234,
            'workflow_run': {'id': 123, 'head_sha': SHA}} for i, kind in enumerate(('image', 'security'))]

    def metadata(self):
        return reuse.metadata(self.run, self.jobs, self.artifacts, PROFILE, '123')

    def test_helper_import_matches_cli_without_extra_publication_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / 'scripts', root / 'scripts',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            loader = (
                'import importlib.util; '
                'spec=importlib.util.spec_from_file_location("reuse_fixture", '
                '"scripts/ci/reuse-candidate-security.py"); '
                'module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)')
            subprocess.run([sys.executable, '-c', loader], cwd=root, check=True, timeout=30,
                           env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '0'})
            generated = list((root / 'scripts/bluebuild/__pycache__').glob('publication.*.pyc'))
            self.assertEqual(generated, [])
            # Child imports still use normal import behavior, matching the CLI.
            self.assertTrue(list((root / 'scripts/bluebuild/__pycache__').glob('security-policy.*.pyc')))

    def test_later_signing_failure_does_not_discard_successful_exact_native_job(self):
        artifact, _, build, security = self.metadata()
        self.assertEqual((artifact['id'], build, security), (11, 4, 5))

    def test_untrusted_wrong_attempt_failed_or_ambiguous_jobs_rejected(self):
        changes = [lambda: self.run.update(head_branch='branch'), lambda: self.run.update(event='pull_request'),
                   lambda: self.run.update(path='.github/workflows/other.yml'),
                   lambda: self.jobs[-1].update(run_attempt=1), lambda: self.jobs[-1].update(conclusion='failure'),
                   lambda: self.jobs[-1].update(head_sha='e' * 40), lambda: self.jobs.append(deepcopy(self.jobs[-1])),
                   lambda: self.artifacts[-1]['workflow_run'].update(head_sha='e' * 40),
                   lambda: self.artifacts[-1].update(digest=None)]
        for change in changes:
            self.setUp()
            change()
            with self.assertRaises(ValueError):
                self.metadata()

    def test_only_missing_or_expired_archive_has_unavailable_classification(self):
        self.artifacts[-1]['expired'] = True
        with self.assertRaises(reuse.Unavailable): self.metadata()
        self.artifacts.pop()
        with self.assertRaises(reuse.Unavailable): self.metadata()

    def archive(self, extra=None, duplicate=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipped:
            for name in sorted(reuse.REQUIRED): zipped.writestr(name, b'{}')
            if extra is not None: zipped.writestr(extra, b'target')
            if duplicate: zipped.writestr('security-result.json', b'{}')
        raw = stream.getvalue()
        return stream, {'size_in_bytes': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}

    def test_safe_archive_only_writes_fixed_named_regular_files(self):
        archive, artifact = self.archive()
        with tempfile.TemporaryDirectory() as temporary:
            reuse.extract(archive, artifact, Path(temporary))
            self.assertEqual({p.name for p in Path(temporary).iterdir()}, reuse.REQUIRED)

    def test_paths_symlinks_duplicates_missing_and_digest_tampering_rejected(self):
        link = zipfile.ZipInfo('runner-resources.log')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra, duplicate in [('../escape', False), ('/absolute', False), ('nested/file', False),
                                  ('unrecognized.json', False), (link, False), (None, True)]:
            archive, artifact = self.archive(extra, duplicate)
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                reuse.extract(archive, artifact, Path(temporary))
        archive, artifact = self.archive()
        artifact['digest'] = 'sha256:' + '0' * 64
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            reuse.extract(archive, artifact, Path(temporary))
        archive, artifact = self.archive()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(reuse.LIMITS, {'sbom.syft.json': 1}), self.assertRaises(ValueError):
            reuse.extract(archive, artifact, Path(temporary))

    def fixture(self, directory):
        original = {'schema': 1, 'status': 'pass', 'image': IMAGE, 'scannedAt': STAMP, 'policySha256': '1' * 64,
            'database': {'status': {'valid': True, 'built': STAMP},
                         'providers': {'fedora': {'captured': STAMP}, 'kev': {'captured': STAMP}}}}
        baseline = {'image': IMAGE, 'profile': PROFILE, 'sourceRevision': SHA, 'buildIdentity': IDENTITY}
        (directory / 'security-result.json').write_text(json.dumps(original))
        (directory / 'approved-baseline.json').write_text(json.dumps(baseline))
        policy = directory / 'policy.json'
        policy.write_bytes((ROOT / 'automation/security/image-policy.json').read_bytes())
        return original, policy

    def test_current_policy_reverification_preserves_scan_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original, policy = self.fixture(directory)
            with patch.object(reuse.security, 'verify', return_value=deepcopy(original)) as verify:
                previous, result = reuse.revalidate(directory, IMAGE, PROFILE, SHA, IDENTITY, policy)
            verify.assert_called_once_with(directory, IMAGE, policy)
            self.assertEqual(result['scannedAt'], previous['scannedAt'])
            self.assertEqual(result['policySha256'], hashlib.sha256(policy.read_bytes()).hexdigest())
            self.assertEqual(json.loads((directory / 'security-result.json').read_text()), original)

    def test_stale_failed_current_policy_or_mismatched_native_context_never_reuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original, policy = self.fixture(directory)
            with patch.object(reuse.security, 'verify', side_effect=ValueError('Scan evidence is stale')), self.assertRaises(ValueError):
                reuse.revalidate(directory, IMAGE, PROFILE, SHA, IDENTITY, policy)
            for result in [{**original, 'status': 'blocked'}, {**original, 'scannedAt': 'new'},
                           {**original, 'image': IMAGE.replace('b' * 64, 'c' * 64)}]:
                with patch.object(reuse.security, 'verify', return_value=result), self.assertRaises(ValueError):
                    reuse.revalidate(directory, IMAGE, PROFILE, SHA, IDENTITY, policy)
            for key, value in [('profile', 'bluefin-next'), ('sourceRevision', 'e' * 40), ('buildIdentity', 'v1:' + 'e' * 64)]:
                self.fixture(directory)
                path = directory / 'approved-baseline.json'
                baseline = json.loads(path.read_text())
                baseline[key] = value
                path.write_text(json.dumps(baseline))
                with patch.object(reuse.security, 'verify') as verify, self.assertRaises(ValueError):
                    reuse.revalidate(directory, IMAGE, PROFILE, SHA, IDENTITY, policy)
                verify.assert_not_called()

    def test_expired_freshness_only_permits_fallback_after_all_timestamp_validation(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            original, policy_path = self.fixture(Path(temporary))
            policy = reuse.security.load_policy(policy_path)
            old = (now - timedelta(days=100)).isoformat()
            for place in ('scan', 'database', 'provider'):
                fixture = deepcopy(original)
                if place == 'scan': fixture['scannedAt'] = old
                elif place == 'database': fixture['database']['status']['built'] = old
                else: fixture['database']['providers']['fedora']['captured'] = old
                with self.assertRaises(reuse.Unavailable): reuse.require_fresh(fixture, policy, now)
            for value in ('invalid', None, (now + timedelta(minutes=1)).isoformat()):
                fixture = deepcopy(original)
                fixture['scannedAt'] = old
                fixture['database']['providers']['fedora']['captured'] = value
                try:
                    reuse.require_fresh(fixture, policy, now)
                except reuse.Unavailable:
                    self.fail('Malformed/future timestamp must not authorize fallback')
                except ValueError:
                    pass
                else:
                    self.fail('Invalid timestamp accepted')

    def test_hosted_main_manual_boundary_precedes_any_api_call_or_output(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REF', 'refs/heads/branch'),
                           ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REPOSITORY', 'fork/finite'),
                           ('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/other.yml@refs/heads/main')]:
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'output'
                with patch.dict(os.environ, {**environment(), key: value}, clear=True), patch.object(reuse.publication, 'github') as api:
                    with self.assertRaises(ValueError): reuse.reuse('123', PROFILE, DIGEST, output)
                api.assert_not_called()
                self.assertFalse(output.exists())

    def test_full_reuse_rechecks_ancestry_and_publisher_then_retains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, _ = self.fixture(root)
            raw_result = (root / 'security-result.json').read_bytes()
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipped:
                for name in sorted(reuse.REQUIRED):
                    raw = (root / name).read_bytes() if (root / name).exists() else b'{}'
                    zipped.writestr(name, raw)
            archive = stream.getvalue()
            self.artifacts[-1].update(size_in_bytes=len(archive), digest='sha256:' + hashlib.sha256(archive).hexdigest())
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                if command[0] == 'gh': kwargs['stdout'].write(archive)
            output = root / 'verified'
            with patch.dict(os.environ, environment(), clear=True), \
                 patch.object(reuse.publication, 'github', side_effect=[self.run, [{'jobs': self.jobs}], [{'artifacts': self.artifacts}]]), \
                 patch.object(reuse.subprocess, 'check_output', return_value=SHA), patch.object(reuse.subprocess, 'run', side_effect=run), \
                 patch.object(reuse.publication.upstream, 'recipes', return_value={PROFILE: {}}), \
                 patch.object(reuse.publication.upstream, 'image_identity', return_value=IDENTITY), \
                 patch.object(reuse.publication.upstream, 'verify') as publisher, \
                 patch.object(reuse.publication.upstream, 'inspect', return_value={}), \
                 patch.object(reuse.publication, 'validate_candidate') as candidate, \
                 patch.object(reuse.publication, 'origin_files', return_value={
                     PROFILE + '-publication.json': b'{}', PROFILE + '-image-ref.txt': IMAGE.encode()}), \
                 patch.object(reuse.security, 'verify', return_value=deepcopy(original)) as native:
                provenance = reuse.reuse('123', PROFILE, DIGEST, output)
            self.assertIn(['git', 'merge-base', '--is-ancestor', SHA, SHA], calls)
            publisher.assert_called_once_with(reuse.ROOT)
            candidate.assert_called_once()
            native.assert_called_once()
            self.assertEqual((output / 'original-security-result.json').read_bytes(), raw_result)
            result = json.loads((output / 'security-result.json').read_text())
            self.assertEqual(result['scannedAt'], original['scannedAt'])
            self.assertEqual(result['policySha256'], reuse.security.file_sha256(reuse.ROOT / 'automation/security/image-policy.json'))
            self.assertEqual(provenance['artifactSha256'], self.artifacts[-1]['digest'])
            self.assertFalse(provenance['newScanPerformed'])
            self.assertFalse(provenance['releaseEligibilityEstablished'])

    def test_scoped_registry_auth_permissions_cleanup_restore_and_no_credential_arguments(self):
        for previous in (None, '', '/previous/auth.json'):
            for failed in (False, True):
                observed = []
                def inspect(command, **kwargs):
                    self.assertEqual(command[0], 'skopeo')
                    self.assertNotIn('fixture-token', ' '.join(command))
                    self.assertNotIn('fixture-user', ' '.join(command))
                    self.assertNotIn('--creds', command)
                    path = Path(os.environ['REGISTRY_AUTH_FILE'])
                    observed.append(path)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                    self.assertEqual(path.stat().st_uid, os.getuid())
                    self.assertEqual(path.parent.stat().st_uid, os.getuid())
                    data = json.loads(path.read_text())
                    decoded = base64.b64decode(data['auths']['ghcr.io']['auth']).decode()
                    self.assertEqual(decoded, 'fixture-user:fixture-token')
                    return subprocess.CompletedProcess(command, 1 if failed else 0,
                        stdout=json.dumps({'Digest': DIGEST}).encode(),
                        stderr=b'credential detail fixture-token' if failed else b'')
                env = environment()
                if previous is not None: env['REGISTRY_AUTH_FILE'] = previous
                with patch.dict(os.environ, env, clear=True), patch.object(reuse.publication.upstream.subprocess, 'run', side_effect=inspect), \
                     patch('sys.stdout', new_callable=io.StringIO) as out, patch('sys.stderr', new_callable=io.StringIO) as error:
                    if failed:
                        with self.assertRaisesRegex(ValueError, '^Authenticated candidate registry inspection failed$') as caught:
                            reuse.inspect_candidate(IMAGE)
                        self.assertNotIn('fixture-token', str(caught.exception))
                    else:
                        self.assertEqual(reuse.inspect_candidate(IMAGE), {'Digest': DIGEST})
                    self.assertEqual(os.environ.get('REGISTRY_AUTH_FILE'), previous)
                    self.assertNotIn('fixture-token', out.getvalue() + error.getvalue())
                self.assertTrue(observed)
                self.assertTrue(all(not path.exists() and not path.parent.exists() for path in observed))

    def test_registry_auth_missing_actor_or_token_fails_before_inspection(self):
        for key in ('GITHUB_ACTOR', 'GH_TOKEN'):
            env = environment()
            env.pop(key)
            with patch.dict(os.environ, env, clear=True), patch.object(reuse.publication.upstream, 'inspect') as inspect:
                with self.assertRaises(ValueError): reuse.inspect_candidate(IMAGE)
                inspect.assert_not_called()

    def test_bounded_reuse_unit_receives_actor_without_credential_command_arguments(self):
        workflow = (ROOT / '.github/workflows/publication.yml').read_text()
        self.assertIn('--preserve-env=GH_TOKEN,GITHUB_ACTOR,GITHUB_ACTIONS', workflow)
        self.assertIn('--setenv=GH_TOKEN --setenv=GITHUB_ACTOR', workflow)
        self.assertNotIn('--setenv="GH_TOKEN=', workflow)
        self.assertIn('--uid="$(id -u)" --gid="$(id -g)"', workflow)
        self.assertIn('--property=MemoryMax=2G --property=MemorySwapMax=0', workflow)

    def test_existing_or_symlinked_output_is_never_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'alias').symlink_to(root, target_is_directory=True)
            for output in (root, root / 'alias' / 'output'):
                with patch.dict(os.environ, environment(), clear=True), patch.object(reuse.publication, 'github') as api:
                    with self.assertRaises(ValueError): reuse.reuse('123', PROFILE, DIGEST, output)
                api.assert_not_called()


inventory_spec = importlib.util.spec_from_file_location('inventory_fixture', ROOT / 'scripts/ci/inventory-evidence.py')
inventory = importlib.util.module_from_spec(inventory_spec)
exec(compile(Path(inventory_spec.origin).read_bytes(), inventory_spec.origin, 'exec'), inventory.__dict__)
fetch_spec = importlib.util.spec_from_file_location('inventory_fetch_fixture', ROOT / 'scripts/ci/reuse-image-inventory.py')
fetch = importlib.util.module_from_spec(fetch_spec)
exec(compile(Path(fetch_spec.origin).read_bytes(), fetch_spec.origin, 'exec'), fetch.__dict__)
GENERATION = {'platform': 'linux/amd64', 'tools': {'syft': 'fixture 1', 'umoci': 'fixture 1'},
              'catalogers': 'image', 'implementations': {'collector': 'a' * 64}}


class Inventory(unittest.TestCase):
    def bundle(self, directory, risk=True):
        files = inventory.REQUIRED | ({'rpm-file-evidence.json', 'applicability-evidence.json'} if risk else set())
        for name in files:
            (directory / name).write_text('{}')
        with patch.object(inventory, 'generation', return_value=GENERATION):
            return inventory.write(directory, IMAGE, DIGEST, risk)

    def verify(self, directory, risk=True):
        with patch.object(inventory, 'generation', return_value=GENERATION), \
             patch.object(reuse.security, 'read_manifests', return_value={}), \
             patch.object(reuse.security, 'manifest_binding', return_value=DIGEST):
            return inventory.verify(directory, IMAGE, reuse.security, risk)

    def test_generation_changes_when_current_policy_or_collector_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in inventory.IMPLEMENTATIONS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            with patch.object(inventory, 'ROOT', root), \
                 patch.object(inventory.subprocess, 'check_output', return_value='fixture version'):
                original = inventory.generation()
                (root / 'automation/security/image-policy.json').write_text('new applicability probes')
                changed = inventory.generation()
                self.assertNotEqual(original, changed)
                (root / 'scripts/ci/applicability-evidence.py').write_text('new collector')
                self.assertNotEqual(changed, inventory.generation())

    def test_exact_inventory_only_reuse_and_probe_compatibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = self.bundle(directory)
            self.assertEqual(self.verify(directory), original)
            output = directory / 'ready'
            output.mkdir()
            inventory.copy(directory, output, original)
            self.assertEqual({p.name for p in output.iterdir()}, set(original['files']) | {'inventory-provenance.json'})
            self.assertFalse((output / 'vulnerabilities.json').exists())
            self.assertFalse((output / 'security-result.json').exists())
            path = directory / 'inventory-provenance.json'
            changed = deepcopy(original)
            changed['generation']['tools']['syft'] = 'fixture 2'
            path.write_text(json.dumps(changed))
            with self.assertRaises(inventory.Unavailable): self.verify(directory)

    def test_missing_probe_legacy_or_expired_is_a_safe_miss(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(inventory.Unavailable): self.verify(directory)
            original = self.bundle(directory, risk=False)
            with self.assertRaises(inventory.Unavailable): self.verify(directory)
            original['generatedAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            (directory / 'inventory-provenance.json').write_text(json.dumps(original))
            with self.assertRaises(inventory.Unavailable): self.verify(directory, risk=False)

    def test_tampered_or_unbound_bytes_future_time_symlink_and_manifest_are_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = self.bundle(directory)
            path = directory / 'inventory-provenance.json'
            for changed in [dict(original, image=IMAGE.replace('b' * 64, 'c' * 64)),
                            dict(original, platformDigest='sha256:' + 'c' * 64),
                            dict(original, generatedAt=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()),
                            dict(original, generatedAt='2026-01-01T00:00:00'),
                            dict(original, files={**original['files'], '../escape': 'a' * 64})]:
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError) as error: self.verify(directory)
                self.assertNotIsInstance(error.exception, inventory.Unavailable)
            original['generatedAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            path.write_text(json.dumps(original))
            # A stale timestamp must not conceal corrupted content.
            (directory / 'sbom.syft.json').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'content hash'): self.verify(directory)
            original = self.bundle(directory)
            (directory / 'platform-manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'unbound'): self.verify(directory)
            (directory / 'platform-manifest.json').unlink()
            sbom = directory / 'sbom.syft.json'
            sbom.unlink()
            sbom.symlink_to(directory / 'sbom.spdx.json')
            with self.assertRaisesRegex(ValueError, 'content hash'): self.verify(directory)

    def test_authenticated_fetch_reuses_inventory_from_expired_results_without_findings(self):
        events = ((producer, consumer) for producer in ('workflow_dispatch', 'schedule')
                  for consumer in ('workflow_dispatch', 'push', 'schedule'))
        for producer_event, consumer_event in events:
            fixture = Reuse()
            fixture.setUp()
            fixture.run['event'] = producer_event
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                original, _ = fixture.fixture(directory)
                original['scannedAt'] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                (directory / 'security-result.json').write_text(json.dumps(original))
                self.bundle(directory)
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipped:
                    for name in sorted(reuse.REQUIRED | set(inventory.FILES) | {'inventory-provenance.json'}):
                        path = directory / name
                        if path.exists(): zipped.writestr(name, path.read_bytes())
                        elif name in reuse.REQUIRED: zipped.writestr(name, b'{}')
                archive = stream.getvalue()
                fixture.artifacts[-1].update(size_in_bytes=len(archive), digest='sha256:' + hashlib.sha256(archive).hexdigest())
                def download(command, **kwargs):
                    kwargs['stdout'].write(archive)
                record = {'profile': PROFILE, 'revision': SHA, 'buildIdentity': IDENTITY,
                          'qualificationMode': 'enforce', 'publish': True}
                with patch.dict(os.environ, {**environment(), 'GITHUB_EVENT_NAME': consumer_event}, clear=True), \
                     patch.object(fetch.publication, 'github', side_effect=[fixture.run, [{'artifacts': fixture.artifacts}], [{'jobs': fixture.jobs}]]), \
                     patch.object(fetch.publication, 'origin_files', return_value={
                         PROFILE + '-publication.json': json.dumps(record).encode(), PROFILE + '-image-ref.txt': IMAGE.encode()}), \
                     patch.object(fetch.subprocess, 'run', side_effect=download), \
                     patch.object(fetch.inventory, 'generation', return_value=GENERATION), \
                     patch.object(fetch.reuse.security, 'read_manifests', return_value={}), \
                     patch.object(fetch.reuse.security, 'manifest_binding', return_value=DIGEST):
                    result = fetch.retrieve(IMAGE, PROFILE, directory / 'ready', '123')
                ready = directory / 'ready'
                self.assertTrue(result['newScanRequired'])
                self.assertFalse(result['releaseEligibilityEstablished'])
                self.assertEqual(result['originSecurityJob'], 5)
                self.assertEqual(result['artifactSha256'], fixture.artifacts[-1]['digest'])
                self.assertFalse((ready / 'security-result.json').exists())
                self.assertFalse((ready / 'vulnerabilities.json').exists())
                self.assertFalse((ready / 'database-coverage.json').exists())

    def test_fetch_rejects_untrusted_consumer_before_api_access(self):
        for key, value in [('GITHUB_REF', 'refs/heads/branch'), ('GITHUB_REPOSITORY', 'fork/finite'),
                           ('GITHUB_ACTIONS', 'false'), ('GITHUB_SHA', 'not-a-commit'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'merge_group'),
                           ('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/build.yml@refs/heads/branch'),
                           ('GITHUB_WORKFLOW_REF', 'closure-labs/finite/.github/workflows/unknown.yml@refs/heads/main')]:
            with patch.dict(os.environ, {**environment(), key: value}, clear=True), \
                 patch.object(fetch.publication, 'github') as api, self.assertRaises(ValueError):
                fetch.retrieve(IMAGE, PROFILE, Path('/tmp/never-created'), '123')
            api.assert_not_called()

    def test_security_benchmark_inventory_consumer_is_manual_main_only(self):
        base = {**environment(), 'GITHUB_WORKFLOW_REF':
                'closure-labs/finite/.github/workflows/benchmark-security-reuse.yml@refs/heads/main'}
        with patch.dict(os.environ, base, clear=True):
            fetch.hosted()
        for key, value in [('GITHUB_EVENT_NAME', 'schedule'), ('GITHUB_EVENT_NAME', 'push'),
                           ('GITHUB_REF', 'refs/heads/branch'), ('GITHUB_REPOSITORY', 'fork/finite'),
                           ('GITHUB_WORKFLOW_REF', base['GITHUB_WORKFLOW_REF'].replace('@refs/heads/main', '@refs/heads/branch'))]:
            with patch.dict(os.environ, {**base, key: value}, clear=True), \
                 patch.object(fetch.publication, 'github') as api, self.assertRaises(ValueError):
                fetch.retrieve(IMAGE, PROFILE, Path('/tmp/never-created'), '123')
            api.assert_not_called()

    def test_reused_scan_always_refreshes_db_and_current_policy(self):
        spec = importlib.util.spec_from_file_location('reused_scanner', ROOT / 'scripts/bluebuild/security-scan.py')
        scanner = importlib.util.module_from_spec(spec)
        exec(compile(Path(spec.origin).read_bytes(), spec.origin, 'exec'), scanner.__dict__)
        for database_fails in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'inventory'
                source.mkdir()
                record = self.bundle(source)
                (source / 'inventory-origin.json').write_text(json.dumps({
                    'schema': 1, 'status': 'authenticated-inventory-only', 'image': IMAGE,
                    'newScanRequired': True, 'validationRevision': SHA}))
                commands = []
                def run(command, output=None):
                    commands.append(command)
                    if database_fails and command[:3] == ['grype', 'db', 'update']:
                        raise subprocess.CalledProcessError(1, command)
                    if output: output.write_text('{}')
                with patch.dict(os.environ, environment(), clear=True), \
                     patch.object(sys, 'argv', ['security-scan.py', IMAGE, str(root / 'scan'), '--inventory-dir', str(source)]), \
                     patch.object(scanner.inventory_module, 'verify', return_value=record), \
                     patch.object(scanner.policy_module, 'load_policy', return_value={'mode': 'strict', 'coverageProbePackage': 'systemd'}), \
                     patch.object(scanner.policy_module, 'read_manifests', return_value={}), \
                     patch.object(scanner.policy_module, 'inventory', return_value={'effective': 'fedora:42'}), \
                     patch.object(scanner, 'run', side_effect=run), \
                     patch.object(scanner.subprocess, 'call', return_value=0) as evaluate, self.assertRaises(SystemExit) as status:
                    scanner.main()
                self.assertIn(['grype', 'db', 'update'], commands)
                self.assertFalse(any(command[0] in ('syft', 'skopeo', 'umoci') for command in commands))
                if database_fails:
                    self.assertEqual(status.exception.code, 2)
                    evaluate.assert_not_called()
                    self.assertEqual(json.loads((root / 'scan/security-result.json').read_text())['status'], 'scanner-error')
                else:
                    self.assertEqual(status.exception.code, 0)
                    self.assertTrue(any(command[0] == 'grype' and command[1].startswith('sbom:') for command in commands))
                    evaluate.assert_called_once()
                self.assertTrue(json.loads((root / 'scan/phase-timings.json').read_text())['inventoryReused'])


if __name__ == '__main__':
    unittest.main()
