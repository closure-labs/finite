#!/usr/bin/env bash
set -euo pipefail

matrix_json="${1:?usage: shard-plan.sh MATRIX_JSON [MAX_SHARDS]}"
max_shards="${2:-4}"

[[ "${max_shards}" =~ ^[1-9][0-9]*$ ]] || {
	echo "MAX_SHARDS must be a positive integer" >&2
	exit 2
}

jq -cen \
	--argjson matrix "${matrix_json}" \
	--argjson max_shards "${max_shards}" '
	def invalid(message): error(message);
	if ($matrix | type) != "object" or ($matrix.include | type) != "array" then
		invalid("matrix must contain an include array")
	else
		$matrix.include
	end as $profiles |
	if any($profiles[];
		(type != "object") or
		(.profile | type != "string" or length == 0) or
		(.build_input | type != "string" or test("^[0-9a-f]{64}$") | not) or
		(.tags | type != "string" or length == 0)
	) then
		invalid("matrix contains an invalid profile entry")
	elif ([$profiles[].profile] | length) != ([$profiles[].profile] | unique | length) then
		invalid("matrix contains duplicate profiles")
	else
		($profiles | length) as $profile_count |
		([$profile_count, $max_shards] | min) as $shard_count |
		{
			include: [
				range(0; $shard_count) as $shard |
				[
					($profiles | to_entries[]) |
					select((.key % $shard_count) == $shard) |
					.value
				] as $selected |
				{
					shard: ($shard + 1),
					name: ($selected | map(.profile) | join(", ")),
					profiles: $selected
				}
			]
		}
	end
'
