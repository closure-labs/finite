#!/usr/bin/env bash
# Run inside the final image, after BlueBuild's post_build.sh has cleared /var.
set -euo pipefail
expected="${1:?expected profile required}"
repository="${2:-ghcr.io/closure-labs/finite}"
case "$expected" in
  finite|finite-dev) ;;
  *) echo 'Unsupported image profile' >&2; exit 2 ;;
esac
[[ $(cat /usr/share/finite/build-profile) == "$expected" ]]
jq -e --arg profile "$expected" '
  .schema == 1 and .profile == $profile and
  (keys | sort) == ["channel", "foundation", "hardware", "kernelRelease", "profile", "schema"]
' /usr/share/finite/profile.json >/dev/null
rpm -q cloud-init jq nix nix-daemon nix-filesystem nix-system yq zenity \
  fprintd fprintd-pam libfprint pam-u2f pamu2fcfg libfido2 opensc pcsc-lite yubikey-manager
mapfile -t kernels < <(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)
[[ ${#kernels[@]} == 1 ]]
[[ ${kernels[0]} == "$(jq -r .kernelRelease /usr/share/finite/profile.json)" ]]
# The receipt was captured from the authenticated Bluefin base before addons.
# It binds inherited RPM NEVRAs and kernel/module bytes, including ZFS and any
# upstream camera modules. Trust belongs to that preserved upstream set.
python3 /usr/libexec/finite/check-upstream-kernel verify
bash /usr/libexec/finite/check-initramfs "${kernels[0]}"
test -s /usr/lib/finite/determinate-nix-seed/receipt.json
test -x /usr/lib/finite/determinate-nix-seed/nix-installer
test -d /usr/lib/finite/determinate-nix-seed/store
test -d /usr/lib/finite/determinate-nix-seed/var/nix
test -s /usr/share/selinux/packages/determinate-nix.pp
# Both controls are intentional: no generator activation and no datasource scan.
test -f /etc/cloud/cloud-init.disabled
yq -o=json '.' /etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg | jq -se 'length == 1 and .[0].datasource_list == ["None"]' >/dev/null
test -s /usr/share/finite/home-manager-template/customize.nix
test -s /usr/share/finite/home-profile-catalog.json
test ! -e /usr/lib/udev/rules.d/70-finite-espanso-input.rules
test -x /usr/bin/finite-keyboard-access
test -x /usr/bin/finite-app-status
test -x /usr/libexec/finite/desktop-integration
test -x /usr/libexec/finite/password-manager-setup
extension_schemas=/usr/share/gnome-shell/extensions/custom-command-list@storageb.github.com/schemas
if [[ -d "${extension_schemas%/schemas}" ]]; then
  test -s "$extension_schemas/gschemas.compiled"
  gsettings --schemadir "$extension_schemas" list-keys org.gnome.shell.extensions.custom-command-list >/dev/null
fi
python3 /usr/libexec/finite/desktop-integration inspect |
  jq -e '.camera.status != "legacy-selected"' >/dev/null
test -L /usr/lib/systemd/system/multi-user.target.wants/nix-daemon.socket
test -L /usr/lib/systemd/system/multi-user.target.wants/finite-nix-gpu.service
test ! -L /etc/systemd/system/sockets.target.wants/nix-daemon.socket
test ! -L /usr/lib/systemd/system/sockets.target.wants/nix-daemon.socket
key=$(jq -er --arg repo "$repository" '
  .transports.docker[$repo][] | select(.type == "sigstoreSigned" and
    .signedIdentity.type == "matchRepository") | .keyPath
' /etc/containers/policy.json)
test -s "$key"
authselect check
bootc container lint
