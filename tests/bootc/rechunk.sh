#!/usr/bin/env bash
set -euo pipefail

rechunk_image="${1:?usage: rechunk.sh RECHUNK_IMAGE}"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
touch "${test_root}/auth.json"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/podman"
cat >>"${test_root}/podman" <<'EOF'
set -euo pipefail
if [[ "$1" == inspect ]]; then
	jq -n '[{Config:{Labels:{
		"io.finite.build.profile":"bluefin-generic",
		"org.opencontainers.image.version":"test",
		"containers.bootc":"1",
		"ostree.commit":"excluded"
	}}}]'
	exit 0
fi
[[ "$1" == run ]]
if [[ " $* " == *' --help '* ]]; then
	if [[ "${FAKE_PREVIOUS_SUPPORT}" == true ]]; then
		echo '  --previous-build <REFERENCE>'
	else
		echo '  --format-version <VERSION>'
	fi
	exit 0
fi
printf '%s\n' "$*" >>"${FAKE_PODMAN_LOG}"
if [[ "${FAKE_INCREMENTAL_FAIL}" == true && " $* " == *' --previous-build '* ]]; then
	exit 42
fi
EOF
chmod +x "${test_root}/podman"

printf '#!%s\n' "$(command -v bash)" >"${test_root}/skopeo"
cat >>"${test_root}/skopeo" <<'EOF'
set -euo pipefail
if [[ "$1" == copy ]]; then
	printf '%s\n' "$*" >>"${FAKE_SKOPEO_LOG}"
	exit 0
fi
[[ "$1" == inspect ]]
jq -n '{
	Digest:"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	Labels:{
		"io.finite.build.profile":"bluefin-generic",
		"org.opencontainers.image.version":"test"
	}
}'
EOF
chmod +x "${test_root}/skopeo"

source_image='localhost/finite:test'
output="oci-archive:${test_root}/finite.oci"
previous='docker://ghcr.io/example/finite@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
skopeo_log="${test_root}/skopeo.log"
: >"${skopeo_log}"

run_rechunk() {
	local support=$1 fail=$2 log=$3
	shift 3
	: >"${log}"
	FAKE_INCREMENTAL_FAIL="${fail}" \
		FAKE_PODMAN_LOG="${log}" \
		FAKE_PREVIOUS_SUPPORT="${support}" \
		FAKE_SKOPEO_LOG="${skopeo_log}" \
		FINITE_PODMAN="${test_root}/podman" \
		FINITE_SKOPEO="${test_root}/skopeo" \
		"${rechunk_image}" \
			--source "${source_image}" \
			--output "${output}" \
			"$@"
}

full_log="${test_root}/full.log"
report="$(run_rechunk false false "${full_log}")"
jq -e '
	.mode == "full" and
	.previous_build_digest == "none" and
	(.digest | test("^sha256:[0-9a-f]{64}$")) and
	(.rechunk_seconds | type == "number")
' <<<"${report}" >/dev/null
grep -qF -- '--max-layers 127' "${full_log}"
grep -qF -- '--format-version=2' "${full_log}"
grep -qF -- '--label io.finite.build.profile=bluefin-generic' "${full_log}"
grep -qF -- '--bootc --rootfs /rpm-ostree' "${full_log}"
grep -qF -- "--volume ${test_root}:/run/finite-rechunk-output" "${full_log}"
grep -qF -- '--output oci-archive:/run/finite-rechunk-output/finite.oci' \
	"${full_log}"
if grep -qF -- '--previous-build' "${full_log}"; then
	echo 'Full rechunk unexpectedly received a previous build' >&2
	exit 1
fi

incremental_log="${test_root}/incremental.log"
report="$(run_rechunk true false "${incremental_log}" \
	--previous-build "${previous}" --authfile "${test_root}/auth.json")"
jq -e --arg digest "${previous##*@}" '
	.mode == "incremental" and .previous_build_digest == $digest
' <<<"${report}" >/dev/null
grep -qF -- "--previous-build ${previous}" "${incremental_log}"
grep -qF -- "--volume ${test_root}/auth.json:/run/registry-auth.json:ro" \
	"${incremental_log}"

unsupported_log="${test_root}/unsupported.log"
report="$(run_rechunk false false "${unsupported_log}" --previous-build "${previous}")"
jq -e '.mode == "full"' <<<"${report}" >/dev/null
if grep -qF -- '--previous-build' "${unsupported_log}"; then
	echo 'Unsupported rpm-ostree received the incremental flag' >&2
	exit 1
fi

fallback_log="${test_root}/fallback.log"
report="$(run_rechunk true true "${fallback_log}" --previous-build "${previous}")"
jq -e '.mode == "full"' <<<"${report}" >/dev/null
[[ "$(wc -l <"${fallback_log}")" == 2 ]]
grep -qF -- "--previous-build ${previous}" "${fallback_log}"
[[ "$(grep -cF -- '--previous-build' "${fallback_log}")" == 1 ]]

remote_output='docker://ghcr.io/example/finite:test'
remote_log="${test_root}/remote.log"
: >"${remote_log}"
: >"${skopeo_log}"
report="$(
	FAKE_INCREMENTAL_FAIL=false \
		FAKE_PODMAN_LOG="${remote_log}" \
		FAKE_PREVIOUS_SUPPORT=false \
		FAKE_SKOPEO_LOG="${skopeo_log}" \
		FINITE_PODMAN="${test_root}/podman" \
		FINITE_SKOPEO="${test_root}/skopeo" \
		"${rechunk_image}" \
			--source "${source_image}" \
			--output "${remote_output}" \
			--previous-build "${previous}" \
			--authfile "${test_root}/auth.json"
)"
jq -e '.mode == "passthrough" and .previous_build_digest == "none"' \
	<<<"${report}" >/dev/null
if [[ -s "${remote_log}" ]]; then
	echo 'Registry publication unexpectedly invoked rpm-ostree' >&2
	exit 1
fi
grep -qF -- "copy --retry-times 3 --authfile ${test_root}/auth.json --all --preserve-digests containers-storage:${source_image}" \
	"${skopeo_log}"
grep -qF -- " ${remote_output}" "${skopeo_log}"
