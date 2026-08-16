#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

export MOCK_LOG="${test_root}/gh.log"
export MOCK_STATE="${test_root}/dispatched"

gh() {
	{
		printf 'gh'
		printf ' %q' "$@"
		printf '\n'
	} >>"${MOCK_LOG}"

	case "${1-} ${2-}" in
	"pr view")
		printf '%s\n' '{"headRefName":"update-test","headRefOid":"abc123","state":"OPEN","title":"Test update","url":"https://github.com/example/purplefin/pull/1"}'
		;;
	"run list")
		if [[ " $* " == *' --event pull_request '* ]]; then
			[[ "${MOCK_MODE}" == existing ]] && printf '%s\n' 101
		elif [[ -e "${MOCK_STATE}" ]]; then
			printf '%s\n' 202
		fi
		:
		;;
	"workflow run")
		: >"${MOCK_STATE}"
		;;
	"run watch" | "pr merge")
		;;
	*)
		echo "Unexpected gh command: $*" >&2
		return 2
		;;
	esac
}

sleep() {
	:
}

export -f gh sleep

run_validator() {
	env \
		EXPECTED_BRANCH=update-test \
		EXPECTED_TITLE='Test update' \
		GH_TOKEN=test-token \
		GITHUB_REPOSITORY=example/purplefin \
		PR_NUMBER=1 \
		VALIDATE_INSTALLER=false \
		"${repo_root}/ci/validate-trusted-update.sh"
}

export MOCK_MODE=existing
run_validator
grep -qF 'gh run watch 101' "${MOCK_LOG}"
grep -qF 'gh pr merge' "${MOCK_LOG}"
if grep -qF 'gh workflow run' "${MOCK_LOG}"; then
	echo 'Validator dispatched duplicate CI despite an existing pull-request run' >&2
	exit 1
fi

: >"${MOCK_LOG}"
rm -f "${MOCK_STATE}"
export MOCK_MODE=fallback
run_validator
grep -qF 'gh workflow run build.yml' "${MOCK_LOG}"
grep -qF 'gh run watch 202' "${MOCK_LOG}"
grep -qF 'gh pr merge' "${MOCK_LOG}"
