#!/usr/bin/env bash
set -euo pipefail

: "${DEFAULT_BRANCH:?DEFAULT_BRANCH is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"

pull_requests="$({
	gh api --paginate \
		"repos/${GITHUB_REPOSITORY}/pulls?state=open&per_page=100" \
		--slurp
})"

jq -c \
	--arg branch "${DEFAULT_BRANCH}" \
	--arg repository "${GITHUB_REPOSITORY}" '
    add[] |
    select(.draft == false) |
    select(.user.login == "dependabot[bot]") |
    select(.head.repo.full_name == $repository) |
    select(.base.ref == $branch) |
    {sha: .head.sha, url: .html_url}
  ' <<<"${pull_requests}" |
	while IFS= read -r pull_request; do
		head_sha="$(jq -er '.sha' <<<"${pull_request}")"
		pr_url="$(jq -er '.url' <<<"${pull_request}")"
		gh pr merge \
			--auto \
			--merge \
			--match-head-commit "${head_sha}" \
			"${pr_url}"
	done
