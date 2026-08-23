#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
fake_skopeo="${test_root}/skopeo"
fake_oras="${test_root}/oras"
promotion_log="${test_root}/promotions"
auth_file="${test_root}/auth.json"
touch "${auth_file}"

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'profile=base' \
	'digest="sha256:$(printf '\''a%.0s'\'' {1..64})"' \
	'parent="${UPSTREAM_BASE_DIGEST}"' \
	'if [[ "$*" == *"hardware-candidate"* ]]; then' \
	'  profile=hardware' \
	'  digest="sha256:$(printf '\''b%.0s'\'' {1..64})"' \
	'  parent="${FAKE_HARDWARE_PARENT:-sha256:$(printf '\''a%.0s'\'' {1..64})}"' \
	'fi' \
	'jq -cn --arg digest "${digest}" --arg input "$(printf '\''c%.0s'\'' {1..64})" --arg parent "${parent}" --arg profile "${profile}" --arg revision "${GITHUB_SHA}" --arg upstream "${UPSTREAM_BASE_DIGEST}" --arg version "${VERSION}" '\''{Digest: $digest, Labels: {"io.finite.build.input": $input, "io.finite.build.profile": $profile, "io.finite.upstream.digest": $upstream, "org.opencontainers.image.base.digest": $parent, "org.opencontainers.image.revision": $revision, "org.opencontainers.image.version": $version}}'\''' \
	>"${fake_skopeo}"

printf '%s\n' \
	"#!${BASH}" \
	'set -euo pipefail' \
	'printf '\''%s\n'\'' "$*" >>"${PROMOTION_LOG}"' \
	>"${fake_oras}"
chmod 0755 "${fake_skopeo}" "${fake_oras}"

digest_a="sha256:$(printf 'a%.0s' {1..64})"
build_input="$(printf 'c%.0s' {1..64})"
BUILD_MATRIX="$({
	jq -cn --arg digest "${digest_a}" --arg input "${build_input}" --arg upstream "${UPSTREAM_BASE_DIGEST:-sha256:$(printf 'd%.0s' {1..64})}" '{include: [
		{profile: "base", parent: null, build_input: $input, tags: "base stable", upstream: {digest: $upstream}},
		{profile: "hardware", parent: "base", parent_digest: $digest,
		 build_input: $input, tags: "hardware latest", upstream: {digest: $upstream}}
	]}'
})"
export BUILD_MATRIX
export GITHUB_REPOSITORY=example/finite
export GITHUB_SHA=0123456789abcdef0123456789abcdef01234567
export IMAGE_REF=ghcr.io/example/finite
export PROMOTION_LOG="${promotion_log}"
export FINITE_COSIGN=true
export FINITE_GH=true
export FINITE_ORAS="${fake_oras}"
export FINITE_SKOPEO="${fake_skopeo}"
export REGISTRY_AUTH_FILE="${auth_file}"
UPSTREAM_BASE_DIGEST="sha256:$(printf 'd%.0s' {1..64})"
export UPSTREAM_BASE_DIGEST
export VERSION=testing

finite-promote-images
[[ "$(wc -l <"${promotion_log}")" == 2 ]]
grep -qF "${IMAGE_REF}@${digest_a} base stable" "${promotion_log}"
grep -qF 'hardware latest' "${promotion_log}"

rm -f "${promotion_log}"
FAKE_HARDWARE_PARENT="sha256:$(printf 'e%.0s' {1..64})"
export FAKE_HARDWARE_PARENT
if finite-promote-images >/dev/null 2>&1; then
	echo 'Promotion accepted a candidate with the wrong immutable parent' >&2
	exit 1
fi
[[ ! -e "${promotion_log}" ]]
