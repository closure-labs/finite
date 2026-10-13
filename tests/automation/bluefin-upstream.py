#!/usr/bin/env python3
"""Failure-path coverage for upstream resolution and candidate promotion."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


upstream = load('upstream', 'scripts/ci/bluefin-upstream.py')
publication = load('publication', 'scripts/bluebuild/publication.py')
NEW = 'sha256:' + 'a' * 64
IMAGE = 'sha256:' + 'b' * 64
IDENTITY = 'v1:' + 'c' * 64


class BluefinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'recipes', self.root / 'recipes')
        security = patch.object(publication.security, 'verify')
        security.start()
        self.addCleanup(security.stop)
        # This suite exercises upstream selection and promotion sequencing.
        # Receipt contents have dedicated desktop-qualification coverage; the
        # negative integration test below deliberately restores the real gate.
        self.desktop_verifier = publication.desktop.verify
        desktop = patch.object(publication.desktop, 'verify')
        self.desktop = desktop.start()
        self.addCleanup(desktop.stop)
        current_main = patch.object(publication, 'github', return_value={
            'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'f' * 40}})
        current_main.start()
        self.addCleanup(current_main.stop)
        self.approved = upstream.recipes(self.root)
        self.observed = {r['base']: r['digest'] for r in self.approved.values()}
        verification = patch.object(upstream, 'authenticate', return_value={'verified': True})
        verification.start()
        self.addCleanup(verification.stop)
        for module in (upstream, publication.upstream):
            mock = patch.object(module, 'image_identity', return_value=IDENTITY)
            mock.start()
            self.addCleanup(mock.stop)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in (self.root / 'recipes').glob('*.yml')}

    def published(self, reference, **_kwargs):
        tag = reference.rsplit(':', 1)[1]
        profile, recipe = next((p, r) for p, r in self.approved.items() if tag in r['tags'])
        return {'Digest': IMAGE, 'Labels': {
            'org.opencontainers.image.base.digest': recipe['digest'],
            'io.finite.profile': profile,
            'io.finite.build-inputs': IDENTITY,
            'org.opencontainers.image.source': 'https://github.com/closure-labs/finite',
        }}

    def test_unchanged_poll_is_noop(self):
        before = self.snapshot()
        with patch.object(upstream, 'resolve', side_effect=lambda base: self.observed[base]):
            self.assertFalse(upstream.update(self.root)['changed'])
        self.assertEqual(before, self.snapshot())

    def test_changed_foundation_updates_only_its_two_profiles(self):
        self.observed['ghcr.io/ublue-os/bluefin'] = NEW
        before = self.snapshot()
        result = upstream.update(self.root, self.observed)
        self.assertEqual(set(result['profiles']), {'bluefin-generic', 'bluefin-next'})
        for name, content in self.snapshot().items():
            if name.startswith('bluefin-dx'):
                self.assertEqual(content, before[name])
        self.assertFalse(upstream.update(self.root, self.observed)['changed'])

    def test_second_lookup_failure_changes_nothing(self):
        before = self.snapshot()
        with patch.object(upstream, 'resolve', side_effect=[NEW, RuntimeError('registry unavailable')]):
            with self.assertRaises(RuntimeError):
                upstream.update(self.root)
        self.assertEqual(before, self.snapshot())

    def test_invalid_observation_changes_nothing(self):
        before = self.snapshot()
        self.observed['ghcr.io/ublue-os/bluefin'] = 'stable'
        with self.assertRaises(ValueError):
            upstream.update(self.root, self.observed)
        self.assertEqual(before, self.snapshot())

    def test_signature_failure_does_not_change_any_recipe(self):
        before = self.snapshot()
        self.observed['ghcr.io/ublue-os/bluefin'] = NEW
        with patch.object(upstream, 'authenticate', side_effect=[{'verified': True},
                          subprocess.CalledProcessError(1, 'cosign')]):
            with self.assertRaises(subprocess.CalledProcessError):
                upstream.update(self.root, self.observed)
        self.assertEqual(before, self.snapshot())

    def test_relayed_observations_are_verified_before_apply(self):
        with patch.object(upstream, 'authenticate', return_value={'verified': True}) as verify:
            result = upstream.update(self.root, self.observed)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(len(result['verified']), 2)

    def test_disagreeing_foundation_pins_fail(self):
        path = self.root / 'recipes/bluefin-next.yml'
        path.write_text(path.read_text().replace(self.approved['bluefin-next']['digest'], NEW))
        with self.assertRaises(ValueError):
            upstream.recipes(self.root)

    def test_single_manifest_is_hashed_then_inspected_by_digest(self):
        raw = b'{"schemaVersion":2,"config":{}}'
        expected = 'sha256:' + hashlib.sha256(raw).hexdigest()
        with patch.object(upstream, 'inspect', side_effect=[raw, {'Architecture': 'amd64', 'Os': 'linux'}]) as inspect:
            self.assertEqual(upstream.resolve('ghcr.io/ublue-os/bluefin'), expected)
        self.assertEqual(inspect.call_args.args[0], 'ghcr.io/ublue-os/bluefin@' + expected)

    def test_index_selects_only_linux_amd64_child(self):
        raw = json.dumps({'manifests': [
            {'digest': IMAGE, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
            {'digest': NEW, 'platform': {'os': 'linux', 'architecture': 'amd64'}},
        ]}).encode()
        with patch.object(upstream, 'inspect', side_effect=[raw, {'Architecture': 'amd64', 'Os': 'linux'}]):
            self.assertEqual(upstream.resolve('base'), NEW)
        with patch.object(upstream, 'inspect', return_value=b'{"manifests":[]}'):
            with self.assertRaises(ValueError):
                upstream.resolve('base')

    def test_wrong_platform_fails(self):
        with patch.object(upstream, 'inspect', side_effect=[b'{}', {'Architecture': 'arm64', 'Os': 'linux'}]):
            with self.assertRaises(ValueError):
                upstream.resolve('base')

    def test_transient_registry_failures_have_bounded_retries(self):
        failure = subprocess.CompletedProcess([], 1, b'', b'502 Bad Gateway')
        success = subprocess.CompletedProcess([], 0, b'{}', b'')
        with patch.object(upstream.subprocess, 'run', side_effect=[failure, success]) as run, patch.object(upstream.time, 'sleep') as sleep:
            self.assertEqual(upstream.inspect('base'), {})
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs['timeout'], 30)
            sleep.assert_called_once_with(2)
        with patch.object(upstream.subprocess, 'run', return_value=failure) as run, patch.object(upstream.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                upstream.inspect('base')
            self.assertEqual(run.call_count, 4)

    def test_only_manifest_unknown_is_missing(self):
        for message in [b'unauthorized', b'403 Forbidden', b'404 Not Found']:
            with self.subTest(message=message), patch.object(upstream.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', message)) as run:
                with self.assertRaises(RuntimeError):
                    upstream.inspect('base', allow_missing=True)
                self.assertEqual(run.call_count, 1)
        with patch.object(upstream.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'manifest unknown')):
            self.assertIsNone(upstream.inspect('base', allow_missing=True))

    def test_reconciliation_uses_approved_pins_and_checks_aliases(self):
        with patch.object(upstream, 'inspect', side_effect=self.published):
            self.assertEqual(upstream.reconcile(self.root)['profiles'], [])
        def alias_drift(reference, **kwargs):
            image = self.published(reference, **kwargs)
            if reference.endswith(':latest'):
                image['Digest'] = NEW
            return image
        with patch.object(upstream, 'inspect', side_effect=alias_drift):
            self.assertEqual(upstream.reconcile(self.root)['profiles'], ['bluefin-generic'])
        def missed_publication(reference, **kwargs):
            image = self.published(reference, **kwargs)
            if reference.endswith(':finite-dev-next'):
                image['Labels']['org.opencontainers.image.base.digest'] = NEW
            return image
        with patch.object(upstream, 'inspect', side_effect=missed_publication):
            self.assertEqual(upstream.reconcile(self.root)['profiles'], ['bluefin-dx-next'])

    def test_docs_push_recovers_replaced_pending_publication(self):
        docs = {'checks': False, 'nix': False, 'profiles': []}
        with patch.object(upstream, 'inspect', side_effect=self.published):
            self.assertEqual(upstream.merge_impact(upstream.reconcile(self.root), docs), docs)
        def unpublished(reference, **kwargs):
            image = self.published(reference, **kwargs)
            if reference.endswith(':finite-next'):
                image['Labels']['io.finite.build-inputs'] = 'v1:' + 'd' * 64
            return image
        with patch.object(upstream, 'inspect', side_effect=unpublished):
            self.assertEqual(upstream.merge_impact(upstream.reconcile(self.root), docs),
                             {'checks': True, 'nix': False, 'profiles': ['bluefin-next']})

    def test_reconciliation_preserves_diff_selection_and_payload_comparison(self):
        pending = {'checks': True, 'nix': False, 'profiles': ['bluefin-next']}
        impact = {'checks': True, 'nix': True, 'profiles': ['bluefin-generic']}
        self.assertEqual(upstream.merge_impact(pending, impact),
                         {'checks': True, 'nix': True, 'profiles': ['bluefin-generic', 'bluefin-next']})
        with self.assertRaises(ValueError):
            upstream.merge_impact(pending, {**impact, 'profiles': ['untrusted-profile']})

    def test_missing_channel_requires_recovery_but_outage_fails(self):
        with patch.object(upstream, 'inspect', return_value=None):
            self.assertEqual(set(upstream.reconcile(self.root)['profiles']), set(upstream.PROFILES))
        with patch.object(upstream, 'inspect', side_effect=RuntimeError('outage')):
            with self.assertRaises(RuntimeError):
                upstream.reconcile(self.root)

    def test_recovery_defers_to_active_publication_then_retries(self):
        plan = {'checks': True, 'nix': False, 'profiles': ['bluefin-next']}
        with patch.object(upstream, 'reconcile', return_value=plan), patch.object(upstream, 'github', return_value={'workflow_runs': [{'event': 'push'}]}), patch.object(upstream.subprocess, 'run') as run:
            self.assertFalse(upstream.recover(self.root)['dispatched'])
            run.assert_not_called()
        with patch.dict(os.environ, GITHUB_REPOSITORY='closure-labs/finite'), patch.object(upstream, 'reconcile', return_value=plan), patch.object(upstream, 'github', return_value={'workflow_runs': []}), patch.object(upstream.subprocess, 'run') as run:
            self.assertTrue(upstream.recover(self.root)['dispatched'])
            self.assertIn('reconcile=true', run.call_args.args[0])

    def test_freshness_uses_successful_check_job_even_if_parent_failed(self):
        now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        run = {'id': 12, 'created_at': '2026-09-07T10:00:00Z', 'conclusion': 'failure'}
        job = {'name': 'Resolve Bluefin upstream', 'conclusion': 'success', 'completed_at': '2026-09-07T10:05:00Z', 'html_url': 'https://github.com/check'}
        with patch.object(upstream, 'github', side_effect=[{'workflow_runs': [run]}, {'jobs': [job]}]):
            self.assertEqual(upstream.freshness(now)['last_success'], job['completed_at'])
        job['conclusion'] = 'failure'
        with patch.object(upstream, 'github', side_effect=[{'workflow_runs': [run]}, {'jobs': [job]}]):
            with self.assertRaises(RuntimeError):
                upstream.freshness(now)
        with patch.object(upstream, 'github', return_value={'workflow_runs': []}):
            with self.assertRaises(RuntimeError):
                upstream.freshness(now)

    def prepare(self, publish=True):
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.upstream, 'inspect', side_effect=self.published), patch.object(publication.subprocess, 'run'):
            publication.prepare('bluefin-generic', publish, self.root)

    def recovery_policy(self):
        path = self.root / 'automation/qualification-recovery.json'
        path.parent.mkdir(exist_ok=True)
        policy = {'schema': 1, 'profiles': {'bluefin-generic': {
            'publishedDigest': IMAGE, 'baselineDigest': NEW, 'reason': 'Missing initramfs'}}}
        path.write_text(json.dumps(policy))
        return path, policy

    def prepare_recovery(self):
        self.recovery_policy()
        baseline = {'Digest': NEW, 'Labels': {'io.finite.profile': 'bluefin-generic'}}
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), \
                patch.object(publication.upstream, 'inspect', side_effect=[self.published(upstream.REPOSITORY + ':finite'), baseline]), \
                patch.object(publication.subprocess, 'run') as run:
            publication.prepare('bluefin-generic', True, self.root)
        self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                         [upstream.REPOSITORY + '@' + IMAGE, upstream.REPOSITORY + '@' + NEW])
        return self.root / '.bluebuild'

    def test_recovery_only_applies_to_exact_profile_and_broken_digest(self):
        self.recovery_policy()
        self.assertEqual(publication.recovery_baseline('bluefin-generic', IMAGE, self.root),
                         (NEW, 'Missing initramfs'))
        self.assertEqual(publication.recovery_baseline('bluefin-generic', NEW, self.root), (NEW, ''))
        self.assertEqual(publication.recovery_baseline('bluefin-next', IMAGE, self.root), (IMAGE, ''))

    def test_invalid_recovery_policy_fails_closed(self):
        path, policy = self.recovery_policy()
        for key, value in [('publishedDigest', ''), ('baselineDigest', IMAGE), ('reason', '')]:
            invalid = json.loads(json.dumps(policy))
            invalid['profiles']['bluefin-generic'][key] = value
            path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                publication.recovery_baseline('bluefin-generic', IMAGE, self.root)

    def test_recovery_forces_qualification_and_records_both_digests(self):
        evidence = self.prepare_recovery()
        record = json.loads((evidence / 'bluefin-generic-publication.json').read_text())
        self.assertTrue(record['qualify'])
        self.assertEqual(record['publishedDigest'], IMAGE)
        self.assertEqual(record['previousDigest'], NEW)
        self.assertEqual(record['recoveryReason'], 'Missing initramfs')

    def test_wrong_profile_or_unsigned_recovery_never_mutates_recipe(self):
        self.recovery_policy()
        before = self.snapshot()
        wrong = {'Digest': NEW, 'Labels': {'io.finite.profile': 'bluefin-next'}}
        with patch.object(publication.upstream, 'inspect', side_effect=[self.published(upstream.REPOSITORY + ':finite'), wrong]), \
                patch.object(publication.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'different profile'):
                publication.prepare('bluefin-generic', True, self.root)
        with patch.object(publication.upstream, 'inspect', return_value=self.published(upstream.REPOSITORY + ':finite')), \
                patch.object(publication.subprocess, 'run', side_effect=[None, subprocess.CalledProcessError(1, 'cosign')]):
            with self.assertRaises(subprocess.CalledProcessError):
                publication.prepare('bluefin-generic', True, self.root)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_promotion_requires_exact_acceptance_and_unchanged_channel(self):
        evidence = self.prepare_recovery()
        candidate = upstream.REPOSITORY + '@sha256:' + 'd' * 64
        (evidence / 'bluefin-generic-image-ref.txt').write_text(candidate)
        acceptance = {'accepted': True, 'candidate': candidate, 'previousDigest': NEW,
                      'profile': 'bluefin-generic', 'revision': 'f' * 40,
                      'buildIdentity': IDENTITY, 'secureBoot': True, 'encryptedRoot': True}
        path = evidence / 'bluefin-generic-acceptance.json'
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'lacks matching successful'):
                publication.promote('bluefin-generic', self.root)
            for key, value in [('accepted', False), ('previousDigest', IMAGE), ('secureBoot', False)]:
                path.write_text(json.dumps({**acceptance, key: value}))
                with self.assertRaisesRegex(ValueError, 'lacks matching successful'):
                    publication.promote('bluefin-generic', self.root)
            path.write_text(json.dumps(acceptance))
            with patch.object(publication.upstream, 'inspect', return_value={'Digest': NEW}):
                with self.assertRaisesRegex(ValueError, 'Public channel changed'):
                    publication.promote('bluefin-generic', self.root)
            self.assertFalse(any(call.args[0][0] == 'skopeo' for call in run.call_args_list))
            run.reset_mock()
            with patch.object(publication.upstream, 'inspect', side_effect=[{'Digest': IMAGE},
                    {'Digest': candidate.split('@')[1]}, {'Digest': candidate.split('@')[1]}]):
                publication.promote('bluefin-generic', self.root)
            self.assertEqual(run.call_count, 3)

    def test_recovery_record_cannot_skip_or_change_reviewed_baseline(self):
        evidence = self.prepare_recovery()
        path = evidence / 'bluefin-generic-publication.json'
        original = json.loads(path.read_text())
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            for key, value in [('qualify', False), ('previousDigest', IMAGE), ('recoveryReason', '')]:
                path.write_text(json.dumps({**original, key: value}))
                with self.assertRaisesRegex(ValueError, 'reviewed recovery baseline'):
                    publication.promote('bluefin-generic', self.root)
            run.assert_not_called()

    def test_candidate_preparation_never_exposes_channel_tags(self):
        self.prepare()
        recipe = upstream.yaml.safe_load((self.root / 'recipes/bluefin-generic.yml').read_text())
        self.assertEqual(recipe['alt-tags'], ['candidate-bluefin-generic'])
        self.assertEqual(recipe['image-version'], 'stable@' + self.approved['bluefin-generic']['digest'])
        record = json.loads((self.root / '.bluebuild/bluefin-generic-publication.json').read_text())
        self.assertEqual(record['tags'], ['finite', 'latest'])

    def test_manual_qualification_overrides_matching_input_identity(self):
        with patch.dict(os.environ, FORCE_QUALIFICATION='true'):
            self.prepare()
        record = json.loads((self.root / '.bluebuild/bluefin-generic-publication.json').read_text())
        self.assertTrue(record['qualify'])

    def test_untrusted_predecessor_never_mutates_recipe(self):
        before = self.snapshot()
        with patch.object(publication.upstream, 'inspect', side_effect=self.published), \
                patch.object(publication.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cosign')):
            with self.assertRaises(subprocess.CalledProcessError):
                publication.prepare('bluefin-generic', True, self.root)
        self.assertEqual(before, self.snapshot())

    def test_validation_keeps_recipe_and_cannot_promote(self):
        before = self.snapshot()
        self.prepare(False)
        after = self.snapshot()
        self.assertEqual(before['bluefin-next.yml'], after['bluefin-next.yml'])
        self.assertEqual(upstream.yaml.safe_load(after['bluefin-generic.yml'])['alt-tags'], ['finite', 'latest'])
        with self.assertRaises(ValueError), patch.object(publication.subprocess, 'run') as run:
            publication.promote('bluefin-generic', self.root)
        run.assert_not_called()

    def test_unverified_candidate_cannot_promote(self):
        self.prepare()
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaises(FileNotFoundError):
                publication.promote('bluefin-generic', self.root)
            run.assert_not_called()

    def accepted_candidate(self, image):
        acceptance = {'accepted': True, 'candidate': image, 'previousDigest': IMAGE,
                      'profile': 'bluefin-generic', 'revision': 'f' * 40,
                      'buildIdentity': IDENTITY, 'secureBoot': True, 'encryptedRoot': True}
        (self.root / '.bluebuild/bluefin-generic-acceptance.json').write_text(json.dumps(acceptance))

    def test_missing_vm_receipt_blocks_before_registry_access(self):
        self.prepare()
        image = upstream.REPOSITORY + '@' + IMAGE
        (self.root / '.bluebuild/bluefin-generic-image-ref.txt').write_text(image + '\n')
        self.accepted_candidate(image)
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), \
                patch.object(publication.desktop, 'verify', self.desktop_verifier), \
                patch.object(publication.subprocess, 'run') as run, \
                patch.object(publication.upstream, 'inspect') as inspect:
            with self.assertRaisesRegex(ValueError, 'Missing hash-bound VM security receipt'):
                publication.promote('bluefin-generic', self.root)
            run.assert_not_called()
            inspect.assert_not_called()
        self.assertFalse((self.root / '.bluebuild/bluefin-generic-promoted.json').exists())

    def test_promotion_uses_verified_digest_for_both_aliases(self):
        self.prepare()
        image = upstream.REPOSITORY + '@' + IMAGE
        (self.root / '.bluebuild/bluefin-generic-image-ref.txt').write_text(image + '\n')
        self.accepted_candidate(image)
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run, patch.object(publication.upstream, 'inspect', return_value={'Digest': IMAGE}):
            publication.promote('bluefin-generic', self.root)
            self.desktop.assert_called_once()
            self.assertEqual(self.desktop.call_args.args[0], self.root / '.bluebuild')
            self.assertEqual(self.desktop.call_args.args[1]['candidate'], image)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args_list[0].args[0], ['cosign', 'verify', '--new-bundle-format=false', '--key', str(self.root / 'cosign.pub'), image])
            for call in run.call_args_list[1:]:
                self.assertIn('docker://' + image, call.args[0])
                self.assertIn('--preserve-digests', call.args[0])
            self.assertTrue((self.root / '.bluebuild/bluefin-generic-promoted.json').exists())

    def test_failed_promotion_does_not_report_success(self):
        self.prepare()
        (self.root / '.bluebuild/bluefin-generic-image-ref.txt').write_text(upstream.REPOSITORY + '@' + IMAGE)
        self.accepted_candidate(upstream.REPOSITORY + '@' + IMAGE)
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'skopeo')):
            with self.assertRaises(subprocess.CalledProcessError):
                publication.promote('bluefin-generic', self.root)
        self.assertFalse((self.root / '.bluebuild/bluefin-generic-promoted.json').exists())

    def test_inspection_failure_never_creates_verified_marker(self):
        self.prepare()
        bindir = self.root / 'bin'
        bindir.mkdir()
        shutil.copytree(ROOT / 'sources', self.root / 'sources')
        shutil.copytree(ROOT / 'files/security', self.root / 'files/security')
        recipe = self.approved['bluefin-generic']
        labels = {'org.opencontainers.image.base.digest': recipe['digest'], 'org.opencontainers.image.revision': 'f' * 40,
                  'io.finite.build-inputs': IDENTITY,
                  'io.finite.profile': 'bluefin-generic', 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}
        (self.root / 'image.json').write_text(json.dumps([{'Config': {'Labels': labels}}]))
        for name, script in {
            'skopeo': 'echo \'{"Digest":"' + IMAGE + '"}\'',
            'docker': 'case "$1" in pull) exit 0;; inspect) cat image.json;; run) exit "${RUNTIME_STATUS:-0}";; *) exit 1;; esac',
        }.items():
            path = bindir / name
            path.write_text('#!' + shutil.which('bash') + '\n' + script + '\n')
            path.chmod(0o755)
        env = {**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'], 'GITHUB_SHA': 'f' * 40}
        command = ['bash', str(ROOT / 'scripts/bluebuild/inspect-built.sh'), 'bluefin-generic', 'finite', 'true']
        marker = self.root / '.bluebuild/bluefin-generic-image-ref.txt'
        for failure in [{'RUNTIME_STATUS': '1'}]:
            result = subprocess.run(command, cwd=self.root, env={**env, **failure}, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
        labels['org.opencontainers.image.base.digest'] = NEW
        (self.root / 'image.json').write_text(json.dumps([{'Config': {'Labels': labels}}]))
        self.assertNotEqual(subprocess.run(command, cwd=self.root, env=env, capture_output=True).returncode, 0)
        self.assertFalse(marker.exists())
        labels['org.opencontainers.image.base.digest'] = recipe['digest']
        (self.root / 'image.json').write_text(json.dumps([{'Config': {'Labels': labels}}]))
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), upstream.REPOSITORY + '@' + IMAGE)

    def test_same_base_with_stale_or_missing_payload_requires_recovery(self):
        for identity in ('v1:' + 'd' * 64, None):
            def stale(reference, **kwargs):
                image = self.published(reference, **kwargs)
                image['Labels']['io.finite.build-inputs'] = identity
                return image
            with patch.object(upstream, 'inspect', side_effect=stale):
                self.assertEqual(set(upstream.reconcile(self.root)['profiles']), set(upstream.PROFILES))

    def test_enforced_qualification_requires_exact_evidence(self):
        self.prepare()
        evidence = self.root / '.bluebuild'
        path = evidence / 'bluefin-generic-publication.json'
        record = json.loads(path.read_text())
        record.update(qualify=True, qualificationMode='enforce')
        path.write_text(json.dumps(record))
        image = upstream.REPOSITORY + '@' + IMAGE
        (evidence / 'bluefin-generic-image-ref.txt').write_text(image)
        accepted = {'accepted': True, 'candidate': image, 'previousDigest': IMAGE,
                    'profile': 'bluefin-generic', 'revision': 'f' * 40,
                    'buildIdentity': IDENTITY, 'secureBoot': True, 'encryptedRoot': True}
        with patch.dict(os.environ, GITHUB_SHA='f' * 40, FINITE_QUALIFICATION_MODE='enforce'), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                publication.promote('bluefin-generic', self.root)
            for field in accepted:
                (evidence / 'bluefin-generic-acceptance.json').write_text(json.dumps({**accepted, field: None}))
                with self.assertRaises(ValueError):
                    publication.promote('bluefin-generic', self.root)
            run.assert_not_called()
            (evidence / 'bluefin-generic-acceptance.json').write_text(json.dumps(accepted))
            with patch.object(publication.upstream, 'inspect', return_value={'Digest': IMAGE}):
                publication.promote('bluefin-generic', self.root)
            self.desktop.assert_called_once()
            self.assertEqual(self.desktop.call_args.args[0], self.root / '.bluebuild')
            self.assertEqual(self.desktop.call_args.args[1]['candidate'], image)
            self.assertEqual(run.call_count, 3)

    def test_shadow_mode_cannot_prepare_or_promote(self):
        with patch.dict(os.environ, FINITE_QUALIFICATION_MODE='shadow'):
            with self.assertRaisesRegex(ValueError, 'must be enforced'):
                self.prepare()
        self.prepare()
        evidence = self.root / '.bluebuild'
        path = evidence / 'bluefin-generic-publication.json'
        record = json.loads(path.read_text())
        record.update(qualify=True, qualificationMode='shadow')
        path.write_text(json.dumps(record))
        (evidence / 'bluefin-generic-image-ref.txt').write_text(upstream.REPOSITORY + '@' + IMAGE)
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'must be enforced'):
                publication.promote('bluefin-generic', self.root)
            run.assert_not_called()

    def test_default_policy_rejects_failed_qualification(self):
        with patch.dict(os.environ, FORCE_QUALIFICATION='true'):
            self.prepare()
        evidence = self.root / '.bluebuild'
        (evidence / 'bluefin-generic-image-ref.txt').write_text(upstream.REPOSITORY + '@' + IMAGE)
        (evidence / 'bluefin-generic-qualification-outcome.json').write_text('{"outcome":"failure"}')
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'lacks matching successful'):
                publication.promote('bluefin-generic', self.root)
            run.assert_not_called()


class PublisherAuthentication(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'sources', self.root / 'sources')
        shutil.copytree(ROOT / 'recipes', self.root / 'recipes')
        self.policy_path = self.root / 'sources/bluefin-trust.json'
        self.policy = json.loads(self.policy_path.read_text())
        self.base = 'ghcr.io/ublue-os/bluefin'

    def test_exact_digest_and_reviewed_key_are_verified(self):
        with patch.object(upstream.subprocess, 'run') as run:
            evidence = upstream.authenticate(self.base, NEW, self.root)
        run.assert_called_once_with(
            ['cosign', 'verify', '--new-bundle-format=false', '--key',
             str(self.root / 'sources/bluefin.pub'), self.base + '@' + NEW],
            check=True, stdout=subprocess.DEVNULL, timeout=150)
        self.assertEqual(evidence, {'image': self.base + '@' + NEW,
                                   'keySha256': self.policy['keySha256'], 'signatureFormat': 'legacy'})

    def test_successful_build_verification_retains_exact_publisher_receipt(self):
        verify = upstream.verify
        with patch.object(upstream, 'ROOT', self.root), patch.object(upstream, 'verify', lambda: verify(self.root)), \
                patch.object(upstream.subprocess, 'run'), patch('sys.argv', ['bluefin-upstream.py', 'verify']), \
                patch.dict(os.environ, GITHUB_SHA='f' * 40, GITHUB_OUTPUT='', GITHUB_STEP_SUMMARY=''), patch('builtins.print'):
            upstream.main()
        receipt = json.loads((self.root / '.bluebuild/upstream-verified.json').read_text())
        self.assertEqual(receipt['sourceRevision'], 'f' * 40)
        self.assertEqual(receipt['trustPolicySha256'], hashlib.sha256(self.policy_path.read_bytes()).hexdigest())
        self.assertEqual(receipt['repository'], 'closure-labs/finite')
        self.assertEqual({entry['image'] for entry in receipt['verified']},
                         {recipe['base'] + '@' + recipe['digest'] for recipe in upstream.recipes(self.root).values()})

    def test_failed_publisher_verification_cannot_emit_build_receipt(self):
        verify = upstream.verify
        with patch.object(upstream, 'ROOT', self.root), patch.object(upstream, 'verify', lambda: verify(self.root)), \
                patch.object(upstream.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cosign')), \
                patch('sys.argv', ['bluefin-upstream.py', 'verify']), patch.dict(os.environ, GITHUB_SHA='f' * 40):
            with self.assertRaises(subprocess.CalledProcessError):
                upstream.main()
        self.assertFalse((self.root / '.bluebuild/upstream-verified.json').exists())

    def test_invalid_policy_never_invokes_verifier(self):
        for field, value in [('schema', 0), ('signatureFormat', 'unknown'),
                             ('key', '../unreviewed.pub'), ('keySha256', '0' * 64),
                             ('repositories', [self.base, 'ghcr.io/untrusted/image'])]:
            with self.subTest(field=field):
                self.policy_path.write_text(json.dumps({**self.policy, field: value}))
                with patch.object(upstream.subprocess, 'run') as run:
                    with self.assertRaises(ValueError):
                        upstream.authenticate(self.base, NEW, self.root)
                    run.assert_not_called()

    def test_replaced_key_unapproved_repository_and_mutable_tag_rejected(self):
        for base, digest in [('ghcr.io/attacker/bluefin', NEW), (self.base, 'stable')]:
            with self.subTest(base=base, digest=digest), patch.object(upstream.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    upstream.authenticate(base, digest, self.root)
                run.assert_not_called()
        (self.root / 'sources/bluefin.pub').write_text('substituted key')
        with patch.object(upstream.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                upstream.authenticate(self.base, NEW, self.root)
            run.assert_not_called()

    def test_unsigned_wrong_signer_and_timeout_keep_all_pins(self):
        observed = {recipe['base']: NEW for recipe in upstream.recipes(self.root).values()}
        before = {p.name: p.read_bytes() for p in (self.root / 'recipes').glob('*.yml')}
        errors = [subprocess.CalledProcessError(1, 'cosign', stderr='no matching signatures'),
                  subprocess.CalledProcessError(1, 'cosign', stderr='invalid signature'),
                  subprocess.TimeoutExpired('cosign', 150)]
        for error in errors:
            with self.subTest(error=str(error)), patch.object(upstream.subprocess, 'run', side_effect=[None, error]):
                with self.assertRaises(type(error)):
                    upstream.update(self.root, observed)
            self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'recipes').glob('*.yml')})

    def test_verify_checks_both_approved_foundations(self):
        with patch.object(upstream.subprocess, 'run') as run:
            evidence = upstream.verify(self.root)
        self.assertEqual(len(evidence['verified']), 2)
        self.assertEqual({call.args[0][-1] for call in run.call_args_list},
                         {recipe['base'] + '@' + recipe['digest'] for recipe in upstream.recipes(self.root).values()})


if __name__ == '__main__':
    unittest.main()
