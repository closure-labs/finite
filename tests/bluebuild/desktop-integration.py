"""Exercise guarded camera migration and real GNOME schema compilation."""
import hashlib
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'files/system/usr/libexec/finite/desktop-integration'
LEGACY = '/var/lib/finite/libcamera/ipa'
EXTENSION = 'usr/share/gnome-shell/extensions/custom-command-list@storageb.github.com'
LOADER = SourceFileLoader('desktop_integration', str(SCRIPT))
MODULE = module_from_spec(spec_from_loader(LOADER.name, LOADER))
LOADER.exec_module(MODULE)


class DesktopIntegration(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.camera = self.root / 'etc/libcamera/configuration.yaml'
        self.camera.parent.mkdir(parents=True)
        self.host_module = self.root / 'usr/lib64/libcamera/ipa/ipa_soft_simple.so'
        self.host_module.parent.mkdir(parents=True)
        self.host_module.write_bytes(b'host module fixture')
        self.value = {'version': 1, 'configuration': {
            'ipa': {'module_paths': [LEGACY], 'other': True},
            'pipelines': {'simple': {'cameras': ['ov02c10']}}}}

    def configuration(self, value=None):
        self.camera.write_text(json.dumps(self.value if value is None else value))
        return hashlib.sha256(self.camera.read_bytes()).hexdigest()

    def run_command(self, operation, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), operation, '--root', str(self.root), *arguments],
                              capture_output=True, text=True)

    def read_camera(self):
        result = subprocess.run(['yq', '-o=json', '.', str(self.camera)],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_absent_components_are_a_noop(self):
        result = self.run_command('image')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'camera': {'status': 'absent'}, 'extension': {'status': 'absent'}})

    def test_image_removes_only_the_legacy_path_and_preserves_custom_configuration(self):
        self.value['configuration']['ipa']['module_paths'].append('/opt/other/ipa')
        self.configuration()
        result = self.run_command('image')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.value['configuration']['ipa']['module_paths'] = ['/opt/other/ipa']
        self.assertEqual(self.read_camera(), self.value)
        self.assertFalse(list(self.camera.parent.glob('*.finite-previous.*')))

    def test_reviewed_migration_backs_up_and_is_idempotent(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        os.chmod(self.camera, 0o600)
        result = self.run_command('repair-camera', '--expected-sha256', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = Path(json.loads(result.stdout)['camera']['backup'])
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.camera.stat().st_mode), 0o600)
        del self.value['configuration']['ipa']['module_paths']
        self.assertEqual(self.read_camera(), self.value)
        new_digest = hashlib.sha256(self.camera.read_bytes()).hexdigest()
        again = self.run_command('repair-camera', '--expected-sha256', new_digest)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)['camera']['status'], 'unchanged')

    def test_empty_ipa_configuration_uses_host_defaults(self):
        self.configuration({'version': 1, 'configuration': {'ipa': {'module_paths': [LEGACY]}}})
        result = self.run_command('image')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_camera(), {'version': 1, 'configuration': {}})

    def test_missing_or_stale_approval_never_changes_configuration(self):
        self.configuration()
        original = self.camera.read_bytes()
        for args in [(), ('--expected-sha256', '0' * 64), ('--expected-sha256', 'invalid')]:
            result = self.run_command('repair-camera', *args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.camera.read_bytes(), original)
        self.assertFalse(list(self.camera.parent.glob('*.finite-previous.*')))

    def test_missing_host_module_does_not_remove_legacy_selection(self):
        self.configuration()
        original = self.camera.read_bytes()
        self.host_module.unlink()
        result = self.run_command('image')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.camera.read_bytes(), original)

    def test_linked_configuration_and_malformed_paths_are_not_overwritten(self):
        target = self.root / 'external.yaml'
        target.write_text(json.dumps(self.value))
        self.camera.symlink_to(target)
        result = self.run_command('image')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(target.read_text()), self.value)
        self.camera.unlink()
        self.value['configuration']['ipa']['module_paths'] = LEGACY
        self.configuration()
        original = self.camera.read_bytes()
        result = self.run_command('image')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.camera.read_bytes(), original)

    def test_linked_ancestor_cannot_escape_the_requested_root(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        outside = self.root / 'outside-etc'
        (self.root / 'etc').rename(outside)
        (self.root / 'etc').symlink_to(outside, target_is_directory=True)
        result = self.run_command('repair-camera', '--expected-sha256', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((outside / 'libcamera/configuration.yaml').read_bytes(), original)
        self.assertFalse(list((outside / 'libcamera').glob('*.finite-previous.*')))

    def test_linked_image_root_is_rejected_before_migration(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        linked = self.root / 'linked-root'
        linked.symlink_to(self.root, target_is_directory=True)
        result = subprocess.run([sys.executable, str(SCRIPT), 'repair-camera', '--root', str(linked),
                                 '--expected-sha256', digest], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.camera.read_bytes(), original)

    def test_approved_bytes_are_parsed_without_rereading_path(self):
        digest = self.configuration()
        original_capture = MODULE.capture
        parsed = []
        def capture(command, **kwargs):
            if '-o=json' in command:
                self.assertEqual(command, ['yq', '-o=json', '.'])
                self.assertEqual(kwargs['input'].encode(), self.camera.read_bytes())
                parsed.append(True)
            return original_capture(command, **kwargs)
        with patch.object(MODULE, 'capture', side_effect=capture):
            MODULE.repair_camera(self.root, digest)
        self.assertEqual(parsed, [True])

    def test_failed_relabel_restores_original_bytes_owner_and_mode(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        os.chmod(self.camera, 0o600)
        before = self.camera.stat()
        events = []
        def relabel(path):
            events.append(path.read_bytes())
            if len(events) == 1:
                raise subprocess.CalledProcessError(1, ['restorecon'])
        with self.assertRaisesRegex(ValueError, 'original configuration and label restored'):
            MODULE.repair_camera(self.root, digest, relabel=relabel)
        self.assertEqual(self.camera.read_bytes(), original)
        after = self.camera.stat()
        self.assertEqual((after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)),
                         (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)))
        self.assertEqual(events[1], original)

    def test_failed_rollback_relabel_surfaces_retained_backup(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        def fail_relabel(path):
            raise subprocess.CalledProcessError(1, ['restorecon'])
        with self.assertRaisesRegex(ValueError, 'retained original backup') as error:
            MODULE.repair_camera(self.root, digest, relabel=fail_relabel)
        self.assertEqual(self.camera.read_bytes(), original)
        self.assertIn(digest, str(error.exception))

    def test_conflicting_backup_is_not_overwritten(self):
        digest = self.configuration()
        original = self.camera.read_bytes()
        backup = self.camera.with_name(self.camera.name + '.finite-previous.' + digest)
        backup.write_text('unrelated backup')
        result = self.run_command('repair-camera', '--expected-sha256', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.camera.read_bytes(), original)
        self.assertEqual(backup.read_text(), 'unrelated backup')

    def test_schema_is_compiled_for_the_installed_extension(self):
        schemas = self.root / EXTENSION / 'schemas'
        schemas.mkdir(parents=True)
        (schemas / 'org.gnome.shell.extensions.custom-command-list.gschema.xml').write_text(
            '<schemalist><schema id="org.gnome.shell.extensions.custom-command-list" '
            'path="/org/gnome/shell/extensions/custom-command-list/">'
            '<key name="commands" type="as"><default>[]</default></key></schema></schemalist>')
        result = self.run_command('image')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater((schemas / 'gschemas.compiled').stat().st_size, 0)

    def test_missing_or_invalid_extension_schema_stops_image_assembly(self):
        schemas = self.root / EXTENSION / 'schemas'
        schemas.mkdir(parents=True)
        self.assertNotEqual(self.run_command('image').returncode, 0)
        (schemas / 'invalid.gschema.xml').write_text('<not-a-schema>')
        self.assertNotEqual(self.run_command('image').returncode, 0)
        self.assertFalse((schemas / 'gschemas.compiled').exists())


if __name__ == '__main__':
    unittest.main()
