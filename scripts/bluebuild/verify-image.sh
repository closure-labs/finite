#!/usr/bin/env bash
# Run inside the final image, after BlueBuild's post_build.sh has cleared /var.
set -euo pipefail
expected="${1:?expected profile required}"
repository="${2:-ghcr.io/closure-labs/finite}"
expected_kernel="${3:-}"
[[ $(cat /usr/share/finite/build-profile) == "$expected" ]]
jq -e --arg profile "$expected" '
  .schema == 1 and .profile == $profile and
  (keys | sort) == ["channel", "foundation", "hardware", "kernelRelease", "profile", "schema"]
' /usr/share/finite/profile.json >/dev/null
rpm -q cloud-init jq nix nix-daemon nix-filesystem nix-system yq zenity \
  fprintd fprintd-pam libfprint pam-u2f pamu2fcfg libfido2 opensc pcsc-lite yubikey-manager
mapfile -t kernels < <(rpm -q --qf '%{EVR}.%{ARCH}\n' kernel-core)
[[ ${#kernels[@]} == 1 ]]
[[ -n $expected_kernel && ${kernels[0]} == "$expected_kernel" ]]
[[ ${kernels[0]} == "$(jq -r .kernelRelease /usr/share/finite/profile.json)" ]]
for package in kmod-v4l2loopback v4l2loopback kmod-zfs zfs python3-pyzfs; do
  if rpm -q "$package" >/dev/null 2>&1; then
    echo "Unsupported host kernel/storage package remains installed: $package" >&2
    exit 1
  fi
done
if modinfo -k "${kernels[0]}" -F filename zfs >/dev/null 2>&1; then
  echo 'Unsupported ZFS kernel module remains available' >&2
  exit 1
fi
bash /usr/libexec/finite/check-initramfs "${kernels[0]}"
if [[ $expected == *-next ]]; then
  for module in intel_cvs intel_ipu7 intel_ipu7_isys ipu_bridge ov02c10; do
    [[ $(modinfo -k "${kernels[0]}" -F intree "$module") == Y ]]
    [[ $(modinfo -k "${kernels[0]}" -F signer "$module") == *Fedora* ]]
  done
fi
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
