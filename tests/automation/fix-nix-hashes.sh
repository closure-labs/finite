#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
repository="${test_root}/repository"
mkdir -p "${repository}"
printf '{}\n' >"${repository}/flake.nix"

export MOCK_CHANGED="${test_root}/changed"
export MOCK_DETERMINATE_LOG="${test_root}/determinate.log"
export MOCK_FIX_CHANGED=true
export MOCK_GH_LOG="${test_root}/gh.log"
export MOCK_GIT_LOG="${test_root}/git.log"
export MOCK_STAGED="${test_root}/staged"

git() {
	printf '%s\n' "$*" >>"${MOCK_GIT_LOG}"
	case "${1:-}" in
	status | check-ref-format | fetch | checkout | config | commit)
		;;
	rev-parse)
		printf '%s\n' "${PR_HEAD_SHA}"
		;;
	diff)
		if [[ " $* " == *' --cached '* ]]; then
			[[ ! -e "${MOCK_STAGED}" ]]
		else
			[[ ! -e "${MOCK_CHANGED}" ]]
		fi
		;;
	add)
		: >"${MOCK_STAGED}"
		;;
	push)
		[[ " $* " == *" --force-with-lease=refs/heads/${PR_HEAD_REF}:${PR_HEAD_SHA} "* ]]
		;;
	*)
		printf 'Unexpected git command: %s\n' "$*" >&2
		return 1
		;;
	esac
}

determinate-nixd() {
	[[ -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]
	[[ "$*" == 'fix hashes --auto-apply' ]]
	printf '%s\n' "$*" >>"${MOCK_DETERMINATE_LOG}"
	[[ "${MOCK_FIX_CHANGED}" == false ]] || : >"${MOCK_CHANGED}"
}

gh() {
	[[ "${GH_TOKEN}" == fixture-token ]]
	[[ "$*" == 'auth setup-git' ]]
	printf '%s\n' "$*" >>"${MOCK_GH_LOG}"
}

export -f determinate-nixd gh git

head_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
run_fixer() {
	env \
		FINITE_SOURCE_ROOT="${repository}" \
		GH_TOKEN=fixture-token \
		GITHUB_REPOSITORY=example/finite \
		PR_AUTHOR="${PR_AUTHOR:-dependabot[bot]}" \
		PR_HEAD_REF="${PR_HEAD_REF:-dependabot/github_actions/example}" \
		PR_HEAD_REPOSITORY="${PR_HEAD_REPOSITORY:-example/finite}" \
		PR_HEAD_SHA="${head_sha}" \
			finite-fix-nix-hashes
}

: >"${MOCK_GIT_LOG}"
: >"${MOCK_GH_LOG}"
: >"${MOCK_DETERMINATE_LOG}"
run_fixer
grep -qFx 'fix hashes --auto-apply' "${MOCK_DETERMINATE_LOG}"
grep -qFx 'auth setup-git' "${MOCK_GH_LOG}"
grep -qF 'fetch --no-tags --depth=1 origin refs/heads/dependabot/github_actions/example' \
	"${MOCK_GIT_LOG}"
grep -qF "checkout --detach ${head_sha}" "${MOCK_GIT_LOG}"
grep -qF 'add --update --ignore-removal .' "${MOCK_GIT_LOG}"
grep -qF 'commit -m [dependabot skip] Automatically fix Nix hashes' "${MOCK_GIT_LOG}"
grep -qF "push --force-with-lease=refs/heads/dependabot/github_actions/example:${head_sha}" \
	"${MOCK_GIT_LOG}"

rm -f -- "${MOCK_CHANGED}" "${MOCK_STAGED}"
: >"${MOCK_GIT_LOG}"
: >"${MOCK_GH_LOG}"
MOCK_FIX_CHANGED=false run_fixer >/dev/null
[[ ! -s "${MOCK_GH_LOG}" ]]
if grep -q '^commit ' "${MOCK_GIT_LOG}"; then
	echo 'No-op hash repair created a commit' >&2
	exit 1
fi

if PR_AUTHOR=attacker run_fixer >/dev/null 2>&1; then
	echo 'Hash fixer accepted an untrusted author' >&2
	exit 1
fi
if PR_HEAD_REPOSITORY=attacker/finite run_fixer >/dev/null 2>&1; then
	echo 'Hash fixer accepted a foreign pull-request repository' >&2
	exit 1
fi
if PR_HEAD_REF=feature/untrusted run_fixer >/dev/null 2>&1; then
	echo 'Hash fixer accepted a non-Dependabot branch' >&2
	exit 1
fi

printf 'Nix hash repair fixtures passed\n'
