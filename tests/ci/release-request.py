#!/usr/bin/env python3
"""Reject mistaken release labels before preparing or signing assets."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_request', ROOT / 'scripts/ci/release-request.py')
request = importlib.util.module_from_spec(spec)
spec.loader.exec_module(request)


class RequestTests(unittest.TestCase):
    def test_tag_lookup_rejects_existing_tag_and_failed_lookup(self):
        tag = 'finite-finite-0.8.0'
        for refs in ('[]', '[{"ref":"refs/tags/finite-finite-0.8.0-rc"}]'):
            with patch.object(request.subprocess, 'check_output', return_value=refs):
                request.require_new_tag(tag)
        for refs in ('{}', '[null]', '[{"ref":"refs/tags/finite-finite-0.8.0"}]'):
            with patch.object(request.subprocess, 'check_output', return_value=refs), self.assertRaises(ValueError):
                request.require_new_tag(tag)
        with patch.object(request.subprocess, 'check_output', side_effect=request.subprocess.CalledProcessError(1, 'gh')):
            with self.assertRaises(request.subprocess.CalledProcessError):
                request.require_new_tag(tag)

    def test_all_channels_and_optional_iso(self):
        for channel in request.CHANNELS:
            for iso in ('', '38639819537'):
                tag = f'finite-{channel}-0.8.0'
                self.assertEqual(request.validate(channel, tag, '0.8.0', '38639819537', iso), tag)

    def test_mismatched_or_unsafe_requests(self):
        valid = ['finite-next', 'finite-finite-next-0.8.0', '0.8.0', '38639819537', '']
        for index, value in ((0, 'latest'), (0, ''), (1, 'v0.8.0'),
                             (1, 'finite-finite-0.8.0'), (1, 'finite-finite-next-0.7.0'),
                             (1, '--latest'), (2, '00.8.0'), (2, '0.8.0\n'),
                             (2, '0.8.0-dev'), (3, ''), (3, '0'), (3, '123\n'),
                             (3, '../123'), (3, '1' * 21), (4, '0'), (4, '--help')):
            args = valid.copy()
            args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                request.validate(*args)

    def test_workflow_validates_before_cost_or_signing(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        self.assertEqual(workflow['concurrency']['group'], 'finite-release-${{ inputs.channel }}')
        for name in ('release', 'sign-release'):
            steps = workflow['jobs'][name]['steps']
            validate = next(i for i, step in enumerate(steps) if step.get('name') == 'Validate release request')
            setup = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/setup-nix')
            self.assertLess(validate, setup)
            self.assertNotIn('secrets.', str(steps[validate]))
        signer = workflow['jobs']['sign-release']
        self.assertEqual(signer['environment'], 'release')
        checkout = signer['steps'][0]['with']['sparse-checkout']
        self.assertIn('VERSION', checkout)
        self.assertIn('scripts/ci/release-request.py', checkout)
        create = next(step for step in signer['steps'] if step.get('name') == 'Create draft release with durable evidence')['run']
        self.assertIn('git/refs', create)
        self.assertIn('refs/tags/$RELEASE_TAG', create)
        self.assertIn('--verify-tag', create)


if __name__ == '__main__':
    unittest.main()
