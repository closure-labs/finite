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


class BluefinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'recipes', self.root / 'recipes')
        self.approved = upstream.recipes(self.root)
        self.observed = {r['base']: r['digest'] for r in self.approved.values()}

    def snapshot(self):
        return {p.name: p.read_bytes() for p in (self.root / 'recipes').glob('*.yml')}

    def published(self, reference, **_kwargs):
        tag = reference.rsplit(':', 1)[1]
        profile, recipe = next((p, r) for p, r in self.approved.items() if tag in r['tags'])
        return {'Digest': IMAGE, 'Labels': {
            'org.opencontainers.image.base.digest': recipe['digest'],
            'io.finite.profile': profile,
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
            if reference.endswith(':dev-next'):
                image['Labels']['org.opencontainers.image.base.digest'] = NEW
            return image
        with patch.object(upstream, 'inspect', side_effect=missed_publication):
            self.assertEqual(upstream.reconcile(self.root)['profiles'], ['bluefin-dx-next'])

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
        with patch.dict(os.environ, GITHUB_SHA='f' * 40):
            publication.prepare('bluefin-generic', publish, self.root)

    def test_candidate_preparation_never_exposes_channel_tags(self):
        self.prepare()
        recipe = upstream.yaml.safe_load((self.root / 'recipes/bluefin-generic.yml').read_text())
        self.assertEqual(recipe['alt-tags'], ['candidate-bluefin-generic'])
        self.assertEqual(recipe['image-version'], 'stable@' + self.approved['bluefin-generic']['digest'])
        record = json.loads((self.root / '.bluebuild/bluefin-generic-publication.json').read_text())
        self.assertEqual(record['tags'], ['bluefin-generic', 'latest'])

    def test_validation_keeps_recipe_and_cannot_promote(self):
        before = self.snapshot()
        self.prepare(False)
        self.assertEqual(before, self.snapshot())
        with self.assertRaises(ValueError), patch.object(publication.subprocess, 'run') as run:
            publication.promote('bluefin-generic', self.root)
        run.assert_not_called()

    def test_unverified_candidate_cannot_promote(self):
        self.prepare()
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run:
            with self.assertRaises(FileNotFoundError):
                publication.promote('bluefin-generic', self.root)
            run.assert_not_called()

    def test_promotion_uses_verified_digest_for_both_aliases(self):
        self.prepare()
        image = upstream.REPOSITORY + '@' + IMAGE
        (self.root / '.bluebuild/bluefin-generic-image-ref.txt').write_text(image + '\n')
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run') as run, patch.object(publication.upstream, 'inspect', return_value={'Digest': IMAGE}):
            publication.promote('bluefin-generic', self.root)
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertIn('docker://' + image, call.args[0])
                self.assertIn('--preserve-digests', call.args[0])
            self.assertTrue((self.root / '.bluebuild/bluefin-generic-promoted.json').exists())

    def test_failed_promotion_does_not_report_success(self):
        self.prepare()
        (self.root / '.bluebuild/bluefin-generic-image-ref.txt').write_text(upstream.REPOSITORY + '@' + IMAGE)
        with patch.dict(os.environ, GITHUB_SHA='f' * 40), patch.object(publication.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'skopeo')):
            with self.assertRaises(subprocess.CalledProcessError):
                publication.promote('bluefin-generic', self.root)
        self.assertFalse((self.root / '.bluebuild/bluefin-generic-promoted.json').exists())

    def test_inspection_failure_never_creates_verified_marker(self):
        self.prepare()
        bindir = self.root / 'bin'
        bindir.mkdir()
        shutil.copytree(ROOT / 'sources', self.root / 'sources')
        recipe = self.approved['bluefin-generic']
        labels = {'org.opencontainers.image.base.digest': recipe['digest'], 'org.opencontainers.image.revision': 'f' * 40,
                  'io.finite.profile': 'bluefin-generic', 'org.opencontainers.image.source': 'https://github.com/closure-labs/finite'}
        (self.root / 'image.json').write_text(json.dumps([{'Config': {'Labels': labels}}]))
        for name, script in {
            'skopeo': 'echo \'{"Digest":"' + IMAGE + '"}\'',
            'cosign': 'exit "${SIGNATURE_STATUS:-0}"',
            'docker': 'case "$1" in pull) exit 0;; inspect) cat image.json;; run) exit "${RUNTIME_STATUS:-0}";; *) exit 1;; esac',
        }.items():
            path = bindir / name
            path.write_text('#!' + shutil.which('bash') + '\n' + script + '\n')
            path.chmod(0o755)
        env = {**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'], 'GITHUB_SHA': 'f' * 40}
        command = ['bash', str(ROOT / 'scripts/bluebuild/inspect-built.sh'), 'bluefin-generic', 'bluefin-generic', 'true']
        marker = self.root / '.bluebuild/bluefin-generic-image-ref.txt'
        for failure in [{'SIGNATURE_STATUS': '1'}, {'RUNTIME_STATUS': '1'}]:
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


if __name__ == '__main__':
    unittest.main()
