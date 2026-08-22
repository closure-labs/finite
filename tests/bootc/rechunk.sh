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
		"io.purplefin.build.profile":"base-generic-x86_64",
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
jq -n '{
	Digest:"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	Labels:{
		"io.purplefin.build.profile":"base-generic-x86_64",
		"org.opencontainers.image.version":"test"
	}
}'
EOF
chmod +x "${test_root}/skopeo"

source_image='localhost/purplefin:test'
output="oci-archive:${test_root}/purplefin.oci"
previous='docker://ghcr.io/example/purplefin@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'

run_rechunk() {
	local support=$1 fail=$2 log=$3
	shift 3
	: >"${log}"
	FAKE_INCREMENTAL_FAIL="${fail}" \
		FAKE_PODMAN_LOG="${log}" \
		FAKE_PREVIOUS_SUPPORT="${support}" \
		PURPLEFIN_PODMAN="${test_root}/podman" \
		PURPLEFIN_SKOPEO="${test_root}/skopeo" \
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
grep -qF -- '--label io.purplefin.build.profile=base-generic-x86_64' "${full_log}"
grep -qF -- '--bootc --rootfs /rpm-ostree' "${full_log}"
grep -qF -- "--volume ${test_root}:/run/purplefin-rechunk-output" "${full_log}"
grep -qF -- '--output oci-archive:/run/purplefin-rechunk-output/purplefin.oci' \
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
