#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
gate="${repo_root}/automation/github/ci-gate.sh"

run_gate() {
	env \
		BASE_PUBLISH_RESULT=skipped \
		BASE_SBOM_RESULT=skipped \
		BUILD_CANDIDATE_RESULT=skipped \
		EVENT_NAME=pull_request \
		HARDWARE_PUBLISH_RESULT=skipped \
		HARDWARE_SBOM_RESULT=skipped \
		HAS_BUILDS=false \
		HAS_HARDWARE=false \
		HAS_ROLES=false \
		HAS_ROOT_BASE=false \
		IMAGES_SELECTED=false \
		INSTALLER_CANDIDATE_RESULT=skipped \
		INSTALLER_SELECTED=false \
		PLAN_RESULT=skipped \
		PREPARE_RESULT=success \
		REF=refs/heads/example \
		ROLE_SBOM_RESULT=skipped \
		ROLES_PUBLISH_RESULT=skipped \
		"$@" bash "${gate}"
}

run_gate
run_gate \
	IMAGES_SELECTED=true PLAN_RESULT=success HAS_BUILDS=true \
	BUILD_CANDIDATE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main IMAGES_SELECTED=true PLAN_RESULT=success \
	HAS_ROOT_BASE=true BASE_PUBLISH_RESULT=success BASE_SBOM_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main IMAGES_SELECTED=true PLAN_RESULT=success \
	HAS_HARDWARE=true HARDWARE_PUBLISH_RESULT=success HARDWARE_SBOM_RESULT=success \
	HAS_ROLES=true ROLES_PUBLISH_RESULT=success ROLE_SBOM_RESULT=success

if run_gate PREPARE_RESULT=failure 2>/dev/null; then
	echo 'A failed preparation job unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate IMAGES_SELECTED=true PLAN_RESULT=success HAS_BUILDS=true \
	BUILD_CANDIDATE_RESULT=failure 2>/dev/null; then
	echo 'A failed candidate shard unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate EVENT_NAME=workflow_dispatch REF=refs/heads/topic 2>/dev/null; then
	echo 'A publishing dispatch outside main unexpectedly passed the gate' >&2
	exit 1
fi
