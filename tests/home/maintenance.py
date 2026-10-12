#!/usr/bin/env python3
"""App update reporting must preserve user inputs and survive notification failure."""
import copy
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "files/system/usr/bin/finite-app-status"


def fixture():
    return {
        "version": 7, "root": "root", "nodes": {
            "root": {"inputs": {"apps": "apps"}},
            "apps": {
                "original": {"type": "github", "owner": "finite", "repo": "apps"},
                "locked": {"type": "github", "rev": "approved"},
                "inputs": {"dependency": "dependency"},
            },
            "dependency": {"locked": {"type": "github", "rev": "approved-dependency"}},
        },
    }


class AppStatus(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / "template"
        self.installed = self.root / "installed"
        self.bin = self.root / "bin"
        for path in (self.template, self.installed, self.bin):
            path.mkdir()
        self.write(self.template, fixture())
        self.write(self.installed, fixture())
        (self.template / "finite-template.json").write_text('{"schema":1}')
        self.env = dict(os.environ, FINITE_HOME_TEMPLATE_PATH=str(self.template),
                        FINITE_HOME_FLAKE_PATH=str(self.installed), XDG_STATE_HOME=str(self.root / "state"),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.notify = self.bin / "notify-send"
        self.notify.write_text(f'#!{shutil.which("bash")}\nprintf "notified\\n" >> "{self.root}/notifications"\n')
        self.notify.chmod(0o755)

    def write(self, directory, lock):
        (directory / "flake.lock").write_text(json.dumps(lock))

    def run_status(self, *args, expected=0):
        before = (self.installed / "flake.lock").read_bytes()
        result = subprocess.run([sys.executable, str(COMMAND), "--json", *args], env=self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(before, (self.installed / "flake.lock").read_bytes())
        return json.loads(result.stdout) if result.stdout else None

    def test_current_read_only_and_node_renaming(self):
        lock = fixture()
        lock["nodes"]["renamed"] = lock["nodes"].pop("dependency")
        lock["nodes"]["apps"]["inputs"]["dependency"] = "renamed"
        self.write(self.installed, lock)
        self.assertEqual(self.run_status()["current"], ["apps"])
        self.assertFalse((self.root / "state").exists())

    def test_transitive_pin_change(self):
        lock = fixture()
        lock["nodes"]["dependency"]["locked"]["rev"] = "old"
        self.write(self.installed, lock)
        self.assertEqual(self.run_status()["different"], ["apps"])

    def test_custom_sources_and_additions_are_separate(self):
        lock = fixture()
        lock["nodes"]["apps"]["original"]["repo"] = "my-fork"
        lock["nodes"]["root"]["inputs"]["extra"] = "dependency"
        self.write(self.installed, lock)
        result = self.run_status()
        self.assertEqual(result["custom"], ["apps", "extra"])
        self.assertEqual(result["different"], [])

    def test_missing_managed_input(self):
        lock = fixture()
        lock["nodes"]["root"]["inputs"] = {}
        self.write(self.installed, lock)
        self.assertEqual(self.run_status()["missing"], ["apps"])

    def test_follow_reference_uses_root(self):
        lock = fixture()
        lock["nodes"]["root"]["inputs"]["dependency"] = "dependency"
        approved = copy.deepcopy(lock)
        lock["nodes"]["apps"]["inputs"]["dependency"] = ["dependency"]
        self.write(self.template, approved)
        self.write(self.installed, lock)
        self.assertEqual(self.run_status()["different"], [])

    def test_malformed_and_cyclic_follows_fail_visible(self):
        for lock in ({"version": 7, "nodes": {}}, {
            "version": 7, "root": "root", "nodes": {"root": {"inputs": {"apps": ["apps"]}}},
        }):
            self.write(self.installed, lock)
            self.run_status(expected=2)

    def test_notification_once_per_approved_template(self):
        lock = fixture()
        lock["nodes"]["apps"]["locked"]["rev"] = "old"
        self.write(self.installed, lock)
        for _ in range(2):
            self.run_status("--notify")
        self.assertEqual((self.root / "notifications").read_text().splitlines(), ["notified"])
        (self.template / "finite-template.json").write_text('{"schema":2}')
        self.run_status("--notify")
        self.assertEqual(len((self.root / "notifications").read_text().splitlines()), 2)

    def test_failed_notification_retries_without_writing_state(self):
        lock = fixture()
        lock["nodes"]["apps"]["locked"]["rev"] = "old"
        self.write(self.installed, lock)
        self.notify.write_text(f'#!{shutil.which("bash")}\nexit 1\n')
        self.run_status("--notify")
        self.assertFalse((self.root / "state").exists())


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
