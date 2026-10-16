#!/usr/bin/env python3
"""Host keyboard access remains an explicit Finite administrator operation."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class KeyboardAccess(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.etc = self.root / "etc"
        self.rules = self.etc / "udev/rules.d"
        self.rules.mkdir(parents=True)
        self.rule = self.rules / "70-finite-espanso-input.rules"
        self.command = ROOT / "files/system/usr/bin/finite-keyboard-access"

    def invoke(self, operation, owner="0"):
        # Exercise the production function in an isolated directory; only owner and
        # udev calls are stubbed. The installed CLI always fixes /etc and checks EUID.
        script = r'''source "$1"
stat() {
    if [[ "$2" == %u ]]; then printf '%s\n' "$TEST_OWNER"; else command stat "$@"; fi
}
udevadm() { printf '%s\n' "$*" >>"$TEST_UDEV_LOG"; }
set_keyboard_access "$2" "$3"
'''
        return subprocess.run([shutil.which("bash"), "-c", script,
                               "test", str(self.command), operation, str(self.etc)],
                              env=dict(os.environ, TEST_OWNER=owner, TEST_UDEV_LOG=str(self.root / "udev.log")),
                              text=True, capture_output=True)

    def test_enable_disable_and_reboot_notice(self):
        enabled = self.invoke("enable")
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        content = self.rule.read_text()
        self.assertIn('ENV{ID_INPUT_KEYBOARD}=="1", TAG+="uaccess"', content)
        self.assertEqual(self.rule.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.invoke("enable").returncode, 0)
        disabled = self.invoke("disable")
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertIn("Reboot", disabled.stdout)
        self.assertFalse(self.rule.exists())
        self.assertEqual(self.invoke("disable").returncode, 0)
        self.assertIn("control --reload-rules", (self.root / "udev.log").read_text())
        self.assertIn("--sysname-match=event*", (self.root / "udev.log").read_text())

    def test_symlink_rule_never_changes_target(self):
        target = self.root / "unrelated"
        target.write_text("preserve")
        self.rule.symlink_to(target)
        for operation in ("enable", "disable"):
            self.assertNotEqual(self.invoke(operation).returncode, 0)
            self.assertEqual(target.read_text(), "preserve")
            self.assertTrue(self.rule.is_symlink())
        self.assertFalse((self.root / "udev.log").exists())

    def test_writable_and_wrong_owner_directories_refused(self):
        self.rules.chmod(0o777)
        self.assertNotEqual(self.invoke("enable").returncode, 0)
        self.rules.chmod(0o755)
        self.assertNotEqual(self.invoke("enable", owner="1000").returncode, 0)
        self.assertFalse(self.rule.exists())

    def test_symlink_parent_refused(self):
        elsewhere = self.root / "elsewhere"
        self.rules.rename(elsewhere)
        self.rules.symlink_to(elsewhere, target_is_directory=True)
        self.assertNotEqual(self.invoke("enable").returncode, 0)
        self.assertEqual(list(elsewhere.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
