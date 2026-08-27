#!/usr/bin/env bash
set -euo pipefail

profile_command="${1:?profile command is required}"
init_command="${2:?home init command is required}"
cloud_init_command="${3:?cloud-init command is required}"
template="${4:?rendered home template is required}"
first_login="modules/aspects/base/rootfs/usr/libexec/finite/home-first-login"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

patch_test_shebang() {
	local script="${1:?script is required}"
	{
		printf '#!%s\n' "${BASH}"
		tail -n +2 "${script}"
	} >"${script}.new"
	mv "${script}.new" "${script}"
}

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
printf '%s\n' '{"foundation":"bluefin-dx","hardware":"next-x86_64"}' \
	>"${test_root}/running-next.json"
FINITE_SKIP_FOUNDATION_CHECK=false \
	FINITE_RUNNING_PROFILE_PATH="${test_root}/running-next.json" \
	"${profile_command}" \
	--foundation bluefin-dx --hardware dell-xps-9350-intel \
	--format yaml >/dev/null
if "${profile_command}" \
	--foundation bluefin --hardware next-x86_64 \
	--format yaml >/dev/null 2>&1; then
	echo 'Profile generator accepted boot-only next-x86_64 as Home Manager hardware' >&2
	exit 1
fi

for invalid_roles in developer,developer unknown; do
	if "${profile_command}" \
		--foundation bluefin --hardware generic-x86_64 \
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

"${cloud_init_command}" \
	--foundation bluefin --hardware generic-x86_64 \
	--roles support,developer --user provisioned \
	--output "${test_root}/cloud-init"
yq -o=json '.' "${test_root}/cloud-init/profile.yaml" |
	jq -e '.roles == ["developer", "support"] and .identity.username == "provisioned"' >/dev/null
grep -qF '/etc/finite/home-profiles/provisioned.yaml' "${test_root}/cloud-init/user-data"
test -s "${test_root}/cloud-init/seed.iso"

for required in \
	flake.nix flake.lock finite-template.json profile.json \
	modules/finite.nix modules/finite-configure modules/finite-home-apply \
	modules/aspects/base/home.nix \
	modules/aspects/hardware/dell-xps-9350-intel/home.nix \
	modules/aspects/hardware/dell-xps-9350-intel/dell-xps-9350-panel-policy; do
	test -f "${template}/${required}"
done
jq -e '.schema == 1 and .generator == "finite-home-init" and (.version | length > 0)' \
	"${template}/finite-template.json" >/dev/null
jq -e '[.nodes[].locked? | select(. != null) | .type] | all(. != "path")' \
	"${template}/flake.lock" >/dev/null
if rg -n '/var/home/.*/projects|inputs\.finite|github:closure-labs/finite' "${template}"; then
	echo 'Rendered Home Manager template references an external Finite checkout' >&2
	exit 1
fi
if find "${template}" -type l -print | grep -q .; then
	echo 'Rendered Home Manager template contains an external symlink' >&2
	exit 1
fi

mkdir -p "${test_root}/activation" "${test_root}/fake-bin"
cat >"${test_root}/activation/activate" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'activated\n' >>"${FINITE_TEST_ACTIVATION_LOG}"
EOF
cat >"${test_root}/fake-bin/nix" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"${FINITE_TEST_NIX_LOG}"
printf '\n' >>"${FINITE_TEST_NIX_LOG}"
[[ " ${*} " == *' build '* ]] || {
	echo 'Unexpected mutating Nix command' >&2
	exit 1
}
[[ "${FINITE_TEST_BUILD_FAIL:-false}" != true ]]
printf '%s\n' "${FINITE_TEST_ACTIVATION}"
EOF
patch_test_shebang "${test_root}/activation/activate"
patch_test_shebang "${test_root}/fake-bin/nix"
chmod +x "${test_root}/activation/activate" "${test_root}/fake-bin/nix"

export FINITE_HOME_TEMPLATE_PATH="${template}"
export FINITE_HOME_CATALOG_PATH="${FINITE_GENERATED_ROOT}/bootc/generated/home-profile-catalog.json"
export FINITE_NIX_COMMAND="${test_root}/fake-bin/nix"
export FINITE_TEST_ACTIVATION="${test_root}/activation"
export FINITE_TEST_ACTIVATION_LOG="${test_root}/activation.log"
export FINITE_TEST_NIX_LOG="${test_root}/nix.log"
export XDG_CONFIG_HOME="${test_root}/config"

printf '%s\n' 'not: [valid' >"${test_root}/malformed.yaml"
if "${init_command}" --profile "${test_root}/malformed.yaml" --check >/dev/null 2>&1; then
	echo 'Home initializer accepted malformed YAML' >&2
	exit 1
fi
jq '.identity.username = "invalid user"' "${test_root}/profile.json" |
	yq -P >"${test_root}/invalid-identity.yaml"
if "${init_command}" --profile "${test_root}/invalid-identity.yaml" --check >/dev/null 2>&1; then
	echo 'Home initializer accepted a mismatched identity' >&2
	exit 1
fi
jq '.roles = ["developer", "developer"]' "${test_root}/profile.json" |
	yq -P >"${test_root}/duplicate.yaml"
if "${init_command}" --profile "${test_root}/duplicate.yaml" --check >/dev/null 2>&1; then
	echo 'Home initializer accepted duplicate roles' >&2
	exit 1
fi
jq '.payload = "unexpected"' "${test_root}/profile.json" |
	yq -P >"${test_root}/extra-key.yaml"
if "${init_command}" --profile "${test_root}/extra-key.yaml" --check >/dev/null 2>&1; then
	echo 'Home initializer accepted an undeclared profile field' >&2
	exit 1
fi

: >"${FINITE_TEST_NIX_LOG}"
"${init_command}" --profile "${test_root}/profile.yaml" --check >/dev/null
test ! -e "${XDG_CONFIG_HOME}/home-manager"
grep -qF -- '--no-update-lock-file' "${FINITE_TEST_NIX_LOG}"
if grep -qF 'flake lock' "${FINITE_TEST_NIX_LOG}"; then
	echo 'Home initializer attempted to rewrite its pinned lock' >&2
	exit 1
fi

mkdir -p "${XDG_CONFIG_HOME}/home-manager"
printf 'old\n' >"${XDG_CONFIG_HOME}/home-manager/partial-old-config"
: >"${FINITE_TEST_NIX_LOG}"
"${init_command}" --profile "${test_root}/profile.yaml" >/dev/null
hm_dir="${XDG_CONFIG_HOME}/home-manager"
test -f "${hm_dir}/finite-template.json"
test ! -e "${hm_dir}/partial-old-config"
test -w "${hm_dir}/flake.nix"
jq -e '.roles == ["developer", "support"]' "${hm_dir}/profile.json" >/dev/null
jq -e '.roles == ["developer", "support"]' \
	"${XDG_CONFIG_HOME}/finite/profile.json" >/dev/null
grep -qF 'activated' "${FINITE_TEST_ACTIVATION_LOG}"
backups=("${XDG_CONFIG_HOME}"/home-manager.previous.*)
[[ "${#backups[@]}" == 1 ]]
test -f "${backups[0]}/partial-old-config"
if rg -n '/var/home/.*/projects|inputs\.finite|github:closure-labs/finite' "${hm_dir}"; then
	echo 'Installed Home Manager flake references an external Finite checkout' >&2
	exit 1
fi

printf 'preserve\n' >"${hm_dir}/preserve-on-failure"
if FINITE_TEST_BUILD_FAIL=true \
	"${init_command}" --profile "${test_root}/profile.yaml" >/dev/null 2>&1; then
	echo 'Home initializer replaced a configuration after a failed build' >&2
	exit 1
fi
grep -qF 'preserve' "${hm_dir}/preserve-on-failure"

bad_template="${test_root}/bad-template"
cp -a "${template}" "${bad_template}"
chmod -R u+w "${bad_template}"
jq '.nodes.local = {locked: {type: "path", path: "/tmp/local"}}' \
	"${bad_template}/flake.lock" >"${bad_template}/.flake.lock.new"
mv "${bad_template}/.flake.lock.new" "${bad_template}/flake.lock"
if FINITE_HOME_TEMPLATE_PATH="${bad_template}" \
	"${init_command}" --profile "${test_root}/profile.yaml" --check >/dev/null 2>&1; then
	echo 'Home initializer accepted a local path input in the template lock' >&2
	exit 1
fi

apply="${hm_dir}/modules/finite-home-apply"
FINITE_HOME_FLAKE_ROOT="${hm_dir}" bash "${apply}" \
	--roles it,developer,sales,trainer,support,executive >/dev/null
jq -e '.roles == ["developer", "sales", "trainer", "support", "executive", "it"]' \
	"${hm_dir}/profile.json" >/dev/null
if FINITE_HOME_FLAKE_ROOT="${hm_dir}" bash "${apply}" \
	--roles developer,unknown --check >/dev/null 2>&1; then
	echo 'Local role application accepted an unknown role' >&2
	exit 1
fi
cp "${hm_dir}/profile.json" "${test_root}/profile-before-failed-apply.json"
if FINITE_TEST_BUILD_FAIL=true FINITE_HOME_FLAKE_ROOT="${hm_dir}" \
	bash "${apply}" --roles developer >/dev/null 2>&1; then
	echo 'Local role application changed configuration after a failed build' >&2
	exit 1
fi
cmp "${test_root}/profile-before-failed-apply.json" "${hm_dir}/profile.json"

mkdir -p "${test_root}/login-bin"
cat >"${test_root}/login-bin/zenity" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FINITE_TEST_ZENITY_LOG}"
if [[ " ${*} " == *' --error '* ]]; then
	exit 0
fi
[[ "${FINITE_TEST_CANCEL:-false}" != true ]] || exit 1
printf '%s' "${FINITE_TEST_SELECTED_ROLES:-}"
EOF
cat >"${test_root}/login-bin/systemctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${FINITE_TEST_NIX_READY:-true}" == true ]]
EOF
cat >"${test_root}/login-bin/home-init" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${FINITE_TEST_INIT_FAIL:-false}" != true ]]
[[ "$1" == --profile ]]
printf '%s\n' "$*" >>"${FINITE_TEST_INIT_LOG}"
yq -o=json '.' "$2" | jq -c . >>"${FINITE_TEST_INIT_LOG}"
EOF
cat >"${test_root}/login-bin/nix" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
for test_command in zenity systemctl home-init nix; do
	patch_test_shebang "${test_root}/login-bin/${test_command}"
done
chmod +x "${test_root}/login-bin/"*

printf '%s\n' '{"foundation":"bluefin","hardware":"generic-x86_64"}' \
	>"${test_root}/running.json"
mkdir -p "${test_root}/dmi"
printf '%s\n' 'Finite Test Vendor' >"${test_root}/dmi/sys_vendor"
printf '%s\n' 'Finite Test System' >"${test_root}/dmi/product_name"
export PATH="${test_root}/login-bin:${PATH}"
export FINITE_NIX_COMMAND="${test_root}/login-bin/nix"
export FINITE_HOME_INIT_COMMAND="${test_root}/login-bin/home-init"
export FINITE_RUNNING_PROFILE_PATH="${test_root}/running.json"
export FINITE_DMI_ROOT="${test_root}/dmi"
export FINITE_HOME_PROFILE_PATH="${test_root}/login-profile.json"
export FINITE_HOME_FLAKE_PATH="${test_root}/login-home-manager"
export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/no-seed.yaml"
export FINITE_TEST_INIT_LOG="${test_root}/init.log"
export FINITE_TEST_ZENITY_LOG="${test_root}/zenity.log"

FINITE_TEST_CANCEL=true bash "${first_login}"
test ! -s "${FINITE_TEST_INIT_LOG}"

: >"${FINITE_TEST_ZENITY_LOG}"
if FINITE_TEST_NIX_READY=false FINITE_NIX_WAIT_SECONDS=0 \
	bash "${first_login}" >/dev/null 2>&1; then
	echo 'First-login succeeded before Nix became ready' >&2
	exit 1
fi
grep -qF -- '--error' "${FINITE_TEST_ZENITY_LOG}"

: >"${FINITE_TEST_INIT_LOG}"
FINITE_TEST_SELECTED_ROLES='developer,it' bash "${first_login}"
grep -qF -- '--profile ' "${FINITE_TEST_INIT_LOG}"
tail -n 1 "${FINITE_TEST_INIT_LOG}" |
	jq -e '.hardware == "generic-x86_64" and .roles == ["developer", "it"] and .identity == {}' >/dev/null

printf '%s\n' '{"foundation":"bluefin","hardware":"next-x86_64"}' \
	>"${test_root}/running.json"
printf '%s\n' 'Dell Inc.' >"${test_root}/dmi/sys_vendor"
printf '%s\n' 'XPS 13 9350' >"${test_root}/dmi/product_name"
: >"${FINITE_TEST_INIT_LOG}"
FINITE_TEST_SELECTED_ROLES='' bash "${first_login}"
tail -n 1 "${FINITE_TEST_INIT_LOG}" |
	jq -e '.foundation == "bluefin" and .hardware == "dell-xps-9350-intel" and .roles == []' >/dev/null
printf '%s\n' '{"foundation":"bluefin","hardware":"generic-x86_64"}' \
	>"${test_root}/running.json"
printf '%s\n' 'Finite Test Vendor' >"${test_root}/dmi/sys_vendor"
printf '%s\n' 'Finite Test System' >"${test_root}/dmi/product_name"

printf '%s\n' 'schema: 1' >"${test_root}/seed.yaml"
export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/seed.yaml"
: >"${FINITE_TEST_INIT_LOG}"
bash "${first_login}"
grep -qF -- "--profile ${test_root}/seed.yaml" "${FINITE_TEST_INIT_LOG}"

export FINITE_PROVISIONED_PROFILE_PATH="${test_root}/no-seed.yaml"
cp "${test_root}/profile.json" "${FINITE_HOME_PROFILE_PATH}"
: >"${FINITE_TEST_INIT_LOG}"
bash "${first_login}"
grep -qF -- "--profile ${FINITE_HOME_PROFILE_PATH}" "${FINITE_TEST_INIT_LOG}"
rm "${FINITE_HOME_PROFILE_PATH}"

: >"${FINITE_TEST_ZENITY_LOG}"
if FINITE_TEST_INIT_FAIL=true bash "${first_login}" >/dev/null 2>&1; then
	echo 'First-login succeeded after local initialization failed' >&2
	exit 1
fi
grep -qF -- '--error' "${FINITE_TEST_ZENITY_LOG}"

mkdir -p "${FINITE_HOME_FLAKE_PATH}/modules"
touch "${FINITE_HOME_FLAKE_PATH}/flake.nix" "${FINITE_HOME_FLAKE_PATH}/modules/finite.nix"
cp "${template}/finite-template.json" "${FINITE_HOME_FLAKE_PATH}/finite-template.json"
printf '%s\n' '{"nodes":{"root":{}},"root":"root","version":7}' \
	>"${FINITE_HOME_FLAKE_PATH}/flake.lock"
cp "${test_root}/profile.json" "${FINITE_HOME_FLAKE_PATH}/profile.json"
: >"${FINITE_TEST_INIT_LOG}"
FINITE_TEST_NIX_READY=false bash "${first_login}"
test ! -s "${FINITE_TEST_INIT_LOG}"

grep -qF -- '--hide-column=3 --print-column=3' \
	"${template}/modules/finite-configure" "${first_login}"
grep -qF 'exec finite-home-apply --roles' "${template}/modules/finite-configure"
if grep -qF 'FINITE_RUNNING_PROFILE_PATH' "${template}/modules/finite-home-apply"; then
	echo 'Local role changes must preserve bootstrap-set foundation and hardware variables' >&2
	exit 1
fi
# shellcheck disable=SC2016
grep -qF 'ExecStart = "${lib.getExe panelPolicy} --watch"' \
	"${template}/modules/aspects/hardware/dell-xps-9350-intel/home.nix"
if rg -n 'firefox|pipewire|camera' \
	"${template}/modules/aspects/hardware/dell-xps-9350-intel"; then
	echo 'Dell Home Manager aspect retains the obsolete camera workaround' >&2
	exit 1
fi
# Match literal shell and jq expressions.
# shellcheck disable=SC2016
grep -qF 'jq -e --arg role "$role" '\''.roles | index($role) != null'\'' "$current"' \
	"${template}/modules/finite-configure"
if rg -n 'github:closure-labs/finite|nix.*flake lock' \
	"${first_login}" modules/aspects/base/rootfs/usr/libexec/finite/home-init; then
	echo 'First-login provisioning still depends on a remote Finite flake' >&2
	exit 1
fi

bash -n "${first_login}" modules/aspects/base/rootfs/usr/libexec/finite/home-init \
	"${template}/modules/finite-configure" "${template}/modules/finite-home-apply"
bash -n "${template}/modules/aspects/hardware/dell-xps-9350-intel/dell-xps-9350-panel-policy"
