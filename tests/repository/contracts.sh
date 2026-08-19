#!/usr/bin/env bash
set -euo pipefail

generated_root="${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
catalog="${generated_root}/bootc/generated/profile-catalog.json"
matrix="${generated_root}/bootc/generated/image-matrix.json"

test -f VERSION
grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' VERSION
test -f "${catalog}"
test -f "${matrix}"
jq -e '
  .schema == 3 and
  (.profiles | length) == 12 and
  .profiles.base.parent == null and
  .profiles["base-generic"].parent == "base" and
  .profiles.dale.parent == "base-dell-xps-9350-intel" and
  .profiles.dale.modules == [
    "base", "devops", "sales", "trainer", "support",
    "hardware-dell-xps-9350-intel"
  ] and
  .profiles.dale.deltaModules == ["devops", "sales", "trainer", "support"]
' "${catalog}" >/dev/null
jq -e 'length == 12 and all(.[]; .build_input | test("^[0-9a-f]{64}$"))' "${matrix}" >/dev/null

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
test -f sources/image-builder.json
test -f secretspec.toml
jq -e '
  .schema == 1 and
  .image == "ghcr.io/projectbluefin/bluefin" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.cosign.issuer | startswith("https://")) and
  (.cosign.identity | startswith("https://"))
' sources/bluefin.json >/dev/null
jq -e '
  .schema == 1 and
  .image == "ghcr.io/osbuild/image-builder-cli" and
  .architecture == "amd64" and
  (.digest | test("^sha256:[0-9a-f]{64}$"))
' sources/image-builder.json >/dev/null
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
test -x modules/aspects/capabilities/devops/apply.sh
test -x modules/aspects/hardware/dell-xps-9350-intel/apply.sh
test -d modules/aspects/hardware/dell-xps-9350-intel/rootfs
test -x modules/aspects/roles/support/apply.sh

if find modules/aspects/roles -type d \( -path '*/rootfs/files' -o -path '*/rootfs/manifests' \) | grep -q .; then
	echo 'Role aspects retain a legacy rootfs/files or rootfs/manifests wrapper' >&2
	exit 1
fi

grep -qF 'dnf5 -y install nix nix-daemon' modules/aspects/base/apply.sh
if grep -qF 'install -d -m 0755 /nix' \
	modules/aspects/base/apply.sh modules/aspects/base/install-determinate-nix.sh; then
	echo 'Fedora nix-filesystem must own creation of /nix' >&2
	exit 1
fi
grep -qF 'marp-cli' modules/aspects/base/manifests/Brewfile
grep -qF '[Flatpak Preinstall org.mozilla.thunderbird]' modules/aspects/base/manifests/flatpaks.preinstall
grep -qF 'tailscale-stable' modules/aspects/base/independently-managed-rpms.list
grep -qF 'espanso-wayland' modules/aspects/base/independently-managed-rpms.list
