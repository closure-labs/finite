#!/usr/bin/env python3
"""Drop Bluefin's superseded standalone Compass integration at image build time."""

from pathlib import Path
import re
import subprocess

# Match projectbluefin/common #1729 while the stable images still ship these files.
COMPASS_FILES = (
    "usr/share/ublue-os/homebrew/preinstall.d/compass.Brewfile",
    "usr/lib/systemd/user-preset/01-compass.preset",
    "usr/lib/systemd/user/compass.service",
    "usr/lib/systemd/user/graphical-session.target.wants/compass.service",
    "etc/systemd/user/graphical-session.target.wants/compass.service",
)
COMPASS_SECTION = (
    "[org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/compass]"
)
COMPASS_ITEMS = {
    "enabled-extensions": "compass@tunaos.org",
    "custom-keybindings": (
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/compass/"
    ),
}


def remove_legacy_compass(root):
    for relative in COMPASS_FILES:
        (root / relative).unlink(missing_ok=True)

    dconf = root / "etc/dconf/db/distro.d/02-bluefin-keybindings"
    if dconf.is_file():
        original = dconf.read_text()
        updated = re.sub(
            rf"(?m)^{re.escape(COMPASS_SECTION)}[ \t]*\n(?:^(?:name|command|binding)[ \t]*=.*\n?)*",
            "",
            original,
        )
        if updated != original:
            dconf.write_text(updated)
            subprocess.run(["dconf", "update"], check=True)

    schema_dir = root / "usr/share/glib-2.0/schemas"
    override = schema_dir / "zz0-bluefin-modifications.gschema.override"
    if override.is_file():
        original = override.read_text()
        updated = original
        for key, item in COMPASS_ITEMS.items():
            quoted = re.escape(f"'{item}'")
            updated = re.sub(
                rf"(?m)^({key}[ \t]*=[^\n]*),[ \t]*{quoted}(?=[ \t]*[,\]])",
                r"\1",
                updated,
            )
            updated = re.sub(
                rf"(?m)^({key}[ \t]*=[ \t]*\[)[ \t]*{quoted}(?:,[ \t]*)?",
                r"\1",
                updated,
            )
        if updated != original:
            override.write_text(updated)
            subprocess.run(["glib-compile-schemas", str(schema_dir)], check=True)


if __name__ == "__main__":
    remove_legacy_compass(Path("/"))
