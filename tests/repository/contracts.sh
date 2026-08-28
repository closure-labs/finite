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
  .profiles["bluefin-generic"].kernelRelease == null and
  .profiles["bluefin-next"].modules == ["base", "hardware-next-x86_64"] and
  .profiles["bluefin-next"].kernelRelease == "7.2.0-61.fc45.x86_64" and
  .profiles["bluefin-next"].tags == ["next"] and
  .profiles["bluefin-dx-next"].modules == ["base", "hardware-next-x86_64"] and
  .profiles["bluefin-dx-next"].kernelRelease == "7.2.0-61.fc45.x86_64" and
  .profiles["bluefin-dx-next"].tags == ["dev-next"]
' "${catalog}" >/dev/null
jq -e '
  map(.profile) == [
    "bluefin-next",
    "bluefin-dx-next",
    "bluefin-dx-generic",
    "bluefin-generic"
  ] and
  all(.[];
    .stage == "root" and
    ((.hardware == "next-x86_64" and .kernelRelease == "7.2.0-61.fc45.x86_64") or
      (.hardware == "generic-x86_64" and .kernelRelease == null)) and
    (.build_input | test("^[0-9a-f]{64}$")) and
    (.upstream.digest | test("^sha256:[0-9a-f]{64}$")))
' "${matrix}" >/dev/null
jq -e '
  .schema == 3 and
  (.foundations | keys) == ["bluefin", "bluefin-dx"] and
  (.hardware | keys) == ["dell-xps-9350-intel", "generic-x86_64"] and
  (.packages | keys) == ["hack-font", "herdr", "jj", "opencode", "uv"] and
  (.roles | keys) == ["developer", "executive", "it", "sales", "support", "trainer"] and
  .foundations.bluefin.template == "home-bluefin" and
  .foundations["bluefin-dx"].template == "home-bluefin-dx" and
  .foundations.bluefin.profiles == {
    "generic-x86_64": "bluefin-generic", "next-x86_64": "bluefin-next"
  } and
  .foundations["bluefin-dx"].profiles == {
    "generic-x86_64": "bluefin-dx-generic", "next-x86_64": "bluefin-dx-next"
  } and
  all(.hardware[]; .imageHardware == ["generic-x86_64", "next-x86_64"]) and
  all(.foundations[]; .packages == ["hack-font", "herdr", "jj", "opencode", "uv"]) and
  all(.compatibility[];
    (.hardware | length) == 2 and (.packages | length) == 5 and (.roles | length) == 6) and
  all(.packages[]; (.foundations | sort) == ["bluefin", "bluefin-dx"]) and
  all(.roles[]; (.foundations | sort) == ["bluefin", "bluefin-dx"])
' "${home_catalog}" >/dev/null

for profile in \
	bluefin-generic \
	bluefin-next \
	bluefin-dx-generic \
	bluefin-dx-next; do
	grep -qF -- "- ${profile}" .github/workflows/build-installer.yml
done
grep -A24 -F 'name: Validate installer' .github/workflows/build.yml |
	grep -qF 'end-to-end: true'
if rg -q \
	'bluefin-(dx-)?dell-xps-9350-intel|base-generic-x86_64|base-dell-xps-9350-intel|sales-generic|sales-dell|support-generic|support-dell|developer-generic|trainer-generic|executive-generic|it-generic' \
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
test -f sources/kernel-next.json
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
jq -e '
  .schema == 1 and
  .release == "7.2.0-61.fc45.x86_64" and
  (.baseUrl | startswith("https://kojipkgs.fedoraproject.org/packages/kernel/7.2.0/61.fc45/")) and
  (.packages | map(.name)) == [
    "kernel", "kernel-core", "kernel-modules-core", "kernel-modules", "kernel-modules-extra"
  ] and
  all(.packages[]; (.sha256 | test("^[0-9a-f]{64}$"))) and
  (.requiredModules | sort) == [
    "intel_cvs", "intel_ipu7", "intel_ipu7_isys", "ipu_bridge", "ov02c10"
  ]
' sources/kernel-next.json >/dev/null
kernel_root="${generated_root}/bootc/generated/kernel-next"
test -f "${kernel_root}/kernel-next.json"
while IFS=$'\t' read -r file sha256; do
	test -f "${kernel_root}/${file}"
	printf '%s  %s\n' "${sha256}" "${kernel_root}/${file}" | sha256sum --check --strict
done < <(jq -r '.packages[] | [.file, .sha256] | @tsv' sources/kernel-next.json)
grep -qFx 'ARG BASE_REF' bootc/Containerfile
if grep -qF 'bluefin:stable' bootc/Containerfile; then
	echo 'Containerfile contains a mutable Bluefin tag' >&2
	exit 1
fi
grep -qF 'COPY modules/aspects/' bootc/Containerfile
grep -qF '/tmp/finite-build/bootc/builder/full.sh' bootc/Containerfile
grep -qF '/tmp/finite-build/bootc/builder/derived.sh' bootc/Containerfile.derived
for build_driver in \
	lib/ci-applications/image-operations.nix \
	lib/ci-applications/profile-stage.nix \
	lib/ci-applications/validate-image-shard.nix; do
	grep -qF 'kernel_label+=(--label "ostree.linux=' "${build_driver}"
done
# shellcheck disable=SC2016
grep -qF '$labels["ostree.linux"] == $kernel_release' \
	lib/ci-applications/image-operations.nix
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
test -x modules/aspects/hardware/next-x86_64/apply.sh
test -f modules/aspects/hardware/next-x86_64/default.nix
test -f modules/aspects/hardware/dell-xps-9350-intel/default.nix
test ! -e modules/aspects/hardware/dell-xps-9350-intel/apply.sh
test ! -e modules/aspects/hardware/dell-xps-9350-intel/rootfs
# shellcheck disable=SC2016
grep -qF 'dnf5 -y install --allowerasing "${rpms[@]}"' \
	modules/aspects/hardware/next-x86_64/apply.sh
# shellcheck disable=SC2016
grep -qF 'modinfo -k "${release}" -F intree' \
	modules/aspects/hardware/next-x86_64/apply.sh
if rg -n 'libcamera|hm1092|updates/finite|configure-firefox-pipewire-camera' \
	modules/aspects/hardware/next-x86_64/apply.sh \
	modules/aspects/hardware/next-x86_64/default.nix \
	templates/home-manager/modules/aspects/hardware/dell-xps-9350-intel/home.nix \
	templates/home-manager/modules/aspects/hardware/dell-xps-9350-intel/dell-xps-9350-panel-policy; then
	echo 'The next image or Dell Home Manager aspect retains a camera workaround' >&2
	exit 1
fi
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
grep -qF 'weekly.bitwarden-cli' templates/home-manager/modules/aspects/base/home.nix
grep -qF 'config.lib.nixGL.wrap weekly.bitwarden-desktop' \
	templates/home-manager/modules/aspects/base/home.nix
grep -qF 'config.lib.nixGL.wrap weekly.firefox' \
	templates/home-manager/modules/aspects/base/home.nix
for package in element-desktop libreoffice nextcloud-client; do
	grep -qF "config.lib.nixGL.wrap weekly.${package}" \
		templates/home-manager/modules/aspects/base/home.nix
done
for package in thunderbird vlc; do
	grep -qF "config.lib.nixGL.wrap pkgs.${package}" \
		templates/home-manager/modules/aspects/base/home.nix
done
grep -qF 'config.lib.nixGL.wrap pkgs.vscodium' \
	templates/home-manager/modules/aspects/roles/developer/home.nix
if grep -qF 'pkgs.thunderbird' templates/home-manager/modules/aspects/roles/sales/home.nix; then
	echo 'Thunderbird must be supplied by the all-role base, not the sales role' >&2
	exit 1
fi
if grep -Eq 'com\.nextcloud\.desktopclient\.nextcloud|com\.spotify\.Client|im\.riot\.Riot|org\.libreoffice\.LibreOffice|org\.signal\.Signal' \
	templates/home-manager/modules/aspects/base/home.nix; then
	echo 'Nix desktop replacements must not remain in the managed Flatpak list' >&2
	exit 1
fi
if grep -Eq '(^|[[:space:]])bitwarden-cli([[:space:]]|$)|wrap pkgs\.bitwarden-desktop' \
	templates/home-manager/modules/aspects/base/home.nix; then
	echo 'Bitwarden Desktop and CLI must come from the weekly input' >&2
	exit 1
fi
grep -qF 'fzf.enable = true' templates/home-manager/modules/aspects/base/home.nix
grep -qF 'weekly.bbrew' templates/home-manager/modules/aspects/base/home.nix
grep -qF 'weekly.mise' templates/home-manager/modules/aspects/base/home.nix
if rg -n '\b(codex|awscli)\b' \
	lib/domain-catalog.nix templates/home-manager/modules/aspects/base/home.nix \
	templates/home-manager/modules/finite.nix; then
	echo 'Codex or AWS CLI leaked into the Finite base Home Manager configuration' >&2
	exit 1
fi
# shellcheck disable=SC2016
grep -qF 'den.homes.${system}.${cfg.identity.username}' lib/home-manager-flake-module.nix
# shellcheck disable=SC2016
grep -qF 'den.homes.${system}.${vars.identity.username}' \
	templates/home-manager/modules/finite.nix
grep -qF 'den.aspects.finite-home' lib/home-manager-flake-module.nix
grep -qF 'nh.homeFlake' lib/home-manager-flake-module.nix
grep -qF 'zsh.shellAliases.finite-configure' lib/home-manager-flake-module.nix
grep -qF 'FINITE_HOME_TEMPLATE_PATH' lib/home-profile-applications.nix
# shellcheck disable=SC2016
grep -qF 'homeConfigurations.${username}.activationPackage' \
	modules/aspects/base/rootfs/usr/libexec/finite/home-init
grep -qF 'home-manager.previous.' \
	modules/aspects/base/rootfs/usr/libexec/finite/home-init
test -f templates/home-manager/finite-template.json
test -f templates/home-manager/flake.lock
test -f templates/home-manager/customize.nix
test -f templates/home-manager/modules/finite-brew-migration-status
test -f templates/home-manager/modules/aspects/base/home.nix
if grep -qF 'ConditionPathExists=' \
	modules/aspects/base/rootfs/usr/lib/systemd/user/finite-home-first-login.service; then
	echo 'The login service cannot detect and replace an older Home Manager scaffold' >&2
	exit 1
fi
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
