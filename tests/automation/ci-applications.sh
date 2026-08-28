#!/usr/bin/env bash
set -euo pipefail

github_output="${1:?usage: ci-applications.sh OUTPUT IMAGE_VERIFY PROFILE_STAGE RELEASE_CONTROL FIXTURES}"
image_verify="${2:?usage: ci-applications.sh OUTPUT IMAGE_VERIFY PROFILE_STAGE RELEASE_CONTROL FIXTURES}"
profile_stage="${3:?usage: ci-applications.sh OUTPUT IMAGE_VERIFY PROFILE_STAGE RELEASE_CONTROL FIXTURES}"
release_control="${4:?usage: ci-applications.sh OUTPUT IMAGE_VERIFY PROFILE_STAGE RELEASE_CONTROL FIXTURES}"
fixtures="${5:?usage: ci-applications.sh OUTPUT IMAGE_VERIFY PROFILE_STAGE RELEASE_CONTROL FIXTURES}"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
bash_path="$(type -P bash)"

make_executable() {
	local mock
	for mock in "$@"; do
		sed -i "1c\\#!${bash_path}" "${mock}"
		chmod +x "${mock}"
	done
}

set +e
GITHUB_OUTPUT="${test_root}/invalid-output" \
	"${github_output}" "${fixtures}/malformed.json" >"${test_root}/invalid-report"
invalid_status=$?
set -e
[[ ${invalid_status} -eq 2 ]]
[[ ! -s "${test_root}/invalid-output" ]]

valid_report='{"schema":1,"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","hit":false}'
printf '%s\n' "${valid_report}" >"${test_root}/valid.json"
GITHUB_OUTPUT="${test_root}/valid-output" \
	"${github_output}" "${test_root}/valid.json" >"${test_root}/normalized.json"
jq -e '.schema == 1 and .hit == false' "${test_root}/normalized.json" >/dev/null
grep -qFx 'hit=false' "${test_root}/valid-output"

set +e
"${image_verify}" \
	--image ghcr.io/example/finite \
	--digest invalid \
	--cosign-identity trusted >"${test_root}/invalid-digest.json"
invalid_digest_status=$?
set -e
[[ ${invalid_digest_status} -eq 2 ]]

cp "${fixtures}/image-metadata.json" "${test_root}/metadata.json"
cat >"${test_root}/skopeo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat "${FAKE_METADATA}"
EOF
cat >"${test_root}/cosign" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ " $* " == *" --certificate-identity trusted "* ]]
EOF
cat >"${test_root}/gh-retry" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -f "${FAKE_ATTESTATION_COUNT}" ]] || count="$(<"${FAKE_ATTESTATION_COUNT}")"
count=$((count + 1))
printf '%s\n' "${count}" >"${FAKE_ATTESTATION_COUNT}"
((count >= 2))
EOF
make_executable "${test_root}/skopeo" "${test_root}/cosign" "${test_root}/gh-retry"

set +e
FAKE_METADATA="${test_root}/metadata.json" \
FINITE_COSIGN="${test_root}/cosign" \
FINITE_SKOPEO="${test_root}/skopeo" \
	"${image_verify}" \
		--image ghcr.io/example/finite \
		--digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
		--cosign-identity wrong >"${test_root}/wrong-signer.json"
wrong_signer_status=$?
set -e
[[ ${wrong_signer_status} -eq 1 ]]

FAKE_ATTESTATION_COUNT="${test_root}/attestation-count" \
FAKE_METADATA="${test_root}/metadata.json" \
FINITE_ATTESTATION_RETRY_DELAY=0 \
FINITE_COSIGN="${test_root}/cosign" \
FINITE_GH="${test_root}/gh-retry" \
FINITE_SKOPEO="${test_root}/skopeo" \
GITHUB_REPOSITORY=example/finite \
	"${image_verify}" \
		--image ghcr.io/example/finite \
		--digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
		--cosign-identity trusted \
		--source-sha cccccccccccccccccccccccccccccccccccccccc \
		--provenance-workflow example/finite/.github/workflows/build-profile.yml \
		--expect-label io.finite.build.profile=bluefin-generic \
		--attempts 3 >"${test_root}/verified.json"
jq -e '.provenance_attempts == 2 and .cosign_verified == true' \
	"${test_root}/verified.json" >/dev/null

cat >"${test_root}/empty-reuse" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"${test_root}/success" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"${test_root}/stage-skopeo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == list-tags ]]; then
	exit 1
fi
if [[ " $* " == *" --format "* ]]; then
	printf '%s\n' 'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
else
	printf '%s\n' '{}'
fi
EOF
cat >"${test_root}/rechunk" <<'EOF'
#!/usr/bin/env bash
jq -cn '{digest:"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",mode:"passthrough",previous_build_digest:"none",rechunk_seconds:0}'
EOF
make_executable "${test_root}/empty-reuse" "${test_root}/success" \
	"${test_root}/stage-skopeo" "${test_root}/rechunk"

BUILD_INPUT=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee \
BUILD_PROFILE=bluefin-generic \
CACHE_WRITE=true \
COSIGN_IDENTITY=trusted \
EXPECTED_REVISION=ffffffffffffffffffffffffffffffffffffffff \
EXPECTED_UPSTREAM_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
EXPECTED_VERSION=1.2.3 \
FINITE_BUILDAH="${test_root}/success" \
FINITE_IMAGE_REUSE="${test_root}/empty-reuse" \
FINITE_RECHUNK_IMAGE="${test_root}/rechunk" \
FINITE_SKOPEO="${test_root}/stage-skopeo" \
FINITE_SOURCE_ROOT="$PWD" \
IMAGE_REF=ghcr.io/example/finite \
PARENT_DIGEST=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
PARENT_FROM_LOCK=false \
PARENT_IMAGE=ghcr.io/example/base \
REGISTRY_AUTH_FILE=/dev/null \
REUSE_EXISTING=true \
	"${profile_stage}" >"${test_root}/cache-miss.json"
jq -e '
	.reuse_hit == false and
	.cache_available == false and
	.build_outcome == "success" and
	.rechunk_outcome == "success"
' "${test_root}/cache-miss.json" >/dev/null

set +e
FINITE_REMOTE_SHA=1111111111111111111111111111111111111111 \
FORCE_REBUILD=true \
GITHUB_REPOSITORY=example/finite \
SOURCE_SHA=2222222222222222222222222222222222222222 \
	"${release_control}" candidate-run >"${test_root}/stale-source.json"
stale_status=$?
set -e
[[ ${stale_status} -eq 1 ]]

cat >"${test_root}/gh-closed" <<'EOF'
#!/usr/bin/env bash
jq -cn '{mergeCommit:null,mergedAt:null,state:"CLOSED"}'
EOF
make_executable "${test_root}/gh-closed"
set +e
FINITE_GH="${test_root}/gh-closed" \
FINITE_WAIT_ATTEMPTS=1 \
PR_NUMBER=42 \
	"${release_control}" wait-pr >"${test_root}/closed-pr.json"
closed_status=$?
set -e
[[ ${closed_status} -eq 1 ]]

mkdir -p "${test_root}/generated/bootc/generated"
cp "${fixtures}/partial-matrix.json" \
	"${test_root}/generated/bootc/generated/image-matrix.json"
cat >"${test_root}/promotion-skopeo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
reference="${*: -1}"
if [[ "${reference}" == *profile-two* ]]; then
	digest=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
	input=2222222222222222222222222222222222222222222222222222222222222222
	profile=profile-two
else
	digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
	input=1111111111111111111111111111111111111111111111111111111111111111
	profile=profile-one
fi
if [[ " $* " == *" --format "* ]]; then
	printf 'sha256:%s\n' "${digest}"
else
	jq -cn --arg digest "sha256:${digest}" --arg input "${input}" --arg profile "${profile}" '{Digest:$digest,Labels:{"org.opencontainers.image.base.digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","io.finite.build.input":$input,"io.finite.build.profile":$profile}}'
fi
EOF
cat >"${test_root}/image-verify-success" <<'EOF'
#!/usr/bin/env bash
jq -cn '{schema:1,digest:"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
EOF
cat >"${test_root}/sbom-success" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' '{"spdxVersion":"SPDX-2.3","packages":[]}' >"$2"
EOF
cat >"${test_root}/oras-partial" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -f "${FAKE_ORAS_COUNT}" ]] || count="$(<"${FAKE_ORAS_COUNT}")"
count=$((count + 1))
printf '%s\n' "${count}" >"${FAKE_ORAS_COUNT}"
((count < 2))
EOF
make_executable "${test_root}/promotion-skopeo" "${test_root}/image-verify-success" \
	"${test_root}/sbom-success" "${test_root}/oras-partial"
set +e
(
	cd "${test_root}"
	COSIGN_IDENTITY=trusted \
	FAKE_ORAS_COUNT="${test_root}/oras-count" \
	FINITE_GENERATED_ROOT="${test_root}/generated" \
	FINITE_IMAGE_VERIFY="${test_root}/image-verify-success" \
	FINITE_ORAS="${test_root}/oras-partial" \
	FINITE_SBOM_ATTESTATION="${test_root}/sbom-success" \
	FINITE_SKOPEO="${test_root}/promotion-skopeo" \
	GITHUB_REPOSITORY=example/finite \
	IMAGE_REF=ghcr.io/example/finite \
	REGISTRY_AUTH_FILE=/dev/null \
	SBOM_SIGNER_WORKFLOW=example/finite/.github/workflows/attest-software-bill-of-materials.yml \
	SOURCE_SHA=dddddddddddddddddddddddddddddddddddddddd \
	VERSION=1.2.3 \
		"${release_control}" promote >partial-promotion.json
)
partial_status=$?
set -e
[[ ${partial_status} -eq 1 ]]
[[ ! -e "${test_root}/release-manifest.json" ]]

git_root="${test_root}/release-git"
mkdir "${git_root}"
git -C "${git_root}" init -q
git -C "${git_root}" config user.email finite@example.invalid
git -C "${git_root}" config user.name Finite
printf '%s\n' '0.1.0-dev.0' >"${git_root}/VERSION"
git -C "${git_root}" add VERSION
git -C "${git_root}" commit -qm 'feat: initial release'
release_sha="$(git -C "${git_root}" rev-parse HEAD)"
(
	cd "${git_root}"
	FINITE_REMOTE_SHA="${release_sha}" \
	GITHUB_REPOSITORY=example/finite \
	GITHUB_SHA="${release_sha}" \
	REQUESTED_BUMP=auto \
		"${release_control}" select-version >select-version.json
	jq -e '.version == "0.1.0" and .selected_bump == "initial"' select-version.json >/dev/null
	FINITE_REMOTE_SHA="${release_sha}" \
	SOURCE_SHA="${release_sha}" \
	VERSION=0.1.0 \
		"${release_control}" next-version >next-version.json
	jq -e '.next_version == "0.1.1-dev.0"' next-version.json >/dev/null
)
