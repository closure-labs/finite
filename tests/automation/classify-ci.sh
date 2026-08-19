#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
git -C "${test_root}" init --quiet
git -C "${test_root}" config user.name Purplefin
git -C "${test_root}" config user.email purplefin@example.invalid

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
	env PURPLEFIN_SOURCE_ROOT="${test_root}" "$@" \
		purplefin-classify-ci "${output}"
	grep -qxF "images=${expected_images}" "${output}"
	grep -qxF "installer=${expected_installer}" "${output}"
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
