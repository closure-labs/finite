#!/usr/bin/env bash
set -euo pipefail

vendor_theme=':(exclude)bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/**'

if trailing_whitespace="$(git grep -nI -E '[[:blank:]]+$' -- . "${vendor_theme}")"; then
	printf '%s\n' "${trailing_whitespace}" >&2
	echo 'Tracked text contains trailing whitespace' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 1 ]] || exit "${status}"
fi

if carriage_returns="$(git grep -nIl $'\r' -- . "${vendor_theme}")"; then
	printf '%s\n' "${carriage_returns}" >&2
	echo 'Tracked text contains carriage returns' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 1 ]] || exit "${status}"
fi

missing_newline=false
while IFS= read -r -d '' file; do
	last_byte="$(tail -c 1 -- "${file}" | od -An -tx1 | tr -d '[:space:]')"
	if [[ "${last_byte}" != 0a ]]; then
		echo "${file}: missing final newline" >&2
		missing_newline=true
	fi
done < <(git grep -Ilz '' -- . "${vendor_theme}")

[[ "${missing_newline}" == false ]]
