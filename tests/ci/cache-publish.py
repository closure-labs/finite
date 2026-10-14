#!/usr/bin/env python3
"""Keep cache write credentials outside source realization and untrusted events."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cache_publish', ROOT / 'scripts/ci/cache-publish.py')
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)
ENV = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
       'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_run',
       'CACHE_SOURCE_REVISION': 'a' * 40}
STORE = '/nix/store/' + 'b' * 32 + '-proof'


class Publisher(unittest.TestCase):
    def test_only_trusted_successor_can_publish(self):
        cache.boundary(ENV)
        for key, value in [('GITHUB_REF', 'refs/pull/1/merge'), ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_REPOSITORY', 'fork/finite'), ('CACHE_SOURCE_REVISION', 'main')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                cache.boundary(dict(ENV, **{key: value}))

    def test_realization_refuses_a_writer_credential(self):
        with patch.dict(os.environ, dict(ENV, CACHIX_AUTH_TOKEN='secret'), clear=True), self.assertRaises(ValueError):
            cache.prepare(Path('/tmp/unused-cache-manifest'))

    def test_push_checks_roots_again_before_external_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'roots.json'
            record = {'schema': 1, 'revision': 'a' * 40, 'cache': 'finite-os',
                      'roots': [{'kind': 'proof', 'name': 'check', 'path': STORE, 'bytes': 10}]}
            manifest.write_text(json.dumps(record))
            with patch.dict(os.environ, dict(ENV, CACHIX_AUTH_TOKEN='secret'), clear=True), \
                    patch.object(cache, 'closure_size', return_value=10), patch.object(cache.subprocess, 'run') as run:
                cache.push(manifest)
                self.assertEqual(run.call_args.args[0], ['cachix', 'push', '--omit-deriver', 'finite-os', STORE])
                record['roots'][0]['path'] = '/tmp/credential'
                manifest.write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    cache.push(manifest)
                self.assertEqual(run.call_count, 1)

    def test_changed_closure_size_cannot_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'roots.json'
            manifest.write_text(json.dumps({'schema': 1, 'revision': 'a' * 40, 'cache': 'finite-os',
                'roots': [{'kind': 'tool', 'name': 'scanner-tools', 'path': STORE, 'bytes': 10}]}))
            with patch.dict(os.environ, dict(ENV, CACHIX_AUTH_TOKEN='secret'), clear=True), \
                    patch.object(cache, 'closure_size', return_value=11), patch.object(cache.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    cache.push(manifest)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
