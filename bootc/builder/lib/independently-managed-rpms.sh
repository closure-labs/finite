#!/usr/bin/env bash

purplefin_load_independently_managed_rpms() {
	local manifest="${1:?independently managed RPM manifest is required}"
	local line line_number=0 repository package trailing
	local -A packages_seen=() repositories_seen=()

	[[ -f "${manifest}" ]] || {
		echo "Independently managed RPM manifest is missing: ${manifest}" >&2
		return 2
	}

	declare -ga independently_managed_rpms=()
	declare -ga independently_managed_rpm_repo_args=()
	while IFS= read -r line || [[ -n "${line}" ]]; do
		((line_number += 1))
		[[ "${line}" =~ ^[[:space:]]*(#|$) ]] && continue
		read -r repository package trailing <<<"${line}"
		if [[ -z "${repository:-}" || -z "${package:-}" || -n "${trailing:-}" ]]; then
			echo "Invalid independently managed RPM entry at ${manifest}:${line_number}" >&2
			return 2
		fi
		if [[ ! "${repository}" =~ ^[A-Za-z0-9_.:-]+$ || ! "${package}" =~ ^[A-Za-z0-9_.+:-]+$ ]]; then
			echo "Invalid independently managed RPM name at ${manifest}:${line_number}" >&2
			return 2
		fi
		if [[ -n "${packages_seen[${package}]:-}" ]]; then
			echo "Duplicate independently managed RPM ${package} at ${manifest}:${line_number}" >&2
			return 2
		fi

		packages_seen["${package}"]=1
		independently_managed_rpms+=("${package}")
		if [[ -z "${repositories_seen[${repository}]:-}" ]]; then
			repositories_seen["${repository}"]=1
			independently_managed_rpm_repo_args+=("--enable-repo=${repository}")
		fi
	done <"${manifest}"

	if ((${#independently_managed_rpms[@]} == 0)); then
		echo "Independently managed RPM manifest is empty: ${manifest}" >&2
		return 2
	fi
}
