"""Finite owns OS adapters; Foundation owns the Home Manager implementation."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FoundationIntegration(unittest.TestCase):
    def test_shims_delegate_to_the_selected_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "scripts").mkdir()
            (source / "scripts/home.py").write_text("import sys\nprint('|'.join(sys.argv[1:]))\n")
            for command, operation in (("usr/libexec/finite/home-init", "init"),
                                       ("usr/bin/finite-home-update", "update"),
                                       ("usr/bin/finite-home-migrate", "migrate"),
                                       ("usr/bin/finite-app-status", "status")):
                # Fedora provides /usr/bin/python3; the Nix sandbox supplies a store interpreter.
                shim = source / "shim"
                shim.write_text((ROOT / "files/system" / command).read_text().replace(
                    "/usr/bin/python3", sys.executable))
                result = subprocess.run(["bash", str(shim), "--check"],
                                        env=dict(os.environ, FINITE_FOUNDATION_SOURCE=str(source)),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), operation + "|--check")

    def test_existing_user_configuration_skips_login_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("flake.nix", "flake.lock", "profile.json"):
                (root / name).write_text("user-owned configuration")
            result = subprocess.run(["bash", str(ROOT / "files/system/usr/libexec/finite/home-first-login")],
                                    env=dict(os.environ, FINITE_HOME_FLAKE_PATH=str(root),
                                             FINITE_NIX_COMMAND="/does-not-exist", FINITE_NIX_WAIT_SECONDS="0"),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "flake.nix").read_text(), "user-owned configuration")


if __name__ == "__main__":
    unittest.main()
