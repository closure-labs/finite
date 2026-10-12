#!/usr/bin/env python3
"""Hosted diagnostic evidence only; never grants vulnerability clearance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone

IMAGE = re.compile(r"ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}")
PATHS = (
    "/usr/bin/buildah", "/usr/bin/containerd", "/usr/bin/containerd-shim-runc-v2",
    "/usr/bin/containerd-stress", "/usr/bin/cosign", "/usr/bin/ctr",
    "/usr/bin/glow", "/usr/bin/gum", "/usr/bin/ipp-usb", "/usr/bin/podman",
    "/usr/bin/rclone", "/usr/bin/restic", "/usr/bin/runc", "/usr/bin/skopeo",
    "/usr/bin/tailscale", "/usr/bin/tailscaled", "/usr/sbin/tailscaled",
    "/usr/bin/toolbox", "/usr/bin/uupd", "/usr/bin/yq",
    "/usr/libexec/podman/quadlet", "/usr/libexec/podman/rootlessport",
)
MAX_JSON = 32 * 1024 * 1024
SCANNER_GO_VERSION = re.compile(r"^go[0-9]+\.[0-9]+(?:\.[0-9]+|(?:(?:beta|rc|-pre)[0-9]+))?$")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def messages(path):
    if path.stat().st_size > MAX_JSON:
        raise ValueError("govulncheck JSON exceeds diagnostic limit")
    data = path.read_text()
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(data):
        if data[offset].isspace():
            offset += 1
            continue
        message, offset = decoder.raw_decode(data, offset)
        if not isinstance(message, dict) or len(message) != 1:
            raise ValueError("invalid govulncheck message")
        yield message


def summarize(path):
    """Public streaming JSON protocol; do not parse private extract-mode blobs."""
    configs, findings, advisories, sboms = [], [], {}, []
    for message in messages(path):
        if not configs and "config" not in message:
            raise ValueError("govulncheck configuration must be first")
        if not isinstance(next(iter(message.values())), dict):
            raise ValueError("govulncheck payload must be an object")
        if "config" in message:
            configs.append(message["config"])
        elif "osv" in message:
            osv = message["osv"]
            advisories[osv["id"]] = {"aliases": osv.get("aliases", []),
                                     "modified": osv.get("modified")}
        elif "finding" in message:
            finding = message["finding"]
            trace = finding.get("trace")
            if (not isinstance(finding.get("osv"), str) or not isinstance(trace, list)
                    or len(trace) != 1 or not isinstance(trace[0], dict)
                    or not isinstance(trace[0].get("module"), str) or not trace[0]["module"]):
                raise ValueError("invalid govulncheck finding")
            findings.append(finding)
        elif "SBOM" in message:
            sboms.append(message["SBOM"])
        elif "progress" not in message:
            raise ValueError("unknown govulncheck message")
    if len(configs) != 1:
        raise ValueError("missing or duplicate govulncheck configuration")
    config = configs[0]
    if config.get("protocol_version") != "v1.0.0" or config.get("scan_mode") != "binary":
        raise ValueError("unreviewed govulncheck protocol or scan mode")
    if config.get("scanner_version") != "v1.9.0":
        raise ValueError("unreviewed govulncheck version")
    if config.get("scanner_name") != "govulncheck" or config.get("scan_level") != "symbol":
        raise ValueError("unreviewed scanner or scan level")
    if config.get("db") != "https://vuln.go.dev" or not config.get("db_last_modified"):
        raise ValueError("missing official database provenance")
    modified = datetime.fromisoformat(config["db_last_modified"].replace("Z", "+00:00"))
    if modified.tzinfo is None:
        raise ValueError("database timestamp must have timezone")
    if len(sboms) != 1 or not sboms[0].get("go_version"):
        raise ValueError("missing binary compiler inventory")
    if any(f["osv"] not in advisories for f in findings):
        raise ValueError("finding has no retained advisory")
    pairs = {(f["osv"], frame.get("module"), frame.get("version"))
             for f in findings for frame in f["trace"]}
    return {"config": config, "scannerInventory": sboms[0],
            "advisories": advisories, "findings": findings, "componentAdvisoryCount": len(pairs),
            "findingCount": len(findings), "absenceNotProof": True,
            "coverage": "diagnostic-only; silent module fallback and incomplete provenance remain possible"}


def bounded(command, output, log):
    unit = "finite-go-evidence-" + os.urandom(6).hex()
    args = ["sudo", "systemd-run", "--unit=" + unit, "--wait", "--pipe",
            "--service-type=exec", "--property=MemoryMax=2048M",
            "--property=MemorySwapMax=0", "--property=OOMPolicy=stop",
            "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=",
            "--property=ProtectControlGroups=yes", "--property=RuntimeMaxSec=240",
            "--property=User=" + str(os.getuid()),
            "--property=Group=" + str(os.getgid()),
            "--setenv=PATH=" + os.environ["PATH"],
            "--setenv=HOME=" + os.environ["HOME"], "--setenv=GOMEMLIMIT=1536MiB",
            "--setenv=GOMAXPROCS=2",
            *command]
    try:
        with output.open("wb") as out, log.open("wb") as err:
            result = subprocess.run(args, stdout=out, stderr=err, timeout=270, check=False)
        return result.returncode
    finally:
        for operation in ("stop", "reset-failed"):
            try:
                subprocess.run(["sudo", "systemctl", operation, unit + ".service"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False, timeout=15)
            except subprocess.SubprocessError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--inspector", type=Path, required=True)
    parser.add_argument("--govulncheck", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not IMAGE.fullmatch(args.image):
        parser.error("hosted runner and immutable Finite image required")
    if args.directory.exists() or args.directory.is_symlink():
        parser.error("refusing stale evidence directory")
    args.directory.mkdir(parents=True)
    report = {"schema": 1, "image": args.image, "revision": os.environ.get("GITHUB_SHA"),
              "observedAt": datetime.now(timezone.utc).isoformat(), "status": "in-progress",
              "scope": "selected live executables; excludes historical OSTree objects",
              "vulnerabilityClearance": "not-assessed", "releaseEligibility": "not-assessed",
              "inspectorSha256": digest(args.inspector),
              "govulncheckSha256": digest(args.govulncheck), "requestedPaths": list(PATHS),
              "binaries": []}
    deadline = time.monotonic() + 40 * 60

    def checkpoint():
        temporary = args.directory / "summary.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(args.directory / "summary.json")

    checkpoint()
    container = "finite-go-evidence-" + os.urandom(6).hex()
    try:
        with (args.directory / "signature.json").open("wb") as out:
            subprocess.run(["cosign", "verify", "--new-bundle-format=false", "--key", "cosign.pub",
                            args.image], stdout=out, check=True, timeout=180)
        report["signatureSha256"] = digest(args.directory / "signature.json")
        checkpoint()
        subprocess.run(["docker", "create", "--platform=linux/amd64", "--name", container, "--entrypoint", "/never-execute",
                        args.image], check=True, timeout=900, stdout=subprocess.DEVNULL)
        selected = subprocess.check_output(["docker", "inspect", "--type=container",
                                           "--format={{.Image}}", container], timeout=30).decode().strip()
        image_metadata = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", selected], timeout=30))[0]
        report["selectedImage"] = {"configDigest": image_metadata["Id"],
                                   "os": image_metadata["Os"], "arch": image_metadata["Architecture"],
                                   "repoDigests": image_metadata.get("RepoDigests", [])}
        if image_metadata["Os"] != "linux" or image_metadata["Architecture"] != "amd64":
            raise ValueError("selected image is not Linux amd64")
        checkpoint()
        with tempfile.TemporaryDirectory() as temp:
            for index, source in enumerate(PATHS):
                binary = Path(temp) / "binary"
                binary.unlink(missing_ok=True)
                entry = {"path": source, "status": "unknown"}
                report["binaries"].append(entry)
                checkpoint()
                if time.monotonic() > deadline - 450:
                    entry["error"] = "collector time budget exhausted; path not inspected"
                    checkpoint()
                    continue
                prefix = args.directory / str(index)
                copy = subprocess.run(["docker", "cp", "--follow-link", container + ":" + source,
                                       str(binary)], capture_output=True, timeout=90, check=False)
                if copy.returncode:
                    entry["error"] = "copy failed; missing path is not proof of remediation"
                    Path(str(prefix) + ".copy.log").write_bytes(copy.stderr)
                    checkpoint()
                    continue
                metadata = Path(str(prefix) + ".metadata.json")
                code = bounded([str(args.inspector.resolve()), str(binary)], metadata,
                               Path(str(prefix) + ".metadata.log"))
                entry["metadataExitCode"] = code
                entry["binarySha256"] = digest(binary)
                entry["metadataSha256"] = digest(metadata)
                checkpoint()
                if metadata.stat().st_size > MAX_JSON:
                    raise ValueError("binary metadata exceeds diagnostic limit")
                parsed = json.loads(metadata.read_text())
                if parsed.get("sha256") != entry["binarySha256"]:
                    raise ValueError("binary metadata hash mismatch")
                if code:
                    entry["metadataError"] = parsed.get("error", "binary metadata extraction failed")
                for key in ("os", "arch", "goVersion", "moduleCoverage", "modules",
                            "symbolCount", "symbolCoverage", "absenceNotProof"):
                    entry[key] = parsed[key]
                entry["stdlibCoverage"] = ("version-recognized; binary-symbol-coverage-not-proven"
                    if SCANNER_GO_VERSION.fullmatch(parsed["goVersion"])
                    else "unknown-compiler-version-format")
                checkpoint()
                if parsed.get("os") != "linux" or parsed.get("arch") != "amd64" or not parsed.get("goVersion"):
                    entry["error"] = "Go binary platform/compiler evidence unavailable"
                    checkpoint()
                    continue
                raw = Path(str(prefix) + ".govulncheck.json")
                code = bounded([str(args.govulncheck.resolve()), "-json", "-mode=binary", str(binary)],
                               raw, Path(str(prefix) + ".govulncheck.log"))
                entry["govulncheckExitCode"] = code
                entry["govulncheckSha256"] = digest(raw)
                checkpoint()
                if code:
                    entry["error"] = "govulncheck failed; findings may be incomplete"
                    checkpoint()
                    continue
                try:
                    analysis = summarize(raw)
                    if analysis["scannerInventory"]["go_version"] != parsed["goVersion"]:
                        raise ValueError("binary compiler version mismatch")
                    entry.update(analysis)
                    entry["status"] = "diagnostic-complete"
                except (ValueError, KeyError, TypeError) as error:
                    entry["error"] = str(error)
                checkpoint()
        report["status"] = "diagnostic-complete-with-unknowns" if any(
            x["status"] == "unknown" or x.get("symbolCoverage") == "unknown"
            or x.get("moduleCoverage") == "unknown"
            or x.get("stdlibCoverage") == "unknown-compiler-version-format"
            for x in report["binaries"]) else "diagnostic-complete"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "error"
        report["error"] = str(error)
    finally:
        try:
            subprocess.run(["docker", "rm", "--force", container], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except subprocess.SubprocessError as error:
            report["cleanupError"] = str(error)
        checkpoint()
    return 2 if report["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
