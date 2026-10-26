#!/usr/bin/env python3
"""Reject mistaken release labels before preparing or signing assets."""
import importlib.util
import os
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
    def test_release_names_include_channel_once(self):
        self.assertEqual(request.canonical_tag('finite', '0.8.1'), 'finite-0.8.1')
        self.assertEqual(request.canonical_tag('finite-dev', '0.8.1'), 'finite-dev-0.8.1')
        with self.assertRaises(ValueError):
            request.validate('finite', 'finite-finite-0.8.1', '0.8.1', '123')

    def test_notes_select_only_current_entry_and_pin_document_links(self):
        changelog = ('## [Unreleased]\n\n- Future work.\n\n## [0.8.1] - 2026-10-15\n\n'
                     '### Changed\n\n- See [migration](docs/v0.8.1-release-plan.md).\n\n'
                     '## [0.8.0] - 2026-10-14\n\n- Historical entry.\n')
        with patch.dict(os.environ, {'RELEASE_SOURCE_SHA': 'a' * 40}):
            notes = request.release_notes('0.8.1', changelog)
            self.assertIn('blob/' + 'a' * 40 + '/docs/v0.8.1-release-plan.md', notes)
            self.assertNotIn('Future work', notes)
            self.assertNotIn('Historical entry', notes)
            for malformed in ('## [Unreleased]\n', '## [0.8.1]\n\n', changelog + '\n## [0.8.1]\n- Duplicate\n'):
                with self.subTest(changelog=malformed), self.assertRaises(ValueError):
                    request.release_notes('0.8.1', malformed)
        with patch.dict(os.environ, {'RELEASE_SOURCE_SHA': 'not-a-revision'}), self.assertRaises(ValueError):
            request.release_notes('0.8.1', changelog)

    def test_tag_lookup_rejects_existing_tag_and_failed_lookup(self):
        tag = 'finite-0.8.1'
        for refs in ('[]', '[{"ref":"refs/tags/finite-0.8.1-rc"}]'):
            with patch.object(request.subprocess, 'check_output', return_value=refs):
                request.require_new_tag(tag)
        for refs in ('{}', '[null]', '[{"ref":"refs/tags/finite-0.8.1"}]'):
            with patch.object(request.subprocess, 'check_output', return_value=refs), self.assertRaises(ValueError):
                request.require_new_tag(tag)
        with patch.object(request.subprocess, 'check_output', side_effect=request.subprocess.CalledProcessError(1, 'gh')):
            with self.assertRaises(request.subprocess.CalledProcessError):
                request.require_new_tag(tag)

    def test_all_channels_and_optional_iso(self):
        for channel in request.CHANNELS:
            for iso in ('', '38639819537'):
                tag = f'{channel}-0.8.1'
                self.assertEqual(request.validate(channel, tag, '0.8.1', '38639819537', iso), tag)

    def test_mismatched_or_unsafe_requests(self):
        valid = ['finite-dev', 'finite-dev-0.8.1', '0.8.1', '38639819537', '']
        for index, value in ((0, 'finite-next'), (0, 'finite-dev-next'), (0, 'latest'), (0, ''), (1, 'v0.8.1'),
                             (1, 'finite-0.8.1'), (1, 'finite-dev-0.7.0'),
                             (1, 'finite-finite-dev-0.8.1'), (1, 'finite-dev-next-0.8.1'), (1, '--latest'), (2, '00.8.1'), (2, '0.8.1\n'),
                             (2, '0.8.1-dev'), (3, ''), (3, '0'), (3, '123\n'),
                             (3, '../123'), (3, '1' * 21), (4, '0'), (4, '--help')):
            args = valid.copy()
            args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                request.validate(*args)

    def test_workflow_validates_before_cost_or_signing(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        self.assertEqual(workflow['concurrency']['group'], 'finite-official-release')
        for name in ('release-recovery', 'publish-release-set'):
            sibling = yaml.safe_load((ROOT / '.github/workflows' / (name + '.yml')).read_text())
            self.assertEqual(sibling['concurrency']['group'], workflow['concurrency']['group'])
        for name in ('release', 'sign-release'):
            steps = workflow['jobs'][name]['steps']
            validate = next(i for i, step in enumerate(steps) if step.get('name') == 'Validate release request')
            setup = next(i for i, step in enumerate(steps) if step.get('uses') == '$/.github/actions/setup-nix')
            self.assertLess(validate, setup)
            self.assertNotIn('secrets.', str(steps[validate]))
        signer = workflow['jobs']['sign-release']
        self.assertEqual(signer['environment'], 'release')
        checkout = next(step for step in signer['steps'] if step.get('uses', '').startswith('actions/checkout@'))['with']['sparse-checkout']
        self.assertIn('VERSION', checkout)
        self.assertIn('CHANGELOG.md', checkout)
        self.assertIn('scripts/ci/release-request.py', checkout)
        create = next(step for step in signer['steps'] if step.get('name') == 'Create draft release with durable evidence')
        self.assertEqual(create['run'], 'finite-ci-secrets-run release-publishing -- bash scripts/ci/create-release-draft.sh')
        self.assertEqual(create['env']['RELEASE_SOURCE_SHA'], '${{ github.sha }}')
        self.assertIn('scripts/ci/create-release-draft.sh', checkout)
        publisher = (ROOT / 'scripts/ci/create-release-draft.sh').read_text()
        self.assertIn('git/refs', publisher)
        self.assertIn('refs/tags/$RELEASE_TAG', publisher)
        self.assertIn('--verify-tag', publisher)


if __name__ == '__main__':
    unittest.main()
