#!/usr/bin/env python3
"""Exercise benchmark isolation and exact source boundaries without builds."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('benchmark', ROOT / 'experiments/builder-benchmark/run.py')
benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)


class Benchmark(unittest.TestCase):
    def test_export_is_explicit_and_no_remote_cache_or_publication(self):
        args = benchmark.build_command('private', Path('Containerfile'), Path('ctx'), 'localhost/test',
            Path('meta.json'), 'type=docker,dest=/tmp/output.tar', {'PROFILE': 'finite'})
        self.assertIn('type=docker,dest=/tmp/output.tar', args)
        self.assertIn('--pull', args)
        self.assertIn('--progress=rawjson', args)
        self.assertIn('--provenance=false', args)
        self.assertFalse(set(args) & {'--push', '--cache-from', '--cache-to', '--secret', '--ssh'})

    def test_measure_records_failure_and_preserves_exception(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(benchmark, 'command', side_effect=ValueError('failure')):
            with self.assertRaises(ValueError):
                benchmark.measure(Path(directory), 'assembly', ['false'])
            record = json.loads((Path(directory) / 'timings.jsonl').read_text())
            self.assertEqual(record['status'], 1)
            self.assertEqual(record['stage'], 'assembly')

    def test_graph_preserves_cache_network_and_overlapping_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.jsonl'
            events = [{'vertexes': [{'digest': 'fetch', 'name': 'load metadata for pinned base', 'started': 'one'}]},
                {'vertexes': [{'digest': 'run', 'name': 'RUN customization', 'started': 'one'}]},
                {'vertexes': [{'digest': 'fetch', 'name': 'load metadata for pinned base', 'completed': 'two', 'cached': True}]}]
            path.write_text('\n'.join(map(json.dumps, events)))
            observed = benchmark.graph(path)
            self.assertEqual(observed['cachedVertices'], 1)
            self.assertTrue(observed['durationsOverlap'])
            self.assertEqual(observed['vertices'][0]['started'], 'one')
            self.assertEqual(observed['vertices'][0]['completed'], 'two')

    def test_installer_tag_is_replaced_as_a_whole_reference(self):
        cli = {'image': 'ghcr.io/blue-build/cli', 'version': 'v0.9.37', 'digest': 'sha256:' + 'a' * 64}
        for suffix in ('', '-installer'):
            source = 'COPY --from=ghcr.io/blue-build/cli:v0.9.37' + suffix + ' \\\n  /out/bluebuild /bins/bluebuild\n'
            result = benchmark.pin_cli_reference(source, cli)
            self.assertIn(cli['image'] + '@' + cli['digest'] + ' ', result)
            self.assertNotIn(cli['digest'] + '-installer', result)
        with self.assertRaises(ValueError):
            benchmark.pin_cli_reference('COPY --from=ghcr.io/blue-build/cli:v0.9.37-other /out /bins', cli)

    def test_wrong_image_binding_stops_before_runtime_execution(self):
        with patch.object(benchmark.subprocess, 'check_output', return_value='[{"Config":{"Labels":{}}}]'), \
             patch.object(benchmark, 'measure') as runtime:
            with self.assertRaises(ValueError):
                benchmark.verify(Path('/unused'), 'sha256:' + 'a' * 64,
                    {'profile': 'finite', 'sourceRevision': 'b' * 40, 'baseDigest': 'sha256:' + 'c' * 64,
                     'referenceIdentity': 'v1:reference'})
            runtime.assert_not_called()

    def test_internal_branch_authorization_is_exact(self):
        payload = {'number': 999, 'action': 'opened', 'repository': {'full_name': 'closure-labs/finite'},
            'pull_request': {'number': 999, 'head': {'sha': 'a' * 40, 'ref': 'codex/matched-builder-benchmark',
                'repo': {'full_name': 'closure-labs/finite', 'fork': False}},
                'base': {'ref': 'main', 'repo': {'full_name': 'closure-labs/finite'}}}}
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / 'event.json'; event.write_text(json.dumps(payload))
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'closure-labs/finite',
                   'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_EVENT_PATH': str(event),
                   'GITHUB_REF': 'refs/pull/999/merge'}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(benchmark.containerfile.authorized_revision(), 'a' * 40)
                for key, value in [('ref', 'other-branch'), ('repo', {'full_name': 'other/finite', 'fork': True})]:
                    original = payload['pull_request']['head'][key]
                    payload['pull_request']['head'][key] = value; event.write_text(json.dumps(payload))
                    with self.assertRaises(ValueError): benchmark.containerfile.authorized_revision()
                    payload['pull_request']['head'][key] = original

    def test_plan_contract_matches_current_recipes_and_foundation(self):
        recipes, _, _ = benchmark.containerfile.contract(ROOT)
        self.assertEqual(set(recipes), {'recipes/finite.yml', 'recipes/finite-dev.yml',
            'recipes/shared/base.yml', 'recipes/shared/final.yml'})
        self.assertEqual(benchmark.containerfile.foundation_source(ROOT)['rev'],
                         '7a58c945d464c32ae1a86d07a75cce495076a752')

    def test_bounded_work_and_identical_runtime_gate(self):
        workflow = (ROOT / '.github/workflows/builder-benchmark.yml').read_text()
        source = (ROOT / 'experiments/builder-benchmark/run.py').read_text()
        self.assertIn('timeout-minutes: 135', workflow)
        self.assertIn('repetition: [1, 2]', workflow)
        self.assertIn('max-parallel: 2', workflow)
        self.assertIn("for temperature in ('cold', 'warm')", source)
        self.assertIn("if temperature == 'cold'", source)
        self.assertIn("scripts/bluebuild/local-vm.sh", source)
        self.assertIn("'--network=none'", source)
        self.assertNotIn('secrets.', workflow)
        self.assertNotIn('packages: write', workflow)


if __name__ == '__main__':
    unittest.main()
