#!/usr/bin/env python3
"""Propose an immutable, CI-qualified Foundation main commit, never deploy it."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from github_api import get_json

REPOSITORY = "closure-labs/foundation"
WORKFLOW = ".github/workflows/check.yml"


def capture(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True,
                          timeout=600, **kwargs).stdout


def api(path):
    return get_json("repos/" + REPOSITORY + "/" + path)


def main_revision():
    value = api("git/ref/heads/main")
    obj = value.get("object", {})
    if value.get("ref") != "refs/heads/main" or obj.get("type") != "commit" or not re.fullmatch(r"[a-f0-9]{40}", obj.get("sha", "")):
        raise ValueError("Foundation main is not an immutable commit")
    return obj["sha"]


def qualification(rev):
    """No stale-success fallback: the latest canonical run/attempt must pass."""
    workflow = api("actions/workflows/check.yml")
    if (type(workflow.get("id")) is not int or workflow["id"] <= 0
            or workflow.get("path") != WORKFLOW or workflow.get("state") != "active"):
        raise ValueError("Foundation CI workflow identity differs")
    result = api(f"actions/workflows/{workflow['id']}/runs?branch=main&event=push&head_sha={rev}&per_page=100")
    runs = result.get("workflow_runs")
    if not isinstance(runs, list) or type(result.get("total_count")) is not int or result["total_count"] != len(runs):
        raise ValueError("Foundation CI run inventory is incomplete")
    if not runs:
        return None
    for run in runs:
        if type(run.get("run_number")) is not int or type(run.get("id")) is not int:
            raise ValueError("Foundation CI run identity is malformed")
    selected = max(runs, key=lambda run: (run["run_number"], run["id"]))
    run = api(f"actions/runs/{selected['id']}")
    if (run.get("id") != selected["id"] or run.get("workflow_id") != workflow["id"]
            or run.get("path") != WORKFLOW or run.get("head_sha") != rev
            or run.get("head_branch") != "main" or run.get("event") != "push"
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0):
        raise ValueError("Foundation CI run is not the canonical main push")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return None
    jobs = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    if not isinstance(jobs.get("jobs"), list) or jobs.get("total_count") != len(jobs["jobs"]):
        raise ValueError("Foundation CI job inventory is incomplete")
    gates = [job for job in jobs["jobs"] if job.get("name") == "CI gate"]
    if (len(gates) != 1 or gates[0].get("status") != "completed"
            or gates[0].get("conclusion") != "success" or gates[0].get("head_sha") != rev):
        raise ValueError("Foundation CI gate did not qualify this revision")
    # Reruns can begin while attempt-specific jobs are fetched. Never certify
    # an old attempt using a run snapshot from before that read.
    if api(f"actions/runs/{run['id']}") != run:
        return None
    return {"workflow": WORKFLOW, "runId": run["id"], "runAttempt": run["run_attempt"],
            "url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}"}


def input_closure(lock, root=None):
    """Compare dependency meaning, not Nix's incidental node suffixes."""
    nodes = lock["nodes"]

    def resolve(ref):
        if isinstance(ref, list):
            node = lock["root"]
            for part in ref:
                node = resolve(nodes[node]["inputs"][part])
            return node
        return ref

    def tree(ref, parents=()):
        name = resolve(ref)
        if name in parents:
            return {"cycle": parents.index(name)}
        node = nodes[name]
        return {**{key: value for key, value in node.items() if key != "inputs"},
                "inputs": {key: tree(value, (*parents, name))
                           for key, value in node.get("inputs", {}).items()}}

    return {name: tree(ref) for name, ref in nodes[root or lock["root"]].get("inputs", {}).items()}


def unrelated_inputs(lock):
    return {name: value for name, value in input_closure(lock).items() if name != "foundation"}


def update(root, rev, evidence):
    resolved = json.loads(capture(["nix", "flake", "metadata", "--no-update-lock-file", "--json", "github:" + REPOSITORY + "/" + rev]))
    locked = resolved["locked"]
    supplied_hash = locked.get("narHash")
    if (locked.get("type") != "github" or locked.get("owner") != "closure-labs"
            or locked.get("repo") != "foundation" or locked.get("rev") != rev
            or ("narHash" in locked and (not isinstance(supplied_hash, str)
                or not re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", supplied_hash)))):
        raise ValueError("Foundation resolution differs from qualified source")
    expression = ('let f = builtins.getFlake "github:' + REPOSITORY + '/' + rev
                  + '"; in { metadata = (builtins.fromJSON (builtins.readFile (f.outPath + "/foundation.json")))'
                  + ' // { narHash = f.narHash; rev = f.rev; }; lock = builtins.fromJSON (builtins.readFile (f.outPath + "/flake.lock")); }')
    source = json.loads(capture(["nix", "eval", "--json", "--expr", expression]))
    metadata = source["metadata"]
    if (type(metadata.get("schema")) is not int or metadata["schema"] != 1
            or type(metadata.get("compatibility")) is not int or metadata["compatibility"] != 1
            or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", metadata.get("version", ""))
            or metadata.get("rev") != rev
            or not isinstance(metadata.get("narHash"), str)
            or not re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", metadata["narHash"])
            or (supplied_hash is not None and metadata["narHash"] != supplied_hash)):
        raise ValueError("Foundation source metadata or compatibility is unsupported")
    # Nix's lazy source metadata may omit narHash until the immutable source is
    # evaluated. Its evaluated content hash is authoritative; a supplied hash
    # still has to agree before any lock or consumer file can be changed.
    locked = {**locked, "narHash": metadata["narHash"]}
    current = json.loads((root / "sources/foundation.json").read_text())
    if tuple(map(int, metadata["version"].split("."))) < tuple(map(int, current["version"].split("."))):
        raise ValueError("Foundation milestone version would move backwards")
    comparison = api(f"compare/{current['rev']}...{rev}")
    if (comparison.get("status") != "ahead"
            or comparison.get("base_commit", {}).get("sha") != current["rev"]
            or comparison.get("merge_base_commit", {}).get("sha") != current["rev"]):
        raise ValueError("Foundation update is not a forward main descendant")
    paths = [root / name for name in ("flake.nix", "flake.lock", "sources/foundation.json")]
    before = {path: path.read_bytes() for path in paths}
    old_lock = json.loads(before[paths[1]])
    after, count = re.subn(r'foundation.url = "github:closure-labs/foundation/(?:[a-f0-9]{40}|main)";',
                          f'foundation.url = "github:{REPOSITORY}/main";', before[paths[0]].decode())
    if count != 1:
        raise ValueError("Expected exactly one Foundation input")
    # Revalidate before mutation; an advancing main or rerun waits for the next poll.
    if main_revision() != rev or qualification(rev) != evidence:
        raise ValueError("Foundation qualification changed while preparing the proposal")
    try:
        paths[0].write_text(after)
        capture(["nix", "flake", "update", "foundation"], cwd=root)
        new_lock = json.loads(paths[1].read_text())
        node = new_lock["nodes"][new_lock["nodes"][new_lock["root"]]["inputs"]["foundation"]]
        if node["locked"] != locked or node["original"] != {"type": "github", "owner": "closure-labs", "repo": "foundation", "ref": "main"}:
            raise ValueError("Updated lock differs from qualified immutable source")
        foundation_node = new_lock["nodes"][new_lock["root"]]["inputs"]["foundation"]
        if input_closure(new_lock, foundation_node) != input_closure(source["lock"]):
            raise ValueError("Updated Foundation dependency closure differs from its source lock")
        if unrelated_inputs(old_lock) != unrelated_inputs(new_lock):
            raise ValueError("Foundation update changed unrelated dependency closure")
        if main_revision() != rev or qualification(rev) != evidence:
            raise ValueError("Foundation qualification changed during the lock update")
        paths[2].write_text(json.dumps({**metadata, "upstreamCI": evidence}, indent=2, sort_keys=True) + "\n")
    except BaseException:
        for path, data in before.items():
            path.write_bytes(data)
        raise
    return metadata


def main():
    root = Path(os.environ.get("FINITE_SOURCE_ROOT", Path.cwd()))
    current = json.loads((root / "sources/foundation.json").read_text())
    rev = main_revision()
    changed = False
    status = "current"
    if rev != current["rev"]:
        evidence = qualification(rev)
        status = "waiting-for-main-ci"
        if evidence is not None:
            current = update(root, rev, evidence)
            changed, status = True, "qualified-main"
    output = (f"changed={str(changed).lower()}\nrelease={current['version']}\n"
              f"revision={current['rev']}\nstatus={status}\n")
    if len(sys.argv) > 1:
        with Path(sys.argv[1]).open("a") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
