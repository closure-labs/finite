#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT
fake_bin="${test_root}/bin"
install -d "${fake_bin}"

printf '%s\n' \
	'#!/usr/bin/env bash' \
	'set -euo pipefail' \
	'jq -cn --arg input "${FAKE_PUBLISHED_INPUT}" --arg base "${FAKE_PUBLISHED_BASE}" '\''{Labels: {"io.purplefin.build.input": $input, "org.opencontainers.image.base.digest": $base}}'\''' \
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
export BASE_REF=ghcr.io/projectbluefin/bluefin:stable
export BUILD_INPUT=source-state
export IMAGE_REF=ghcr.io/example/purplefin
export FAKE_PUBLISHED_BASE="${BASE_DIGEST}"
export FAKE_PUBLISHED_INPUT="${BUILD_INPUT}"
export FAKE_PODMAN_RUN_LOG="${test_root}/podman-run.log"
profile='[{"profile":"base-generic","tags":"generic-x86_64 latest"}]'

export CHECK_RPM_UPDATES=false
export FAKE_PODMAN_FAIL=true
matrix="$(cd "${repo_root}" && build_files/plan-image-builds.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0

export CHECK_RPM_UPDATES=true
export FAKE_PODMAN_FAIL=false
export FAKE_DNF_STATUS=0
matrix="$(cd "${repo_root}" && build_files/plan-image-builds.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -q -- '--enable-repo=tailscale-stable' "${FAKE_PODMAN_RUN_LOG}"
grep -qw tailscale "${FAKE_PODMAN_RUN_LOG}"
grep -qw -- '-y' "${FAKE_PODMAN_RUN_LOG}"
! grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"

export FAKE_ESPANSO_RPM=true
matrix="$(cd "${repo_root}" && build_files/plan-image-builds.sh "${profile}")"
test "$(jq '.include | length' <<<"${matrix}")" -eq 0
grep -qw espanso-wayland "${FAKE_PODMAN_RUN_LOG}"
grep -q -- '--enable-repo=terra' "${FAKE_PODMAN_RUN_LOG}"

export FAKE_DNF_STATUS=100
export FAKE_LAYERED_RPM=false
matrix="$(cd "${repo_root}" && build_files/plan-image-builds.sh "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base-generic

export FAKE_DNF_STATUS=0
export FAKE_PUBLISHED_INPUT=old-source-state
matrix="$(cd "${repo_root}" && build_files/plan-image-builds.sh "${profile}")"
test "$(jq -r '.include[0].profile' <<<"${matrix}")" = base-generic
