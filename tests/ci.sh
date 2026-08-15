#!/usr/bin/env bash
set -euo pipefail

just check

alejandra --check .
deadnix --fail .

mapfile -d '' shell_files < <(
	find bootc installer tests \
		-type f -name '*.sh' -print0
)
shellcheck --external-sources --source-path=SCRIPTDIR "${shell_files[@]}"

actionlint -color
zizmor --offline .github/workflows
