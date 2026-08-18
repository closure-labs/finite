#!/usr/bin/env bash
set -euo pipefail

profiles="$({
	jq -cn '[range(0; 12) as $index | {
		profile: "profile-\($index)",
		build_input: ("a" * 64),
		tags: "profile-\($index)",
		stage: "role",
		parent: "base"
	}]'
})"
matrix="$(jq -cn --argjson include "${profiles}" '{include: $include}')"
shards="$(bash bootc/builder/shard-plan.sh "${matrix}")"

jq -e '
	(.include | length) == 4 and
	([.include[].profiles[].profile] | length) == 12 and
	([.include[].profiles[].profile] | unique | length) == 12
' <<<"${shards}" >/dev/null
jq -e '
	.include[0].profiles | map(.profile) == ["profile-0", "profile-4", "profile-8"]
' <<<"${shards}" >/dev/null
jq -e '
	.include[3].profiles | map(.profile) == ["profile-3", "profile-7", "profile-11"]
' <<<"${shards}" >/dev/null

for count in $(seq 0 12); do
	selected="$(jq -c --argjson count "${count}" '.[0:$count]' <<<"${profiles}")"
	selected_matrix="$(jq -cn --argjson include "${selected}" '{include: $include}')"
	selected_shards="$(bash bootc/builder/shard-plan.sh "${selected_matrix}")"
	jq -e --argjson count "${count}" '
		(.include | length) == ([4, $count] | min) and
		all(.include[]; (.profiles | length) > 0) and
		([.include[].profiles[].profile] | length) == $count and
		([.include[].profiles[].profile] | unique | length) == $count
	' <<<"${selected_shards}" >/dev/null
done

duplicate="$(jq -cn --argjson profile "$(jq -c '.[0]' <<<"${profiles}")" '{include: [$profile, $profile]}')"
if bash bootc/builder/shard-plan.sh "${duplicate}" >/dev/null 2>&1; then
	echo "duplicate profiles must fail shard planning" >&2
	exit 1
fi
if bash bootc/builder/shard-plan.sh '[]' >/dev/null 2>&1; then
	echo "a non-object matrix must fail shard planning" >&2
	exit 1
fi
if bash bootc/builder/shard-plan.sh "${matrix}" 0 >/dev/null 2>&1; then
	echo "a zero shard limit must fail shard planning" >&2
	exit 1
fi

generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
valid_shard="$(jq -c '.[0:2]' "${generated_root}/bootc/generated/image-matrix.json")"
PROFILE_SHARD="${valid_shard}" \
	PURPLEFIN_GENERATED_ROOT="${generated_root}" \
	PURPLEFIN_BASE_DIGEST="sha256:$(printf 'b%.0s' {1..64})" \
	PURPLEFIN_LOAD_BLUEFIN=/not-used \
	PURPLEFIN_VERSION=testing \
	bash bootc/builder/validate-shard.sh --check |
	jq -e '. == ["base", "base-dell-xps-9350-intel"]' >/dev/null

unknown="$(jq -c '.[0] | .profile = "unknown" | [.]' "${generated_root}/bootc/generated/image-matrix.json")"
if PROFILE_SHARD="${unknown}" \
	PURPLEFIN_GENERATED_ROOT="${generated_root}" \
	PURPLEFIN_BASE_DIGEST="sha256:$(printf 'b%.0s' {1..64})" \
	PURPLEFIN_LOAD_BLUEFIN=/not-used \
	PURPLEFIN_VERSION=testing \
	bash bootc/builder/validate-shard.sh --check >/dev/null 2>&1; then
	echo "unknown profiles must fail shard validation" >&2
	exit 1
fi

duplicated="$(jq -cn --argjson entry "$(jq -c '.[0]' "${generated_root}/bootc/generated/image-matrix.json")" '[$entry, $entry]')"
if PROFILE_SHARD="${duplicated}" \
	PURPLEFIN_GENERATED_ROOT="${generated_root}" \
	PURPLEFIN_BASE_DIGEST="sha256:$(printf 'b%.0s' {1..64})" \
	PURPLEFIN_LOAD_BLUEFIN=/not-used \
	PURPLEFIN_VERSION=testing \
	bash bootc/builder/validate-shard.sh --check >/dev/null 2>&1; then
	echo "duplicate shard profiles must fail validation" >&2
	exit 1
fi

for invalid_shard in \
	'{}' \
	"$(jq -c '.[0] | .build_input = ("c" * 64) | [.]' "${generated_root}/bootc/generated/image-matrix.json")"; do
	if PROFILE_SHARD="${invalid_shard}" \
		PURPLEFIN_GENERATED_ROOT="${generated_root}" \
		PURPLEFIN_BASE_DIGEST="sha256:$(printf 'b%.0s' {1..64})" \
		PURPLEFIN_LOAD_BLUEFIN=/not-used \
		PURPLEFIN_VERSION=testing \
		bash bootc/builder/validate-shard.sh --check >/dev/null 2>&1; then
		echo "malformed or stale shard contracts must fail validation" >&2
		exit 1
	fi
done
