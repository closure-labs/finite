#!/usr/bin/env python3
"""Exercise the real Nix CLI application without loading any flake graph."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('trial_command', ROOT / 'scripts/ci/benchmark-home-evaluation.py')
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class Command(unittest.TestCase):
    def test_both_strategies_call_the_expression_and_return_json(self):
        nix = shutil.which('nix')
        self.assertIsNotNone(nix, 'The home contract check supplies Nix')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'function.nix'
            fixture.write_text('{ strategy ? "not-called", preflight ? false, flake ? throw "No real graph may be read" }: { result = if preflight then "preflight" else strategy; }')
            env = {**os.environ, 'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '1'}
            for mode in trial.MODES + ('preflight',):
                with self.subTest(mode=mode):
                    _, args = trial.command(mode, 1, root / 'metrics.json', env)
                    # Exercise the exact evaluator arguments; the service and
                    # cgroup launcher are independently covered by fixtures.
                    args = args[args.index(nix):]
                    args[args.index('--file') + 1] = str(fixture)
                    args[1:1] = ['--store', 'dummy://', '--offline',
                                 '--extra-experimental-features', 'nix-command flakes']
                    result = subprocess.run(args, capture_output=True, text=True, check=True, timeout=15)
                    self.assertEqual(json.loads(result.stdout), {'result': mode})


if __name__ == '__main__':
    unittest.main()
