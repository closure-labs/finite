#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

export MOCK_LOG="${test_root}/gh.log"
export MOCK_STATE="${test_root}/dispatched"
export MOCK_PR_STATE="${test_root}/pr-state"
export MOCK_AUTHOR='github-actions[bot]'
export MOCK_HEAD_REPOSITORY=example/purplefin

gh() {
	{
		printf 'gh'
		printf ' %q' "$@"
		printf '\n'
	} >>"${MOCK_LOG}"

	case "${1-} ${2-}" in
	"pr view")
		if [[ "${MOCK_MODE}" == behind && ! -e "${MOCK_PR_STATE}" ]]; then
			merge_state=BEHIND
			sha=abc123
		else
			merge_state=CLEAN
			sha=def456
		fi
		printf '{"author":{"login":"%s"},"baseRefName":"main","headRefName":"update-test","headRefOid":"%s","headRepository":{"nameWithOwner":"%s"},"mergeStateStatus":"%s","state":"OPEN","title":"Test update","url":"https://github.com/example/purplefin/pull/1"}\n' "${MOCK_AUTHOR}" "${sha}" "${MOCK_HEAD_REPOSITORY}" "${merge_state}"
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
	"pr update-branch")
		: >"${MOCK_PR_STATE}"
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
		DEFAULT_BRANCH=main \
		EXPECTED_AUTHOR='github-actions[bot]' \
		EXPECTED_BRANCH=update-test \
		EXPECTED_TITLE='Test update' \
		GH_TOKEN=test-token \
		GITHUB_REPOSITORY=example/purplefin \
		PR_NUMBER=1 \
		VALIDATE_INSTALLER=false \
		bash "${repo_root}/automation/github/validate-trusted-update.sh"
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
rm -f "${MOCK_PR_STATE}"
export MOCK_MODE=behind
run_validator
grep -qF 'gh pr update-branch 1' "${MOCK_LOG}"
grep -qF -- '--match-head-commit def456' "${MOCK_LOG}"

: >"${MOCK_LOG}"
export MOCK_MODE=existing
export MOCK_AUTHOR=attacker
if run_validator; then
	echo 'Validator accepted an unexpected pull-request author' >&2
	exit 1
fi
if grep -qF 'gh pr merge' "${MOCK_LOG}"; then
	echo 'Validator attempted to merge an update from an unexpected author' >&2
	exit 1
fi
export MOCK_AUTHOR='github-actions[bot]'

: >"${MOCK_LOG}"
export MOCK_HEAD_REPOSITORY=attacker/purplefin
if run_validator; then
	echo 'Validator accepted a pull request from a fork' >&2
	exit 1
fi
if grep -qF 'gh pr merge' "${MOCK_LOG}"; then
	echo 'Validator attempted to merge an update from a fork' >&2
	exit 1
fi
export MOCK_HEAD_REPOSITORY=example/purplefin

: >"${MOCK_LOG}"
rm -f "${MOCK_STATE}"
export MOCK_MODE=fallback
run_validator
grep -qF 'gh workflow run build.yml' "${MOCK_LOG}"
grep -qF 'gh run watch 202' "${MOCK_LOG}"
grep -qF 'gh pr merge' "${MOCK_LOG}"
