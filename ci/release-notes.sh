#!/usr/bin/env bash
set -euo pipefail

version="${1:?usage: release-notes.sh VERSION [CHANGELOG]}"
changelog="${2:-CHANGELOG.md}"

[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
	echo "Release notes require a stable semantic version: ${version}" >&2
	exit 2
}
[[ -f "${changelog}" ]] || {
	echo "Changelog does not exist: ${changelog}" >&2
	exit 2
}

heading_prefix="## [${version}] - "
heading_count="$(grep -cF "${heading_prefix}" "${changelog}" || true)"
[[ "${heading_count}" -eq 1 ]] || {
	echo "Expected one changelog heading beginning with ${heading_prefix}" >&2
	exit 2
}

escaped_version="${version//./\\.}"
grep -Eq "^## \\[${escaped_version}\\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" \
	"${changelog}" || {
	echo "Changelog release heading must include an ISO date" >&2
	exit 2
}

awk -v heading_prefix="${heading_prefix}" '
	index($0, heading_prefix) == 1 {
		found = 1
		next
	}
	found && /^## \[/ {
		exit
	}
	found && /^\[[^]]+\]:/ {
		exit
	}
	found {
		if (!started && $0 == "") {
			next
		}
		started = 1
		lines[++count] = $0
	}
	END {
		if (!found) {
			exit 2
		}
		while (count > 0 && lines[count] == "") {
			count--
		}
		for (line = 1; line <= count; line++) {
			print lines[line]
		}
	}
' "${changelog}"
