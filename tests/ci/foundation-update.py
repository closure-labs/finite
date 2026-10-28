"""Offline regressions for CI-qualified, transactional Foundation proposals."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('foundation_update', ROOT / 'scripts/ci/update-foundation.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
REV = 'a' * 40
OLD = 'b' * 40
HASH = 'sha256-' + 'A' * 43 + '='
LOCKED = {'type': 'github', 'owner': 'closure-labs', 'repo': 'foundation',
          'rev': REV, 'narHash': HASH, 'lastModified': 100}
METADATA = {'schema': 1, 'compatibility': 1, 'version': '0.5.1', 'rev': REV, 'narHash': HASH}
RUN = {'id': 42, 'run_number': 10, 'run_attempt': 2, 'workflow_id': 7,
       'path': updater.WORKFLOW, 'head_sha': REV, 'head_branch': 'main', 'event': 'push',
       'repository': {'full_name': updater.REPOSITORY},
       'head_repository': {'full_name': updater.REPOSITORY},
       'status': 'completed', 'conclusion': 'success'}
GATE = {'name': 'CI gate', 'head_sha': REV, 'status': 'completed', 'conclusion': 'success'}


class Qualification(unittest.TestCase):
    def check(self, run=None, gates=None, runs=None):
        responses = [{'id': 7, 'path': updater.WORKFLOW, 'state': 'active'},
                     {'total_count': len(runs or [RUN]), 'workflow_runs': runs or [RUN]},
                     run or RUN,
                     {'total_count': len(gates if gates is not None else [GATE]),
                      'jobs': gates if gates is not None else [GATE]}, run or RUN]
        with patch.object(updater, 'api', side_effect=responses) as api:
            result = updater.qualification(REV)
            return result, api

    def test_exact_push_success_and_attempt_specific_gate(self):
        result, api = self.check()
        self.assertEqual(result['runId'], 42)
        self.assertEqual(result['runAttempt'], 2)
        self.assertIn('attempts/2/jobs', api.call_args_list[-2].args[0])

    def test_pending_or_failed_latest_run_never_falls_back(self):
        for status, conclusion in [('queued', None), ('in_progress', None), ('completed', 'failure'), ('completed', 'cancelled')]:
            with self.subTest(status=status, conclusion=conclusion):
                result, api = self.check(run={**RUN, 'status': status, 'conclusion': conclusion},
                                         runs=[{**RUN, 'id': 1, 'run_number': 1}, RUN])
                self.assertIsNone(result)
                self.assertEqual(api.call_args.args[0], 'actions/runs/42')

    def test_reject_wrong_origin_revision_event_workflow_attempt(self):
        for key, value in [('path', '.github/workflows/other.yml'), ('workflow_id', 8),
                           ('head_sha', OLD), ('head_branch', 'feature'), ('event', 'pull_request'),
                           ('repository', {'full_name': 'attacker/foundation'}),
                           ('head_repository', {'full_name': 'attacker/foundation'}), ('run_attempt', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(run={**RUN, key: value})

    def test_reject_missing_skipped_wrong_or_duplicate_gate(self):
        for gates in [[], [GATE, GATE], [{**GATE, 'conclusion': 'skipped'}], [{**GATE, 'head_sha': OLD}]]:
            with self.subTest(gates=gates), self.assertRaises(ValueError):
                self.check(gates=gates)

    def test_rerun_during_jobs_read_is_not_qualified(self):
        responses = [{'id': 7, 'path': updater.WORKFLOW, 'state': 'active'},
                     {'total_count': 1, 'workflow_runs': [RUN]}, RUN,
                     {'total_count': 1, 'jobs': [GATE]},
                     {**RUN, 'run_attempt': 3, 'status': 'queued', 'conclusion': None}]
        with patch.object(updater, 'api', side_effect=responses):
            self.assertIsNone(updater.qualification(REV))

    def test_incomplete_inventory_fails_closed(self):
        with patch.object(updater, 'api', side_effect=[{'id': 7, 'path': updater.WORKFLOW, 'state': 'active'},
                                                     {'total_count': 101, 'workflow_runs': [RUN]}]), self.assertRaises(ValueError):
            updater.qualification(REV)


class Transaction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sources').mkdir()
        (self.root / 'flake.nix').write_text(f'foundation.url = "github:closure-labs/foundation/{OLD}";\n')
        self.lock = {'version': 7, 'root': 'root', 'nodes': {
            'root': {'inputs': {'foundation': 'foundation', 'other': 'other'}},
            'foundation': {'locked': {**LOCKED, 'rev': OLD},
                           'original': {'type': 'github', 'owner': 'closure-labs', 'repo': 'foundation', 'rev': OLD}},
            'other': {'locked': {'rev': 'c' * 40}, 'inputs': {'nested': 'nested'}},
            'nested': {'locked': {'rev': 'd' * 40}}}}
        (self.root / 'flake.lock').write_text(json.dumps(self.lock))
        (self.root / 'sources/foundation.json').write_text(json.dumps({**METADATA, 'rev': OLD}))
        self.before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.evidence = {'workflow': updater.WORKFLOW, 'runId': 42, 'runAttempt': 2, 'url': 'https://github.com/closure-labs/foundation/actions/runs/42'}

    def execute(self, mutate=None, metadata=None, main=REV, evidence=None, comparison=None, resolved=None):
        def capture(command, **kwargs):
            if command[1:3] == ['flake', 'metadata']:
                return json.dumps({'locked': LOCKED if resolved is None else resolved, 'locks': {'root': 'root', 'nodes': {'root': {}}}})
            if command[1] == 'eval':
                return json.dumps({'metadata': metadata or METADATA, 'lock': {'root': 'root', 'nodes': {'root': {}}}})
            self.assertEqual(command, ['nix', 'flake', 'update', 'foundation'])
            lock = copy.deepcopy(self.lock)
            lock['nodes']['foundation'] = {'locked': copy.deepcopy(LOCKED),
                'original': {'type': 'github', 'owner': 'closure-labs', 'repo': 'foundation', 'ref': 'main'}}
            if mutate:
                mutate(lock)
            (self.root / 'flake.lock').write_text(json.dumps(lock))
            return ''
        with patch.object(updater, 'api', return_value=comparison or {'status': 'ahead', 'base_commit': {'sha': OLD}, 'merge_base_commit': {'sha': OLD}}), patch.object(updater, 'capture', side_effect=capture), patch.object(updater, 'main_revision', return_value=main), patch.object(updater, 'qualification', return_value=evidence or self.evidence):
            return updater.update(self.root, REV, self.evidence)

    def assert_unchanged(self):
        for path, before in self.before.items():
            self.assertEqual(path.read_bytes(), before, str(path))

    def test_same_version_new_revision_with_provenance(self):
        self.execute()
        self.assertIn('/main"', (self.root / 'flake.nix').read_text())
        metadata = json.loads((self.root / 'sources/foundation.json').read_text())
        self.assertEqual(metadata['version'], '0.5.1')
        self.assertEqual(metadata['rev'], REV)
        self.assertEqual(metadata['upstreamCI'], self.evidence)

    def test_metadata_without_hash_uses_exact_evaluated_source(self):
        self.execute(resolved={key: value for key, value in LOCKED.items() if key != 'narHash'})
        node = json.loads((self.root / 'flake.lock').read_text())['nodes']['foundation']
        self.assertEqual(node['locked'], LOCKED)
        self.assertEqual(json.loads((self.root / 'sources/foundation.json').read_text())['narHash'], HASH)

    def test_malformed_or_mismatched_resolution_hash_never_mutates(self):
        for value in [None, False, 'wrong', 'sha256-' + 'B' * 43 + '=']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.execute(resolved={**LOCKED, 'narHash': value})
            self.assert_unchanged()

    def test_missing_metadata_hash_does_not_allow_invalid_evaluated_source(self):
        for delta in [{'rev': OLD}, {'narHash': None}, {'narHash': 'wrong'}]:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.execute(resolved={key: value for key, value in LOCKED.items() if key != 'narHash'},
                             metadata={**METADATA, **delta})
            self.assert_unchanged()

    def test_wrong_lock_hash_revision_original_or_unrelated_closure_rolls_back(self):
        for mutate in [lambda lock: lock['nodes']['foundation']['locked'].update(rev=OLD),
                       lambda lock: lock['nodes']['foundation'].update(locked={**LOCKED, 'narHash': 'wrong'}),
                       lambda lock: lock['nodes']['foundation']['original'].update(rev=REV),
                       lambda lock: lock['nodes']['nested']['locked'].update(rev='e' * 40)]:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.execute(mutate=mutate)
            self.assert_unchanged()

    def test_unsupported_or_inconsistent_metadata_no_mutation(self):
        for delta in [{'schema': 2}, {'version': '0.5.0'}, {'compatibility': True}, {'rev': OLD}, {'narHash': 'wrong'}, {'version': 'injected\nchanged=true'}]:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.execute(metadata={**METADATA, **delta})
            self.assert_unchanged()

    def test_main_advancement_or_rerun_no_mutation(self):
        for kwargs in [{'main': OLD}, {'evidence': {**self.evidence, 'runAttempt': 3}}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.execute(**kwargs)
            self.assert_unchanged()

    def test_source_dependency_override_is_rejected(self):
        def override(lock):
            lock['nodes']['foundation']['inputs'] = {'injected': 'other'}
        with self.assertRaises(ValueError):
            self.execute(mutate=override)
        self.assert_unchanged()

    def test_rerun_during_lock_update_rolls_back(self):
        def rerun(lock):
            updater.qualification.return_value = {**self.evidence, 'runAttempt': 3}
        with self.assertRaises(ValueError):
            self.execute(mutate=rerun)
        self.assert_unchanged()

    def test_nonforward_history_is_rejected(self):
        for comparison in [{'status': 'behind'}, {'status': 'diverged'},
                           {'status': 'ahead', 'base_commit': {'sha': OLD}, 'merge_base_commit': {'sha': REV}}]:
            with self.subTest(comparison=comparison), self.assertRaises(ValueError):
                self.execute(comparison=comparison)
            self.assert_unchanged()

    def test_failed_lock_update_restores_all_files(self):
        def fail(lock):
            (self.root / 'flake.lock').write_text('partial lock')
            raise RuntimeError('Nix update failed')
        with self.assertRaises(RuntimeError):
            self.execute(mutate=fail)
        self.assert_unchanged()


if __name__ == '__main__':
    unittest.main()
