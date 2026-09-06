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
