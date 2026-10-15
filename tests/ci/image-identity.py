#!/usr/bin/env python3
"""Keep image bytes independent of host qualification without dropping build inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image = load('image_identity', 'scripts/ci/image_identity.py')
qualification = load('image_qualification_context', 'scripts/bluebuild/qualification-context.py')
PROFILES = ('bluefin-generic', 'bluefin-dx-generic')
PAYLOAD = '/nix/store/fixture-image-payload.drv'
BUILD_FILES = (
    'cosign.pub', 'sources/cosign-runtime.json', 'scripts/ci/cosign-runtime.py',
    'scripts/ci/image_identity.py', 'sources/bluebuild-cli.json', 'sources/bluebuild-cli.pub',
    'sources/bluefin-trust.json', 'sources/bluefin.pub',
    'recipes/shared/base.yml', 'recipes/shared/final.yml',
    'files/scripts/nix-install.sh', 'files/scripts/upstream-kernel.py', 'files/dnf/terra.repo',
    'files/system/usr/libexec/finite/guest-check.py',
    'scripts/bluebuild/build.sh', 'scripts/bluebuild/stage.sh',
    'scripts/bluebuild/install-cli.sh', 'scripts/bluebuild/inspect-built.sh',
    'scripts/bluebuild/verify-image.sh', '.github/workflows/image.yml',
)


class ImageInputContract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for path in (*BUILD_FILES, *image.QUALIFICATION_ONLY,
                     *('recipes/' + profile + '.yml' for profile in PROFILES)):
            self.write(path, path + '\n')

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def values(self):
        return {profile: image.identity(profile, self.root, PAYLOAD) for profile in PROFILES}

    def test_host_qualification_changes_requalify_without_rebuilding_images(self):
        # Exercise the real qualification-context hash collector, rather than
        # asserting a second hand-maintained qualification dependency list.
        host_inputs = [path for path in image.QUALIFICATION_ONLY if
                       path.startswith(('scripts/bluebuild/', 'files/installer/')) and
                       path not in ('scripts/bluebuild/security-policy.py',
                                    'scripts/bluebuild/security-scan.py',
                                    'scripts/bluebuild/security-run.sh',
                                    'scripts/bluebuild/audit-published.sh')]
        host_inputs += ['sources/bluebuild-installer.json', 'sources/installer-security.json',
                        '.github/workflows/qualification.yml',
                        '.github/workflows/vm-acceptance.yml', '.github/workflows/iso.yml']
        for relative in sorted(host_inputs):
            with self.subTest(path=relative):
                before_image = self.values()
                before_context = qualification.source_inputs(self.root)
                path = self.root / relative
                path.write_text(path.read_text() + 'changed host contract\n')
                self.assertEqual(before_image, self.values())
                self.assertNotEqual(qualification.identity(before_context),
                                    qualification.identity(qualification.source_inputs(self.root)))

    def test_build_payload_and_trust_changes_invalidate_every_image(self):
        for relative in BUILD_FILES:
            with self.subTest(path=relative):
                before = self.values()
                path = self.root / relative
                path.write_text(path.read_text() + 'changed build input\n')
                self.assertTrue(all(before[profile] != value for profile, value in self.values().items()))
        before = self.values()
        for profile in PROFILES:
            self.assertNotEqual(before[profile], image.identity(profile, self.root, '/nix/store/new-payload.drv'))

    def test_profile_recipe_changes_affect_only_its_image(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                before = self.values()
                self.write('recipes/' + profile + '.yml', 'changed recipe\n')
                after = self.values()
                self.assertNotEqual(before[profile], after[profile])
                self.assertTrue(all(before[other] == after[other] for other in PROFILES if other != profile))


    def test_unknown_helpers_and_installer_files_are_conservative_inputs(self):
        for relative in ('scripts/bluebuild/new-build-helper.py',
                         'scripts/bluebuild/nested/new-helper.sh',
                         'files/installer/new-unknown-file',
                         '.github/workflows/new-qualification-builder.yml'):
            with self.subTest(path=relative):
                before = self.values()
                self.write(relative, 'unreviewed input\n')
                self.assertTrue(all(before[profile] != value for profile, value in self.values().items()))

    def test_host_bytecode_is_ignored_but_shipped_bytecode_is_an_input(self):
        before = self.values()
        for relative in ('scripts/bluebuild/__pycache__/new.cpython-313.pyc',
                         'scripts/bluebuild/helper.pyo'):
            self.write(relative, 'host bytecode\n')
        self.assertEqual(before, self.values())
        self.write('files/system/shipped.pyc', 'shipped bytecode\n')
        self.assertTrue(all(before[profile] != value for profile, value in self.values().items()))

    def test_symlink_target_and_executable_mode_remain_image_inputs(self):
        before = self.values()
        path = self.root / 'files/scripts/nix-install.sh'
        path.chmod(path.stat().st_mode | 0o111)
        self.assertTrue(all(before[profile] != value for profile, value in self.values().items()))
        link = self.root / 'files/system/test-link'
        link.symlink_to('first-target')
        before = self.values()
        link.unlink()
        link.symlink_to('second-target')
        self.assertTrue(all(before[profile] != value for profile, value in self.values().items()))

    def test_installer_executable_modes_are_bound_to_qualification(self):
        before_image = self.values()
        before_context = qualification.source_inputs(self.root)
        path = self.root / 'files/installer/install_finite_fstab'
        path.chmod(path.stat().st_mode | 0o111)
        self.assertEqual(before_image, self.values())
        self.assertNotEqual(before_context, qualification.source_inputs(self.root))

    def test_schema_migration_never_relabels_old_contract(self):
        encoded = []
        dumps = json.dumps

        def capture(value, **kwargs):
            encoded.append(value)
            return dumps(value, **kwargs)

        with patch.object(image.json, 'dumps', side_effect=capture):
            current = image.identity(PROFILES[0], self.root, PAYLOAD)
        self.assertEqual(encoded[0]['schema'], 4)
        self.assertRegex(current, r'^v1:[0-9a-f]{64}$')
        for old_schema in (1, 2, 3):
            old_contract = {**encoded[0], 'schema': old_schema}
            old = 'v1:' + hashlib.sha256(dumps(old_contract, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
            self.assertNotEqual(old, current)


if __name__ == '__main__':
    unittest.main()
