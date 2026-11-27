#!/usr/bin/env python3
"""Exercise the image-only compatibility cleanup on an isolated filesystem."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "legacy_compass", ROOT / "files/scripts/remove-legacy-compass.py"
)
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


class LegacyCompassTests(unittest.TestCase):
    def test_removes_only_legacy_defaults_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            brew = root / "usr/share/ublue-os/homebrew/preinstall.d"
            for name in CLEANUP.COMPASS_FILES:
                entry = root / name
                entry.parent.mkdir(parents=True, exist_ok=True)
                if entry.parent.name.endswith(".wants"):
                    entry.symlink_to("../compass.service")
                else:
                    entry.touch()
            chairlift = brew / "chairlift.Brewfile"
            chairlift.write_text("keep me\n")
            dconf = root / "etc/dconf/db/distro.d/02-bluefin-keybindings"
            dconf.parent.mkdir(parents=True)
            remaining = "[another/shortcut]\ncommand='untouched'\n"
            dconf.write_text(
                CLEANUP.COMPASS_SECTION + "\nname='Compass'\n"
                "command='compass toggle'\nbinding='<Super>space'\n" + remaining
            )
            schema = root / "usr/share/glib-2.0/schemas/zz0-bluefin-modifications.gschema.override"
            schema.parent.mkdir(parents=True)
            schema.write_text(
                "[org.gnome.shell]\nenabled-extensions = ['keep', 'compass@tunaos.org']\n"
                "[org.gnome.settings-daemon.plugins.media-keys]\n"
                f"custom-keybindings=['{CLEANUP.COMPASS_ITEMS['custom-keybindings']}', '/keep/']\n"
            )

            with patch.object(CLEANUP.subprocess, "run") as run:
                CLEANUP.remove_legacy_compass(root)
                CLEANUP.remove_legacy_compass(root)
            self.assertEqual(run.call_args_list, [
                call(["dconf", "update"], check=True),
                call(["glib-compile-schemas", str(schema.parent)], check=True),
            ])
            self.assertTrue(all(not (root / path).is_symlink() and not (root / path).exists()
                                for path in CLEANUP.COMPASS_FILES))
            self.assertEqual(chairlift.read_text(), "keep me\n")
            self.assertEqual(dconf.read_text(), remaining)
            self.assertIn("enabled-extensions = ['keep']", schema.read_text())
            self.assertIn("custom-keybindings=['/keep/']", schema.read_text())

    def test_clean_upstream_does_not_trigger_rebuilds(self):
        with TemporaryDirectory() as directory, patch.object(CLEANUP.subprocess, "run") as run:
            CLEANUP.remove_legacy_compass(Path(directory))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
