"""Finite owns OS adapters; Foundation owns the Home Manager implementation."""
import os
import json
import shutil
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

    def test_schema_three_saved_and_seeded_profiles_follow_actual_helper_capabilities(self):
        reader = {**CAPABILITIES, "initializeSchemas": [1, 2, 3], "normalizeSchemas": [2, 3]}
        value = {"schema": 3, "roles": ["family", "creative"], "packages": [],
                 "capabilities": ["recording"], "custom": {"retain": True}}
        for path in (self.saved, self.seed):
            self.saved.unlink(missing_ok=True)
            self.seed.unlink(missing_ok=True)
            path.write_text(json.dumps(value))
            with self.subTest(path=path):
                result, events = self.run_login(LOGIN_CAPABILITIES=json.dumps(reader))
                self.assertEqual(result.returncode, 0, result.stderr)
                selected = self.selections(events)
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0][2], str(path))
                self.assertEqual(json.loads(selected[0][-1]), value)
                self.assertFalse(any("--list" in event for event in events))

    def test_schema_three_is_not_regenerated_when_an_old_helper_cannot_read_it(self):
        value = {"schema": 3, "roles": ["family"], "capabilities": ["notes"], "custom": "retain"}
        self.saved.write_text(json.dumps(value))
        self.seed.write_text("schema: 2\nroles: [developer]\n")
        result, events = self.run_login()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.selections(events), [])
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

    def current_catalog(self):
        reader = {**CAPABILITIES, "initializeSchemas": [1, 2, 3], "normalizeSchemas": [2, 3]}
        value = json.loads(self.catalog.read_text())
        value.update(profileSchema=3, profileCapabilities={**reader, "writeSchema": 3})
        value["classifications"]["personal"] = {"label": "Personal"}
        value["roles"]["family"] = {"label": "Family", "order": 70, "classification": "personal"}
        self.catalog.write_text(json.dumps(value))
        return reader

    def test_current_catalog_selects_schema_three_with_a_capable_reader(self):
        reader = self.current_catalog()
        for write_schema in (2, 3):
            with self.subTest(helper_write_schema=write_schema):
                result, events = self.run_login(LOGIN_CAPABILITIES=json.dumps({**reader, "writeSchema": write_schema}),
                                                LOGIN_ROLES="developer,family")
                self.assertEqual(result.returncode, 0, result.stderr)
                generated = json.loads(self.selections(events)[0][-1])
                self.assertEqual(generated, {"schema": 3, "foundation": "bluefin", "hardware": "generic-x86_64",
                                            "roles": ["developer", "family"], "packages": [], "capabilities": [], "identity": {}})
                dialog = next(event for event in events if "--list" in event)
                self.assertIn("Personal", dialog)

    def test_current_writer_rejects_an_incapable_helper_before_selection(self):
        self.current_catalog()
        result, events = self.run_login()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.selections(events), [])
        self.assertFalse(any("--list" in event for event in events))

    def test_declared_profile_schema_must_match_selected_writer(self):
        reader = self.current_catalog()
        value = json.loads(self.catalog.read_text())
        value["profileSchema"] = 2
        self.catalog.write_text(json.dumps(value))
        result, events = self.run_login(LOGIN_CAPABILITIES=json.dumps(reader))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("--list" in event for event in events))

    def test_current_catalog_does_not_override_saved_profile_precedence(self):
        self.current_catalog()
        self.saved.write_text('{"schema":2,"roles":["it"]}')
        result, events = self.run_login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.selections(events)[0][2], str(self.saved))
        self.assertFalse(any("--list" in event for event in events))

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


class UpdateSequence(unittest.TestCase):
    """Run real Just; substitute only host paths and external update commands."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.temporary = self.root / "temporary"
        self.temporary.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.log = self.root / "events.jsonl"
        self.upstream = self.root / "update.just"
        self.wrapper = self.root / "custom.just"
        self.hook = ROOT / "files/system/usr/libexec/finite/lib/update-shell-env"
        self.policy = self.root / "rpm-ostreed.conf"
        self.policy.write_text("LockLayering=false\n")
        config = self.root / "config/home-manager"
        config.mkdir(parents=True)
        self.lock = config / "flake.lock"
        self.lock.write_text(json.dumps({"root": "root", "nodes": {"root": {"inputs": {"foundation": "foundation"}}}}))
        for name in ("systemctl", "rpm-ostree", "sudo", "flatpak", "brew", "finite-home-update"):
            command = self.bin / name
            command.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with Path(os.environ["UPDATE_LOG"]).open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\\n")
if name == "systemctl":
    sys.exit(0 if args[0] == "cat" or os.environ.get("UPDATE_BUSY") == "true" else 1)
if name == "flatpak" and args == ["remotes"]:
    for scope in os.environ.get("UPDATE_REMOTES", "system,user").split(","):
        if scope: print("flathub " + scope)
    sys.exit(int(os.environ.get("UPDATE_REMOTES_STATUS", "0")))
stage = ("os" if name in ("rpm-ostree", "sudo") else
         "user-flatpak" if name == "flatpak" and "--user" in args else
         "system-flatpak" if name == "flatpak" else
         "foundation" if name == "finite-home-update" else name)
if os.environ.get("UPDATE_FAIL") == stage:
    print("injected " + stage + " failure", file=sys.stderr)
    sys.exit(17)
''')
            command.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("BASH_ENV", "SHELLOPTS", "BASHOPTS")}
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ["PATH"], UPDATE_LOG=str(self.log),
                        XDG_CONFIG_HOME=str(self.root / "config"), TMPDIR=str(self.temporary),
                        XDG_RUNTIME_DIR=str(self.runtime))
        self.install_upstream((ROOT / "tests/home/fixtures/bluefin-update.just").read_text())
        self.install_wrapper()

    def install_upstream(self, contents):
        self.upstream.write_text(contents.replace("/usr/bin/bash", shutil.which("bash"))
                                 .replace("/etc/rpm-ostreed.conf", str(self.policy))
                                 .replace("/var/home/linuxbrew/.linuxbrew/bin/brew", str(self.bin / "brew")))

    def install_wrapper(self, *, uid="1000", hook=None):
        # EUID is readonly in Bash. Only this test copy substitutes its value;
        # the installed recipe has no test switch or root-check bypass.
        contents = (ROOT / "files/system/usr/share/ublue-os/just/60-custom.just").read_text()
        self.wrapper.write_text(contents.replace("#!/usr/bin/env bash", "#!" + shutil.which("bash"))
                                .replace('"$EUID"', '"' + uid + '"')
                                .replace("/usr/libexec/finite/lib/update-shell-env", str(hook or self.hook))
                                .replace("/usr/share/ublue-os/just/update.just", str(self.upstream)))

    def invoke(self, **changes):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(["just", "--justfile", str(self.wrapper), "update"],
                                env={**self.env, **changes}, text=True, capture_output=True)
        events = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        self.assertEqual(list(self.temporary.iterdir()), [], "Update guard leaked temporary state")
        actions = []
        for name, *args in events:
            if name in ("rpm-ostree", "sudo"):
                actions.append("os")
            elif name == "flatpak" and args[0] == "update":
                actions.append("user-flatpak" if "--user" in args else "system-flatpak")
            elif name in ("brew", "finite-home-update"):
                actions.append("foundation" if name == "finite-home-update" else name)
        return result, events, actions

    def test_order_on_both_os_update_paths(self):
        for policy, os_command in (("LockLayering=false", "rpm-ostree"), ("LockLayering=true", "sudo")):
            with self.subTest(policy=policy):
                self.policy.write_text(policy + "\n")
                result, events, actions = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(actions, ["os", "system-flatpak", "user-flatpak", "brew", "foundation"])
                self.assertTrue(any(event[0] == os_command for event in events))

    def test_each_failed_update_blocks_all_later_stages(self):
        stages = ["os", "system-flatpak", "user-flatpak", "brew", "foundation"]
        for policy in ("LockLayering=false", "LockLayering=true"):
            self.policy.write_text(policy + "\n")
            for index, stage in enumerate(stages):
                with self.subTest(policy=policy, stage=stage):
                    result, _, actions = self.invoke(UPDATE_FAIL=stage)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(actions, stages[:index + 1])
                    self.assertIn("injected " + stage + " failure", result.stderr)

    def test_intentional_brew_and_flatpak_skips_reach_foundation(self):
        (self.bin / "brew").unlink()
        result, _, actions = self.invoke(UPDATE_REMOTES="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["os", "foundation"])

    def test_upstream_conditional_pipeline_semantics_are_preserved(self):
        # Upstream tests grep's result, not the producer's status. Enabling
        # pipefail here would silently skip both updates despite valid rows.
        result, _, actions = self.invoke(UPDATE_REMOTES_STATUS="19")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["os", "system-flatpak", "user-flatpak", "brew", "foundation"])

    def test_busy_automatic_updater_blocks_foundation(self):
        result, _, actions = self.invoke(UPDATE_BUSY="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, [])

    def test_root_is_rejected_before_any_delegation(self):
        self.install_wrapper(uid="0")
        result, events, actions = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])
        self.assertEqual(actions, [])
        self.assertIn("desktop user", result.stderr)

    def test_missing_hook_is_rejected_before_any_delegation(self):
        self.install_wrapper(hook=self.root / "missing-hook")
        result, events, _ = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])
        self.assertIn("Missing Finite update shell hook", result.stderr)

    def test_upstream_without_bash_hook_never_reaches_foundation(self):
        self.upstream.write_text(f"update:\n    #!{sys.executable}\n    print('upstream completed')\n")
        result, _, actions = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actions, [])
        self.assertIn("did not run", result.stderr)

    def test_nested_bash_tool_receives_no_hook_or_strict_options(self):
        nested = self.bin / "nested-tool"
        report = self.root / "nested-report"
        nested.write_text(f"#!{shutil.which('bash')}\n" +
                          'printf "%s\\n" "$-" "${BASH_ENV-unset}" "${FINITE_UPDATE_SHELL_MARKER-unset}" "$SHELLOPTS" > "$UPDATE_REPORT"\n' +
                          'false\nprintf "continued\\n" >> "$UPDATE_REPORT"\n')
        nested.chmod(0o755)
        self.upstream.write_text(self.upstream.read_text().replace("    # rpm-ostree used", "    nested-tool\n    # rpm-ostree used"))
        result, _, actions = self.invoke(UPDATE_REPORT=str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        flags, startup, marker, shell_options, continued = report.read_text().splitlines()
        self.assertNotIn("e", flags)
        self.assertNotIn("u", flags)
        self.assertNotIn("pipefail", shell_options.split(":"))
        self.assertEqual((startup, marker, continued), ("unset", "unset", "continued"))
        self.assertEqual(actions[-1], "foundation")

    def test_legacy_consumer_skips_only_foundation(self):
        self.lock.write_text(json.dumps({"root": "root", "nodes": {"root": {"inputs": {}}}}))
        result, _, actions = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(actions, ["os", "system-flatpak", "user-flatpak", "brew"])
        self.assertIn("finite-home-migrate", result.stdout)


if __name__ == "__main__":
    unittest.main()
