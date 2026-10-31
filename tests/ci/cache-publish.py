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
    def setUp(self):
        checkout = patch.object(cache.subprocess, 'check_output', return_value=ENV['CACHE_SOURCE_REVISION'] + '\n')
        self.git = checkout.start()
        self.addCleanup(checkout.stop)

    def test_only_trusted_successor_can_publish(self):
        cache.boundary(ENV)
        self.git.assert_called_once_with(['git', 'rev-parse', '--verify', 'HEAD'],
                                         cwd=cache.ROOT, env=cache.preparation_env(), text=True, timeout=30)
        for key, value in [('GITHUB_REF', 'refs/pull/1/merge'), ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_REPOSITORY', 'fork/finite'), ('CACHE_SOURCE_REVISION', 'main')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                cache.boundary(dict(ENV, **{key: value}))

    def test_invalid_workflow_boundary_does_not_read_git(self):
        with self.assertRaises(ValueError):
            cache.boundary(dict(ENV, GITHUB_EVENT_NAME='pull_request'))
        self.git.assert_not_called()

    def test_mismatched_or_malformed_checkout_stops_prepare_before_realization(self):
        for head in ('c' * 40, 'main', 'a' * 40 + '\n' + 'b' * 40):
            self.git.return_value = head
            with self.subTest(head=head), patch.dict(os.environ, ENV, clear=True), \
                    patch.object(cache, 'output') as realize, \
                    self.assertRaisesRegex(ValueError, 'checkout differs'):
                cache.prepare(Path('/tmp/unused-cache-manifest'))
            realize.assert_not_called()

    def test_mismatched_checkout_stops_push_before_reading_manifest_or_uploading(self):
        self.git.return_value = 'c' * 40
        with patch.dict(os.environ, dict(ENV, FINITE_CACHIX_TOKEN='fixture-token'), clear=True), \
                patch.object(Path, 'read_text') as read, \
                patch.object(cache, 'closure_size') as measure, \
                patch.object(cache.subprocess, 'run') as upload, \
                self.assertRaisesRegex(ValueError, 'checkout differs'):
            cache.push(Path('/tmp/nonexistent-cache-manifest'))
        read.assert_not_called()
        measure.assert_not_called()
        upload.assert_not_called()

    def test_realization_uses_the_same_verified_checkout(self):
        self.git.return_value = STORE + '\n'
        command = ['nix', 'build', '--no-link', '.#ci-checks']
        self.assertEqual(cache.output(command), STORE)
        self.git.assert_called_once_with(command, cwd=cache.ROOT, env=cache.preparation_env(), text=True, timeout=3600)

    def test_realization_refuses_a_writer_credential(self):
        with patch.dict(os.environ, dict(ENV, FINITE_CACHIX_TOKEN='secret'), clear=True), self.assertRaises(ValueError):
            cache.prepare(Path('/tmp/unused-cache-manifest'))

    def test_push_rechecks_exact_proof_identity_source_and_union_before_upload(self):
        identities = {'check': {'drvPath': STORE + '.drv', 'outputPath': STORE}}
        roots = [{'kind': 'check-result', 'name': name, **identity} for name, identity in identities.items()]
        closure = {'bytes': 112, 'pathCount': 1, 'paths': {STORE: {'narHash': 'sha256-' + 'a' * 43 + '=', 'narSize': 112, 'references': []}}}
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'roots.json'
            record = {'schema': 2, 'revision': 'a' * 40, 'cache': 'finite-os', 'roots': roots, 'closure': closure}
            manifest.write_text(json.dumps(record))
            with patch.dict(os.environ, dict(ENV, FINITE_CACHIX_TOKEN='fixture'), clear=True), \
                    patch.object(cache.native, 'proof_identities', return_value=identities), \
                    patch.object(cache.native, 'proof_closure', return_value=closure), patch.object(cache.native, 'publish') as upload:
                cache.push(manifest)
                upload.assert_called_once_with([STORE], provider='env')
                import copy
                for field, value in [('schema', 1), ('revision', 'c' * 40), ('cache', 'other'),
                                     ('roots', [{'kind': 'tool', 'name': 'scanner-tools', 'path': STORE, 'bytes': 10}]),
                                     ('roots', [{**roots[0], 'outputPath': STORE + '-unknown'}]),
                                     ('roots', [{**roots[0], 'drvPath': STORE + '-wrong.drv'}]),
                                     ('roots', roots + roots), ('closure', {**closure, 'pathCount': True}),
                                     ('closure', {**closure, 'bytes': 111})]:
                    bad = copy.deepcopy(record);bad[field] = value;manifest.write_text(json.dumps(bad))
                    with self.subTest(field=field), self.assertRaises(ValueError):cache.push(manifest)
                self.assertEqual(upload.call_count, 1)

    def test_default_realization_selects_only_exact_current_proofs(self):
        identities = {'check': {'drvPath': STORE + '.drv', 'outputPath': STORE}}
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary) / 'check';proof.symlink_to(STORE)
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(cache.native, 'proof_identities', return_value=identities), \
                    patch.object(cache.native, 'proof_closure', return_value={'bytes': 112}) as budget, \
                    patch.object(cache, 'output', return_value=temporary) as build, \
                    patch.object(Path, 'resolve', return_value=Path(STORE)), patch.object(cache, 'batched_tools') as tools:
                roots, closure = cache.realize_roots()
                self.assertEqual(roots, [{'kind': 'check-result', 'name': 'check', **identities['check']}])
                self.assertEqual(closure['bytes'], 112)
                self.assertEqual(build.call_args.args[0][-1], '.#ci-checks')
                tools.assert_not_called()
                (Path(temporary) / 'unknown').symlink_to(STORE)
                with self.assertRaisesRegex(ValueError, 'unknown or missing'):cache.realize_roots()
                self.assertEqual(budget.call_count, 1)

    def test_workflow_keeps_writer_boundary_and_no_ambient_upload_hook(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/cache-maintenance.yml').read_text())
        job = workflow['jobs']['publish']
        for condition in ("vars.FINITE_CACHIX_WRITER == 'true'", "github.event.workflow_run.conclusion == 'success'",
                          "github.event.workflow_run.head_repository.full_name == 'closure-labs/finite'",
                          "github.event.workflow_run.head_branch == 'main'"):
            self.assertIn(condition, job['if'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        setup = (ROOT / '.github/actions/setup-nix/action.yml').read_text()
        root = (ROOT / 'devenv.nix').read_text()
        self.assertNotIn('cachix.push', root)
        self.assertNotIn('post-build-hook', setup + root)
        self.assertNotIn('watch-store', setup + root)


def fixture_identities():
    return {name: {'drvPath': '/nix/store/' + str(index) * 32 + '-tool.drv',
                   'outputPath': '/nix/store/' + str(index) * 32 + '-tool'}
            for index, name in enumerate(cache.TOOLS, 1)}


class Batching(unittest.TestCase):
    def test_per_attribute_association_does_not_assume_build_order(self):
        identities = fixture_identities()
        records = [{'drvPath': value['drvPath'], 'outputs': {'out': value['outputPath']}}
                   for value in reversed(list(identities.values()))]
        with patch.object(cache, 'tool_identities', return_value=identities), \
                patch.object(cache, 'json_output', return_value=records) as command:
            roots = cache.batched_tools()
        self.assertEqual({root['name']: root['path'] for root in roots},
                         {name: value['outputPath'] for name, value in identities.items()})
        self.assertEqual(command.call_args.args[0],
                         ['nix', 'build', '--file', 'lib/ci-tools.nix', *cache.TOOLS, '--no-link', '--json'])

    def test_wrong_missing_extra_duplicate_and_multi_output_results_fail(self):
        identities = fixture_identities()
        valid = [{'drvPath': value['drvPath'], 'outputs': {'out': value['outputPath']}}
                 for value in identities.values()]
        import copy
        variants = [valid[:-1], valid + valid[:1], valid[:3] + valid[:1], {},
                    [{**valid[0], 'drvPath': STORE + '.drv'}, *valid[1:]],
                    [{**valid[0], 'outputs': {'out': STORE}}, *valid[1:]],
                    [{**valid[0], 'outputs': {**valid[0]['outputs'], 'dev': STORE}}, *valid[1:]],
                    [{**valid[0], 'outputs': {'out': None}}, *valid[1:]]]
        for records in copy.deepcopy(variants):
            with self.subTest(records=records), patch.object(cache, 'tool_identities', return_value=identities), \
                    patch.object(cache, 'json_output', return_value=records), self.assertRaises(ValueError):
                cache.batched_tools()

    def test_metadata_requires_exact_distinct_declared_tool_identities(self):
        import copy
        valid = fixture_identities()
        with patch.object(cache, 'json_output', return_value=valid):
            self.assertEqual(cache.tool_identities(), valid)
        variants = [{}, {**valid, 'unapproved': valid[cache.TOOLS[0]]}]
        for field, bad in [('drvPath', STORE), ('outputPath', STORE + '.drv'), ('outputPath', '/tmp/tool')]:
            value = copy.deepcopy(valid)
            value[cache.TOOLS[0]][field] = bad
            variants.append(value)
        value = copy.deepcopy(valid)
        value[cache.TOOLS[1]] = value[cache.TOOLS[0]]
        variants.append(value)
        for value in variants:
            with self.subTest(value=value), patch.object(cache, 'json_output', return_value=value), self.assertRaises(ValueError):
                cache.tool_identities()

    def test_nix_serializer_collapsed_string_cannot_lose_derivation_binding(self):
        # Nix 2.35.2 printValueAsJSON returns attrs.outPath rather than an
        # object whenever an attrset contains that key. This is the shape
        # produced by the former { drvPath = ...; outPath = ...; } expression.
        collapsed = {name: value['outputPath'] for name, value in fixture_identities().items()}
        with patch.object(cache, 'json_output', return_value=collapsed), \
                patch.object(cache.subprocess, 'run') as realize, self.assertRaises(cache.ToolIdentityError) as error:
            cache.tool_identities()
        realize.assert_not_called()
        facts = error.exception.diagnostics['tools'][cache.TOOLS[0]]
        self.assertEqual(facts['recordType'], 'str')
        self.assertTrue(facts['stringIsStorePath'])
        self.assertEqual(facts['problems'], ['record-not-object'])
        self.assertNotIn(collapsed[cache.TOOLS[0]], str(error.exception))

    def test_evaluation_uses_noncoercing_metadata_field(self):
        with patch.object(cache, 'json_output', return_value=fixture_identities()) as evaluate:
            cache.tool_identities()
        expression = evaluate.call_args.args[0][-1]
        self.assertIn('outputPath = tools.${name}.outPath;', expression)
        self.assertNotIn(' outPath = ', expression)

    def test_identity_errors_report_bounded_facts_without_unknown_values_or_keys(self):
        valid = fixture_identities()
        valid[cache.TOOLS[0]] = {'drvPath': 'SECRET-VALUE' * 10000, 'SECRET-KEY': 'SECRET-VALUE'}
        with patch.object(cache, 'json_output', return_value=valid), self.assertRaises(cache.ToolIdentityError) as error:
            cache.tool_identities()
        message = str(error.exception)
        self.assertLess(len(message), 4096)
        self.assertNotIn('SECRET-VALUE', message)
        self.assertNotIn('SECRET-KEY', message)
        facts = error.exception.diagnostics['tools'][cache.TOOLS[0]]
        self.assertEqual(facts['missingFieldCount'], 1)
        self.assertEqual(facts['unexpectedFieldCount'], 1)
        self.assertFalse(facts['drvPath']['validStorePath'])

    def test_default_realizes_only_tools_with_one_closure_query(self):
        roots = [{'kind': 'tool', 'name': name, 'path': identity['outputPath']}
                 for name, identity in fixture_identities().items()]
        with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'output') as proofs, \
                patch.object(cache, 'batched_tools', return_value=roots), \
                patch.object(cache, 'closure_sizes', return_value={root['path']: 10 for root in roots}) as sizes:
            result = cache.diagnostic_roots()
        proofs.assert_not_called()
        sizes.assert_called_once_with([root['path'] for root in roots])
        self.assertEqual(len(result), len(cache.TOOLS))
        self.assertTrue(all(root['kind'] == 'tool' and root['bytes'] == 10 for root in result))

    def test_explicit_proofs_share_batched_size_query_and_remain_bounded(self):
        roots = [{'kind': 'tool', 'name': name, 'path': identity['outputPath']}
                 for name, identity in fixture_identities().items()]
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary) / 'check'
            proof.symlink_to(STORE)
            original_resolve = Path.resolve
            def resolve(path, **kwargs):
                return Path(STORE) if path == proof else original_resolve(path, **kwargs)
            measurements = {root['path']: 10 for root in roots}
            measurements[STORE] = cache.MIB
            with patch.dict(os.environ, {}, clear=True), patch.object(cache, 'output', return_value=temporary) as realize, \
                    patch.object(Path, 'resolve', resolve), patch.object(cache, 'batched_tools', return_value=roots), \
                    patch.object(cache, 'closure_sizes', return_value=measurements):
                result = cache.diagnostic_roots(include_proofs=True)
                self.assertEqual(result[0], {'kind': 'proof', 'name': 'check', 'path': STORE, 'bytes': cache.MIB})
                self.assertEqual(realize.call_args.args[0][-1], '.#ci-checks')
                measurements[STORE] += 1
                with self.assertRaises(ValueError):
                    cache.diagnostic_roots(include_proofs=True)

    def test_batched_sizes_reject_extra_missing_boolean_and_negative_records(self):
        for records in ({}, {STORE: {'closureSize': 1}, STORE + '-extra': {'closureSize': 1}},
                        {STORE: {'closureSize': True}}, {STORE: {'closureSize': -1}}):
            with self.subTest(records=records), patch.object(cache, 'json_output', return_value=records), self.assertRaises(ValueError):
                cache.closure_sizes([STORE])

    def test_root_limits_and_duplicate_names_are_enforced(self):
        valid = {'kind': 'tool', 'name': cache.TOOLS[0], 'path': STORE, 'bytes': 2 * 1024 ** 3}
        cache.validate_diagnostic_roots([valid])
        for roots in ([{**valid, 'bytes': valid['bytes'] + 1}], [valid, valid],
                      [{**valid, 'name': 'unapproved'}], [{**valid, 'bytes': True}],
                      [{**valid, 'path': STORE + '.drv'}]):
            with self.subTest(roots=roots), self.assertRaises(ValueError):
                cache.validate_diagnostic_roots(roots)

    def test_metadata_subprocesses_do_not_receive_credentials(self):
        with patch.dict(os.environ, {'CACHIX_AUTH_TOKEN': 'secret', 'COSIGN_PRIVATE_KEY': 'secret', 'SAFE': 'yes'}, clear=True), \
                patch.object(cache.subprocess, 'check_output', return_value=json.dumps({STORE: {'closureSize': 10}})) as run:
            self.assertEqual(cache.closure_sizes([STORE]), {STORE: 10})
            self.assertEqual(run.call_args.kwargs['env'], {'SAFE': 'yes'})

    def test_duplicate_json_fields_fail_closed(self):
        with patch.object(cache.subprocess, 'check_output', return_value='{"out": 1, "out": 2}'), self.assertRaises(ValueError):
            cache.json_output(['fixture'])

    def test_any_preparation_credential_stops_before_commands(self):
        for key in cache.CREDENTIALS:
            with self.subTest(key=key), patch.dict(os.environ, {key: 'secret'}, clear=True), \
                    patch.object(cache, 'batched_tools') as realize, self.assertRaises(ValueError):
                cache.diagnostic_roots()
            realize.assert_not_called()


if __name__ == '__main__':
    unittest.main()
