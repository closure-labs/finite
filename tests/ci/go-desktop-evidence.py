import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

SOURCE = Path(__file__).resolve().parents[2] / "scripts/ci/go-desktop-evidence.py"
SPEC = importlib.util.spec_from_file_location("go_desktop_evidence", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StreamingEvidenceTests(unittest.TestCase):
    def test_scanner_compiler_formats_do_not_claim_experiment_coverage(self):
        for value in ("go1.26.8-X:nodwarf5", "go1.26rc2-X:nodwarf5", "devel go1.27"):
            self.assertIsNone(MODULE.SCANNER_GO_VERSION.fullmatch(value))
        for value in ("go1.26.8", "go1.26rc2", "go1.27.1"):
            self.assertIsNotNone(MODULE.SCANNER_GO_VERSION.fullmatch(value))

    def stream(self):
        return [{"config": {"protocol_version": "v1.0.0", "scan_mode": "binary",
                "scanner_version": "v1.9.0", "scanner_name": "govulncheck",
                "scan_level": "symbol", "db": "https://vuln.go.dev",
                "db_last_modified": "2026-10-12T00:00:00Z"}},
                {"SBOM": {"go_version": "go1.27.1", "modules": []}},
                {"osv": {"id": "GO-2026-6604", "aliases": ["CVE-fixture"]}},
                {"finding": {"osv": "GO-2026-6604", "trace": [{"module": "stdlib",
                  "version": "v1.27.1"}]}},
                {"finding": {"osv": "GO-2026-6604", "trace": [{"module": "stdlib",
                  "version": "v1.27.1", "package": "os", "function": "Open"}]}}]

    def parse(self, values):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.json"
            path.write_text("\n".join(json.dumps(x) for x in values))
            return MODULE.summarize(path)

    def test_multiple_levels_are_one_component_advisory(self):
        result = self.parse(self.stream())
        self.assertEqual(result["findingCount"], 2)
        self.assertEqual(result["componentAdvisoryCount"], 1)
        self.assertTrue(result["absenceNotProof"])
        self.assertNotIn("pass", result.values())

    def test_osv_presence_is_not_an_affected_version(self):
        result = self.parse(self.stream()[:3])
        self.assertEqual(result["componentAdvisoryCount"], 0)
        self.assertTrue(result["absenceNotProof"])

    def test_unknown_protocol_or_scanner_is_error(self):
        for key, value in (("protocol_version", "v2"), ("scanner_version", "devel"),
                           ("scan_mode", "source"), ("db", "https://example.org"),
                           ("scan_level", "module")):
            with self.subTest(key=key):
                values = self.stream()
                values[0]["config"][key] = value
                with self.assertRaises(ValueError):
                    self.parse(values)

    def test_missing_inventory_config_or_advisory_is_error(self):
        original = self.stream()
        for remove in (0, 1, 2):
            with self.assertRaises(ValueError):
                self.parse(original[:remove] + original[remove + 1:])

    def test_duplicate_config_and_unknown_message_are_error(self):
        for extra in (self.stream()[0], {"unexpected": {}}):
            with self.assertRaises(ValueError):
                self.parse(self.stream() + [extra])

    def test_truncated_stream_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.json"
            path.write_text(json.dumps(self.stream()[0]) + '\n{"finding":')
            with self.assertRaises(ValueError):
                MODULE.summarize(path)

    def test_malformed_payloads_and_empty_traces_are_error(self):
        for replacement in ({"config": []}, {"SBOM": []},
                            {"finding": {"osv": "GO-test", "trace": []}},
                            {"finding": {"osv": "GO-test", "trace": [None]}}):
            values = self.stream()
            if "config" in replacement:
                values[0] = replacement
            else:
                values.append(replacement)
            with self.assertRaises(ValueError):
                self.parse(values)


    def test_invalid_database_timestamp_is_error(self):
        for timestamp in ("yesterday", "2026-10-12T00:00:00"):
            values = self.stream()
            values[0]["config"]["db_last_modified"] = timestamp
            with self.assertRaises(ValueError):
                self.parse(values)


class CollectorFailureTests(unittest.TestCase):
    def invoke(self, directory):
        root = Path(directory)
        for name in ("inspector", "scanner"):
            (root / name).write_bytes(b"fixture")
        return ["collector", "ghcr.io/closure-labs/finite@sha256:" + "a" * 64,
                str(root / "evidence"), "--inspector", str(root / "inspector"),
                "--govulncheck", str(root / "scanner")]

    def test_authentication_failure_retains_summary_before_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = self.invoke(directory)
            summary = Path(directory) / "evidence/summary.json"
            def command(args, **kwargs):
                if args[0] == "cosign":
                    self.assertEqual(json.loads(summary.read_text())["status"], "in-progress")
                    raise subprocess.CalledProcessError(1, args)
                self.assertEqual(args[:3], ["docker", "rm", "--force"])
                return subprocess.CompletedProcess(args, 0)
            with patch("sys.argv", argv), patch.dict("os.environ", GITHUB_ACTIONS="true"), \
                    patch.object(MODULE.subprocess, "run", side_effect=command):
                self.assertEqual(MODULE.main(), 2)
            result = json.loads(summary.read_text())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["binaries"], [])
            self.assertEqual(result["vulnerabilityClearance"], "not-assessed")

    def test_deadline_retains_every_uninspected_path_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = self.invoke(directory)
            image = json.dumps([{"Id": "sha256:" + "b" * 64, "Os": "linux",
                                 "Architecture": "amd64", "RepoDigests": []}]).encode()
            with patch("sys.argv", argv), patch.dict("os.environ", GITHUB_ACTIONS="true"), \
                    patch.object(MODULE.time, "monotonic", side_effect=[0] + [2401] * len(MODULE.PATHS)), \
                    patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                    patch.object(MODULE.subprocess, "check_output", side_effect=[b"sha256:fixture", image]), \
                    patch.object(MODULE, "bounded") as bounded:
                self.assertEqual(MODULE.main(), 0)
                bounded.assert_not_called()
            result = json.loads((Path(directory) / "evidence/summary.json").read_text())
            self.assertEqual(result["status"], "diagnostic-complete-with-unknowns")
            self.assertEqual([x["path"] for x in result["binaries"]], list(MODULE.PATHS))
            self.assertTrue(all(x["status"] == "unknown" for x in result["binaries"]))
            self.assertEqual(result["releaseEligibility"], "not-assessed")

if __name__ == "__main__":
    unittest.main()
