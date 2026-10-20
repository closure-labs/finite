"""Finite owns OS adapters; Foundation owns the Home Manager implementation."""
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = {"schema": 1, "initializeSchemas": [1, 2], "normalizeSchemas": [2],
                "writeSchema": 2, "catalogSchemas": [3]}


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


class FirstLoginReaders(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.saved = self.root / "saved.json"
        self.seed = self.root / "seed.yaml"
        self.home = self.root / "home-manager"
        self.log = self.root / "events.jsonl"
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps({
            "schema": 3, "profileCapabilities": CAPABILITIES,
            "classifications": {"professional": {"label": "Professional"}},
            "foundations": {"bluefin": {"hardware": ["generic-x86_64", "dell-xps-9350-intel"]}},
            "roles": {"it": {"label": "IT", "order": 60, "classification": "professional"},
                      "developer": {"label": "Developer", "order": 10, "classification": "professional"}},
        }))
        self.running = self.root / "running.json"
        self.running.write_text(json.dumps({"foundation": "bluefin", "hardware": "generic-x86_64"}))
        for command in ("nix", "systemctl", "home-init", "zenity"):
            executable = self.bin / command
            executable.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
command = Path(sys.argv[0]).name
with Path(os.environ["LOGIN_LOG"]).open("a") as stream:
    event = [command, *sys.argv[1:]]
    if command == "home-init" and "--profile" in sys.argv:
        event.append(Path(sys.argv[sys.argv.index("--profile") + 1]).read_text())
    stream.write(json.dumps(event) + "\\n")
if command == "home-init":
    if "--capabilities" in sys.argv:
        print(os.environ["LOGIN_CAPABILITIES"])
        sys.exit(int(os.environ.get("LOGIN_CAPABILITY_STATUS", "0")))
    sys.exit(int(os.environ.get("LOGIN_INIT_STATUS", "0")))
if command == "zenity" and "--list" in sys.argv:
    print(os.environ.get("LOGIN_ROLES", "developer,it"))
    sys.exit(int(os.environ.get("LOGIN_DIALOG_STATUS", "0")))
''')
            executable.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        FINITE_HOME_PROFILE_PATH=str(self.saved), FINITE_HOME_FLAKE_PATH=str(self.home),
                        FINITE_PROVISIONED_PROFILE_PATH=str(self.seed), FINITE_RUNNING_PROFILE_PATH=str(self.running),
                        FINITE_FOUNDATION_CATALOG=str(self.catalog), FINITE_NIX_COMMAND=str(self.bin / "nix"),
                        FINITE_NIX_WAIT_SECONDS="0", FINITE_HOME_INIT_COMMAND=str(self.bin / "home-init"),
                        FINITE_DMI_ROOT=str(self.root / "no-dmi"), LOGIN_LOG=str(self.log),
                        LOGIN_CAPABILITIES=json.dumps(CAPABILITIES))

    def run_login(self, **overrides):
        before = {path: path.read_bytes() for path in (self.saved, self.seed) if path.is_file()}
        self.log.unlink(missing_ok=True)
        result = subprocess.run(["bash", str(ROOT / "files/system/usr/libexec/finite/home-first-login")],
                                env={**self.env, **overrides}, text=True, capture_output=True)
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
        events = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        self.assertFalse(self.home.exists())
        return result, events

    def selections(self, events):
        return [event for event in events if event[0] == "home-init" and "--profile" in event]

    def test_saved_schema_one_and_two_are_preserved_and_dispatched(self):
        for schema in (1, 2):
            self.saved.write_text(json.dumps({"schema": schema, "roles": ["developer"], "packages": []}))
            with self.subTest(schema=schema):
                result, events = self.run_login()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.selections(events)[0][2], str(self.saved))
                self.assertFalse(any("--list" in event for event in events))

    def test_saved_profile_takes_precedence_over_seed(self):
        self.saved.write_text('{"schema":2,"roles":["developer"]}')
        self.seed.write_text("schema: 2\nroles: [it]\n")
        result, events = self.run_login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.selections(events)[0][2], str(self.saved))

    def test_unsupported_or_malformed_saved_profile_never_selects_a_replacement(self):
        self.seed.write_text("schema: 2\nroles: [it]\n")
        for content in ('{"schema":3}', '{"schema":true}', '{}', 'not: [valid yaml', ''):
            self.saved.write_text(content)
            with self.subTest(content=content):
                result, events = self.run_login()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.selections(events), [])
                self.assertFalse(any("--list" in event for event in events))

    def test_helper_validation_failure_does_not_open_selector_or_use_seed(self):
        self.saved.write_text('{"schema":2,"roles":["unknown","unknown"]}')
        self.seed.write_text("schema: 2\n")
        result, events = self.run_login(LOGIN_INIT_STATUS="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.selections(events)), 1)
        self.assertEqual(self.selections(events)[0][2], str(self.saved))
        self.assertFalse(any("--list" in event for event in events))

    def test_dangling_saved_profile_is_preserved_without_replacement(self):
        self.saved.symlink_to(self.root / "missing-profile.json")
        self.seed.write_text("schema: 2\n")
        result, events = self.run_login()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.saved.is_symlink())
        self.assertEqual(self.selections(events), [])
        self.assertFalse(any("--list" in event for event in events))

    def test_seed_yaml_is_used_only_without_saved_profile(self):
        self.seed.write_text("schema: 2\nroles: [developer]\npackages: []\n")
        result, events = self.run_login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.selections(events)[0][2], str(self.seed))

    def test_legacy_helper_only_allows_known_schemas(self):
        for schema, success in ((1, True), (2, True), (3, False)):
            self.saved.write_text(json.dumps({"schema": schema}))
            with self.subTest(schema=schema):
                result, events = self.run_login(LOGIN_CAPABILITY_STATUS="2")
                self.assertEqual(result.returncode == 0, success, result.stderr)
                self.assertEqual(bool(self.selections(events)), success)
                self.assertFalse(any("--list" in event for event in events))

    def test_explicit_malformed_helper_capabilities_fail(self):
        self.saved.write_text('{"schema":2}')
        for value in ("not JSON", "{}", "null", json.dumps({**CAPABILITIES, "initializeSchemas": []})):
            with self.subTest(value=value):
                result, events = self.run_login(LOGIN_CAPABILITIES=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.selections(events), [])

    def test_partial_consumer_is_preserved_without_invoking_helper(self):
        self.home.mkdir()
        self.home.joinpath("customize.nix").write_text("private customization")
        result = subprocess.run(["bash", str(ROOT / "files/system/usr/libexec/finite/home-first-login")],
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.home.joinpath("customize.nix").read_text(), "private customization")
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertFalse(any(event[0] == "home-init" for event in events))

    def test_fresh_choices_use_catalog_labels_order_and_classification(self):
        result, events = self.run_login()
        self.assertEqual(result.returncode, 0, result.stderr)
        dialog = next(event for event in events if "--list" in event)
        self.assertIn("--hide-column=4", dialog)
        start = dialog.index("FALSE")
        self.assertEqual(dialog[start:], ["FALSE", "Professional", "Developer", "developer", "FALSE", "Professional", "IT", "it"])
        generated = json.loads(self.selections(events)[0][-1])
        self.assertEqual(generated, {"schema": 2, "foundation": "bluefin", "hardware": "generic-x86_64",
                                     "roles": ["developer", "it"], "packages": [], "identity": {}})

    def test_old_catalog_without_classifications_or_capabilities_remains_usable(self):
        value = json.loads(self.catalog.read_text())
        del value["profileCapabilities"]
        del value["classifications"]
        for role in value["roles"].values():
            del role["classification"]
        self.catalog.write_text(json.dumps(value))
        result, events = self.run_login(LOGIN_CAPABILITY_STATUS="2")
        self.assertEqual(result.returncode, 0, result.stderr)
        dialog = next(event for event in events if "--list" in event)
        self.assertEqual(dialog[dialog.index("FALSE"):][:4], ["FALSE", "", "Developer", "developer"])

    def test_newer_helper_does_not_change_the_fresh_login_writer_format(self):
        future = {**CAPABILITIES, "initializeSchemas": [1, 2, 3], "normalizeSchemas": [2, 3], "writeSchema": 3}
        result, events = self.run_login(LOGIN_CAPABILITIES=json.dumps(future))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.selections(events)[0][-1])["schema"], 2)

    def test_fresh_catalog_mismatch_prevents_selector_and_writer(self):
        baseline = json.loads(self.catalog.read_text())
        for change in ({"writeSchema": 3}, {"catalogSchemas": [4]}, {"initializeSchemas": [True]},
                       {"initializeSchemas": [1, 1, 2]}, {"normalizeSchemas": []}):
            value = {**baseline, "profileCapabilities": {**baseline["profileCapabilities"], **change}}
            self.catalog.write_text(json.dumps(value))
            with self.subTest(change=change):
                result, events = self.run_login()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.selections(events), [])
                self.assertFalse(any("--list" in event for event in events))

    def test_cancelled_fresh_dialog_never_initializes(self):
        result, events = self.run_login(LOGIN_DIALOG_STATUS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.selections(events), [])


if __name__ == "__main__":
    unittest.main()
