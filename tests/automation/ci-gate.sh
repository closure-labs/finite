#!/usr/bin/env bash
set -euo pipefail

run_gate() {
	env \
		BASE_PUBLISH_RESULT=skipped \
		BASE_SBOM_RESULT=skipped \
		BUILD_CANDIDATE_RESULT=skipped \
		EVENT_NAME=pull_request \
		HARDWARE_PUBLISH_RESULT=skipped \
		HARDWARE_SBOM_RESULT=skipped \
		HAS_BUILDS=false \
		HAS_BASE_SBOM=false \
		HAS_HARDWARE=false \
		HAS_HARDWARE_SBOM=false \
		HAS_ROLES=false \
		HAS_ROLE_SBOM=false \
		HAS_ROOT_BASE=false \
		INSTALLER_CANDIDATE_RESULT=skipped \
		INSTALLER_SELECTED=false \
		PREPARE_RESULT=success \
		PROMOTE_RESULT=skipped \
		REF=refs/heads/example \
		ROLE_SBOM_RESULT=skipped \
		ROLES_PUBLISH_RESULT=skipped \
		"$@" purplefin-ci-gate
}

run_gate
run_gate \
	HAS_BUILDS=true \
	BUILD_CANDIDATE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main \
	HAS_BUILDS=true HAS_ROOT_BASE=true HAS_BASE_SBOM=true \
	BASE_PUBLISH_RESULT=success BASE_SBOM_RESULT=success PROMOTE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main HAS_BUILDS=true \
	HAS_HARDWARE=true HARDWARE_PUBLISH_RESULT=success HARDWARE_SBOM_RESULT=success \
	HAS_HARDWARE_SBOM=true HAS_ROLES=true HAS_ROLE_SBOM=true \
	ROLES_PUBLISH_RESULT=success ROLE_SBOM_RESULT=success PROMOTE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main HAS_BASE_SBOM=true \
	BASE_SBOM_RESULT=success

if run_gate PREPARE_RESULT=failure 2>/dev/null; then
	echo 'A failed preparation job unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate HAS_BUILDS=true \
	BUILD_CANDIDATE_RESULT=failure 2>/dev/null; then
	echo 'A failed candidate shard unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate EVENT_NAME=push REF=refs/heads/main HAS_BUILDS=true \
	PROMOTE_RESULT=failure 2>/dev/null; then
	echo 'A failed promotion unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate EVENT_NAME=workflow_dispatch REF=refs/heads/topic 2>/dev/null; then
	echo 'A publishing dispatch outside main unexpectedly passed the gate' >&2
	exit 1
fi
