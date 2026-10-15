#!/usr/bin/env python3
"""Protect cache retention against incomplete listings and broad deletions."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('prune', ROOT / 'scripts/ci/prune-ci-caches.py')
prune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune)
LOCK = 'a' * 64


def cache(identifier, kind='checks', platform='Linux-X64', ref='refs/heads/main', created=None):
    keys = {'checks': f'nix-store-v2-{platform}-{LOCK}-{identifier:040x}',
            'legacy': f'nix-store-v1-{platform}-{LOCK}',
            'sources': f'nix-sources-v1-{platform}-{LOCK}',
            'grype': f'grype-db-v1-{platform}-{LOCK}-{identifier}-1',
            'grype-benchmark': f'grype-security-benchmark-v1-{platform}-{LOCK}-{identifier}-1'}
    stamp = created or datetime(2026, 1, identifier, tzinfo=timezone.utc)
    return {'id': identifier, 'key': keys[kind], 'ref': ref,
            'created_at': stamp.isoformat(), 'timestamp': stamp}


class Retention(unittest.TestCase):
    def test_benchmark_databases_have_separate_two_generation_retention(self):
        entries = [cache(number, 'grype-benchmark') for number in (1, 2, 3, 4)]
        entries += [cache(5, 'grype'), cache(6, 'grype-benchmark', ref='refs/heads/topic'),
                    dict(cache(7, 'grype-benchmark'), key=cache(7, 'grype-benchmark')['key'] + '-unrecognized')]
        self.assertEqual([item['id'] for item in prune.deletions(entries)], [1, 2])

    def workflow_event(self):
        return {'action': 'completed', 'repository': {'full_name': prune.REPOSITORY},
                'workflow_run': {'status': 'completed', 'conclusion': 'failure',
                                 'head_repository': {'full_name': prune.REPOSITORY},
                                 'head_branch': 'main', 'path': '.github/workflows/build.yml', 'event': 'push'}}

    def event_env(self, path):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': prune.REPOSITORY,
                'GITHUB_REF': prune.MAIN_REF, 'GITHUB_EVENT_NAME': 'workflow_run',
                'GITHUB_EVENT_PATH': str(path)}

    def test_completed_main_build_workflow_run_may_have_failed_downstream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            for event in ('push', 'schedule', 'workflow_dispatch'):
                payload = self.workflow_event()
                payload['workflow_run']['event'] = event
                path.write_text(json.dumps(payload))
                prune.require_trusted_main(self.event_env(path))

    def test_workflow_run_rejects_foreign_pr_wrong_workflow_and_incomplete_origin(self):
        mutations = [lambda item: item.update(action='requested'),
                     lambda item: item['repository'].update(full_name='foreign/finite'),
                     lambda item: item['workflow_run'].update(status='in_progress'),
                     lambda item: item['workflow_run']['head_repository'].update(full_name='foreign/finite'),
                     lambda item: item['workflow_run'].update(head_repository=None),
                     lambda item: item['workflow_run'].update(head_branch='topic'),
                     lambda item: item['workflow_run'].update(path='.github/workflows/untrusted.yml'),
                     lambda item: item['workflow_run'].update(event='pull_request'),
                     lambda item: item['workflow_run'].update(event='pull_request_target')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            for mutate in mutations:
                payload = self.workflow_event()
                mutate(payload)
                path.write_text(json.dumps(payload))
                with self.subTest(payload=payload), patch.dict(prune.os.environ, self.event_env(path), clear=True), \
                        patch.object(prune, 'list_caches') as listing, self.assertRaises(ValueError):
                    prune.prune(True)
                listing.assert_not_called()

    def test_workflow_run_requires_valid_bounded_local_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            for payload in (b'invalid json', b'[]', b'{}', b'{"workflow_run": null}',
                            b' ' * (prune.MAX_EVENT_BYTES + 1)):
                path.write_bytes(payload)
                with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                    prune.require_trusted_main(self.event_env(path))
            with self.assertRaises(ValueError):
                prune.require_trusted_main(dict(self.event_env(path), GITHUB_EVENT_PATH=''))
            with self.assertRaises(OSError):
                prune.require_trusted_main(self.event_env(Path(directory) / 'missing.json'))

    def test_keep_two_newest_checks_and_grype_per_platform(self):
        entries = [cache(1), cache(3), cache(2), cache(4, platform='Linux-ARM64'),
                   cache(5, 'grype'), cache(6, 'grype'), cache(7, 'grype')]
        self.assertEqual([item['id'] for item in prune.deletions(entries)], [1, 5])

    def test_sources_keep_latest_per_platform_and_use_creation_not_last_access(self):
        entries = [dict(cache(1, 'sources'), last_accessed_at='2099-01-01T00:00:00Z'),
                   cache(2, 'sources'), cache(3, 'sources', platform='Linux-ARM64')]
        self.assertEqual([item['id'] for item in prune.deletions(entries)], [1])

    def test_never_prune_pr_merge_or_unrelated_caches(self):
        entries = [cache(1, ref='refs/pull/10/merge'), cache(2, ref='refs/heads/topic'),
                   cache(3, ref='refs/heads/gh-readonly-queue/main/pr-1'),
                   dict(cache(4), key='nix-store-v2-Linux-X64-unrecognized'),
                   dict(cache(5), key=cache(5)['key'] + '-extra'),
                   dict(cache(6), key='other-' + cache(6)['key'])]
        self.assertEqual(prune.deletions(entries), [])

    def test_legacy_requires_two_current_platform_v2_seeds(self):
        legacy = [cache(1, 'legacy'), cache(2, 'legacy', platform='Linux-ARM64')]
        self.assertEqual(prune.deletions(legacy + [cache(3)]), [])
        self.assertEqual([item['id'] for item in prune.deletions(legacy + [cache(3), cache(4)])], [1])

    def test_duplicate_archive_versions_are_not_distinct_v2_generations(self):
        first = cache(3)
        duplicate_version = dict(first, id=4)
        self.assertEqual(prune.deletions([cache(1, 'legacy'), first, duplicate_version]), [])

    def test_malformed_or_incomplete_api_never_yields_a_plan(self):
        entry = cache(1)
        entry.pop('timestamp')
        invalid = [[], {}, [{'total_count': True, 'actions_caches': []}],
                   [{'total_count': 2, 'actions_caches': [entry]}],
                   [{'total_count': 2, 'actions_caches': [entry]}, {'total_count': 2, 'actions_caches': [entry]}],
                   [{'total_count': 1, 'actions_caches': [entry]}, {'total_count': 2, 'actions_caches': []}],
                   [{'total_count': 1, 'actions_caches': [dict(entry, id='1')]}],
                   [{'total_count': 1, 'actions_caches': [dict(entry, created_at='bad')]}],
                   [{'total_count': 1, 'actions_caches': [dict(entry, created_at='2026-01-01')]}]]
        for pages in invalid:
            with self.subTest(pages=pages), patch.object(prune.subprocess, 'check_output', return_value=json.dumps(pages)):
                with self.assertRaises((ValueError, TypeError)):
                    prune.list_caches()

    def test_all_paginated_entries_are_consumed(self):
        entries = [cache(1), cache(2)]
        pages = [{'total_count': 2, 'actions_caches': [{k: v for k, v in item.items() if k != 'timestamp'}]}
                 for item in entries]
        with patch.object(prune.subprocess, 'check_output', return_value=json.dumps(pages)) as command:
            self.assertEqual([item['id'] for item in prune.list_caches()], [1, 2])
        self.assertIn('--paginate', command.call_args.args[0])
        self.assertIn('--slurp', command.call_args.args[0])

    def test_transport_errors_abort_before_any_delete(self):
        for error in (subprocess.CalledProcessError(1, 'gh'), subprocess.TimeoutExpired('gh', 180),
                      OSError('transport failed'), json.JSONDecodeError('broken', '!', 0)):
            with self.subTest(error=error), patch.object(prune, 'list_caches', side_effect=error), \
                    patch.object(prune.subprocess, 'run') as delete:
                with self.assertRaises(type(error)):
                    prune.prune()
                delete.assert_not_called()

    def test_default_dry_run_has_no_deletion(self):
        with patch.object(prune, 'list_caches', return_value=[cache(1), cache(2), cache(3)]), \
                patch.object(prune.subprocess, 'run') as delete, patch('builtins.print'):
            result = prune.prune()
        self.assertFalse(result['apply'])
        self.assertEqual([item['id'] for item in result['candidates']], [1])
        delete.assert_not_called()

    def test_delete_transport_failure_stops_before_later_deletions(self):
        trusted = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': prune.REPOSITORY,
                   'GITHUB_REF': prune.MAIN_REF, 'GITHUB_EVENT_NAME': 'schedule'}
        with patch.dict(prune.os.environ, trusted, clear=True), \
                patch.object(prune, 'list_caches', return_value=[cache(1), cache(2), cache(3), cache(4)]), \
                patch.object(prune.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gh')) as delete, \
                patch('builtins.print'):
            with self.assertRaises(subprocess.CalledProcessError):
                prune.prune(True)
        self.assertEqual(delete.call_count, 1)

    def test_apply_checks_trusted_context_before_network_and_only_deletes_selected_id(self):
        trusted = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': prune.REPOSITORY,
                   'GITHUB_REF': prune.MAIN_REF, 'GITHUB_EVENT_NAME': 'workflow_dispatch'}
        for env in ({}, dict(trusted, GITHUB_REF='refs/pull/1/merge'),
                    dict(trusted, GITHUB_REPOSITORY='fork/finite'), dict(trusted, GITHUB_EVENT_NAME='pull_request_target')):
            with self.subTest(env=env), patch.dict(prune.os.environ, env, clear=True), \
                    patch.object(prune, 'list_caches') as listing:
                with self.assertRaises(ValueError):
                    prune.prune(True)
                listing.assert_not_called()
        with patch.dict(prune.os.environ, trusted, clear=True), \
                patch.object(prune, 'list_caches', return_value=[cache(1), cache(2), cache(3)]), \
                patch.object(prune.subprocess, 'run') as delete, patch('builtins.print'):
            result = prune.prune(True)
        self.assertEqual(result['deletedIds'], [1])
        self.assertEqual(delete.call_args.args[0], ['gh', 'api', '--method', 'DELETE',
                         'repos/closure-labs/finite/actions/caches/1'])
        self.assertTrue(delete.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
