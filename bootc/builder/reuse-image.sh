#!/usr/bin/env bash
set -euo pipefail

primary_tag="${1:?usage: reuse-image.sh PRIMARY_TAG}"
: "${BUILD_INPUT:?BUILD_INPUT is required}"
: "${BUILD_PROFILE:?BUILD_PROFILE is required}"
: "${COSIGN_IDENTITY:?COSIGN_IDENTITY is required}"
: "${EXPECTED_PARENT_DIGEST:?EXPECTED_PARENT_DIGEST is required}"
: "${EXPECTED_REVISION:?EXPECTED_REVISION is required}"
: "${EXPECTED_UPSTREAM_DIGEST:?EXPECTED_UPSTREAM_DIGEST is required}"
: "${EXPECTED_VERSION:?EXPECTED_VERSION is required}"
: "${IMAGE_REF:?IMAGE_REF is required}"

published_ref="${IMAGE_REF}:${primary_tag}"
if ! metadata="$(skopeo inspect --retry-times 3 "docker://${published_ref}")"; then
	echo "${BUILD_PROFILE}: no readable published image to reuse" >&2
	exit 0
fi

if ! digest="$(jq -er '.Digest' <<<"${metadata}")" ||
	[[ ! "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "${BUILD_PROFILE}: published image has no immutable digest to reuse" >&2
	exit 0
fi

if ! jq -e \
	--arg build_input "${BUILD_INPUT}" \
	--arg parent_digest "${EXPECTED_PARENT_DIGEST}" \
	--arg profile "${BUILD_PROFILE}" \
	--arg revision "${EXPECTED_REVISION}" \
	--arg upstream_digest "${EXPECTED_UPSTREAM_DIGEST}" \
	--arg version "${EXPECTED_VERSION}" '
		(.Labels // {}) as $labels |
		$labels["io.purplefin.build.input"] == $build_input and
		$labels["io.purplefin.build.profile"] == $profile and
		$labels["io.purplefin.upstream.digest"] == $upstream_digest and
		$labels["org.opencontainers.image.base.digest"] == $parent_digest and
		$labels["org.opencontainers.image.revision"] == $revision and
		$labels["org.opencontainers.image.version"] == $version
	' <<<"${metadata}" >/dev/null; then
	echo "${BUILD_PROFILE}: published image does not match the requested build" >&2
	exit 0
fi

immutable_ref="${IMAGE_REF}@${digest}"
if ! cosign verify \
	--certificate-oidc-issuer https://token.actions.githubusercontent.com \
	--certificate-identity "${COSIGN_IDENTITY}" \
	"${immutable_ref}" >/dev/null; then
	echo "${BUILD_PROFILE}: matching image is not signed by the trusted build workflow" >&2
	exit 0
fi

echo "${BUILD_PROFILE}: reuse ${immutable_ref}" >&2
printf '%s\n' "${digest}"
