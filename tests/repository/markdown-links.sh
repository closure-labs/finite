#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
status=0

while IFS= read -r -d '' document; do
	while IFS= read -r target; do
		[[ -n "${target}" ]] || continue
		resolved="$(dirname "${document}")/${target}"
		if [[ ! -e "${resolved}" ]]; then
			printf '%s: missing local link target: %s\n' \
				"${document#"${repo_root}/"}" "${target}" >&2
			status=1
		fi
	done < <(
		rg --no-filename --only-matching --pcre2 \
			--replace '$1' \
			'\[[^]]+\]\(((?!https?://|mailto:|#)[^)#]+)(?:#[^)]+)?\)' \
			"${document}" || true
	)
done < <(
	find "${repo_root}" \
		-path "${repo_root}/.git" -prune -o \
		-path "${repo_root}/.jj" -prune -o \
		-type f -name '*.md' -print0
)

exit "${status}"
