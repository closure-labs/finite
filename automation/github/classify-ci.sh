#!/usr/bin/env bash
set -euo pipefail

output_file="${1:?usage: classify-ci.sh GITHUB_OUTPUT}"
repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
event_name="${EVENT_NAME:?EVENT_NAME is required}"

emit() {
	printf 'images=%s\ninstaller=%s\n' "$1" "$2" >>"${output_file}"
}

select_all() {
	echo 'Could not establish a trustworthy event diff; requiring all expensive validations' >&2
	emit true true
}

classify_range() {
	local base_sha=$1
	local head_sha=$2
	local allow_release_metadata=${3:-false}
	local changed_paths

	if [[ ! "${base_sha}" =~ ^[0-9a-f]{40}$ || ! "${head_sha}" =~ ^[0-9a-f]{40}$ ]] ||
		! git -C "${repo_root}" cat-file -e "${base_sha}^{commit}" 2>/dev/null ||
		! git -C "${repo_root}" cat-file -e "${head_sha}^{commit}" 2>/dev/null; then
		select_all
		return
	fi

	changed_paths="$(mktemp)"
	if ! git -C "${repo_root}" diff --name-only --diff-filter=ACDMRT \
		"${base_sha}" "${head_sha}" >"${changed_paths}"; then
		rm -f -- "${changed_paths}"
		select_all
		return
	fi
	if [[ "${allow_release_metadata}" == true ]] &&
		grep -qxF VERSION "${changed_paths}" &&
		! grep -Ev '^(VERSION|CHANGELOG\.md|README\.md|docs/.*)$' "${changed_paths}" | grep -q .; then
		echo 'Release metadata only; skipping image and installer candidates' >&2
		emit false false
		rm -f -- "${changed_paths}"
		return
	fi

	emit \
		"$(purplefin-classify-changes images <"${changed_paths}")" \
		"$(purplefin-classify-changes installer <"${changed_paths}")"
	rm -f -- "${changed_paths}"
}

case "${event_name}" in
pull_request)
	classify_range \
		"${PULL_REQUEST_BASE_SHA:-}" \
		"${PULL_REQUEST_HEAD_SHA:-}" \
		true
	;;
merge_group)
	classify_range \
		"${MERGE_GROUP_BASE_SHA:-}" \
		"${MERGE_GROUP_HEAD_SHA:-}" \
		true
	;;
push)
	before_sha="${PUSH_BEFORE_SHA:-}"
	after_sha="${PUSH_AFTER_SHA:-}"
	if [[ "${before_sha}" =~ ^0{40}$ ]]; then
		select_all
	else
		classify_range "${before_sha}" "${after_sha}"
	fi
	;;
schedule)
	# Scheduled runs deliberately probe every profile for independently managed
	# RPM updates even when the repository itself has not changed.
	emit true false
	;;
workflow_dispatch)
	if [[ "${FORCE_REBUILD:-false}" == true || "${VALIDATE_ONLY:-false}" != true ]]; then
		emit true false
	else
		head_sha="$(git -C "${repo_root}" rev-parse HEAD)"
		if base_sha="$(
			git -C "${repo_root}" merge-base \
				"${DEFAULT_BRANCH_REF:-origin/main}" "${head_sha}" 2>/dev/null
		)"; then
			classify_range "${base_sha}" "${head_sha}" true
		else
			select_all
		fi
	fi
	;;
*)
	echo "Unknown event ${event_name}" >&2
	select_all
	;;
esac
