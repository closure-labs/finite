#!/usr/bin/env bash
set -euo pipefail

profile_command="${1:?profile command is required}"
bootstrap_command="${2:?bootstrap command is required}"
cloud_init_command="${3:?cloud-init command is required}"
first_login="modules/aspects/base/rootfs/usr/libexec/finite/home-first-login"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

export FINITE_SKIP_FOUNDATION_CHECK=true
"${profile_command}" \
	--foundation bluefin-dx \
	--hardware dell-xps-9350-intel \
	--roles support,developer \
	--format yaml >"${test_root}/profile.yaml"
yq -o=json '.' "${test_root}/profile.yaml" >"${test_root}/profile.json"
jq -e \
	--arg username "$(id -un)" \
	--arg home "$(getent passwd "$(id -un)" | cut -d: -f6)" '
	.schema == 1 and .foundation == "bluefin-dx" and
	.hardware == "dell-xps-9350-intel" and
	.roles == ["developer", "support"] and
	.identity == {username: $username, homeDirectory: $home}
' "${test_root}/profile.json" >/dev/null

for invalid_roles in developer,developer unknown; do
	if "${profile_command}" \
		--foundation bluefin \
		--hardware generic-x86_64 \
		--roles "${invalid_roles}" --format yaml >/dev/null 2>&1; then
		echo "Profile generator accepted invalid roles: ${invalid_roles}" >&2
		exit 1
	fi
done
if "${profile_command}" \
	--foundation unknown --hardware generic-x86_64 \
	--roles '' --format yaml >/dev/null 2>&1; then
	echo 'Profile generator accepted an unknown foundation' >&2
	exit 1
fi

printf '%s\n' '{"foundation":"bluefin","hardware":"generic-x86_64"}' \
	>"${test_root}/running-mismatch.json"
if FINITE_SKIP_FOUNDATION_CHECK=false \
	FINITE_RUNNING_PROFILE_PATH="${test_root}/running-mismatch.json" \
	"${profile_command}" \
		--foundation bluefin-dx --hardware dell-xps-9350-intel \
		--roles '' --format yaml >/dev/null 2>&1; then
	echo 'Profile generator accepted a running-foundation mismatch' >&2
	exit 1
fi

printf '%s\n' 'not: [valid' >"${test_root}/malformed.yaml"
if "${bootstrap_command}" --profile "${test_root}/malformed.yaml" --check >/dev/null 2>&1; then
	echo 'Bootstrap accepted malformed YAML' >&2
	exit 1
fi
jq '.identity.username = "invalid user"' "${test_root}/profile.json" |
	yq -P >"${test_root}/invalid-identity.yaml"
if "${bootstrap_command}" --profile "${test_root}/invalid-identity.yaml" --check >/dev/null 2>&1; then
	echo 'Bootstrap accepted a mismatched identity' >&2
	exit 1
fi
jq '.roles = ["developer", "developer"]' "${test_root}/profile.json" |
	yq -P >"${test_root}/duplicate.yaml"
if "${bootstrap_command}" --profile "${test_root}/duplicate.yaml" --check >/dev/null 2>&1; then
	echo 'Bootstrap accepted duplicate roles' >&2
	exit 1
fi
jq '.payload = "unexpected"' "${test_root}/profile.json" |
	yq -P >"${test_root}/extra-key.yaml"
if "${bootstrap_command}" --profile "${test_root}/extra-key.yaml" --check >/dev/null 2>&1; then
	echo 'Bootstrap accepted an undeclared profile field' >&2
	exit 1
fi
if "${bootstrap_command}" --profile "${test_root}/profile.yaml" \
	--source $'path:.\ninjected' --check >/dev/null 2>&1; then
	echo 'Bootstrap accepted a multiline source URL' >&2
	exit 1
fi

"${cloud_init_command}" \
	--foundation bluefin --hardware generic-x86_64 \
	--roles support,developer --user provisioned \
	--output "${test_root}/cloud-init"
yq -o=json '.' "${test_root}/cloud-init/profile.yaml" |
	jq -e '.roles == ["developer", "support"] and .identity.username == "provisioned"' >/dev/null
grep -qF '/etc/finite/home-profiles/provisioned.yaml' "${test_root}/cloud-init/user-data"
test -s "${test_root}/cloud-init/seed.iso"

mkdir -p "${test_root}/activation" "${test_root}/fake-bin"
touch "${test_root}/activation/activate"
chmod +x "${test_root}/activation/activate"
{
	printf '#!%s\n' "${BASH}"
	cat <<'EOF'
set -euo pipefail
printf '%q ' "$@" >>"${FINITE_TEST_NIX_LOG}"
printf '\n' >>"${FINITE_TEST_NIX_LOG}"
if [[ " $* " == *' flake lock '* ]]; then
	lock_root="${!#}"
	touch "${lock_root#path:}/flake.lock"
elif [[ " $* " == *' build '* ]]; then
	[[ "${FINITE_TEST_BUILD_FAIL:-false}" != true ]]
	printf '%s\n' "${FINITE_TEST_ACTIVATION}"
fi
EOF
} >"${test_root}/fake-bin/nix"
chmod +x "${test_root}/fake-bin/nix"
export FINITE_NIX_COMMAND="${test_root}/fake-bin/nix"
export FINITE_TEST_ACTIVATION="${test_root}/activation"
export FINITE_TEST_NIX_LOG="${test_root}/nix.log"
export FINITE_BOOTSTRAP_CONFIG_ROOT="${test_root}/configured"
"${bootstrap_command}" --profile "${test_root}/profile.yaml" --source path:. --check >/dev/null
jq -e '.roles == ["developer", "support"]' \
	"${test_root}/configured/.config/finite/profile.json" >/dev/null
test -f "${test_root}/configured/.config/home-manager/flake.lock"
grep -qF 'inputs.finite.url = "path:.";' \
	"${test_root}/configured/.config/home-manager/flake.nix"

jq -n '{name: "archived", foundation: "bluefin", hardware: "generic-x86_64", roles: ["it"], identity: {}}' \
	>"${test_root}/legacy.json"
rm -rf -- "${test_root}/configured"
"${bootstrap_command}" --legacy-profile "${test_root}/legacy.json" --source path:. --check >/dev/null
jq -e '.foundation == "bluefin" and .roles == ["it"]' \
	"${test_root}/configured/.config/finite/profile.json" >/dev/null

rm -rf -- "${test_root}/configured"
if FINITE_TEST_BUILD_FAIL=true "${bootstrap_command}" \
	--profile "${test_root}/profile.yaml" --source path:. --check >/dev/null 2>&1; then
	echo 'Bootstrap succeeded after a failed build' >&2
	exit 1
fi
test ! -e "${test_root}/configured/.config/finite/profile.json"

mkdir -p "${test_root}/login-bin"
{
	printf '#!%s\n' "${BASH}"
	cat <<'EOF'
set -euo pipefail
printf '%s\n' "$*" >>"${FINITE_TEST_ZENITY_LOG}"
if [[ " $* " == *' --error '* ]]; then
	exit 0
fi
[[ "${FINITE_TEST_CANCEL:-false}" != true ]] || exit 1
printf '%s' "${FINITE_TEST_SELECTED_ROLES:-}"
EOF
} >"${test_root}/login-bin/zenity"
{
	printf '#!%s\n' "${BASH}"
	cat <<'EOF'
set -euo pipefail
printf '%s\n' "$*" >>"${FINITE_TEST_NIX_LOG}"
if [[ " $* " == *'#home-profile'* ]]; then
	printf '%s\n' 'schema: 1' 'foundation: bluefin' 'hardware: generic-x86_64' 'roles: []' 'identity: {}'
elif [[ "${FINITE_TEST_BUILD_FAIL:-false}" == true ]]; then
	exit 1
fi
EOF
} >"${test_root}/login-bin/nix"
{
	printf '#!%s\n' "${BASH}"
	cat <<'EOF'
set -euo pipefail
[[ "${FINITE_TEST_NIX_READY:-true}" == true ]]
EOF
} >"${test_root}/login-bin/systemctl"
chmod +x \
	"${test_root}/login-bin/zenity" \
	"${test_root}/login-bin/nix" \
	"${test_root}/login-bin/systemctl"
printf '%s\n' '{"foundation":"bluefin","hardware":"generic-x86_64"}' >"${test_root}/running.json"
export PATH="${test_root}/login-bin:${PATH}"
export FINITE_NIX_COMMAND="${test_root}/login-bin/nix"
export FINITE_RUNNING_PROFILE_PATH="${test_root}/running.json"
export FINITE_HOME_PROFILE_PATH="${test_root}/not-configured.json"
export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/no-seed.yaml"
export FINITE_TEST_ZENITY_LOG="${test_root}/zenity.log"
: >"${FINITE_TEST_NIX_LOG}"

FINITE_TEST_CANCEL=true bash "${first_login}"
test ! -s "${FINITE_TEST_NIX_LOG}"
test ! -e "${FINITE_HOME_PROFILE_PATH}"

: >"${FINITE_TEST_ZENITY_LOG}"
if FINITE_TEST_NIX_READY=false FINITE_NIX_WAIT_SECONDS=0 \
	bash "${first_login}" >/dev/null 2>&1; then
	echo 'First-login succeeded before Nix became ready' >&2
	exit 1
fi
grep -qF -- '--error' "${FINITE_TEST_ZENITY_LOG}"

: >"${FINITE_TEST_NIX_LOG}"
FINITE_TEST_SELECTED_ROLES='' bash "${first_login}"
grep -qF -- '--roles  --format yaml' "${FINITE_TEST_NIX_LOG}"
grep -qF '#home-bootstrap' "${FINITE_TEST_NIX_LOG}"

printf '%s\n' 'schema: 1' >"${test_root}/seed.yaml"
export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/seed.yaml"
: >"${FINITE_TEST_NIX_LOG}"
bash "${first_login}"
grep -qF -- "--profile ${test_root}/seed.yaml" "${FINITE_TEST_NIX_LOG}"

export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/no-seed.yaml"
: >"${FINITE_TEST_ZENITY_LOG}"
if FINITE_TEST_BUILD_FAIL=true bash "${first_login}" >/dev/null 2>&1; then
	echo 'First-login succeeded after a failed bootstrap' >&2
	exit 1
fi
grep -qF -- '--error' "${FINITE_TEST_ZENITY_LOG}"
test ! -e "${FINITE_HOME_PROFILE_PATH}"

# shellcheck disable=SC2016
grep -qF 'selected=($(jq -r '\''.roles[]'\'' $current))' lib/home-manager-flake-module.nix
grep -qF "#!\${cfgPkgs.zsh}/bin/zsh" lib/home-manager-flake-module.nix
