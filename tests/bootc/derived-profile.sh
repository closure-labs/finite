#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
catalog="${generated_root}/bootc/generated/profile-catalog.json"

jq -e '
  (.profiles | length) == 4 and
  all(.profiles[]; .parent == null and .stage == "root")
' "${catalog}" >/dev/null

if PURPLEFIN_BUILD_ROOT="${repo_root}" \
	PURPLEFIN_GENERATED_ROOT="${generated_root}" \
	PURPLEFIN_DERIVED_DRY_RUN=true \
	bash "${repo_root}/bootc/builder/derived.sh" bluefin-generic base >/dev/null 2>&1; then
	echo 'A foundation profile unexpectedly accepted a parent' >&2
	exit 1
fi
