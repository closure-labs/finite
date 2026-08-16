#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN must be set}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
: "${PR_NUMBER:?PR_NUMBER must be set}"
: "${EXPECTED_BRANCH:?EXPECTED_BRANCH must be set}"
: "${EXPECTED_TITLE:?EXPECTED_TITLE must be set}"

VALIDATE_INSTALLER="${VALIDATE_INSTALLER:-false}"

pr="$({
	gh pr view "${PR_NUMBER}" \
		--repo "${GITHUB_REPOSITORY}" \
		--json headRefName,headRefOid,state,title,url
})"
branch="$(jq -er '.headRefName' <<<"${pr}")"
head_sha="$(jq -er '.headRefOid' <<<"${pr}")"
pr_url="$(jq -er '.url' <<<"${pr}")"
[[ "$(jq -er '.state' <<<"${pr}")" == OPEN ]]
[[ "$(jq -er '.title' <<<"${pr}")" == "${EXPECTED_TITLE}" ]]
[[ "${branch}" == "${EXPECTED_BRANCH}" ]]

dispatch_and_wait() {
	local workflow="$1"
	shift
	local previous_run_id run_id

	previous_run_id="$({
		gh run list \
			--repo "${GITHUB_REPOSITORY}" \
			--workflow "${workflow}" \
			--event workflow_dispatch \
			--branch "${branch}" \
			--commit "${head_sha}" \
			--limit 1 \
			--json databaseId \
			--jq '.[0].databaseId // empty'
	})"
	gh workflow run "${workflow}" \
		--repo "${GITHUB_REPOSITORY}" \
		--ref "${branch}" \
		"$@"

	run_id=''
	for _ in {1..24}; do
		run_id="$({
			gh run list \
				--repo "${GITHUB_REPOSITORY}" \
				--workflow "${workflow}" \
				--event workflow_dispatch \
				--branch "${branch}" \
				--commit "${head_sha}" \
				--limit 5 \
				--json databaseId \
				--jq ".[] | select((.databaseId | tostring) != \"${previous_run_id}\") | .databaseId" |
				head -n 1
		})"
		[[ -z "${run_id}" ]] || break
		sleep 5
	done
	[[ -n "${run_id}" ]] || {
		echo "Could not locate ${workflow} validation run" >&2
		exit 1
	}

	gh run watch "${run_id}" \
		--repo "${GITHUB_REPOSITORY}" \
		--exit-status
}

existing_ci_run_id=''
for _ in {1..6}; do
	existing_ci_run_id="$({
		gh run list \
			--repo "${GITHUB_REPOSITORY}" \
			--workflow build.yml \
			--event pull_request \
			--branch "${branch}" \
			--commit "${head_sha}" \
			--limit 1 \
			--json databaseId \
			--jq '.[0].databaseId // empty'
	})"
	[[ -z "${existing_ci_run_id}" ]] || break
	sleep 5
done

if [[ -n "${existing_ci_run_id}" ]]; then
	gh run watch "${existing_ci_run_id}" \
		--repo "${GITHUB_REPOSITORY}" \
		--exit-status
else
	dispatch_and_wait build.yml -f validate_only=true
fi
if [[ "${VALIDATE_INSTALLER}" == true ]]; then
	dispatch_and_wait build-installer.yml -f image-tag=base-generic-x86_64
fi

gh pr merge \
	--repo "${GITHUB_REPOSITORY}" \
	--auto \
	--merge \
	--match-head-commit "${head_sha}" \
	"${pr_url}"
