#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
git -C "${test_root}" init --quiet
git -C "${test_root}" config user.name Finite
git -C "${test_root}" config user.email finite@example.invalid

mkdir -p "${test_root}/docs"
printf '%s\n' '{}' >"${test_root}/flake.nix"
printf '%s\n' initial >"${test_root}/docs/notes.md"
git -C "${test_root}" add .
git -C "${test_root}" commit --quiet -m initial
base_sha="$(git -C "${test_root}" rev-parse HEAD)"

printf '%s\n' documentation >"${test_root}/docs/notes.md"
git -C "${test_root}" commit --quiet -am documentation
docs_sha="$(git -C "${test_root}" rev-parse HEAD)"

mkdir -p "${test_root}/bootc"
printf '%s\n' 'FROM scratch' >"${test_root}/bootc/Containerfile"
git -C "${test_root}" add bootc/Containerfile
git -C "${test_root}" commit --quiet -m image
image_sha="$(git -C "${test_root}" rev-parse HEAD)"

mkdir -p "${test_root}/installer"
printf '%s\n' 'FROM scratch' >"${test_root}/installer/Containerfile"
git -C "${test_root}" add installer/Containerfile
git -C "${test_root}" commit --quiet -m installer
installer_sha="$(git -C "${test_root}" rev-parse HEAD)"

printf '%s\n' 0.2.4 >"${test_root}/VERSION"
printf '%s\n' '# Changelog' >"${test_root}/CHANGELOG.md"
git -C "${test_root}" add VERSION CHANGELOG.md
git -C "${test_root}" commit --quiet -m release-metadata
release_sha="$(git -C "${test_root}" rev-parse HEAD)"

printf '%s\n' 'FROM scratch # changed' >"${test_root}/bootc/Containerfile"
git -C "${test_root}" commit --quiet -am release-with-image-change
release_image_sha="$(git -C "${test_root}" rev-parse HEAD)"

classify_event() {
	local expected_images=$1
	local expected_installer=$2
	shift 2
	local output
	output="$(mktemp)"
	env FINITE_SOURCE_ROOT="${test_root}" "$@" \
		finite-classify-ci "${output}"
	classification="$(sed -n 's/^classification=//p' "${output}")"
	[[ -n "${classification}" ]]
	[[ "$(wc -l <"${output}")" == 1 ]]
	jq -e \
		--argjson images "${expected_images}" \
		--argjson installer "${expected_installer}" '
		.schema == 1 and
		(.diff.status == "classified" or .diff.status == "fallback" or .diff.status == "predetermined") and
		.validation.images.required == $images and
		.validation.installer.required == $installer and
		(if $images then
			(.validation.images.scope == "changed" or .validation.images.scope == "all")
		else
			.validation.images.scope == "none"
		end)
	' <<<"${classification}" >/dev/null
	rm -f -- "${output}"
}

classify_event false false \
	EVENT_NAME=pull_request \
	PULL_REQUEST_BASE_SHA="${base_sha}" \
	PULL_REQUEST_HEAD_SHA="${docs_sha}"
classify_event true false \
	EVENT_NAME=merge_group \
	MERGE_GROUP_BASE_SHA="${docs_sha}" \
	MERGE_GROUP_HEAD_SHA="${image_sha}"
classify_event false false \
	EVENT_NAME=push \
	PUSH_BEFORE_SHA="${base_sha}" \
	PUSH_AFTER_SHA="${docs_sha}"
classify_event false true \
	EVENT_NAME=push \
	PUSH_BEFORE_SHA="${image_sha}" \
	PUSH_AFTER_SHA="${installer_sha}"
classify_event false false \
	EVENT_NAME=pull_request \
	PULL_REQUEST_BASE_SHA="${installer_sha}" \
	PULL_REQUEST_HEAD_SHA="${release_sha}"
classify_event false false \
	EVENT_NAME=merge_group \
	MERGE_GROUP_BASE_SHA="${installer_sha}" \
	MERGE_GROUP_HEAD_SHA="${release_sha}"
classify_event true false \
	EVENT_NAME=pull_request \
	PULL_REQUEST_BASE_SHA="${installer_sha}" \
	PULL_REQUEST_HEAD_SHA="${release_image_sha}"
classify_event true false \
	EVENT_NAME=push \
	PUSH_BEFORE_SHA="${installer_sha}" \
	PUSH_AFTER_SHA="${release_sha}"
classify_event true false EVENT_NAME=schedule
classify_event true false \
	EVENT_NAME=workflow_dispatch \
	FORCE_REBUILD=true
classify_event true false \
	EVENT_NAME=workflow_dispatch \
	VALIDATE_ONLY=false
classify_event true false \
	EVENT_NAME=workflow_dispatch \
	VALIDATE_ONLY=true \
	DEFAULT_BRANCH_REF="${installer_sha}"
classify_event true true \
	EVENT_NAME=push \
	PUSH_BEFORE_SHA=0000000000000000000000000000000000000000 \
	PUSH_AFTER_SHA="${docs_sha}"

divergent_tree="$(git -C "${test_root}" rev-parse "${base_sha}^{tree}")"
divergent_sha="$({
	printf '%s\n' divergent
} | git -C "${test_root}" commit-tree "${divergent_tree}")"
classify_event true true \
	EVENT_NAME=merge_group \
	MERGE_GROUP_BASE_SHA="${divergent_sha}" \
	MERGE_GROUP_HEAD_SHA="${docs_sha}"

prepare_output="$(mktemp)"
env \
	CHECK_PUBLICATION_TRUST=false \
	EVENT_NAME=pull_request \
	GITHUB_OUTPUT="${prepare_output}" \
	GITHUB_REF=refs/pull/1/merge \
	GITHUB_SHA="${docs_sha}" \
	PULL_REQUEST_BASE_SHA="${base_sha}" \
	PULL_REQUEST_HEAD_SHA="${docs_sha}" \
	FINITE_SOURCE_ROOT="${test_root}" \
	finite-ci-prepare
prepared_plan="$(sed -n 's/^plan=//p' "${prepare_output}")"
[[ -n "${prepared_plan}" ]]
jq -e '
	.schema_version == 1 and
	.source.event == "pull_request" and
	.classification.diff.status == "classified" and
	.validation.images.required == false and
	.publication.trusted == false
' <<<"${prepared_plan}" >/dev/null
rm -f -- "${prepare_output}"

git -C "${test_root}" switch --quiet --detach "${installer_sha}"
git -C "${test_root}" mv bootc/Containerfile docs/old-bootc-containerfile.md
git -C "${test_root}" mv installer/Containerfile docs/old-installer-containerfile.md
git -C "${test_root}" commit --quiet -m renamed-into-ignored-directory
renamed_sha="$(git -C "${test_root}" rev-parse HEAD)"
classify_event true true \
	EVENT_NAME=pull_request \
	PULL_REQUEST_BASE_SHA="${installer_sha}" \
	PULL_REQUEST_HEAD_SHA="${renamed_sha}"

# A classification with no image work must still produce a complete plan
# without requiring registry credentials or immutable-image verification.
classification='{"schema":1,"diff":{"status":"classified","base":null,"head":null},"validation":{"images":{"required":false,"scope":"none"},"installer":{"required":true}}}'
plan_output="$(mktemp)"
env \
	CHECK_PUBLICATION_TRUST=false \
	CLASSIFICATION="${classification}" \
	EVENT_NAME=pull_request \
	GITHUB_REF=refs/pull/1/merge \
	GITHUB_SHA=1111111111111111111111111111111111111111 \
	finite-ci-build-plan >"${plan_output}"
finite-ci-validate-plan "${plan_output}"
jq -e '
	.schema_version == 1 and
	.source == {
		event: "pull_request",
		ref: "refs/pull/1/merge",
		sha: "1111111111111111111111111111111111111111",
		version: .source.version
	} and
	.classification.schema == 1 and
	.validation.images == {required: false, targets: []} and
	.validation.installer.required == true and
	.publication == {
		trusted: false,
		builds: {any: false, root: false, hardware: false, roles: false},
		sbom: {base: false, hardware: false, roles: false},
		promote: false
	} and
	.matrices.all == {include: [], sbom_repair: []} and
	.matrices.candidate_shards.include == [] and
	.matrices.root.include == [] and
	.matrices.hardware.include == [] and
	.matrices.roles.include == [] and
	.matrices.sbom.base.include == [] and
	.matrices.sbom.hardware.include == [] and
	.matrices.sbom.roles.include == [] and
	.root_base == {}
' "${plan_output}" >/dev/null

invalid_plan="$(mktemp)"
jq '.unexpected = true' "${plan_output}" >"${invalid_plan}"
if finite-ci-validate-plan "${invalid_plan}" 2>/dev/null; then
	echo 'CI plan schema accepted an undeclared property' >&2
	exit 1
fi
rm -f -- "${invalid_plan}"
rm -f -- "${plan_output}"
