#!/usr/bin/env bash
set -euo pipefail

just check

mapfile -d '' shell_files < <(
	find build_files system_files profile_files installer tests \
		-type f -name '*.sh' -print0
)
shellcheck --external-sources --source-path=SCRIPTDIR "${shell_files[@]}"

actionlint -color
zizmor --offline .github/workflows
