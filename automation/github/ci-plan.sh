#!/usr/bin/env bash
(( $# == 1 )) || {
  echo "usage: nix run .#ci-plan -- GITHUB_OUTPUT" >&2
  exit 2
}
: "${IMAGE_REF:?IMAGE_REF is required}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
"${PURPLEFIN_VERIFY_BLUEFIN:?}" >/dev/null
base_image="${PURPLEFIN_BASE_IMAGE:?}"
base_tag="${PURPLEFIN_BASE_TAG:?}"
base_digest="${PURPLEFIN_BASE_DIGEST:?}"
base_ref="${base_image}@${base_digest}"
profiles="$(jq -c . "${PURPLEFIN_GENERATED_MATRIX:?}")"
export BASE_DIGEST="${base_digest}" BASE_REF="${base_ref}" EXPECTED_VERSION="${PURPLEFIN_VERSION:?}"
matrix="$("${PURPLEFIN_IMAGE_PLAN:?}" "${profiles}")"
root_base="$(jq -c 'first(.include[] | select(.stage == "root")) // {}' <<<"${matrix}")"
hardware_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"${matrix}")"
role_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"${matrix}")"
candidate_shards="$("${PURPLEFIN_SHARD_PLAN:?}" "${profiles}" "${matrix}" 4)"
sbom_matrix="$(jq -c --arg source_digest "${GITHUB_SHA}" \
  --argjson profiles "${profiles}" '
  ([.include[] | . + {
    source_digest: $source_digest,
    subject_tag: (.profile + "-candidate")
  }] + .sbom_repair) as $selected |
  {include: [
    $profiles[] as $decl |
    $selected[] |
    select(.profile == $decl.profile)
  ]}
' <<<"${matrix}")"
base_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "root")]}' <<<"${sbom_matrix}")"
hardware_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"${sbom_matrix}")"
role_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"${sbom_matrix}")"
{
  printf 'base_image=%s\n' "${base_image}"
  printf 'base_digest=%s\n' "${base_digest}"
  printf 'base_tag=%s\n' "${base_tag}"
  printf 'base_sbom_matrix=%s\n' "${base_sbom_matrix}"
  printf 'candidate_shards=%s\n' "${candidate_shards}"
  printf 'hardware_matrix=%s\n' "${hardware_matrix}"
  printf 'hardware_sbom_matrix=%s\n' "${hardware_sbom_matrix}"
  printf 'has_hardware=%s\n' "$(jq -r '.include | length > 0' <<<"${hardware_matrix}")"
  printf 'has_builds=%s\n' "$(jq -r '.include | length > 0' <<<"${matrix}")"
  printf 'has_roles=%s\n' "$(jq -r '.include | length > 0' <<<"${role_matrix}")"
  printf 'has_root_base=%s\n' "$(jq -r 'has("profile")' <<<"${root_base}")"
  printf 'has_base_sbom=%s\n' "$(jq -r '.include | length > 0' <<<"${base_sbom_matrix}")"
  printf 'has_hardware_sbom=%s\n' "$(jq -r '.include | length > 0' <<<"${hardware_sbom_matrix}")"
  printf 'has_role_sbom=%s\n' "$(jq -r '.include | length > 0' <<<"${role_sbom_matrix}")"
  printf 'matrix=%s\n' "${matrix}"
  printf 'role_matrix=%s\n' "${role_matrix}"
  printf 'role_sbom_matrix=%s\n' "${role_sbom_matrix}"
  printf 'root_base=%s\n' "${root_base}"
  printf 'version=%s\n' "${PURPLEFIN_VERSION}"
} >>"$1"
