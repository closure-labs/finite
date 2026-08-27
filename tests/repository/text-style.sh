#!/usr/bin/env bash
set -euo pipefail

mapfile -d '' repository_files < <(
	rg --files --hidden --null \
		-g '!.git/**' \
		-g '!.jj/**'
)
source_files=()
for repository_file in "${repository_files[@]}"; do
	case "$(file --brief --mime-type -- "${repository_file}")" in
		text/* | application/json | application/xml | image/svg+xml)
			source_files+=("${repository_file}")
			;;
	esac
done

if trailing_whitespace="$(rg -nI '[[:blank:]]+$' -- "${source_files[@]}")"; then
	printf '%s\n' "${trailing_whitespace}" >&2
	echo 'Tracked text contains trailing whitespace' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 1 ]] || exit "${status}"
fi

if carriage_returns="$(rg -lI $'\r' -- "${source_files[@]}")"; then
	printf '%s\n' "${carriage_returns}" >&2
	echo 'Tracked text contains carriage returns' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 1 ]] || exit "${status}"
fi

missing_newline=false
for file in "${source_files[@]}"; do
	[[ -s "${file}" ]] || continue
	last_byte="$(tail -c 1 -- "${file}" | od -An -tx1 | tr -d '[:space:]')"
	if [[ "${last_byte}" != 0a ]]; then
		echo "${file}: missing final newline" >&2
		missing_newline=true
	fi
done

[[ "${missing_newline}" == false ]]
