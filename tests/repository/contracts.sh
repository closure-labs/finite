#!/usr/bin/env bash
set -euo pipefail

generated_root="${FINITE_GENERATED_ROOT:?FINITE_GENERATED_ROOT is required}"
catalog="${generated_root}/bootc/generated/profile-catalog.json"
matrix="${generated_root}/bootc/generated/image-matrix.json"

test -f VERSION
test -f lib/domain-catalog.nix
test -f lib/project-policy.nix
grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' VERSION
grep -qF '!= ".git"' modules/outputs.nix
grep -qF 'lib.hasPrefix ".git/" relative' modules/outputs.nix
test -f "${catalog}"
test -f "${matrix}"
home_catalog="${generated_root}/bootc/generated/home-profile-catalog.json"
test -f "${home_catalog}"
jq -e '
  .schema == 4 and
  (.profiles | length) == 4 and
  all(.profiles[]; .parent == null and .roles == [] and (.foundation == "bluefin" or .foundation == "bluefin-dx")) and
  .profiles["bluefin-generic"].modules == ["base", "hardware-generic-x86_64"] and
  .profiles["bluefin-dx-dell-xps-9350-intel"].modules == ["base", "hardware-dell-xps-9350-intel"]
' "${catalog}" >/dev/null
jq -e '
  map(.profile) == [
    "bluefin-dell-xps-9350-intel",
    "bluefin-dx-dell-xps-9350-intel",
    "bluefin-dx-generic",
    "bluefin-generic"
  ] and
  all(.[];
    .stage == "root" and
    (.build_input | test("^[0-9a-f]{64}$")) and
    (.upstream.digest | test("^sha256:[0-9a-f]{64}$")))
' "${matrix}" >/dev/null
jq -e '
  .schema == 2 and
  (.foundations | keys) == ["bluefin", "bluefin-dx"] and
  (.hardware | keys) == ["dell-xps-9350-intel", "generic-x86_64"] and
  (.roles | keys) == ["developer", "executive", "it", "sales", "support", "trainer"] and
  .foundations.bluefin.template == "home-bluefin" and
  .foundations["bluefin-dx"].template == "home-bluefin-dx" and
  all(.compatibility[]; (.hardware | length) == 2 and (.roles | length) == 6) and
  all(.roles[]; (.foundations | sort) == ["bluefin", "bluefin-dx"])
' "${home_catalog}" >/dev/null

for profile in \
	bluefin-generic \
	bluefin-dell-xps-9350-intel \
	bluefin-dx-generic \
	bluefin-dx-dell-xps-9350-intel; do
	grep -qF -- "- ${profile}" .github/workflows/build-installer.yml
done
grep -A24 -F 'name: Validate installer' .github/workflows/build.yml |
	grep -qF 'end-to-end: true'
if rg -q \
	'base-generic-x86_64|base-dell-xps-9350-intel|sales-generic|sales-dell|support-generic|support-dell|developer-generic|trainer-generic|executive-generic|it-generic' \
	.github/workflows; then
	echo 'A removed fixed profile tag remains in the workflows' >&2
	exit 1
fi

while IFS=$'\t' read -r profile step script; do
	[[ -x "${script}" ]] || {
		echo "${profile}: missing executable aspect build step ${step}: ${script}" >&2
		exit 1
	}
done < <(
	jq -r '.profiles | to_entries[] as $profile |
    $profile.value.buildSteps[] |
    [$profile.key, .name, .script] | @tsv' "${catalog}"
)

test -f bootc/Containerfile
test -f bootc/Containerfile.derived
test -f sources/bluefin.json
test -f sources/bluefin-dx.json
test -f sources/dakota-installer.json
test -f secretspec.toml
jq -e '
  .schema == 1 and
  .image == "ghcr.io/ublue-os/bluefin" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.cosign.issuer | startswith("https://")) and
  (.cosign.identity | startswith("https://"))
' sources/bluefin.json >/dev/null
jq -e '
  .schema == 1 and
  .image == "ghcr.io/ublue-os/bluefin-dx" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.cosign.issuer | startswith("https://")) and
  (.cosign.identity | startswith("https://"))
' sources/bluefin-dx.json >/dev/null
jq -e '
  .schema == 3 and
  .iso_source.owner == "projectbluefin" and
  .iso_source.repository == "dakota-iso" and
  (.iso_source.revision | test("^[0-9a-f]{40}$")) and
  (.installer.url | startswith("https://github.com/projectbluefin/bootc-installer/releases/download/")) and
  (.installer.sha256 | test("^[0-9a-f]{64}$")) and
  .live_image.image == "ghcr.io/projectbluefin/dakota" and
  .live_image.tag == "stable" and
  .live_image.architecture == "amd64" and
  (.live_image.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/dakota-installer.json >/dev/null
grep -qFx 'ARG BASE_REF' bootc/Containerfile
if grep -qF 'bluefin:stable' bootc/Containerfile; then
	echo 'Containerfile contains a mutable Bluefin tag' >&2
	exit 1
fi
grep -qF 'COPY modules/aspects/' bootc/Containerfile
grep -qF '/tmp/finite-build/bootc/builder/full.sh' bootc/Containerfile
grep -qF '/tmp/finite-build/bootc/builder/derived.sh' bootc/Containerfile.derived
grep -qF 'name: Classify and plan' .github/workflows/build.yml
grep -qF 'name: Validate repository and workflows' .github/workflows/build.yml
grep -qF 'needs: [prepare, checks, build-candidate' .github/workflows/build.yml
# Literal GitHub expression contract.
# shellcheck disable=SC2016
grep -qF 'CHECKS_RESULT: ${{ needs.checks.result }}' .github/workflows/build.yml

for obsolete in nix bootc/modules bootc/overlays bootc/components bootc/packages bootc/config installer/overlay ci; do
	test ! -e "${obsolete}" || {
		echo "Legacy architecture path still exists: ${obsolete}" >&2
		exit 1
	}
done
test ! -e tests/ci.sh

test -x bootc/builder/full.sh
test -x bootc/builder/derived.sh
grep -qF "finite_finalize_profile \"\${profile}\" \"\${profile_catalog}\"" bootc/builder/full.sh
grep -qF "finite_finalize_profile \"\${profile}\" \"\${profile_catalog}\"" bootc/builder/derived.sh
grep -qF "local profile_catalog=\"\$2\"" bootc/builder/lib/finalize-profile.sh
test -x modules/aspects/base/apply.sh
test -d modules/aspects/base/rootfs
test -f modules/aspects/capabilities/devops/default.nix
test -x modules/aspects/hardware/dell-xps-9350-intel/apply.sh
test -d modules/aspects/hardware/dell-xps-9350-intel/rootfs
grep -qF 'export CCACHE_DISABLE=1' \
	modules/aspects/hardware/dell-xps-9350-intel/build/install-libcamera-ov02c10-ipa.sh
grep -qF -- "--add \"\${required_initramfs_dracut_modules[*]}\"" \
	modules/aspects/hardware/dell-xps-9350-intel/configure.sh
grep -qF 'local build_packages=(dracut-live git make)' \
	modules/aspects/hardware/dell-xps-9350-intel/configure.sh
test -f modules/aspects/roles/support/default.nix

if find modules/aspects/roles -type d \( -path '*/rootfs/files' -o -path '*/rootfs/manifests' \) | grep -q .; then
	echo 'Role aspects retain a legacy rootfs/files or rootfs/manifests wrapper' >&2
	exit 1
fi

grep -qF 'dnf5 -y install cloud-init jq nix nix-daemon yq zenity' modules/aspects/base/apply.sh
if grep -qF 'install -d -m 0755 /nix' \
	modules/aspects/base/apply.sh modules/aspects/base/install-determinate-nix.sh; then
	echo 'Fedora nix-filesystem must own creation of /nix' >&2
	exit 1
fi
test ! -e modules/aspects/base/manifests/Brewfile
test ! -e modules/aspects/base/independently-managed-rpms.list
test ! -e bootc/builder/lib/independently-managed-rpms.sh
grep -qF 'bitwarden-cli' modules/aspects/base/default.nix
grep -qF 'nixGL.wrap finiteHomeDependencies.weeklyPackages.bitwarden-desktop' \
	modules/aspects/base/default.nix
# shellcheck disable=SC2016
grep -qF 'den.homes.${system}.finite' lib/home-manager-flake-module.nix
grep -qF 'den.aspects.finite-home' lib/home-manager-flake-module.nix
grep -qF 'nh.homeFlake' lib/home-manager-flake-module.nix
grep -qF 'zsh.shellAliases.finite-configure' lib/home-manager-flake-module.nix
grep -qF 'finite.flakeModules.home' lib/home-profile-applications.nix
# shellcheck disable=SC2016
grep -qF '"$nix_command" --accept-flake-config flake lock "$workflake"' lib/home-profile-applications.nix
grep -qF 'homeConfigurations.finite.activationPackage' lib/home-profile-applications.nix
grep -qF 'ConditionPathExists=!%h/.config/finite/profile.json' \
	modules/aspects/base/rootfs/usr/lib/systemd/user/finite-home-first-login.service
test -L modules/aspects/base/rootfs/etc/systemd/user/graphical-session.target.wants/finite-home-first-login.service
test -x modules/aspects/base/rootfs/usr/libexec/finite/home-first-login
if rg -n 'den\.lib\.aspects\.resolve' --glob '*.nix' lib modules; then
	echo 'Production code uses Den internal aspect resolution' >&2
	exit 1
fi

old_product='purple''fin'
if find . -path './.git' -prune -o -iname "*${old_product}*" -print | grep -q .; then
	echo 'A tracked path retains the former product name' >&2
	exit 1
fi
if rg -i "${old_product}" --hidden -g '!.git/**'; then
	echo 'Former product text exists in the active repository' >&2
	exit 1
fi
