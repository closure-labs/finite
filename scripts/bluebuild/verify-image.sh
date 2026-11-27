#!/usr/bin/env bash
# Run inside the final image, after BlueBuild's post_build.sh has cleared /var.
set -euo pipefail
expected="${1:?expected profile required}"
repository="${2:-ghcr.io/closure-labs/finite}"
case "$expected" in
  finite|finite-dev|finite-native|finite-native-dev) ;;
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
if [[ -f /usr/lib/composefs/setup-root-conf.toml ]]; then
  python3 - <<'PY_RUNTIME'
import hashlib,json,subprocess
from pathlib import Path
receipt=json.loads(Path('/usr/share/finite/bootc-runtime.json').read_text())
pin=receipt['source']
assert receipt['schema']==1 and pin['kind'] in ('upstream-snapshot','release')
assert set(receipt['files'])=={'/usr/bin/bootc','/usr/lib/bootc/initramfs-setup'}
assert subprocess.check_output(['bootc','--version'],text=True).strip()=='bootc '+pin['version']
assert subprocess.check_output(['rpm','-q','--qf','%{VERSION}-%{RELEASE}','bootc'],text=True)==receipt['rpm']
for name,digest in receipt['files'].items():
 with open(name,'rb') as stream:
  assert hashlib.file_digest(stream,'sha256').hexdigest()==digest, 'Native runtime bytes changed'
PY_RUNTIME
fi
# The receipt was captured from the authenticated Bluefin base before addons.
# It binds inherited RPM NEVRAs and kernel/module bytes, including ZFS and any
# upstream camera modules. Trust belongs to that preserved upstream set.
if [[ -f /usr/lib/composefs/setup-root-conf.toml && ! -f /usr/lib/modules/${kernels[0]}/vmlinuz ]]; then
  uki="/boot/EFI/Linux/${kernels[0]}.efi"
  certificate=/usr/share/finite/secure-boot/finite-boot.pem
  sbverify --cert "$certificate" "$uki"
  payload=$(mktemp -d)
  trap 'rm -rf -- "$payload"' EXIT
  python3 /usr/libexec/finite/check-upstream-kernel verify --uki "$uki" --extract-to "$payload"
  bash /usr/libexec/finite/check-initramfs "${kernels[0]}" "$payload" native
  rm -rf -- "$payload"
  trap - EXIT
else
  python3 /usr/libexec/finite/check-upstream-kernel verify
  bash /usr/libexec/finite/check-initramfs "${kernels[0]}"
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
