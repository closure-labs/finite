#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
fake_bin="${test_root}/bin"
install -d "${fake_bin}"

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'[[ "${FAKE_SKOPEO_FAIL:-false}" != true ]]' \
	'printf '\''%s\n'\'' "${FAKE_METADATA}"' \
	>"${fake_bin}/skopeo"

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'printf '\''%s\n'\'' "$*" >"${FAKE_COSIGN_LOG}"' \
	'[[ "${FAKE_COSIGN_FAIL:-false}" != true ]]' \
	>"${fake_bin}/cosign"
chmod 0755 "${fake_bin}/skopeo" "${fake_bin}/cosign"

export PATH="${fake_bin}:${PATH}"
export BUILD_INPUT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export BUILD_PROFILE=bluefin-generic
export COSIGN_IDENTITY=https://github.com/example/finite/.github/workflows/build-profile.yml@refs/heads/main
export EXPECTED_PARENT_DIGEST=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
export EXPECTED_REVISION=cccccccccccccccccccccccccccccccccccccccc
export EXPECTED_UPSTREAM_DIGEST=sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
export EXPECTED_VERSION=1.2.3
export IMAGE_REF=ghcr.io/example/finite
export FAKE_COSIGN_LOG="${test_root}/cosign.log"
export FINITE_COSIGN="${fake_bin}/cosign"
export FINITE_SKOPEO="${fake_bin}/skopeo"
digest=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee

metadata() {
	jq -cn \
		--arg build_input "${BUILD_INPUT}" \
		--arg digest "${digest}" \
		--arg foundation bluefin \
		--arg hardware generic-x86_64 \
		--arg parent_digest "${EXPECTED_PARENT_DIGEST}" \
		--arg profile "${BUILD_PROFILE}" \
		--arg revision "${1:-${EXPECTED_REVISION}}" \
		--arg upstream_digest "${EXPECTED_UPSTREAM_DIGEST}" \
		--arg version "${EXPECTED_VERSION}" '
		{
			Digest: $digest,
			Labels: {
				"io.finite.build.input": $build_input,
				"io.finite.build.profile": $profile,
				"io.finite.foundation": $foundation,
				"io.finite.hardware": $hardware,
				"io.finite.upstream.digest": $upstream_digest,
				"org.opencontainers.image.base.digest": $parent_digest,
				"org.opencontainers.image.revision": $revision,
				"org.opencontainers.image.version": $version
			}
		}'
}

FAKE_METADATA="$(metadata)"
export FAKE_METADATA
actual="$(finite-image-reuse generic-x86_64)"
test "${actual}" = "${digest}"
grep -qF -- "--certificate-identity ${COSIGN_IDENTITY}" "${FAKE_COSIGN_LOG}"
grep -qF "${IMAGE_REF}@${digest}" "${FAKE_COSIGN_LOG}"

FAKE_METADATA="$(metadata old-revision)"
export FAKE_METADATA
actual="$(finite-image-reuse generic-x86_64)"
test -z "${actual}"

FAKE_METADATA="$(metadata)"
export FAKE_METADATA
export FAKE_COSIGN_FAIL=true
actual="$(finite-image-reuse generic-x86_64)"
test -z "${actual}"
