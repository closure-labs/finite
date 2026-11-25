#!/usr/bin/env python3
"""Keep the temporary upstream runtime pinned and transition only to fixed releases."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
spec = importlib.util.spec_from_file_location('bootc_update', ROOT / 'scripts/ci/update-bootc-runtime.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


def archive(version):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as stream:
        value = ('[package]\nversion = "' + version + '"\n').encode()
        info = tarfile.TarInfo('bootc-release/crates/lib/Cargo.toml')
        info.size = len(value)
        stream.addfile(info, io.BytesIO(value))
    return output.getvalue()


class RuntimeSource(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'bootc-runtime.json'
        self.pin = update.source.validate(json.loads((ROOT / 'sources/bootc-runtime.json').read_text()))
        # Keep exercising the snapshot-to-release transition after the real pin
        # has advanced to an official release.
        self.pin.update(kind='upstream-snapshot', version='1.17.4',
                        ref=self.pin['requiredFix'], revision=self.pin['requiredFix'],
                        rpmRelease='0.1.finite.git' + self.pin['requiredFix'][:11])
        self.path.write_text(json.dumps(self.pin))
        self.data = archive('1.17.5')
        self.fetch = Mock(return_value=self.data)
        self.api = Mock(side_effect=[{'draft': False, 'prerelease': False, 'tag_name': 'v1.17.5'},
            {'object': {'type': 'commit', 'sha': 'a' * 40}},
            {'status': 'ahead', 'merge_base_commit': {'sha': self.pin['requiredFix']}}])

    def test_snapshot_uses_unmodified_merged_upstream_and_low_rpm_release(self):
        self.assertEqual(update.source.validate(self.pin), self.pin)
        self.assertEqual(self.pin['revision'], self.pin['requiredFix'])
        self.assertEqual(self.pin['ref'], self.pin['revision'])
        self.assertEqual(self.pin['minimumOfficialVersion'], '1.17.5')
        self.assertTrue(self.pin['rpmRelease'].startswith('0.'))

    def test_next_fixed_official_release_replaces_commit_source_with_versioned_tag(self):
        self.assertTrue(update.update(self.path, self.api, self.fetch))
        pin = json.loads(self.path.read_text())
        self.assertEqual((pin['kind'], pin['version'], pin['ref']), ('release', '1.17.5', 'v1.17.5'))
        self.assertEqual(pin['revision'], 'a' * 40)
        self.assertEqual(pin['archiveSha256'], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(pin['requiredFix'], self.pin['requiredFix'])
        self.fetch.assert_called_once_with('v1.17.5')
        self.assertEqual(self.api.call_args.args[0], update.PREFIX + 'compare/' + self.pin['requiredFix'] + '...' + 'a' * 40)

    def test_current_release_does_not_fake_a_future_version_or_fetch_sources(self):
        before = self.path.read_bytes()
        api = Mock(return_value={'draft': False, 'prerelease': False, 'tag_name': 'v1.17.4'})
        self.assertFalse(update.update(self.path, api, self.fetch))
        self.assertEqual(before, self.path.read_bytes())
        self.fetch.assert_not_called()
        api.assert_called_once()

    def test_unfixed_release_and_bad_archive_leave_the_pin_unchanged(self):
        before = self.path.read_bytes()
        for comparison in [{'status': 'behind'}, {'status': 'diverged'},
                           {'status': 'ahead', 'merge_base_commit': {'sha': 'f' * 40}}]:
            api = Mock(side_effect=[{'draft': False, 'prerelease': False, 'tag_name': 'v1.17.5'},
                                   {'object': {'type': 'commit', 'sha': 'a' * 40}}, comparison])
            with self.subTest(comparison=comparison), self.assertRaises(ValueError):
                update.update(self.path, api, self.fetch)
            self.assertEqual(before, self.path.read_bytes())
        self.fetch.assert_not_called()
        self.fetch.return_value = archive('1.17.4')
        with self.assertRaisesRegex(ValueError, 'archive version'):
            update.update(self.path, self.api, self.fetch)
        self.assertEqual(before, self.path.read_bytes())

    def test_prereleases_drafts_and_invalid_refs_cannot_change_the_pin(self):
        before = self.path.read_bytes()
        for release in [{'draft': True, 'prerelease': False, 'tag_name': 'v1.17.5'},
                        {'draft': False, 'prerelease': True, 'tag_name': 'v1.17.5'},
                        {'draft': False, 'prerelease': False, 'tag_name': 'v1.17.5-rc1'},
                        {'draft': False, 'prerelease': False, 'tag_name': 'main'}]:
            with self.subTest(release=release), self.assertRaises(ValueError):
                update.update(self.path, Mock(return_value=release), self.fetch)
            self.assertEqual(before, self.path.read_bytes())
        for field, value in [('ref', 'main'), ('revision', '../escape'), ('archiveSha256', 'x'),
                             ('schema', True), ('buildBase', 'fedora:latest')]:
            pin = {**self.pin, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                update.source.validate(pin)

    def test_annotated_tag_and_later_minor_release_are_supported(self):
        api = Mock(side_effect=[{'draft': False, 'prerelease': False, 'tag_name': 'v1.18.0'},
            {'object': {'type': 'tag', 'sha': 'b' * 40}},
            {'object': {'type': 'commit', 'sha': 'c' * 40}},
            {'status': 'ahead', 'merge_base_commit': {'sha': self.pin['requiredFix']}}])
        self.assertTrue(update.update(self.path, api, Mock(return_value=archive('1.18.0'))))
        self.assertEqual(json.loads(self.path.read_text())['ref'], 'v1.18.0')

    def test_stage_passes_the_checked_in_containerfile_explicitly(self):
        root = self.path.parent
        archive_path = root / 'source.tar.gz'
        archive_path.write_bytes(self.data)
        self.pin['archiveSha256'] = hashlib.sha256(self.data).hexdigest()
        sources = root / 'sources'
        sources.mkdir()
        (sources / self.path.name).write_text(json.dumps(self.pin))
        scripts = root / 'scripts/bluebuild'
        scripts.mkdir(parents=True)
        for name in ('bootc-runtime.Containerfile', 'build-bootc-runtime.sh'):
            (scripts / name).write_bytes((ROOT / 'scripts/bluebuild' / name).read_bytes())

        def run(command, *, check):
            self.assertTrue(check)
            if command[1] == 'build':
                context = Path(command[-1])
                self.assertEqual(Path(command[command.index('--file') + 1]), context / 'Containerfile')
                self.assertEqual((context / 'Containerfile').read_bytes(),
                                 (scripts / 'bootc-runtime.Containerfile').read_bytes())
                self.assertEqual(command[command.index('--memory') + 1], '2048m')
            elif command[1] == 'cp':
                Path(command[-1]).write_bytes(b'fixture output')

        for engine in ('docker', 'podman'):
            with self.subTest(engine=engine), patch.object(update.source, 'ROOT', root), \
                    patch.object(update.source.subprocess, 'run', side_effect=run), \
                    patch.object(update.source.subprocess, 'check_output', return_value='fixture\n'):
                result = update.source.stage(engine, root / engine, archive_path)
            self.assertEqual(result['rpmSha256'], hashlib.sha256(b'fixture output').hexdigest())


if __name__ == '__main__':
    unittest.main()
