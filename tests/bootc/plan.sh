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
	'profile=base' \
	'parent_profile=' \
	'if [[ "$*" == *"support-generic"* ]]; then profile=support-generic; parent_profile=base-generic; fi' \
	'if [[ "$*" == *"generic-x86_64"* ]]; then profile=base-generic; parent_profile=base; fi' \
	'[[ "$*" != *"support-generic"* ]] || input="${FAKE_CHILD_PUBLISHED_INPUT:-${input}}"' \
	'parent_digest=sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd' \
	'[[ "$*" != *"support-generic"* ]] || parent_digest="${FAKE_CHILD_PARENT_DIGEST:-${parent_digest}}"' \
	'jq -cn --arg input "${input}" --arg base "${FAKE_PUBLISHED_BASE}" --arg parent "${parent_digest}" --arg parent_profile "${parent_profile}" --arg profile "${profile}" --arg revision "${FAKE_PUBLISHED_REVISION:-}" --arg version "${EXPECTED_VERSION}" '\''{Digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", Labels: {"io.purplefin.build.input": $input, "io.purplefin.build.profile": $profile, "io.purplefin.upstream.digest": $base, "io.purplefin.parent.digest": $parent, "io.purplefin.parent.profile": $parent_profile, "org.opencontainers.image.revision": $revision, "org.opencontainers.image.version": $version}}'\''' \
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

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'[[ "${FAKE_PODMAN_FAIL:-false}" != true ]] || exit 9' \
	'case "${1:-}" in' \
	'  pull) exit 0 ;;' \
	'  run)' \
	'    if [[ " $* " == *" --entrypoint rpm "* ]]; then' \
	'      printf '\''bash\t0:5.2-1\tx86_64\ntailscale\t0:1.98.9-1\tx86_64\n'\''' \
	'      is_base=false' \
	'      for argument in "$@"; do' \
	'        [[ "${argument}" == "${BASE_REF}" ]] && is_base=true' \
	'      done' \
	'      [[ "${is_base}" == true || "${FAKE_LAYERED_RPM:-true}" != true ]] || printf '\''fuse\t0:2.9-1\tx86_64\n'\''' \
	'      [[ "${FAKE_ESPANSO_RPM:-false}" != true ]] || printf '\''espanso-wayland\t0:2.4.0-1.fc44\tx86_64\n'\''' \
	'      exit 0' \
	'    fi' \
	'    printf '\''%s\n'\'' "$*" >"${FAKE_PODMAN_RUN_LOG}"' \
	'    exit "${FAKE_DNF_STATUS}"' \
	'    ;;' \
	'  *) exit 2 ;;' \
	'esac' \
	>"${fake_bin}/podman"
chmod 0755 "${fake_bin}/skopeo" "${fake_bin}/gh" "${fake_bin}/podman"

export PATH="${fake_bin}:${PATH}"
export PURPLEFIN_PODMAN="${fake_bin}/podman"
export PURPLEFIN_SKOPEO="${fake_bin}/skopeo"
export BASE_DIGEST=sha256:base
export BASE_REF=ghcr.io/projectbluefin/bluefin@sha256:base
export EXPECTED_VERSION=testing
export IMAGE_REF=ghcr.io/example/purplefin
export FAKE_PUBLISHED_BASE="${BASE_DIGEST}"
export FAKE_PODMAN_RUN_LOG="${test_root}/podman-run.log"
profile='[{"profile":"base","parent":null,"tags":"base","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]'
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

export CHECK_RPM_UPDATES=false
export FAKE_PODMAN_FAIL=true
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0

export FORCE_REBUILD=true
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = base
test "$(jq -r '.include[0].reuse_existing' <<<"${matrix}")" = false
unset FORCE_REBUILD

export CHECK_RPM_UPDATES=true
export FAKE_PODMAN_FAIL=false
export FAKE_DNF_STATUS=0
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -q -- '--enable-repo=tailscale-stable' "${FAKE_PODMAN_RUN_LOG}"
grep -qw tailscale "${FAKE_PODMAN_RUN_LOG}"
grep -qw -- '-y' "${FAKE_PODMAN_RUN_LOG}"
if grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"; then
	exit 1
fi

export FAKE_ESPANSO_RPM=true
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"
grep -q -- '--enable-repo=terra' "${FAKE_PODMAN_RUN_LOG}"

export FAKE_DNF_STATUS=100
export FAKE_LAYERED_RPM=false
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base
test "$(jq -r '.include[0].reuse_existing' <<<"${matrix}")" = false

export CHECK_PUBLICATION_TRUST=true
export CHECK_RPM_UPDATES=false
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_PUBLISHED_REVISION=0123456789abcdef0123456789abcdef01234567
export FAKE_PROVENANCE_OK=true
export FAKE_SBOM_OK=false
export GITHUB_REPOSITORY=example/purplefin
export PURPLEFIN_COSIGN=true
export PURPLEFIN_GH="${fake_bin}/gh"
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
jq -e '
	(.include | length) == 0 and
	(.sbom_repair | length) == 1 and
	.sbom_repair[0].profile == "base" and
	.sbom_repair[0].subject_tag == "base" and
	.sbom_repair[0].source_digest == "0123456789abcdef0123456789abcdef01234567"
' <<<"${matrix}" >/dev/null

export FAKE_SBOM_OK=true
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
jq -e '(.include | length) == 0 and (.sbom_repair | length) == 0' <<<"${matrix}" >/dev/null

export PURPLEFIN_COSIGN=false
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
jq -e '
	(.include | length) == 1 and
	.include[0].profile == "base" and
	.include[0].reuse_existing == false and
	(.sbom_repair | length) == 0
' <<<"${matrix}" >/dev/null
unset CHECK_PUBLICATION_TRUST FAKE_PROVENANCE_OK FAKE_PUBLISHED_REVISION FAKE_SBOM_OK
unset GITHUB_REPOSITORY PURPLEFIN_COSIGN PURPLEFIN_GH

profiles='[
  {"profile":"base","parent":null,"tags":"base","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  {"profile":"base-generic","parent":"base","tags":"generic-x86_64 latest","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  {"profile":"support-generic","parent":"base-generic","tags":"support-generic","build_input":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
]'
export CHECK_RPM_UPDATES=false
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PUBLISHED_INPUT=old-support-source
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = support-generic
test "$(jq -r '.include[0].reuse_existing' <<<"${matrix}")" = true
test "$(jq -r '.include[0].parent_digest' <<<"${matrix}")" = sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
test "$(jq -r '.include[0].parent_tag' <<<"${matrix}")" = generic-x86_64

export FAKE_PUBLISHED_INPUT=old-base-source
export FAKE_CHILD_PUBLISHED_INPUT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = 'base base-generic support-generic'
test "$(jq -r '.include[] | select(.profile == "base-generic") | .parent_tag' <<<"${matrix}")" = base-candidate
test "$(jq -r '.include[] | select(.profile == "support-generic") | .parent_tag' <<<"${matrix}")" = base-generic-candidate

export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PARENT_DIGEST=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = support-generic
unset FAKE_CHILD_PARENT_DIGEST

export FAKE_DNF_STATUS=0
export FAKE_PUBLISHED_INPUT=old-source-state
matrix="$(cd "${repo_root}" && purplefin-image-plan "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base
