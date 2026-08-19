#!/usr/bin/env bash
set -euo pipefail

profiles_json="${1:?usage: shard-plan.sh PROFILES_JSON SELECTED_MATRIX [MAX_SHARDS]}"
selected_json="${2:?usage: shard-plan.sh PROFILES_JSON SELECTED_MATRIX [MAX_SHARDS]}"
max_shards="${3:-4}"

[[ "${max_shards}" =~ ^[1-9][0-9]*$ ]] || {
	echo "MAX_SHARDS must be a positive integer" >&2
	exit 2
}

jq -cen \
	--argjson profiles "${profiles_json}" \
	--argjson selected "${selected_json}" \
	--argjson max_shards "${max_shards}" '
	def invalid(message): error(message);
	def valid_profile:
		type == "object" and
		(.profile | type == "string" and length > 0) and
		(.build_input | type == "string" and test("^[0-9a-f]{64}$")) and
		(.tags | type == "string" and length > 0);
	def lineage($name):
		[$name] +
		(first($profiles[] | select(.profile == $name)).parent as $parent |
			if $parent == null then [] else lineage($parent) end);
	if ($profiles | type) != "array" or ($selected | type) != "object" or
		($selected.include | type) != "array" then
		invalid("profiles must be an array and selection must contain an include array")
	elif any($profiles[]; valid_profile | not) or any($selected.include[]; valid_profile | not) then
		invalid("profile data is invalid")
	elif ([$profiles[].profile] | length) != ([$profiles[].profile] | unique | length) or
		([$selected.include[].profile] | length) != ([$selected.include[].profile] | unique | length) then
		invalid("profile data contains duplicates")
elif any($selected.include[]; . as $entry | all($profiles[]; .profile != $entry.profile)) then
		invalid("selection contains an unknown profile")
	else
		($selected.include | length) as $count |
		([$count, $max_shards] | min) as $shard_count |
		([$selected.include[].profile]) as $selected_names |
		{
			include: [
				range(0; $shard_count) as $shard |
				[
					($selected.include | to_entries[]) |
					select((.key % $shard_count) == $shard) |
					.value.profile
				] as $targets |
				([$targets[] | lineage(.)[]] | unique) as $needed |
				[
					$profiles[] as $decl |
      select(($needed | index($decl.profile)) != null) |
      select(($selected_names | index($decl.profile)) != null) |
      first($selected.include[] | select(.profile == $decl.profile)) |
      . as $entry |
      $entry + {target: (($targets | index($entry.profile)) != null)}
				] as $entries |
				{
					shard: ($shard + 1),
					name: ($targets | join(", ")),
					profiles: $entries
				}
			]
		}
	end
'
