#!/usr/bin/env python3
"""Self-repository compatibility must preserve Actionlint's real checks."""
import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('workflow_lint', ROOT / 'scripts/ci/lint-workflows.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class WorkflowLint(unittest.TestCase):
    def fixture(self, root):
        action = root / '.github/actions/setup/action.yml'
        action.parent.mkdir(parents=True)
        action.write_text('name: Setup\ndescription: Fixture\nruns:\n  using: composite\n  steps:\n    - run: echo setup\n      shell: bash\n')
        workflow = root / '.github/workflows/test.yml'
        workflow.parent.mkdir(parents=True)
        workflow.write_text('name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: $/.github/actions/setup\n')
        return workflow

    def test_projection_only_changes_actual_uses_scalars(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            source = "runs:\n  steps:\n    - uses: '$/.github/actions/setup' # retained\n    - run: |\n        uses: $/not-an-action\n        echo original\n"
            changed = mod.projection(source, root)
            self.assertIn("uses: './.github/actions/setup' # retained", changed)
            self.assertIn('uses: $/not-an-action', changed)
            self.assertEqual(changed.replace("'./.github/actions/setup'", "'$/.github/actions/setup'"), source)

    def test_aliases_and_workflow_references_keep_valid_yaml(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            source = 'jobs:\n  first: &call\n    uses: $/.github/workflows/test.yml\n  second: *call\n'
            changed = mod.projection(source, root)
            self.assertEqual(mod.yaml.safe_load(changed)['jobs']['second']['uses'], './.github/workflows/test.yml')

    def test_non_action_uses_keys_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            source = 'env:\n  uses: $/not-a-target\njobs:\n  test:\n    env:\n      uses: $/also-not-a-target\n    steps:\n      - run: echo ok\n'
            self.assertEqual(mod.projection(source, root), source)

    def test_invalid_and_missing_targets_fail_before_lint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            for value in ('$/../escape', '$//absolute', '$/.github/actions/../setup',
                          '$/.github/actions/setup@main', '$/other/action',
                          '$/.github/actions/missing', '$/.github/workflows/missing.yml',
                          '$/.github/actions/setup\\evil'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    mod.projection('jobs:\n  test:\n    uses: ' + value + '\n', root)

    def test_symlinks_are_rejected_without_copying_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / '.github/link').symlink_to('/tmp')
            with self.assertRaisesRegex(ValueError, 'symbolic links'):
                mod.lint(root)

    @unittest.skipUnless(shutil.which('actionlint'), 'Actionlint is supplied by the hosted workflow check')
    def test_real_linter_accepts_projection_without_modifying_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workflow = self.fixture(root)
            before = workflow.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(mod.lint(root), 0)
            self.assertEqual(workflow.read_bytes(), before)

    @unittest.skipUnless(shutil.which('actionlint'), 'Actionlint is supplied by the hosted workflow check')
    def test_real_linter_still_rejects_invalid_expressions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); workflow = self.fixture(root)
            workflow.write_text(workflow.read_text() + '      - run: echo ${{ nonexistent.secret }}\n')
            before = workflow.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(mod.lint(root), 0)
            self.assertIn('nonexistent', output.getvalue())
            self.assertNotIn('finite-actionlint-', output.getvalue())
            self.assertEqual(workflow.read_bytes(), before)

    def test_lint_contract_keeps_zizmor_on_original_workflows(self):
        contract = (ROOT / 'lib/bluebuild-checks.nix').read_text()
        self.assertIn('python3 tests/ci/workflow-lint.py', contract)
        self.assertIn('python3 scripts/ci/lint-workflows.py', contract)
        self.assertIn('zizmor --offline --no-config --collect=all .github', contract)
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            for line in path.read_text().splitlines():
                self.assertNotRegex(line, r'^\s*(?:-\s*)?uses:\s*\./', path.name)


if __name__ == '__main__':
    unittest.main()
