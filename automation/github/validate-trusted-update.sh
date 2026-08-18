#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN must be set}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
: "${PR_NUMBER:?PR_NUMBER must be set}"
: "${EXPECTED_BRANCH:?EXPECTED_BRANCH must be set}"
: "${EXPECTED_TITLE:?EXPECTED_TITLE must be set}"
: "${EXPECTED_AUTHOR:?EXPECTED_AUTHOR must be set}"
: "${DEFAULT_BRANCH:?DEFAULT_BRANCH must be set}"

read_pr() {
	gh pr view "${PR_NUMBER}" \
		--repo "${GITHUB_REPOSITORY}" \
		--json author,baseRefName,headRefName,headRefOid,headRepository,mergeStateStatus,state,title,url
}

validate_pr() {
	local candidate=$1
	[[ "$(jq -er '.state' <<<"${candidate}")" == OPEN ]]
	[[ "$(jq -er '.title' <<<"${candidate}")" == "${EXPECTED_TITLE}" ]]
	[[ "$(jq -er '.author.login' <<<"${candidate}")" == "${EXPECTED_AUTHOR}" ]]
	[[ "$(jq -er '.baseRefName' <<<"${candidate}")" == "${DEFAULT_BRANCH}" ]]
	[[ "$(jq -er '.headRepository.nameWithOwner' <<<"${candidate}")" == "${GITHUB_REPOSITORY}" ]]
	[[ "$(jq -er '.headRefName' <<<"${candidate}")" == "${EXPECTED_BRANCH}" ]]
}

pr="$(read_pr)"
validate_pr "${pr}"
if [[ "$(jq -er '.mergeStateStatus' <<<"${pr}")" == BEHIND ]]; then
	gh pr update-branch "${PR_NUMBER}" --repo "${GITHUB_REPOSITORY}"
	pr="$(read_pr)"
	validate_pr "${pr}"
fi
branch="$(jq -er '.headRefName' <<<"${pr}")"
head_sha="$(jq -er '.headRefOid' <<<"${pr}")"
pr_url="$(jq -er '.url' <<<"${pr}")"

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

existing_ci_run=''
for _ in {1..6}; do
	existing_ci_run="$({
		gh run list \
			--repo "${GITHUB_REPOSITORY}" \
			--workflow build.yml \
			--event pull_request \
			--branch "${branch}" \
			--commit "${head_sha}" \
			--limit 1 \
			--json conclusion,databaseId,status \
			--jq '.[0] // empty'
	})"
	[[ -z "${existing_ci_run}" ]] || break
	sleep 5
done

if [[ -n "${existing_ci_run}" ]]; then
	existing_ci_run_id="$(jq -er '.databaseId' <<<"${existing_ci_run}")"
	if [[ "$(jq -r '.conclusion // empty' <<<"${existing_ci_run}")" == action_required ]]; then
		gh api \
			--method POST \
			"repos/${GITHUB_REPOSITORY}/actions/runs/${existing_ci_run_id}/approve"
	fi
	gh run watch "${existing_ci_run_id}" \
		--repo "${GITHUB_REPOSITORY}" \
		--exit-status
else
	dispatch_and_wait build.yml -f validate_only=true
fi
gh pr merge \
	--repo "${GITHUB_REPOSITORY}" \
	--auto \
	--merge \
	--match-head-commit "${head_sha}" \
	"${pr_url}"
