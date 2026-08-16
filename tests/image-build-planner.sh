#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT
fake_bin="${test_root}/bin"
install -d "${fake_bin}"

# The following single-quoted strings intentionally generate mock executables.
printf '%s\n' \
	'#!/usr/bin/env bash' \
	'set -euo pipefail' \
	'input="${FAKE_PUBLISHED_INPUT}"' \
	'[[ "$*" != *"support-generic"* ]] || input="${FAKE_CHILD_PUBLISHED_INPUT:-${input}}"' \
	'parent_digest=sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd' \
	'[[ "$*" != *"support-generic"* ]] || parent_digest="${FAKE_CHILD_PARENT_DIGEST:-${parent_digest}}"' \
	'jq -cn --arg input "${input}" --arg base "${FAKE_PUBLISHED_BASE}" --arg parent "${parent_digest}" '\''{Digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", Labels: {"io.purplefin.build.input": $input, "io.purplefin.upstream.digest": $base, "io.purplefin.parent.digest": $parent}}'\''' \
	>"${fake_bin}/skopeo"

printf '%s\n' \
	'#!/usr/bin/env bash' \
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
chmod 0755 "${fake_bin}/skopeo" "${fake_bin}/podman"

export PATH="${fake_bin}:${PATH}"
export BASE_DIGEST=sha256:base
export BASE_REF=ghcr.io/projectbluefin/bluefin@sha256:base
export IMAGE_REF=ghcr.io/example/purplefin
export FAKE_PUBLISHED_BASE="${BASE_DIGEST}"
export FAKE_PODMAN_RUN_LOG="${test_root}/podman-run.log"
profile='[{"profile":"base","parent":null,"tags":"base","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]'
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

export CHECK_RPM_UPDATES=false
export FAKE_PODMAN_FAIL=true
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0

export FORCE_REBUILD=true
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = base
unset FORCE_REBUILD

export CHECK_RPM_UPDATES=true
export FAKE_PODMAN_FAIL=false
export FAKE_DNF_STATUS=0
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -q -- '--enable-repo=tailscale-stable' "${FAKE_PODMAN_RUN_LOG}"
grep -qw tailscale "${FAKE_PODMAN_RUN_LOG}"
grep -qw -- '-y' "${FAKE_PODMAN_RUN_LOG}"
if grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"; then
	exit 1
fi

export FAKE_ESPANSO_RPM=true
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"
grep -q -- '--enable-repo=terra' "${FAKE_PODMAN_RUN_LOG}"

export FAKE_DNF_STATUS=100
export FAKE_LAYERED_RPM=false
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base

profiles='[
  {"profile":"base","parent":null,"tags":"base","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  {"profile":"base-generic","parent":"base","tags":"generic-x86_64 latest","build_input":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  {"profile":"support-generic","parent":"base-generic","tags":"support-generic","build_input":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
]'
export CHECK_RPM_UPDATES=false
export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PUBLISHED_INPUT=old-support-source
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = support-generic
test "$(jq -r '.include[0].parent_digest' <<<"${matrix}")" = sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
test "$(jq -r '.include[0].parent_tag' <<<"${matrix}")" = generic-x86_64

export FAKE_PUBLISHED_INPUT=old-base-source
export FAKE_CHILD_PUBLISHED_INPUT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = 'base base-generic support-generic'

export FAKE_PUBLISHED_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export FAKE_CHILD_PARENT_DIGEST=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profiles}")"
test "$(jq -r '[.include[].profile] | join(" ")' <<<"${matrix}")" = support-generic
unset FAKE_CHILD_PARENT_DIGEST

export FAKE_DNF_STATUS=0
export FAKE_PUBLISHED_INPUT=old-source-state
matrix="$(cd "${repo_root}" && bootc/build/plan.sh "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base
