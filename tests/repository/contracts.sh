#!/usr/bin/env bash
set -euo pipefail

generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
catalog="${generated_root}/bootc/generated/profile-catalog.json"
matrix="${generated_root}/bootc/generated/image-matrix.json"

test -f VERSION
grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' VERSION
test -f "${catalog}"
test -f "${matrix}"
home_catalog="${generated_root}/bootc/generated/home-profile-catalog.json"
test -f "${home_catalog}"
jq -e '
  .schema == 4 and
  (.profiles | length) == 4 and
  all(.profiles[]; .parent == null and .roles == []) and
  .profiles["bluefin-generic"].modules == ["base", "hardware-generic-x86_64"] and
  .profiles["bluefin-dx-dell-xps-9350-intel"].modules == ["base", "hardware-dell-xps-9350-intel"]
' "${catalog}" >/dev/null
jq -e 'length == 4 and all(.[];
  .stage == "root" and
  (.build_input | test("^[0-9a-f]{64}$")) and
  (.upstream.digest | test("^sha256:[0-9a-f]{64}$")))' "${matrix}" >/dev/null
jq -e '
  .schema == 1 and
  (.profiles | length) == 8 and
  .profiles.sales.baseClass == "bluefin" and
  .profiles.support.baseClass == "bluefin-dx" and
  .profiles.dale.roles == ["sales", "executive", "developer", "support", "it", "trainer"] and
  .profiles.dale.hardware == ["dell-xps-9350-intel"] and
  .profiles.elad.baseClass == "bluefin-dx" and
  .profiles.elad.roles == ["sales", "executive", "developer", "support", "it", "trainer"] and
  .profiles.elad.hardware == ["generic-x86_64"] and
  .profiles.elad.foundations == ["bluefin-dx-generic"]
' "${home_catalog}" >/dev/null

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
test -f sources/image-builder.json
test -f sources/fedora-bootc.json
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
  .schema == 1 and
  .image == "ghcr.io/osbuild/image-builder-cli" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/image-builder.json >/dev/null
jq -e '
  .schema == 1 and
  .image == "quay.io/fedora/fedora-bootc" and
  .tag == "44" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/fedora-bootc.json >/dev/null
grep -qFx 'ARG BASE_REF' bootc/Containerfile
if grep -qF 'bluefin:stable' bootc/Containerfile; then
	echo 'Containerfile contains a mutable Bluefin tag' >&2
	exit 1
fi
grep -qF 'COPY modules/aspects/' bootc/Containerfile
grep -qF '/tmp/purplefin-build/bootc/builder/full.sh' bootc/Containerfile
grep -qF '/tmp/purplefin-build/bootc/builder/derived.sh' bootc/Containerfile.derived

for obsolete in nix bootc/modules bootc/overlays bootc/components bootc/packages bootc/config installer/overlay ci; do
	test ! -e "${obsolete}" || {
		echo "Legacy architecture path still exists: ${obsolete}" >&2
		exit 1
	}
done
test ! -e tests/ci.sh

test -x bootc/builder/full.sh
test -x bootc/builder/derived.sh
grep -qF "purplefin_finalize_profile \"\${profile}\" \"\${profile_catalog}\"" bootc/builder/full.sh
grep -qF "purplefin_finalize_profile \"\${profile}\" \"\${profile_catalog}\"" bootc/builder/derived.sh
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

grep -qF 'dnf5 -y install cloud-init nix nix-daemon' modules/aspects/base/apply.sh
if grep -qF 'install -d -m 0755 /nix' \
	modules/aspects/base/apply.sh modules/aspects/base/install-determinate-nix.sh; then
	echo 'Fedora nix-filesystem must own creation of /nix' >&2
	exit 1
fi
test ! -e modules/aspects/base/manifests/Brewfile
test ! -e modules/aspects/base/independently-managed-rpms.list
test ! -e bootc/builder/lib/independently-managed-rpms.sh
grep -qF 'bitwarden-cli' modules/aspects/base/default.nix
grep -qF 'nixGL.wrap weeklyPkgs.bitwarden-desktop' modules/aspects/base/default.nix
grep -qF "programs.nh.homeFlake = \"path:\${config.xdg.configHome}/home-manager\"" \
	modules/outputs.nix
grep -qF 'home.activation.writeHomeManagerFlake' modules/outputs.nix
grep -qF 'sourceFlake ? "github:declarative-dale/purplefin"' modules/outputs.nix
grep -qF "sourceFlake = \${builtins.toJSON sourceFlake};" modules/outputs.nix
grep -qF 'nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-26.05-chilled/0.1"' \
	modules/outputs.nix
grep -qF 'url = "https://flakehub.com/f/nix-community/home-manager/0.2605"' modules/outputs.nix
grep -qF 'inputs.nixpkgs.follows = "nixpkgs"' modules/outputs.nix
grep -qF 'inputs.nixpkgs-weekly.follows = "nixpkgs-weekly"' modules/outputs.nix
grep -qF 'inputs.home-manager.follows = "home-manager"' modules/outputs.nix
if grep -qF 'xdg.configFile."home-manager/flake.nix"' modules/outputs.nix; then
	echo 'The nh driver flake must be materialized instead of linked into the Nix store' >&2
	exit 1
fi
if grep -qF '/purplefin/home' modules/outputs.nix; then
	echo 'The nh driver flake must use the standard ~/.config/home-manager directory' >&2
	exit 1
fi
