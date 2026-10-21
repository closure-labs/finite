"""Exercise packaged seed writers and the fixed schema-3 pure validation boundary."""
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Path(os.environ["FINITE_HOME_CATALOG_PATH"])
SOURCE = Path(os.environ["FINITE_TEST_FOUNDATION_SOURCE"])
COMMAND = os.environ["FINITE_TEST_CLOUD_INIT_COMMAND"]
SCHEMA = json.loads(CATALOG.read_text()).get("profileCapabilities", {}).get("writeSchema", 2)


def yaml_json(contents):
    return json.loads(subprocess.run(["yq", "-o=json", "."], input=contents, text=True,
                                     capture_output=True, check=True).stdout)


class SeedFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "seed"

    def arguments(self, *selections):
        return ["--foundation", "bluefin", "--user", "seed-target", "--output", str(self.output), *selections]

    def invoke(self, *selections):
        return subprocess.run([COMMAND, *self.arguments(*selections)], text=True, capture_output=True)


class SeedGeneration(SeedFixture):
    def test_default_profile_uses_the_catalog_writer_and_target_identity(self):
        result = self.invoke("--hardware", "generic-x86_64", "--roles", "it,developer", "--packages", "uv,jj")
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = yaml_json((self.output / "profile.yaml").read_text())
        self.assertEqual(profile["schema"], SCHEMA)
        self.assertEqual(profile["roles"], ["developer", "it"])
        self.assertEqual(profile["packages"], ["jj", "uv"])
        self.assertEqual(profile["identity"], {"username": "seed-target", "homeDirectory": "/var/home/seed-target"})
        if SCHEMA == 3:
            self.assertEqual(profile["capabilities"], [])
            self.assertEqual(profile["host"]["formFactor"], "generic")

    def test_invalid_selections_and_identity_leave_output_absent(self):
        for selection in (("--roles", "developer,developer"), ("--roles", "unknown"),
                          ("--packages", "jj,jj"), ("--user", "../escape")):
            with self.subTest(selection=selection):
                result = self.invoke("--hardware", "generic-x86_64", *selection)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_text("preserve")
        result = self.invoke("--hardware", "generic-x86_64")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_new_options_are_explicitly_rejected_by_the_schema_two_writer(self):
        if SCHEMA == 3:
            result = self.invoke("--cpu", "amd", "--form-factor", "desktop", "--no-camera", "--capabilities", "")
            self.assertEqual(result.returncode, 0, result.stderr)
            value = yaml_json((self.output / "profile.yaml").read_text())
            self.assertEqual(value["host"]["cpu"], "amd")
            self.assertFalse(value["host"]["camera"])
        else:
            for selection in (("--capabilities", ""), ("--no-camera",), ("--cpu", "amd")):
                with self.subTest(selection=selection):
                    result = self.invoke("--hardware", "generic-x86_64", *selection)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("schema-3", result.stderr.lower())
                    self.assertFalse(self.output.exists())

    def test_iso_contains_matching_profile_and_cloud_init_metadata(self):
        result = self.invoke("--hardware", "dell-xps-9350-intel")
        self.assertEqual(result.returncode, 0, result.stderr)
        extracted = self.root / "extracted"
        subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(self.output / "seed.iso"),
                        "-extract", "/", str(extracted)], check=True, capture_output=True)
        for name in ("user-data", "meta-data"):
            self.assertEqual((extracted / name).read_bytes(), (self.output / name).read_bytes())
        user_data = (extracted / "user-data").read_text()
        self.assertTrue(user_data.startswith("#cloud-config\n"))
        parsed = yaml_json(user_data)
        self.assertFalse(parsed["ssh_pwauth"])
        entry = parsed["write_files"][0]
        self.assertEqual(entry["path"], "/etc/finite/home-profiles/seed-target.yaml")
        self.assertEqual(yaml_json(entry["content"]), yaml_json((self.output / "profile.yaml").read_text()))
        metadata = yaml_json((extracted / "meta-data").read_text())
        self.assertEqual(metadata["instance-id"], "finite-" + hashlib.sha256(user_data.encode()).hexdigest()[:16])
        self.assertIn("inert", result.stderr)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o644 for path in self.output.iterdir()))


@unittest.skipUnless(SCHEMA == 3, "Requires the current Foundation writer")
class CurrentSeedGeneration(SeedFixture):
    def test_mixed_roles_host_and_capabilities_match_actual_foundation_normalization(self):
        result = self.invoke("--roles", "creative,family,developer", "--capabilities", "recording,office",
                             "--form-factor", "desktop", "--cpu", "intel", "--gpus", "amd-discrete,intel-integrated")
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = yaml_json((self.output / "profile.yaml").read_text())
        submitted = {"schema": 3, "foundation": "bluefin", "roles": ["creative", "family", "developer"],
                     "capabilities": ["recording", "office"], "packages": [],
                     "identity": {"username": "seed-target", "homeDirectory": "/var/home/seed-target"}}
        host = {"formFactor": "desktop", "cpu": "intel", "gpus": ["amd-discrete", "intel-integrated"]}
        profile_file, host_file = self.root / "profile.json", self.root / "host.json"
        profile_file.write_text(json.dumps(submitted))
        host_file.write_text(json.dumps(host))
        expected = json.loads(subprocess.run(["nix-instantiate", "--store", "dummy://", "--eval", "--strict", "--json",
                    str(SOURCE / "lib/generate-profile.nix"), "--argstr", "profileFile", str(profile_file),
                    "--argstr", "hostFile", str(host_file)], check=True, text=True, capture_output=True).stdout)["profile"]
        self.assertEqual(actual, expected)
        self.assertEqual(actual["roles"], ["developer", "family", "creative"])
        self.assertEqual(actual["capabilities"], ["office", "recording"])
        self.assertEqual(actual["host"]["gpus"], ["intel-integrated", "amd-discrete"])

    def test_dell_device_overrides_and_invalid_host_declarations(self):
        result = self.invoke("--hardware", "dell-xps-9350-intel", "--no-camera", "--fingerprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = yaml_json((self.output / "profile.yaml").read_text())
        self.assertFalse(value["host"]["camera"])
        self.assertTrue(value["host"]["fingerprint"])
        for extra in (("--cpu", "amd"), ("--gpus", "intel-integrated,intel-integrated"),
                      ("--capabilities", "unknown"), ("--roles", "family,"),
                      ("--roles", '${builtins.abort "SEED_DATA_EXECUTED"}')):
            self.output = self.root / ("invalid-" + str(len(list(self.root.iterdir()))))
            result = self.invoke("--hardware", "dell-xps-9350-intel", *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.output.exists())
            self.assertNotIn("error: SEED_DATA_EXECUTED", result.stderr)

    def test_bad_catalog_or_missing_generator_never_downgrades(self):
        baseline = json.loads(CATALOG.read_text())
        selected = self.root / "catalog.json"
        for changes in ({"profileSchema": 2}, {"profileCapabilities": {"writeSchema": 4}}, {"profileCapabilities": None}):
            selected.write_text(json.dumps({**baseline, **changes}))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/home/seed.py"), str(SOURCE / "lib/generate-profile.nix"),
                                     str(selected), *self.arguments()], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(self.output.exists())
        result = subprocess.run([sys.executable, str(ROOT / "scripts/home/seed.py"), str(self.root / "missing-generator.nix"),
                                 str(CATALOG), *self.arguments()], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no bundled profile generator", result.stderr)
        self.assertFalse(self.output.exists())
        baseline["foundations"]["bluefin"]["hardware"] = ["generic-x86_64"]
        selected.write_text(json.dumps(baseline))
        result = subprocess.run([sys.executable, str(ROOT / "scripts/home/seed.py"), str(SOURCE / "lib/generate-profile.nix"),
                                 str(selected), *self.arguments("--hardware", "dell-xps-9350-intel")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("incompatible", result.stderr)
        self.assertFalse(self.output.exists())
        for field, name in (("roles", "developer"), ("packages", "jj"), ("capabilities", "office")):
            narrowed = json.loads(CATALOG.read_text())
            del narrowed[field][name]
            selected.write_text(json.dumps(narrowed))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/home/seed.py"), str(SOURCE / "lib/generate-profile.nix"),
                                     str(selected), *self.arguments("--" + field, name)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("outside the Finite image catalog", result.stderr)
            self.assertFalse(self.output.exists())

    def test_failed_publication_cleans_only_its_own_output_directory(self):
        spec = importlib.util.spec_from_file_location("finite_seed", ROOT / "scripts/home/seed.py")
        seed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seed)
        args = seed.parser().parse_args(self.arguments())
        copyfile, run = shutil.copyfile, seed.run

        def fail_copy(source, destination):
            if source.name == "meta-data":
                raise OSError("injected publication failure")
            return copyfile(source, destination)

        with patch.object(seed.shutil, "copyfile", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "injected publication failure"):
                seed.create(args, SOURCE / "lib/generate-profile.nix", CATALOG)
        self.assertFalse(self.output.exists())

        def concurrent_output(command, **kwargs):
            result = run(command, **kwargs)
            if command[0] == "xorriso":
                self.output.mkdir()
                (self.output / "sentinel").write_text("concurrent output")
            return result

        with patch.object(seed, "run", side_effect=concurrent_output):
            with self.assertRaises(FileExistsError):
                seed.create(args, SOURCE / "lib/generate-profile.nix", CATALOG)
        self.assertEqual((self.output / "sentinel").read_text(), "concurrent output")
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_failed_iso_generation_and_dangling_output_preserve_existing_paths(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        failing = fake_bin / "xorriso"
        failing.write_text("#!" + shutil.which("bash") + "\nexit 19\n")
        failing.chmod(0o755)
        env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
        result = subprocess.run([sys.executable, str(ROOT / "scripts/home/seed.py"), str(SOURCE / "lib/generate-profile.nix"),
                                 str(CATALOG), *self.arguments()], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.output.exists())
        self.output.symlink_to(self.root / "absent-target")
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.output.is_symlink())
        self.assertFalse((self.root / "absent-target").exists())


if __name__ == "__main__":
    unittest.main()
