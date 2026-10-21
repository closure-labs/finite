#!/usr/bin/env python3
"""A complete stable pair starts one reviewed development cycle, never a loop."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
import release_versions as versions
spec = importlib.util.spec_from_file_location('release_cycle', ROOT / 'scripts/ci/release-cycle.py')
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)
SHA = 'a' * 40


class ReleaseCycle(unittest.TestCase):
    def test_versions_are_canonical_and_next_cycle_requires_stable(self):
        self.assertEqual(versions.next_development('0.8.1'), '0.8.2-dev')
        self.assertEqual(versions.next_development('1.9.99'), '1.9.100-dev')
        self.assertEqual(versions.previous_stable('0.8.2-dev'), '0.8.1')
        self.assertIsNone(versions.previous_stable('1.2.0-dev'))
        self.assertEqual(versions.canonical_tag('finite-dev', '0.8.2-dev'), 'finite-dev-0.8.2-dev')
        for version in ('0.8.2-dev', '01.2.3', 'v1.2.3', '1.2.3\n', '1.2.3-rc.1', '1.2.3-dev+meta'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                versions.next_development(version)
        for version in ('01.2.3', '1.2.3\n', '../1.2.3', '1.2.3-dev+meta'):
            self.assertFalse(versions.release_version(version))

    def test_stages_only_version_and_changelog_after_both_stable_products(self):
        changelog = '# Changelog\n\n## [Unreleased]\n\n### Changed\n\n- Pending work.\n\n## [0.8.1] - 2026-10-15\n\n- Stable work.\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'VERSION').write_text('0.8.1\n')
            (root / 'CHANGELOG.md').write_text(changelog)
            (root / 'untouched').write_text('preserved')
            def api(endpoint):
                self.assertTrue(endpoint.endswith('/git/ref/heads/main'))
                return {'object': {'sha': SHA}}
            with patch.object(cycle, 'published_stable_pair', return_value=False):
                self.assertIsNone(cycle.stage(root, SHA, api))
                self.assertEqual((root / 'CHANGELOG.md').read_text(), changelog)
            with patch.object(cycle, 'published_stable_pair', return_value=True):
                with self.assertRaisesRegex(ValueError, 'Main advanced'):
                    cycle.stage(root, 'b' * 40, api)
                self.assertEqual((root / 'VERSION').read_text(), '0.8.1\n')
                self.assertEqual(cycle.stage(root, SHA, api), {'stable': '0.8.1', 'development': '0.8.2-dev'})
            self.assertEqual((root / 'VERSION').read_text(), '0.8.2-dev\n')
            after = (root / 'CHANGELOG.md').read_text()
            self.assertIn('Development version: `0.8.2-dev`.', after)
            self.assertIn('## [0.8.2-dev]', after)
            self.assertIn('- Pending work.', after)
            self.assertEqual(after.split('## [0.8.1]')[1], changelog.split('## [0.8.1]')[1])
            self.assertEqual((root / 'untouched').read_text(), 'preserved')
            with patch.object(cycle, 'published_stable_pair') as published:
                self.assertIsNone(cycle.stage(root, SHA, api))
                published.assert_not_called()

    def test_malformed_or_already_versioned_changelog_is_not_overwritten(self):
        for text in ('## [Unreleased]\n', '## [0.8.1]\n',
                     '## [Unreleased]\n## [Unreleased]\n## [0.8.1]\n',
                     '## [Unreleased]\n## [0.8.2-dev]\n## [0.8.1]\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                cycle.development_changelog(text, '0.8.1', '0.8.2-dev')


if __name__ == '__main__':
    unittest.main()
