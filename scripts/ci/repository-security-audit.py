"""Read-only, fail-closed comparison of reviewed GitHub security controls."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote


class Invalid(Exception):
    pass


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def load(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise Invalid(message)


def shape(value, template, path="policy"):
    require(type(value) is type(template), f"{path}: invalid type")
    if path == "policy.environments":
        for name, env in value.items():
            require(isinstance(name, str) and name, "Invalid environment name")
            shape(env, max(template.values(), key=lambda e: len(e["protection_rules"])), f"{path}.{name}")
        return
    if isinstance(template, dict):
        require(value.keys() == template.keys(), f"{path}: missing or unknown fields")
        for key in template:
            shape(value[key], template[key], f"{path}.{key}")
    elif isinstance(template, list) and template:
        for item in value:
            model = template[0]
            if isinstance(item, dict) and "type" in item:
                matches = [t for t in template if isinstance(t, dict) and t.get("type") == item["type"]]
                require(bool(matches), f"{path}: unsupported rule type")
                model = matches[0]
            shape(item, model, path)


def rules(value):
    return canonical([{k: v for k, v in r.items() if k in ("type", "parameters")} for r in value])


def expected_policy(policy, rule_policy):
    result = copy.deepcopy(policy)
    result["main"] = {
        "rulesets": [{"id": policy["main"]["ruleset_id"], **rule_policy}],
        "effective_rules": rules(rule_policy["rules"]),
    }
    # GitHub's explicit defaults are checked too, rather than discarded from the API.
    for collection in (result["main"]["rulesets"][0]["rules"], result["main"]["effective_rules"]):
        for rule in collection:
            if rule["type"] == "pull_request":
                rule["parameters"].setdefault("dismissal_restriction", {"enabled": False, "allowed_actors": []})
                rule["parameters"].setdefault("require_extra_approval_for_unattributed_changes", True)
    return canonical(result)


class API:
    def __init__(self, repository):
        self.prefix = f"repos/{repository}"
        self.inspected = []
        self.unavailable = []
        self.excluded = []
        self.excluded_bypass_ids = []

    def get(self, path, empty=False):
        endpoint = self.prefix + path
        try:
            result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False, timeout=60)
        except subprocess.TimeoutExpired as error:
            self.unavailable.append(endpoint)
            raise Invalid(f"Required GitHub endpoint timed out: {endpoint}") from error
        if result.returncode:
            self.unavailable.append(endpoint)
            raise Invalid(f"Required GitHub endpoint unavailable: {endpoint}")
        self.inspected.append(endpoint)
        if empty:
            return True
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            self.unavailable.append(endpoint)
            raise Invalid(f"Invalid JSON from {endpoint}") from error

    def pages(self, path, key=None):
        values = []
        page = 1
        while True:
            payload = self.get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            items = payload[key] if key else payload
            require(isinstance(items, list), f"Invalid list from {path}")
            values.extend(items)
            if len(items) < 100:
                if key and "total_count" in payload:
                    require(len(values) == payload["total_count"], f"Incomplete pagination for {path}")
                return values
            page += 1


def live(api, read_only_app=False):
    actions = api.get("/actions/permissions")
    selected = api.get("/actions/permissions/selected-actions")
    workflow = api.get("/actions/permissions/workflow")
    metadata = api.get("")
    require(metadata["default_branch"] == "main", "Unexpected default branch")
    dependabot = api.get("/automated-security-fixes")
    alerts = api.get("/vulnerability-alerts", empty=True)
    environments = {}
    for summary in api.pages("/environments", "environments"):
        name = summary["name"]
        require(name not in environments, "Duplicate environment")
        endpoint = "/environments/" + quote(name, safe="")
        env = api.get(endpoint)
        protection = []
        for entry in env["protection_rules"]:
            item = {k: v for k, v in entry.items() if k not in ("id", "node_id")}
            if item["type"] == "required_reviewers":
                item["reviewers"] = [{"type": r["type"], "id": r["reviewer"]["id"]} for r in item["reviewers"]]
            protection.append(item)
        branch_policy = env["deployment_branch_policy"]
        branches = []
        if branch_policy and branch_policy["custom_branch_policies"]:
            branches = [{"name": b["name"], "type": b["type"]} for b in api.pages(endpoint + "/deployment-branch-policies", "branch_policies")]
        environments[name] = {"can_admins_bypass": env["can_admins_bypass"], "protection_rules": protection,
                              "deployment_branch_policy": branch_policy, "deployment_branches": branches,
                              "custom_protection_rules": [{"app_id": r["app"]["id"], "enabled": r["enabled"]}
                                  for r in api.pages(endpoint + "/deployment_protection_rules", "custom_deployment_protection_rules")]}
    effective = api.pages("/rules/branches/main")
    main_rulesets = []
    for rid in sorted({r["ruleset_id"] for r in effective}):
        detail = api.get(f"/rulesets/{rid}")
        if "bypass_actors" not in detail:
            endpoint = f"{api.prefix}/rulesets/{rid}"
            if not read_only_app:
                api.unavailable.append(endpoint)
                raise Invalid(
                    f"Required ruleset bypass actor visibility is unavailable: {endpoint}. "
                    "GitHub omits bypass_actors unless the authenticated identity has write access "
                    "to this ruleset. Missing data cannot be audited as an empty bypass list."
                )
            api.excluded.append(
                f"{endpoint}.bypass_actors: not visible in read-only App mode; "
                "requires a separate administrator CLI audit"
            )
            api.excluded_bypass_ids.append(rid)
        main_rulesets.append({k: detail[k] for k in ("id", "name", "target", "enforcement", "bypass_actors", "conditions", "rules")
                              if k != "bypass_actors" or k in detail})
    return {"schema": 1, "repository": api.prefix.removeprefix("repos/"),
            "actions": {"enabled": actions["enabled"], "allowed_actions": actions["allowed_actions"],
                        "sha_pinning_required": actions["sha_pinning_required"],
                        "selected_actions": {k: selected[k] for k in ("github_owned_allowed", "verified_allowed", "patterns_allowed")},
                        "workflow_permissions": {k: workflow[k] for k in ("default_workflow_permissions", "can_approve_pull_request_reviews")}},
            "security": {"vulnerability_alerts": alerts, "dependabot_security_updates": dependabot["enabled"],
                         "secret_scanning": metadata["security_and_analysis"]["secret_scanning"]["status"] == "enabled",
                         "secret_scanning_push_protection": metadata["security_and_analysis"]["secret_scanning_push_protection"]["status"] == "enabled"},
            "environments": environments, "main": {"rulesets": main_rulesets, "effective_rules": rules(effective)}}


def differences(expected, actual, path=""):
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            child = f"{path}.{key}".lstrip(".")
            result.extend([child] if key not in expected or key not in actual else differences(expected[key], actual[key], child))
        return result
    # JSON distinguishes booleans and numbers, including inside nested arrays.
    return [] if json.dumps(expected, sort_keys=True) == json.dumps(actual, sort_keys=True) else [path]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=os.environ.get("FINITE_SECURITY_POLICY"), required=False)
    parser.add_argument("--repository", default=os.environ.get("GH_REPOSITORY"))
    parser.add_argument("--snapshot")
    parser.add_argument("--read-only-app", action="store_true",
                        help="Live audit: explicitly exclude bypass actors only when GitHub withholds them; require a separate administrator CLI audit")
    args = parser.parse_args()
    api = None
    report = {"schema": 1, "repository": args.repository or "unknown", "status": "invalid", "drift": [],
              "coverage": "incomplete", "coverageScope": "reviewed repository policy",
              "inspected": [], "unavailable": [], "excluded": ["legacy branch protection (effective rulesets checked)", "organization membership and secret access", "environment secret values"]}
    try:
        require(not (args.read_only_app and args.snapshot), "--read-only-app is only supported for live audits")
        baseline = load(os.environ["FINITE_SECURITY_POLICY"])
        policy = load(args.policy)
        shape(policy, baseline)
        require(policy["schema"] == 1 and re.fullmatch(r"[^/]+/[^/]+", policy["repository"]), "Invalid policy identity")
        require(policy["main"]["ruleset_id"] > 0, "Invalid ruleset ID")
        # Policy edits remain reviewed; shape and minimum security invariants fail closed.
        require(policy["actions"]["enabled"] is True and policy["actions"]["sha_pinning_required"] is True
                and policy["actions"]["allowed_actions"] == "selected"
                and policy["actions"]["selected_actions"]["github_owned_allowed"] is True
                and policy["actions"]["selected_actions"]["verified_allowed"] is False
                and policy["actions"]["workflow_permissions"] == {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}
                and all(v is True for v in policy["security"].values()), "Unsafe policy")
        repository = args.repository or policy["repository"]
        report["repository"] = repository
        require(repository == policy["repository"], "Requested repository does not match policy")
        expected = expected_policy(policy, load(os.environ["FINITE_SECURITY_RULESET"]))
        if args.snapshot:
            actual = load(args.snapshot)
            require(isinstance(actual, dict), "Snapshot must be an object")
            report["inspected"] = ["snapshot"]
        else:
            api = API(repository)
            actual = live(api, read_only_app=args.read_only_app)
            for ruleset in expected["main"]["rulesets"]:
                if ruleset["id"] in api.excluded_bypass_ids:
                    del ruleset["bypass_actors"]
        report["coverage"] = "partial" if api and api.excluded else "complete"
        report["drift"] = differences(expected, canonical(actual))
        report["status"] = "drift" if report["drift"] else "pass"
        code = 1 if report["drift"] else 0
    except (Invalid, ValueError, KeyError, TypeError, OSError) as error:
        if api and isinstance(error, (KeyError, TypeError, ValueError)) and api.inspected:
            api.unavailable.append(api.inspected[-1])
        print(str(error), file=sys.stderr)
        report["error"] = str(error)
        code = 2
    if api:
        report["inspected"] = api.inspected
        report["unavailable"] = api.unavailable
        report["excluded"].extend(api.excluded)
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
