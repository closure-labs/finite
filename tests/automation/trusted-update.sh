#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
export MOCK_LOG="$test_root/gh.log" MOCK_READS="$test_root/reads"
export MOCK_MODE=valid MOCK_MERGE_STATE=CLEAN
export MOCK_HEAD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

# The packaged helper invokes only bounded native reads and one queue request.
# Any accidental run approval, workflow dispatch, branch update or wait fails.
gh() {
	{
		printf 'gh'
		printf ' %q' "$@"
		printf '\n'
	} >>"$MOCK_LOG"
	case "$1 $2" in
	"pr view")
		local reads=0
		[[ ! -f $MOCK_READS ]] || reads=$(cat "$MOCK_READS")
		reads=$((reads + 1))
		printf '%s\n' "$reads" >"$MOCK_READS"
		if [[ $MOCK_MODE == read-failed || ($MOCK_MODE == final-read-failed && $reads == 2) ]]; then return 8; fi
		if [[ $MOCK_MODE == malformed ]]; then printf '{invalid'; return; fi
		jq -cn --arg mode "$MOCK_MODE" --arg state "$MOCK_MERGE_STATE" \
			--arg head "$MOCK_HEAD" --argjson reads "$reads" '
			{number:1, author:{login:"github-actions[bot]"}, baseRefName:"main",
			 changedFiles:2, files:[{path:"flake.lock"},{path:"devenv.lock"}],
			 headRefName:"update-test", headRefOid:$head,
			 headRepository:{nameWithOwner:"example/finite"}, mergeStateStatus:$state,
			 state:"OPEN", title:"Test update"} |
			if $mode == "author" or ($mode == "final-author" and $reads == 2) then .author.login="attacker"
			elif $mode == "repository" then .headRepository.nameWithOwner="fork/finite"
			elif $mode == "branch" then .headRefName="other"
			elif $mode == "base" or ($mode == "final-base" and $reads == 2) then .baseRefName="other"
			elif $mode == "title" then .title="Other update"
			elif $mode == "closed" or ($mode == "final-closed" and $reads == 2) then .state="CLOSED"
			elif $mode == "number" then .number=2
			elif $mode == "sha" then .headRefOid="abc123"
			elif $mode == "files" or ($mode == "final-files" and $reads == 2) then .files[0].path="scripts/ci/decision-authority.py"
			elif $mode == "empty-files" then .files=[] | .changedFiles=0
			elif $mode == "missing-files" then del(.files)
			elif $mode == "truncated-files" then .changedFiles=3
			elif $mode == "duplicate-files" then .files[1]=.files[0]
			elif $mode == "changed-head" and $reads == 2 then .headRefOid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
			else . end'
		;;
	"pr merge")
		[[ $* == "pr merge --repo example/finite --auto --merge --match-head-commit $MOCK_HEAD 1" ]] || return 90
		[[ $MOCK_MODE != merge-failed ]] || return 9
		;;
	*) echo "Unexpected gh operation: $*" >&2; return 91 ;;
	esac
}

timeout() {
	[[ $1 == 60s ]] || { echo "Unexpected command timeout: $1" >&2; return 92; }
	shift
	"$@"
}
export -f gh timeout

run_validator() {
	env DEFAULT_BRANCH=main EXPECTED_AUTHOR='github-actions[bot]' \
		EXPECTED_BRANCH=update-test EXPECTED_TITLE='Test update' \
		EXPECTED_FILES=flake.lock,devenv.lock GH_TOKEN=fixture-token \
		GITHUB_REPOSITORY=example/finite PR_NUMBER=1 "$@" finite-trusted-update
}

reset_fixture() {
	: >"$MOCK_LOG"
	rm -f "$MOCK_READS"
}

# Native GitHub requirements own pending/failed/unknown checks and behind-base
# PRs. The helper does not claim those checks passed or change the reviewed head.
for merge_state in CLEAN BLOCKED UNSTABLE UNKNOWN BEHIND; do
	export MOCK_MERGE_STATE=$merge_state MOCK_MODE=valid
	reset_fixture
	run_validator >"$test_root/output"
	[[ $(cat "$MOCK_READS") == 2 ]]
	[[ $(grep -c '^gh pr merge ' "$MOCK_LOG") == 1 ]]
	[[ $(wc -l <"$MOCK_LOG") == 3 ]]
	grep -qF 'Native continuation requested' "$test_root/output"
	grep -qF 'remain pending until GitHub confirms them' "$test_root/output"
	if [[ $merge_state == BEHIND ]]; then grep -qF 'preserving' "$test_root/output"; fi
done

# Every denial, including a failed final read or same-PR metadata mutation,
# occurs before the only mutating request.
export MOCK_MERGE_STATE=CLEAN
for mode in author repository branch base title closed number sha files empty-files missing-files \
	truncated-files duplicate-files malformed read-failed final-read-failed changed-head \
	final-author final-base final-closed final-files; do
	export MOCK_MODE=$mode
	reset_fixture
	if run_validator >"$test_root/output" 2>"$test_root/error"; then
		echo "Continuation accepted invalid fixture: $mode" >&2
		exit 1
	fi
	if grep -q '^gh pr merge ' "$MOCK_LOG"; then
		echo "Continuation mutated after rejecting fixture: $mode" >&2
		exit 1
	fi
done

# Invalid invocation identities and missing credentials fail before any API call.
for override in GH_TOKEN= PR_NUMBER=0 PR_NUMBER=abc GITHUB_REPOSITORY=invalid EXPECTED_AUTHOR=; do
	reset_fixture
	if run_validator "$override" >"$test_root/output" 2>"$test_root/error"; then exit 1; fi
	[[ ! -s $MOCK_LOG ]]
done

# A failed mutation can have an uncertain server outcome. Never issue another
# mutation or invent a successful merge/validation result.
export MOCK_MODE=merge-failed
reset_fixture
if run_validator >"$test_root/output" 2>"$test_root/error"; then exit 1; else status=$?; fi
[[ $status == 9 ]]
[[ $(grep -c '^gh pr merge ' "$MOCK_LOG") == 1 ]]
grep -qF 'outcome is unconfirmed' "$test_root/error"
grep -qF 'no mutation retry was attempted' "$test_root/error"
if grep -qF 'Native continuation requested' "$test_root/output"; then exit 1; fi

# A later explicit invocation revalidates the same head, then delegates
# idempotent auto-merge/queue state to GitHub instead of polling child runs.
export MOCK_MODE=valid
reset_fixture
run_validator >/dev/null
run_validator >/dev/null
[[ $(cat "$MOCK_READS") == 4 ]]
[[ $(grep -c '^gh pr merge ' "$MOCK_LOG") == 2 ]]
printf 'Native dependency continuation fixtures passed\n'
