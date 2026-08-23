#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT
fake_bin="${test_root}/bin"
install -d "${fake_bin}"

# The following single-quoted strings intentionally generate mock executables.
printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'input="${FAKE_PUBLISHED_INPUT}"' \
	'profile=root-profile' \
	'parent_profile=' \
	'if [[ "$*" == *"target-profile"* ]]; then profile=target-profile; parent_profile=hardware-profile; fi' \
	'if [[ "$*" == *"hardware-profile"* ]]; then profile=hardware-profile; parent_profile=root-profile; fi' \
	'[[ "$*" != *"target-profile"* ]] || input="${FAKE_CHILD_PUBLISHED_INPUT:-${input}}"' \
	'parent_digest=sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd' \
	'[[ "$*" != *"target-profile"* ]] || parent_digest="${FAKE_CHILD_PARENT_DIGEST:-${parent_digest}}"' \
	'jq -cn --arg input "${input}" --arg base "${FAKE_PUBLISHED_BASE}" --arg parent "${parent_digest}" --arg parent_profile "${parent_profile}" --arg profile "${profile}" --arg revision "${FAKE_PUBLISHED_REVISION:-}" --arg version "${EXPECTED_VERSION}" '\''{Digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", Labels: {"io.finite.build.input": $input, "io.finite.build.profile": $profile, "io.finite.upstream.digest": $base, "io.finite.parent.digest": $parent, "io.finite.parent.profile": $parent_profile, "org.opencontainers.image.revision": $revision, "org.opencontainers.image.version": $version}}'\''' \
	>"${fake_bin}/skopeo"

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'if [[ "$*" == *"https://spdx.dev/Document/v2.3"* ]]; then' \
	'  [[ "${FAKE_SBOM_OK:-false}" == true ]]' \
	'else' \
	'  [[ "${FAKE_PROVENANCE_OK:-false}" == true ]]' \
	'fi' \
	>"${fake_bin}/gh"

chmod 0755 "${fake_bin}/skopeo" "${fake_bin}/gh"

export PATH="${fake_bin}:${PATH}"
export FINITE_SKOPEO="${fake_bin}/skopeo"
BASE_DIGEST="sha256:$(printf 'd%.0s' {1..64})"
export BASE_DIGEST
export EXPECTED_VERSION=testing
export IMAGE_REF=ghcr.io/example/finite
export FAKE_PUBLISHED_BASE="${BASE_DIGEST}"
profile="$(jq -cn --arg digest "${BASE_DIGEST}" '[{"profile":"root-profile","parent":null,"tags":"root-profile","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","upstream":{"image":"ghcr.io/ublue-os/bluefin","tag":"stable","digest":$digest}}]')"
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0

export FORCE_REBUILD=true
matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = root-profile
test "$(jq -r '.include[0].reuse_existing' <<<"${matrix}")" = false
unset FORCE_REBUILD

export CHECK_PUBLICATION_TRUST=true
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_PUBLISHED_REVISION=0123456789abcdef0123456789abcdef01234567
export FAKE_PROVENANCE_OK=true
export FAKE_SBOM_OK=false
export GITHUB_REPOSITORY=example/finite
export FINITE_COSIGN=true
export FINITE_GH="${fake_bin}/gh"
matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
jq -e '
	(.include | length) == 0 and
	(.sbom_repair | length) == 1 and
	.sbom_repair[0].profile == "root-profile" and
	.sbom_repair[0].subject_tag == "root-profile" and
	.sbom_repair[0].source_digest == "0123456789abcdef0123456789abcdef01234567"
' <<<"${matrix}" >/dev/null

export FAKE_SBOM_OK=true
matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
jq -e '(.include | length) == 0 and (.sbom_repair | length) == 0' <<<"${matrix}" >/dev/null

export FINITE_COSIGN=false
matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
jq -e '
	(.include | length) == 1 and
	.include[0].profile == "root-profile" and
	.include[0].reuse_existing == false and
	(.sbom_repair | length) == 0
' <<<"${matrix}" >/dev/null
unset CHECK_PUBLICATION_TRUST FAKE_PROVENANCE_OK FAKE_PUBLISHED_REVISION FAKE_SBOM_OK
unset GITHUB_REPOSITORY FINITE_COSIGN FINITE_GH

profiles="$(jq -cn --arg digest "${BASE_DIGEST}" '
  {image:"ghcr.io/ublue-os/bluefin",tag:"stable",digest:$digest} as $upstream | [
    {profile:"root-profile",parent:null,tags:"root-profile",build_input:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",upstream:$upstream},
    {profile:"hardware-profile",parent:"root-profile",tags:"hardware-profile",build_input:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",upstream:$upstream},
    {profile:"target-profile",parent:"hardware-profile",tags:"target-profile",build_input:"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",upstream:$upstream}
  ]')"
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PUBLISHED_INPUT=old-target-source
matrix="$(cd "${repo_root}" && finite-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = target-profile
test "$(jq -r '.include[0].reuse_existing' <<<"${matrix}")" = true
test "$(jq -r '.include[0].parent_digest' <<<"${matrix}")" = sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
test "$(jq -r '.include[0].parent_tag' <<<"${matrix}")" = hardware-profile

export FAKE_PUBLISHED_INPUT=old-root-source
export FAKE_CHILD_PUBLISHED_INPUT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
matrix="$(cd "${repo_root}" && finite-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = 'root-profile hardware-profile target-profile'
test "$(jq -r '.include[] | select(.profile == "hardware-profile") | .parent_tag' <<<"${matrix}")" = root-profile-candidate
test "$(jq -r '.include[] | select(.profile == "target-profile") | .parent_tag' <<<"${matrix}")" = hardware-profile-candidate

export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PARENT_DIGEST=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
matrix="$(cd "${repo_root}" && finite-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = target-profile
unset FAKE_CHILD_PARENT_DIGEST

export FAKE_PUBLISHED_INPUT=old-source-state
matrix="$(cd "${repo_root}" && finite-image-plan "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = root-profile
