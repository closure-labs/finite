#!/usr/bin/env python3
"""Reject retired variants before build or credential-bearing operations."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('active_image_identity', ROOT / 'scripts/ci/image_identity.py')
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class ActiveVariants(unittest.TestCase):
    def test_only_bluefin_and_dx_recipes_and_workflow_inputs_remain(self):
        self.assertEqual({p.stem for p in (ROOT / 'recipes').glob('*.yml')},
                         {'finite', 'finite-dev'})
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            with self.subTest(workflow=path.name):
                for retired in ('bluefin-next', 'bluefin-dx-next', 'finite-next', 'finite-dev-next'):
                    self.assertNotIn(retired, path.read_text())
        self.assertFalse((ROOT / '.github/workflows/update-kernel.yml').exists())
        self.assertNotIn('image-payload-next', (ROOT / 'modules/outputs.nix').read_text())

    def test_retired_build_and_identity_requests_fail_before_external_tools(self):
        for profile in ('bluefin-next', 'bluefin-dx-next'):
            with self.subTest(profile=profile):
                for script in ('build.sh', 'stage.sh'):
                    result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild' / script), profile],
                                            capture_output=True, text=True, timeout=5)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Unknown image profile', result.stderr)
                with patch.object(identity.subprocess, 'check_output') as external:
                    with self.assertRaises(ValueError):
                        identity.identity(profile, ROOT)
                    external.assert_not_called()
        for channel in ('finite-next', 'finite-dev-next'):
            result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/iso.sh'), channel, 'sha256:' + 'a' * 64],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unsupported update channel', result.stderr)


if __name__ == '__main__':
    unittest.main()
