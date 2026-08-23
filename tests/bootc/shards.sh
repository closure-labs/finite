#!/usr/bin/env bash
set -euo pipefail

profiles="$({
	jq -cn '
		[{
			profile: "base",
			build_input: ("a" * 64),
			tags: "base",
			stage: "root",
			parent: null
		}] +
		[range(0; 4) as $index | {
			profile: "hardware-\($index)",
			build_input: ("a" * 64),
			tags: "hardware-\($index)",
			stage: "hardware",
			parent: "base"
		}] +
		[range(0; 8) as $index | {
			profile: "role-\($index)",
			build_input: ("a" * 64),
			tags: "role-\($index)",
			stage: "role",
			parent: "hardware-\($index % 4)"
		}]'
})"
matrix="$(jq -cn --argjson include "${profiles}" '{include: $include}')"
shards="$(finite-shard-plan "${profiles}" "${matrix}")"

jq -e '
	(.include | length) == 4 and
	([.include[].profiles[] | select(.target) | .profile] | length) == 13 and
	([.include[].profiles[] | select(.target) | .profile] | unique | length) == 13 and
	all(.include[].profiles[]; .target == true or .target == false) and
	all(.include[]; .estimated_cost > 0)
' <<<"${shards}" >/dev/null
jq -e '
	(.include[0].profiles | map(.profile)) == ["base", "hardware-0", "role-0", "role-4"] and
	.include[0].estimated_cost == 44
' <<<"${shards}" >/dev/null
jq -e '
	(.include[1].profiles | map(.profile)) == ["base", "hardware-1", "role-1", "role-5"] and
	(.include[1].profiles[0].target == false) and
	.include[1].estimated_cost == 34
' <<<"${shards}" >/dev/null

for count in $(seq 0 13); do
	selected="$(jq -c --argjson count "${count}" '.[0:$count]' <<<"${profiles}")"
	selected_matrix="$(jq -cn --argjson include "${selected}" '{include: $include}')"
	selected_shards="$(finite-shard-plan "${profiles}" "${selected_matrix}")"
	jq -e --argjson count "${count}" '
		(.include | length) == ([4, $count] | min) and
		all(.include[]; (.profiles | length) > 0) and
		([.include[].profiles[] | select(.target) | .profile] | length) == $count and
		([.include[].profiles[] | select(.target) | .profile] | unique | length) == $count
	' <<<"${selected_shards}" >/dev/null
done

duplicate="$(jq -cn --argjson profile "$(jq -c '.[0]' <<<"${profiles}")" '{include: [$profile, $profile]}')"
if finite-shard-plan "${profiles}" "${duplicate}" >/dev/null 2>&1; then
	echo "duplicate profiles must fail shard planning" >&2
	exit 1
fi
if finite-shard-plan '[]' "${matrix}" >/dev/null 2>&1; then
	echo "a non-object matrix must fail shard planning" >&2
	exit 1
fi
if finite-shard-plan "${profiles}" "${matrix}" 0 >/dev/null 2>&1; then
	echo "a zero shard limit must fail shard planning" >&2
	exit 1
fi

generated_root="${FINITE_GENERATED_ROOT:?FINITE_GENERATED_ROOT is required}"
valid_shard="$(jq -c '.[0:2] | map(. + {target: true})' "${generated_root}/bootc/generated/image-matrix.json")"
PROFILE_SHARD="${valid_shard}" \
	FINITE_GENERATED_ROOT="${generated_root}" \
	FINITE_LOAD_BLUEFIN=/not-used \
	FINITE_VERSION=testing \
	finite-validate-image-shard --check |
	jq -e --argjson expected "$(jq -c '.[0:2] | map(.profile)' "${generated_root}/bootc/generated/image-matrix.json")" '. == $expected' >/dev/null

unknown="$(jq -c '.[0] | .profile = "unknown" | [.]' "${generated_root}/bootc/generated/image-matrix.json")"
if PROFILE_SHARD="${unknown}" \
	FINITE_GENERATED_ROOT="${generated_root}" \
	FINITE_LOAD_BLUEFIN=/not-used \
	FINITE_VERSION=testing \
	finite-validate-image-shard --check >/dev/null 2>&1; then
	echo "unknown profiles must fail shard validation" >&2
	exit 1
fi

duplicated="$(jq -cn --argjson entry "$(jq -c '.[0]' "${generated_root}/bootc/generated/image-matrix.json")" '[$entry, $entry]')"
if PROFILE_SHARD="${duplicated}" \
	FINITE_GENERATED_ROOT="${generated_root}" \
	FINITE_LOAD_BLUEFIN=/not-used \
	FINITE_VERSION=testing \
	finite-validate-image-shard --check >/dev/null 2>&1; then
	echo "duplicate shard profiles must fail validation" >&2
	exit 1
fi

for invalid_shard in \
	'{}' \
	"$(jq -c '.[0] | .build_input = ("c" * 64) | [.]' "${generated_root}/bootc/generated/image-matrix.json")"; do
	if PROFILE_SHARD="${invalid_shard}" \
		FINITE_GENERATED_ROOT="${generated_root}" \
		FINITE_LOAD_BLUEFIN=/not-used \
		FINITE_VERSION=testing \
		finite-validate-image-shard --check >/dev/null 2>&1; then
		echo "malformed or stale shard contracts must fail validation" >&2
		exit 1
	fi
done
