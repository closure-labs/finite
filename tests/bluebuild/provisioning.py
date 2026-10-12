#!/usr/bin/env python3
"""Default desktop rejects NoCloud input; guest assertions fail on each breach."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Provisioning(unittest.TestCase):
    def test_image_defaults(self):
        self.assertTrue((ROOT / "files/system/etc/cloud/cloud-init.disabled").is_file())
        config = (ROOT / "files/system/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg").read_text()
        self.assertIn("datasource_list: [None]", config)
        self.assertNotIn("cloud-init.target", (ROOT / "recipes/shared/base.yml").read_text())
        image_check = (ROOT / "scripts/bluebuild/verify-image.sh").read_text()
        self.assertIn("test -f /etc/cloud/cloud-init.disabled", image_check)

    def test_guest_rejects_breaches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cloud = root / "cloud"
            cloud.mkdir()
            marker = cloud / "cloud-init.disabled"
            marker.touch()
            config_dir = cloud / "cloud.cfg.d"
            config_dir.mkdir()
            shutil.copy2(ROOT / "files/system/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg", config_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            commands = {
                "blkid": 'test "${MEDIA_PRESENT:-yes}" = yes && echo /dev/sr0',
                "getenforce": 'echo "${ENFORCING:-Enforcing}"',
                "semodule": 'test "${MODULE_PRESENT:-yes}" = yes && echo "nix 1.0"',
                "systemctl": 'if [[ $1 == show ]]; then echo "${CLOUD_STATE:-inactive}"; else test "${POLICY_ACTIVE:-yes}" = yes; fi',
            }
            for name, body in commands.items():
                target = bin_dir / name
                target.write_text("#!" + shutil.which("bash") + "\nset -euo pipefail\n" + body + "\n")
                target.chmod(0o755)
            script = (ROOT / "scripts/bluebuild/check-vm-security.sh").read_text()
            script = script.replace("/etc/cloud", str(cloud)).replace("/var/lib/finite-nocloud-", str(root / "probe-"))
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])

            def run(**overrides):
                result = subprocess.run(["bash", "-c", script], env=dict(env, **overrides), capture_output=True)
                self.last_error = result.stderr.decode()
                return result.returncode

            self.assertEqual(run(), 0, self.last_error)
            for overrides in ({"MEDIA_PRESENT": "no"}, {"ENFORCING": "Permissive"},
                              {"CLOUD_STATE": "active"}, {"MODULE_PRESENT": "no"}, {"POLICY_ACTIVE": "no"}):
                with self.subTest(overrides=overrides):
                    self.assertNotEqual(run(**overrides), 0)
            marker.unlink()
            self.assertNotEqual(run(), 0)
            marker.touch()
            for name in ("write", "command"):
                probe = root / f"probe-{name}-executed"
                probe.touch()
                self.assertNotEqual(run(), 0)
                probe.unlink()

    def test_real_yaml_parser_requires_only_none_datasource(self):
        # Run each production assertion against the real Go yq and jq. Stubbing
        # yq previously hid its non-structural array equality behavior.
        original = ROOT / "files/system/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg"
        cases = [
            (original.read_text(), True),
            ('datasource_list: ["None"]\n', True),
            ('datasource_list:\n  - None\n', True),
            ('datasource_list: [NoCloud]\n', False),
            ('datasource_list: [None, NoCloud]\n', False),
            ('datasource_list: [None, None]\n', False),
            ('datasource_list: []\n', False),
            ('datasource_list: null\n', False),
            ('datasource_list: None\n', False),
            ('datasource_list: {0: None}\n', False),
            ('users: []\n', False),
            ('', False),
            ('datasource_list: [\n', False),
            ('datasource_list: [NoCloud]\n---\ndatasource_list: [None]\n', False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            for name in ("verify-image.sh", "check-vm-security.sh"):
                lines = (ROOT / "scripts/bluebuild" / name).read_text().splitlines()
                checks = [line for line in lines if line.startswith("yq ") and "90-finite-nocloud.cfg" in line]
                self.assertEqual(len(checks), 1)
                command = checks[0].replace("/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg", str(config))
                for content, accepted in cases:
                    with self.subTest(script=name, content=content):
                        config.write_text(content)
                        result = subprocess.run(["bash", "-o", "pipefail", "-c", command], capture_output=True, text=True)
                        self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_candidate_probe_wiring(self):
        script = (ROOT / "scripts/bluebuild/vm-acceptance.sh").read_text()
        self.assertIn("-V cidata", script)
        self.assertIn("finite-nocloud-write-executed", script)
        self.assertIn("finite-nocloud-command-executed", script)
        self.assertIn("$phase == updated || ($phase == first-boot && $phase_name != upgrade)", script)
        self.assertIn('"${provisioning_args[@]}" -boot c', script)
        self.assertIn("<scripts/bluebuild/check-vm-security.sh", script)


if __name__ == "__main__":
    unittest.main()
