#!/usr/bin/env bash
set -euo pipefail

audit="${1:?usage: repository-security.sh AUDIT POLICY FIXTURE_DIR}"
policy="${2:?usage: repository-security.sh AUDIT POLICY FIXTURE_DIR}"
fixtures="${3:?usage: repository-security.sh AUDIT POLICY FIXTURE_DIR}"

report="$("${audit}" --policy "${policy}" --snapshot "${fixtures}/pass.json")"
jq -e '
	.schema == 1 and
	.repository == "closure-labs/finite" and
	.status == "pass" and
	.drift == []
' <<<"${report}" >/dev/null

extra_action=$(mktemp)
trap 'rm -f "$extra_action"' EXIT
jq '.actions.selected_actions.patterns_allowed += ["*"]' "${fixtures}/pass.json" >"$extra_action"
set +e
extra_report=$("${audit}" --policy "${policy}" --snapshot "$extra_action")
extra_status=$?
set -e
[[ $extra_status -eq 1 ]]
jq -e '.drift | index("actions.selected_actions.patterns_allowed") != null' <<<"$extra_report" >/dev/null

set +e
drift_report="$("${audit}" --policy "${policy}" --snapshot "${fixtures}/drift.json")"
drift_status=$?
set -e
[[ ${drift_status} -eq 1 ]]
jq -e '
	.status == "drift" and
	(.drift | index("actions.allowed_actions")) != null and
	(.drift | index("security.secret_scanning_push_protection")) != null
' <<<"${drift_report}" >/dev/null

set +e
malformed_report="$("${audit}" --policy "${policy}" --snapshot "${fixtures}/malformed.json")"
malformed_status=$?
set -e
[[ ${malformed_status} -eq 2 ]]
jq -e '.status == "invalid" and .drift == []' <<<"${malformed_report}" >/dev/null

# Every relevant structure is compared, including additional children of empty objects.
mutate_and_reject() {
	local expression=$1 expected_path=$2
	jq "$expression" "${fixtures}/pass.json" >"$extra_action"
	local result status=0
	result=$("${audit}" --policy "${policy}" --snapshot "$extra_action") || status=$?
	[[ $status -eq 1 ]]
	jq -e --arg path "$expected_path" '.status == "drift" and any(.drift[]; startswith($path))' <<<"$result" >/dev/null
}
mutate_and_reject 'del(.environments.release)' 'environments.release'
mutate_and_reject '.environments.unexpected = {}' 'environments.unexpected'
mutate_and_reject '.environments.release.can_admins_bypass = true' 'environments.release.can_admins_bypass'
mutate_and_reject '.environments.release.custom_protection_rules = [{app_id: 1, enabled: true}]' 'environments.release.custom_protection_rules'
mutate_and_reject '.environments.release.protection_rules = []' 'environments.release.protection_rules'
mutate_and_reject '.environments.release.protection_rules[0].reviewers = [{type: "User", id: 52590374}]' 'environments.release.protection_rules'
mutate_and_reject '.environments["package-cleanup"].protection_rules[0].reviewers = [{type: "Team", id: 20196828}]' 'environments.package-cleanup.protection_rules'
mutate_and_reject '.environments.release.deployment_branches[0].name = "*"' 'environments.release.deployment_branches'
mutate_and_reject '.main.rulesets = []' 'main.rulesets'
mutate_and_reject '.main.rulesets[0].enforcement = "disabled"' 'main.rulesets'
mutate_and_reject '.main.rulesets[0].bypass_actors = [{actor_id: 1, actor_type: "Integration", bypass_mode: "always"}]' 'main.rulesets'
mutate_and_reject '.main.effective_rules |= map(select(.type != "merge_queue"))' 'main.effective_rules'
mutate_and_reject '(.main.effective_rules[] | select(.type == "required_status_checks").parameters.required_status_checks[0].integration_id) = 1' 'main.effective_rules'
mutate_and_reject '(.main.effective_rules[] | select(.type == "required_status_checks").parameters.required_status_checks) |= map(select(.context != "Maintainer decision authority"))' 'main.effective_rules'
mutate_and_reject '(.main.effective_rules[] | select(.type == "required_status_checks").parameters.required_status_checks[] | select(.context == "Maintainer decision authority").integration_id) = 15368' 'main.effective_rules'
mutate_and_reject '(.main.effective_rules[] | select(.type == "pull_request").parameters.required_review_thread_resolution) = false' 'main.effective_rules'
mutate_and_reject '.main.effective_rules = []' 'main.effective_rules'
mutate_and_reject '(.main.effective_rules[] | select(.type == "pull_request").parameters.required_approving_review_count) = false' 'main.effective_rules'
mutate_and_reject '.security.vulnerability_alerts = "true"' 'security.vulnerability_alerts'

# The original false-negative case: an empty expected environment map must
# still detect real environments in the snapshot.
jq '.environments = {}' "$policy" >"$extra_action"
empty_status=0
empty_report=$("${audit}" --policy "$extra_action" --snapshot "${fixtures}/pass.json") || empty_status=$?
[[ $empty_status -eq 1 ]]
jq -e 'any(.drift[]; startswith("environments."))' <<<"$empty_report" >/dev/null

python3 - "$policy" "$fixtures" <<'PY'
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import importlib.util
import os
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("audit", "scripts/ci/repository-security-audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
policy = json.loads(Path(sys.argv[1]).read_text())
snapshot = json.loads((Path(sys.argv[2]) / "pass.json").read_text())
assert audit.differences({}, {"unexpected": {}}) == ["unexpected"]
assert audit.differences([{"required_reviewers": 1}], [{"required_reviewers": 0}]) == [""]
assert audit.differences([False], [0]) == [""]
audit.shape(policy, policy)
for mutation in (lambda p: p.update(schema=True), lambda p: p["main"].update(ruleset_id="1"),
                 lambda p: p["environments"]["release"].update(can_admins_bypass="false"),
                 lambda p: p["actions"].pop("enabled")):
    invalid = copy.deepcopy(policy)
    mutation(invalid)
    try:
        audit.shape(invalid, policy)
    except audit.Invalid:
        pass
    else:
        raise AssertionError("Invalid policy accepted")

# Build raw GitHub responses from the independent normalized fixture.
responses = {
    "/actions/permissions": snapshot["actions"],
    "/actions/permissions/selected-actions": snapshot["actions"]["selected_actions"],
    "/actions/permissions/workflow": snapshot["actions"]["workflow_permissions"],
    "": {"default_branch": "main", "security_and_analysis": {
        "secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}},
    "/automated-security-fixes": {"enabled": True},
    "/vulnerability-alerts": None,
    "/environments?per_page=100&page=1": {"total_count": len(snapshot["environments"]), "environments": [{"name": n} for n in snapshot["environments"]]},
    "/rules/branches/main?per_page=100&page=1": [dict(r, ruleset_id=20912451) for r in snapshot["main"]["effective_rules"]],
    "/rulesets/20912451": snapshot["main"]["rulesets"][0],
}
for name, env in snapshot["environments"].items():
    raw = copy.deepcopy(env)
    for rule in raw["protection_rules"]:
        if rule["type"] == "required_reviewers":
            rule["reviewers"] = [{"type": r["type"], "reviewer": {"id": r["id"]}} for r in rule["reviewers"]]
    responses[f"/environments/{name}"] = raw
    responses[f"/environments/{name}/deployment_protection_rules?per_page=100&page=1"] = {
        "total_count": 0, "custom_deployment_protection_rules": []}
    responses[f"/environments/{name}/deployment-branch-policies?per_page=100&page=1"] = {
        "total_count": 1, "branch_policies": env["deployment_branches"]}

failure = None
bad_json = False

def fake_run(command, **kwargs):
    endpoint = command[-1].removeprefix("repos/closure-labs/finite")
    assert endpoint in responses, endpoint
    if endpoint == failure:
        return subprocess.CompletedProcess(command, 0 if bad_json else 1, "broken", "API denied")
    payload = responses[endpoint]
    return subprocess.CompletedProcess(command, 0, json.dumps(payload) if payload is not None else "", "")

with patch.object(audit.subprocess, "run", side_effect=fake_run):
    assert audit.canonical(audit.live(audit.API("closure-labs/finite"))) == audit.canonical(snapshot)
    # An HTTP 200 response can still omit permission-sensitive fields. Never
    # infer "no bypass actors" from an Administration:read token's response.
    detail = responses["/rulesets/20912451"]
    bypass = detail.pop("bypass_actors")
    try:
        api = audit.API("closure-labs/finite")
        try:
            audit.live(api)
        except audit.Invalid as error:
            assert "bypass actor visibility is unavailable" in str(error)
            assert "write access" in str(error)
            assert api.unavailable == ["repos/closure-labs/finite/rulesets/20912451"]
        else:
            raise AssertionError("Missing bypass actor data was accepted")
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, FINITE_SECURITY_POLICY=sys.argv[1],
                        FINITE_SECURITY_RULESET="automation/github/policies/main-merge-queue.json"), \
                patch.object(sys, "argv", ["audit", "--repository", "closure-labs/finite"]), \
                redirect_stdout(output), redirect_stderr(errors):
            assert audit.main() == 2
        report = json.loads(output.getvalue())
        assert report["status"] == "invalid"
        assert report["drift"] == []
        assert report["unavailable"] == ["repos/closure-labs/finite/rulesets/20912451"]
        assert "bypass actor visibility is unavailable" in report["error"]
        assert report["coverage"] == "incomplete"

        def read_only_report():
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, FINITE_SECURITY_POLICY=sys.argv[1],
                            FINITE_SECURITY_RULESET="automation/github/policies/main-merge-queue.json"), \
                    patch.object(sys, "argv", ["audit", "--repository", "closure-labs/finite", "--read-only-app"]), \
                    redirect_stdout(output), redirect_stderr(errors):
                code = audit.main()
            return code, json.loads(output.getvalue())

        code, report = read_only_report()
        assert code == 0 and report["status"] == "pass"
        assert report["coverage"] == "partial" and report["unavailable"] == []
        assert any("repos/closure-labs/finite/rulesets/20912451.bypass_actors" in item
                   and "administrator CLI audit" in item for item in report["excluded"])
        # The exception applies only to this permission-sensitive field.
        detail["enforcement"] = "disabled"
        code, report = read_only_report()
        assert code == 1 and "main.rulesets" in report["drift"]
        detail["enforcement"] = "active"
        omitted = detail.pop("conditions")
        code, report = read_only_report()
        assert code == 2 and report["status"] == "invalid"
        detail["conditions"] = omitted
        environment = responses["/environments/release"]
        environment["can_admins_bypass"] = True
        code, report = read_only_report()
        assert code == 1 and "environments.release.can_admins_bypass" in report["drift"]
        environment["can_admins_bypass"] = False
    finally:
        detail["bypass_actors"] = bypass
    detail["bypass_actors"] = [{"actor_id": 1, "actor_type": "Integration", "bypass_mode": "always"}]
    try:
        code, report = read_only_report()
        assert code == 1 and report["coverage"] == "complete" and "main.rulesets" in report["drift"]
    finally:
        detail["bypass_actors"] = bypass
    for endpoint in responses:
        failure = endpoint
        api = audit.API("closure-labs/finite")
        try:
            audit.live(api)
        except audit.Invalid:
            assert api.unavailable == ["repos/closure-labs/finite" + endpoint]
        else:
            raise AssertionError(f"Ignored API failure at {endpoint}")
    failure = "/environments/release"
    bad_json = True
    try:
        audit.live(audit.API("closure-labs/finite"))
    except audit.Invalid:
        pass
    else:
        raise AssertionError("Accepted malformed API JSON")

with patch.object(audit.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 60)):
    api = audit.API("closure-labs/finite")
    try:
        api.get("/environments")
    except audit.Invalid:
        assert api.unavailable == ["repos/closure-labs/finite/environments"]
    else:
        raise AssertionError("Accepted timed-out endpoint")

# Pagination must consume every page, including final pages missing expected entries.
api = audit.API("closure-labs/finite")
with patch.object(api, "get", side_effect=[{"total_count": 101, "items": list(range(100))}, {"total_count": 101, "items": [100]}]):
    assert api.pages("/example", "items") == list(range(101))
with patch.object(api, "get", return_value={"total_count": 2, "items": []}):
    try:
        api.pages("/example", "items")
    except audit.Invalid:
        pass
    else:
        raise AssertionError("Accepted incomplete pagination")
print("Repository security negative, API and pagination tests passed")
PY
