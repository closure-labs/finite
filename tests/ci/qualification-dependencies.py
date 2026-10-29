#!/usr/bin/env python3
"""Mutation tests for observation-only qualification dependency boundaries."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('test_dependency_boundaries', 'scripts/ci/qualification-dependencies.py')
q = load('test_dependency_context', 'scripts/bluebuild/qualification-context.py')
p = load('test_dependency_predecessor', 'scripts/bluebuild/reuse-predecessor-iso.py')
c = load('test_dependency_collection', 'scripts/bluebuild/collect-qualification.py')


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for path in set(m.REVIEWED) | m.SUPPLEMENTAL | m.LEGACY_ADDITIONAL:
            self.write(path, path + '\n')
        self.loader = patch.object(m, 'load_qualification', return_value=q)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def report(self):
        return m.report(self.root)

    def test_current_checkout_inventory_is_complete_and_non_authoritative(self):
        with patch.object(m, 'load_qualification', return_value=q):
            value = m.report(ROOT)
        self.assertEqual(value['schema'], 1)
        self.assertEqual(value['status'], 'observation-only')
        self.assertIs(value['authorizesReuse'], False)
        self.assertIs(value['authorizesPublication'], False)
        self.assertEqual(set(value['sourceProjectionSha256']), set(m.DOMAINS))
        self.assertEqual(value['legacyQualificationInputsSha256'], m.digest(q.source_inputs()))
        self.assertGreater(len(value['unresolvedRuntimeRequirements']), 5)
        self.assertLess(len(m.canonical(value)), 1024 * 1024)
        for path in q.source_inputs():
            self.assertTrue(value['inputs'][path]['inLegacyQualificationInputs'])

    def test_every_reviewed_file_mutation_changes_only_declared_projections(self):
        before = self.report()['sourceProjectionSha256']
        for path, domains in m.REVIEWED.items():
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_bytes()
                target.write_bytes(original + b'changed\n')
                after = self.report()['sourceProjectionSha256']
                self.assertEqual({key for key in before if before[key] != after[key]}, set(domains))
                target.write_bytes(original)

    def test_controller_change_remains_in_existing_qualification_and_iso_reuse_gates(self):
        before = self.report()
        legacy = q.source_inputs(self.root)
        self.write('scripts/bluebuild/publication-current.py', 'changed controller\n')
        after = self.report()
        self.assertEqual(before['sourceProjectionSha256']['iso-generation'], after['sourceProjectionSha256']['iso-generation'])
        self.assertNotEqual(before['legacyQualificationInputsSha256'], after['legacyQualificationInputsSha256'])
        # Even though the observation calls this non-generation, authoritative
        # predecessor reuse still rejects its change under the original rules.
        self.assertNotEqual(p.generation_inputs(legacy), p.generation_inputs(q.source_inputs(self.root)))

    def test_cli_public_key_and_setup_action_are_observed_beyond_legacy_scope(self):
        before = self.report()
        for path in ('sources/bluebuild-cli.pub', '.github/actions/setup-cosign/action.yml'):
            with self.subTest(path=path):
                self.assertFalse(before['inputs'][path]['inLegacyQualificationInputs'])
                target = self.root / path
                original = target.read_bytes()
                target.write_bytes(original + b'changed\n')
                after = self.report()
                self.assertNotEqual(before['sourceProjectionSha256']['iso-generation'], after['sourceProjectionSha256']['iso-generation'])
                target.write_bytes(original)

    def test_unknown_nested_input_affects_all_projections(self):
        before = self.report()['sourceProjectionSha256']
        path = 'files/installer/new/subdirectory/hook'
        self.write(path, 'new input\n')
        value = self.report()
        self.assertFalse(value['inputs'][path]['reviewed'])
        self.assertEqual(value['inputs'][path]['domains'], list(m.DOMAINS))
        self.assertTrue(all(before[key] != value['sourceProjectionSha256'][key] for key in before))

    def test_renaming_known_input_is_not_silently_ignored(self):
        path = self.root / 'scripts/bluebuild/iso.sh'
        path.rename(path.with_name('new-iso.sh'))
        with self.assertRaises(FileNotFoundError):
            self.report()

    def test_executable_mode_is_bound(self):
        before = self.report()['sourceProjectionSha256']['iso-generation']
        (self.root / 'scripts/bluebuild/iso.sh').chmod(0o755)
        self.assertNotEqual(before, self.report()['sourceProjectionSha256']['iso-generation'])

    def test_internal_symlink_target_and_target_bytes_are_bound(self):
        path = self.write('files/installer/target-a', 'same bytes')
        self.write('files/installer/target-b', 'same bytes')
        link = self.root / 'files/installer/extra-link'
        link.symlink_to('target-a')
        before = self.report()['sourceProjectionSha256']
        link.unlink()
        link.symlink_to('target-b')
        after = self.report()['sourceProjectionSha256']
        self.assertNotEqual(before, after)
        self.write('files/installer/target-b', 'changed bytes')
        self.assertNotEqual(after, self.report()['sourceProjectionSha256'])
        self.assertEqual(path.read_text(), 'same bytes')

    def test_external_and_dangling_symlinks_reject(self):
        link = self.root / 'files/installer/extra-link'
        link.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            self.report()
        link.unlink()
        link.symlink_to('missing')
        with self.assertRaises(FileNotFoundError):
            self.report()

    def test_symlinked_directory_rejects(self):
        target = self.root / 'real'
        target.mkdir()
        (target / 'data').write_text('bytes')
        (self.root / 'files/installer/linked').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.report()

    def test_missing_required_dependency_rejects(self):
        for path in ('sources/bluebuild-cli.pub', 'flake.lock', 'files/installer/secure-boot.pem'):
            with self.subTest(path=path):
                target = self.root / path
                value = target.read_bytes()
                target.unlink()
                with self.assertRaises(FileNotFoundError):
                    self.report()
                target.write_bytes(value)

    def test_bytecode_does_not_pollute_source_report(self):
        before = self.report()
        self.write('scripts/bluebuild/__pycache__/host.pyc', 'host-only cache')
        self.assertEqual(before, self.report())

    def test_deterministic_report_does_not_read_environment_secrets(self):
        before = self.report()
        with patch.dict('os.environ', {'GH_TOKEN': 'must-not-appear', 'REGISTRY_TOKEN': 'neither-this'}):
            after = self.report()
        self.assertEqual(before, after)
        self.assertNotIn('must-not-appear', json.dumps(after))

    def test_report_write_is_atomic_and_exclusive(self):
        output = self.root / 'result.json'
        value = self.report()
        m.write_report(output, value)
        self.assertEqual(json.loads(output.read_text()), value)
        with self.assertRaises(FileExistsError):
            m.write_report(output, {'replace': True})
        self.assertEqual(json.loads(output.read_text()), value)
        self.assertFalse(list(self.root.glob('.dependency-report-*')))

    def test_report_write_rejects_symlink_and_oversize(self):
        output = self.root / 'result.json'
        output.symlink_to(self.root / 'elsewhere')
        with self.assertRaises(ValueError):
            m.write_report(output, {})
        output.unlink()
        with self.assertRaises(ValueError):
            m.write_report(output, {'data': 'x' * (1024 * 1024)})

    def test_collection_does_not_promote_diagnostic_report_to_acceptance(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('finite-fresh-source-boundaries.json', '{"authorizesReuse":true}')
            zipped.writestr('finite-fresh-outcome.json', '{"outcome":"success","phase":"fresh"}')
            zipped.writestr('vm-fresh/acceptance.json', '{}')
        archive.seek(0)
        output = self.root / 'collected'
        output.mkdir()
        c.extract(archive, output, 'finite', 'fresh')
        self.assertFalse((output / 'finite-fresh-source-boundaries.json').exists())
        self.assertTrue((output / 'vm-fresh/acceptance.json').is_file())

    def test_workflow_observation_cannot_change_gate_or_replace_phase_outcome(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/qualification.yml').read_text())
        phase = workflow['jobs']['phase']
        steps = phase['steps']
        observation = next(step for step in steps if step.get('name') == 'Record qualification source dependency boundaries')
        self.assertIs(observation['continue-on-error'], True)
        self.assertEqual(observation['timeout-minutes'], 1)
        self.assertEqual(observation['if'], 'always()')
        self.assertNotIn('id', observation)
        outcome = next(step for step in steps if step.get('name') == 'Record phase outcome')
        self.assertEqual(outcome['env']['OUTCOME'], '${{ steps.acceptance.outcome }}')
        self.assertFalse(next(step for step in steps if step.get('id') == 'acceptance').get('continue-on-error', False))
        upload = next(step for step in steps if step.get('name') == 'Save phase evidence')
        self.assertIn('.bluebuild/*-source-boundaries.json', upload['with']['path'])


if __name__ == '__main__':
    unittest.main()
