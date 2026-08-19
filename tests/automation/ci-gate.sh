#!/usr/bin/env bash
set -euo pipefail

make_lifecycle() {
	local images=$1 installer=$2 root=$3 hardware=$4 roles=$5
	local base_sbom=$6 hardware_sbom=$7 role_sbom=$8 promote=$9
	jq -cn \
		--argjson images "${images}" \
		--argjson installer "${installer}" \
		--argjson root "${root}" \
		--argjson hardware "${hardware}" \
		--argjson roles "${roles}" \
		--argjson base_sbom "${base_sbom}" \
		--argjson hardware_sbom "${hardware_sbom}" \
		--argjson role_sbom "${role_sbom}" \
		--argjson promote "${promote}" '
		{
			schema: 1,
			validation: {
				images: {required: $images, targets: (if $images then ["base"] else [] end)},
				installer: {required: $installer}
			},
			publication: {
				builds: {
					any: ($root or $hardware or $roles),
					root: $root,
					hardware: $hardware,
					roles: $roles
				},
				sbom: {base: $base_sbom, hardware: $hardware_sbom, roles: $role_sbom},
				promote: $promote
			}
		}
	'
}

empty_lifecycle="$(make_lifecycle false false false false false false false false false)"

run_gate() {
	env \
		BASE_PUBLISH_RESULT=skipped \
		BASE_SBOM_RESULT=skipped \
		BUILD_CANDIDATE_RESULT=skipped \
		EVENT_NAME=pull_request \
		HARDWARE_PUBLISH_RESULT=skipped \
		HARDWARE_SBOM_RESULT=skipped \
		INSTALLER_CANDIDATE_RESULT=skipped \
		LIFECYCLE="${empty_lifecycle}" \
		PREPARE_RESULT=success \
		PROMOTE_RESULT=skipped \
		REF=refs/heads/example \
		ROLE_SBOM_RESULT=skipped \
		ROLES_PUBLISH_RESULT=skipped \
		"$@" purplefin-ci-gate
}

run_gate
run_gate \
	LIFECYCLE="$(make_lifecycle true false false false false false false false false)" \
	BUILD_CANDIDATE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main \
	LIFECYCLE="$(make_lifecycle false false true false false true false false true)" \
	BASE_PUBLISH_RESULT=success BASE_SBOM_RESULT=success PROMOTE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main \
	LIFECYCLE="$(make_lifecycle false false false true true false true true true)" \
	HARDWARE_PUBLISH_RESULT=success HARDWARE_SBOM_RESULT=success \
	ROLES_PUBLISH_RESULT=success ROLE_SBOM_RESULT=success PROMOTE_RESULT=success
run_gate \
	EVENT_NAME=push REF=refs/heads/main \
	LIFECYCLE="$(make_lifecycle false false false false false true false false false)" \
	BASE_SBOM_RESULT=success

if run_gate PREPARE_RESULT=failure 2>/dev/null; then
	echo 'A failed preparation job unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate LIFECYCLE="$(make_lifecycle true false false false false false false false false)" \
	BUILD_CANDIDATE_RESULT=failure 2>/dev/null; then
	echo 'A failed candidate shard unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate EVENT_NAME=push REF=refs/heads/main \
	LIFECYCLE="$(make_lifecycle false false true false false false false false true)" \
	BASE_PUBLISH_RESULT=success \
	PROMOTE_RESULT=failure 2>/dev/null; then
	echo 'A failed promotion unexpectedly passed the gate' >&2
	exit 1
fi
if run_gate EVENT_NAME=workflow_dispatch REF=refs/heads/topic 2>/dev/null; then
	echo 'A publishing dispatch outside main unexpectedly passed the gate' >&2
	exit 1
fi
