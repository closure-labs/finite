#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
script="${repo_root}/bootc/builder/sbom.sh"
workdir="$(mktemp -d)"
trap 'rm -rf -- "${workdir}"' EXIT
mkdir -p "${workdir}/bin"

digest="sha256:$(printf 'a%.0s' {1..64})"
source_digest="$(printf 'b%.0s' {1..40})"
cat >"${workdir}/predicate.json" <<'EOF'
{"spdxVersion":"SPDX-2.3","packages":[{"name":"example","externalRefs":[{"referenceType":"purl","referenceLocator":"pkg:rpm/example@1"}]}]}
EOF
jq -cn \
	--arg digest "${digest#sha256:}" \
	--arg predicate_type 'https://spdx.dev/Document/v2.3' \
	--slurpfile predicate "${workdir}/predicate.json" '
	[
		{
			verificationResult: {
				statement: {
					predicateType: $predicate_type,
					subject: [{digest: {sha256: $digest}}],
					predicate: $predicate[0]
				}
			}
		}
	]
' >"${workdir}/verification.json"

{
	printf '#!%s\n' "$(command -v bash)"
	cat <<'EOF'
set -euo pipefail
case "${MOCK_GH_MODE:-hit}" in
	hit) cat "${MOCK_VERIFICATION}" ;;
	miss) exit 1 ;;
	ambiguous)
		jq '.[0].verificationResult.statement.predicate.packages[0].name = "different"' \
			"${MOCK_VERIFICATION}" |
			jq -s '.[0] + .[1]' "${MOCK_VERIFICATION}" -
		;;
	*) exit 2 ;;
esac
EOF
} >"${workdir}/bin/gh"
chmod +x "${workdir}/bin/gh"

common_env=(
	GITHUB_REPOSITORY=example/purplefin
	MOCK_VERIFICATION="${workdir}/verification.json"
	PURPLEFIN_GH="${workdir}/bin/gh"
	SBOM_IMAGE_DIGEST="${digest}"
	SBOM_IMAGE_REF=ghcr.io/example/purplefin
	SBOM_SIGNER_WORKFLOW=example/purplefin/.github/workflows/attest-software-bill-of-materials.yml
	SBOM_SOURCE_DIGEST="${source_digest}"
)
env "${common_env[@]}" bash "${script}" extract "${workdir}/restored.json"
cmp "${workdir}/predicate.json" "${workdir}/restored.json"

jq . "${workdir}/predicate.json" >"${workdir}/formatted.json"
bash "${script}" equivalent \
	"${workdir}/predicate.json" "${workdir}/formatted.json"
jq '.packages[0].name = "different"' \
	"${workdir}/predicate.json" >"${workdir}/different.json"
if bash "${script}" equivalent \
	"${workdir}/predicate.json" "${workdir}/different.json"; then
	echo 'Distinct software bills were considered equivalent' >&2
	exit 1
fi

if env "${common_env[@]}" MOCK_GH_MODE=miss \
	bash "${script}" extract "${workdir}/miss.json"; then
	echo 'A missing attestation unexpectedly restored an SBOM' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 3 ]]
fi
if env "${common_env[@]}" MOCK_GH_MODE=ambiguous \
	bash "${script}" extract "${workdir}/ambiguous.json" 2>/dev/null; then
	echo 'Distinct verified predicates were accepted' >&2
	exit 1
else
	status=$?
	[[ "${status}" -eq 1 ]]
fi

{
	printf '#!%s\n' "$(command -v bash)"
	cat <<'EOF'
set -euo pipefail
printf '%s\n' "${PURPLEFIN_SYFT_STORE}"
EOF
} >"${workdir}/bin/nix-store"
{
	printf '#!%s\n' "$(command -v bash)"
	cat <<'EOF'
exit 0
EOF
} >"${workdir}/bin/syft"
{
	printf '#!%s\n' "$(command -v bash)"
	cat <<'EOF'
set -euo pipefail
case "$1" in
	pull) printf '%s\n' mock-image ;;
	run)
		cat <<'JSON'
{"spdxVersion":"SPDX-2.3","packages":[{"name":"generated","externalRefs":[{"referenceType":"cpe23Type","referenceLocator":"cpe:2.3:a:example"},{"referenceType":"purl","referenceLocator":"pkg:rpm/generated@1"}]}]}
JSON
		;;
	*) exit 2 ;;
esac
EOF
} >"${workdir}/bin/podman"
chmod +x "${workdir}/bin/nix-store" "${workdir}/bin/podman" "${workdir}/bin/syft"
env \
	PURPLEFIN_NIX_STORE="${workdir}/bin/nix-store" \
	PURPLEFIN_PODMAN="${workdir}/bin/podman" \
	PURPLEFIN_SOURCE_ROOT="${repo_root}" \
	PURPLEFIN_SYFT="${workdir}/bin/syft" \
	PURPLEFIN_SYFT_STORE="${workdir}" \
	SBOM_IMAGE_DIGEST="${digest}" \
	SBOM_IMAGE_REF=ghcr.io/example/purplefin \
	bash "${script}" generate "${workdir}/generated.json"
jq -e '
	.packages[0].name == "generated" and
	([.packages[].externalRefs[]?.referenceType] == ["purl"])
' "${workdir}/generated.json" >/dev/null
bash "${script}" validate "${workdir}/generated.json"
