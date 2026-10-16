#!/usr/bin/env python3
"""Propose an immutable published Foundation release; never follow main."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def capture(command):
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout


def main():
    root = Path(os.environ.get("FINITE_SOURCE_ROOT", Path.cwd()))
    current = json.loads((root / "sources/foundation.json").read_text())
    pages = json.loads(capture(["gh", "api", "--paginate", "--slurp", "repos/closure-labs/foundation/releases?per_page=100"]))
    releases = []
    for release in (item for page in pages for item in page):
        tag = release.get("tag_name", "")
        if not release.get("draft") and not release.get("prerelease") and release.get("published_at") and re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
            releases.append((tuple(map(int, tag[1:].split("."))), tag))
    tag = max(releases)[1] if releases else None
    changed = tag is not None and tuple(map(int, tag[1:].split("."))) > tuple(map(int, current["version"].split(".")))
    if changed:
        resolved = json.loads(capture(["nix", "flake", "metadata", "--json", "github:closure-labs/foundation/" + tag]))
        rev = resolved["locked"]["rev"]
        expression = 'let f = builtins.getFlake "github:closure-labs/foundation/' + rev + '"; in (builtins.fromJSON (builtins.readFile (f.outPath + "/foundation.json"))) // { narHash = f.narHash; rev = f.rev; }'
        metadata = json.loads(capture(["nix", "eval", "--json", "--expr", expression]))
        if metadata.get("compatibility") != 1 or metadata.get("schema") != 1 or metadata["version"] != tag[1:]:
            raise ValueError("Foundation release metadata or compatibility is unsupported")
        path = root / "flake.nix"
        before = path.read_text()
        after, count = re.subn(r'foundation.url = "github:closure-labs/foundation/[a-f0-9]{40}";', f'foundation.url = "github:closure-labs/foundation/{rev}";', before)
        if count != 1:
            raise ValueError("Expected exactly one immutable Foundation input")
        path.write_text(after)
        try:
            subprocess.run(["nix", "flake", "update", "foundation"], cwd=root, check=True)
        except BaseException:
            path.write_text(before)
            raise
        current = {**metadata, "rev": rev}
        (root / "sources/foundation.json").write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    output = f"changed={str(changed).lower()}\nrelease={current['version']}\n"
    if len(sys.argv) > 1:
        with Path(sys.argv[1]).open("a") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
