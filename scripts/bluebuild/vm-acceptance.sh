#!/usr/bin/env bash
# This creates and destroys only a disk in an ephemeral GitHub-hosted runner.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]] || {
  echo 'Run VM acceptance through the finite hosted workflow.' >&2
  exit 2
}
artifact=$(realpath "${1:?ISO artifact directory required}")
state="$PWD/.bluebuild/vm"
mkdir -p "$state"
(cd "$artifact" && sha256sum -c SHA256SUMS)
hook_sha=$(sha256sum files/installer/install_finite_fstab | cut -d' ' -f1)
jq -e --slurpfile expected sources/bluebuild-installer.json --arg hash "$hook_sha" '
  .installer.resolvedImage == ($expected[0].image + "@" + $expected[0].digest) and
  .installer.postInstallHook.sha256 == $hash
' "$artifact/installation.json" >/dev/null || {
  echo 'Rebuild this ISO with the current locked installer before acceptance testing.' >&2
  exit 2
}
source=$(jq -er .image "$artifact/installation.json")
channel=$(jq -er .updateChannel "$artifact/installation.json")
installation_tag=$(jq -er .installationTag "$artifact/installation.json")
profile=$(jq -er .profile "$artifact/installation.json")
[[ $source =~ ^ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
[[ $channel =~ ^ghcr.io/closure-labs/finite:(bluefin-generic|next|bluefin-dx-generic|dev-next)$ ]]
cosign verify --key cosign.pub "$source" >"$state/signature.json"
skopeo inspect --raw "docker://$source" >"$state/source-manifest.json"
mapfile -t isos < <(find "$artifact" -maxdepth 1 -name '*.iso' -type f)
[[ ${#isos[@]} == 1 ]]
test -r /usr/share/OVMF/OVMF_CODE_4M.fd
test -e /dev/kvm
sudo chmod a+rw /dev/kvm
ssh-keygen -q -t ed25519 -N '' -f "$state/ssh-key"
key=$(cat "$state/ssh-key.pub")
cat >"$state/ks.cfg" <<KS
lang en_US.UTF-8
keyboard us
timezone America/Chicago
zerombr
clearpart --all --initlabel --drives=vda
autopart
poweroff
rootpw --lock
user --name=finite-test --groups=wheel --lock
sshkey --username=finite-test "$key"
%include /usr/share/anaconda/interactive-defaults.ks
%post --erroronfail
printf 'finite-test ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/finite-test
chmod 0440 /etc/sudoers.d/finite-test
systemctl enable sshd
%end
KS
bash scripts/bluebuild/prepare-vm-iso.sh "${isos[0]}" "$state/ks.cfg" "$state"
cp /usr/share/OVMF/OVMF_VARS_4M.fd "$state/OVMF_VARS.fd"
qemu-img create -f qcow2 "$state/disk.qcow2" 64G
qemu_args=(
  -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 -display none -no-reboot
  -drive "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd"
  -drive "if=pflash,format=raw,file=$state/OVMF_VARS.fd"
  -drive "if=virtio,format=qcow2,file=$state/disk.qcow2"
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22" -device "virtio-net-pci,netdev=net0"
)
pid=
log_pid=
stream_console() {
  touch "$1"
  tail --pid="$pid" -n +1 -F "$1" &
  log_pid=$!
}
cleanup() {
  if [[ -n $pid ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  if [[ -n $log_pid ]]; then kill "$log_pid" 2>/dev/null || true; wait "$log_pid" 2>/dev/null || true; fi
  rm -f "$state/ssh-key" "$state/install.iso" "$state/disk.qcow2"
}
trap cleanup EXIT
# timeout also bounds Anaconda errors that leave the installer UI waiting.
printf 'Starting unattended UEFI installation at %s (45-minute limit)\n' "$(date -u +%FT%TZ)"
timeout 45m qemu-system-x86_64 "${qemu_args[@]}" -boot d -cdrom "$state/install.iso" \
  -serial "file:$state/install.log" &
pid=$!
stream_console "$state/install.log"
# Fail promptly if UEFI never reaches the kernel with our unattended arguments.
boot_deadline=$((SECONDS + 180))
until grep -qF 'inst.ks=cdrom:/ks.cfg' "$state/install.log"; do
  if ! kill -0 "$pid" 2>/dev/null || ((SECONDS >= boot_deadline)); then
    echo 'Installer kernel did not report its unattended arguments within three minutes.' >&2
    exit 1
  fi
  sleep 1
done
echo 'Installer kernel booted with the unattended kickstart arguments'
while kill -0 "$pid" 2>/dev/null; do
  if grep -Eq 'AnacondaError:|Cannot finalize fstab:|Pane is dead \(status [1-9]|Kernel panic - not syncing' "$state/install.log"; then
    echo 'Installer reported a fatal error; stopping the VM. See install.log.' >&2
    exit 1
  fi
  sleep 2
done
install_status=0
wait "$pid" || install_status=$?
wait "$log_pid" || true
pid=
log_pid=
if ((install_status != 0)); then
  echo "Installer exited with status $install_status; see install.log (124 means timeout)." >&2
  exit "$install_status"
fi
printf 'Installer shut down at %s\n' "$(date -u +%FT%TZ)"
rm "$state/install.iso"
ssh_args=(-i "$state/ssh-key" -p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 finite-test@127.0.0.1)
boot_vm() {
  local phase=$1
  printf 'Booting %s at %s\n' "$phase" "$(date -u +%FT%TZ)"
  qemu-system-x86_64 "${qemu_args[@]}" -boot c -serial "file:$state/$phase.log" &
  pid=$!
  stream_console "$state/$phase.log"
  for _ in {1..120}; do
    kill -0 "$pid"
    if ssh "${ssh_args[@]}" true 2>/dev/null; then
      printf 'SSH ready for %s at %s\n' "$phase" "$(date -u +%FT%TZ)"
      ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/wait-nix.sh | tee "$state/$phase-nix.log"
      ssh "${ssh_args[@]}" sudo journalctl --no-pager -b -u systemd-remount-fs \
        >"$state/$phase-remount.log"
      ssh "${ssh_args[@]}" sudo journalctl --no-pager -b -u mcelog >"$state/$phase-mcelog.log"
      ssh "${ssh_args[@]}" systemctl --failed --no-pager >"$state/$phase-failed-units.log"
      ssh "${ssh_args[@]}" cat /etc/fstab >"$state/$phase-fstab.log"
      ssh "${ssh_args[@]}" findmnt --json >"$state/$phase-mounts.json"
      ssh "${ssh_args[@]}" systemctl is-active --quiet systemd-remount-fs.service
      ssh "${ssh_args[@]}" bash -s <<'KERNEL' | tee "$state/$phase-kernel.log"
set -euo pipefail
expected=$(jq -er .kernelRelease /usr/share/finite/profile.json)
running=$(uname -r)
printf 'Running kernel: %s; image kernel: %s\n' "$running" "$expected"
[[ $running == "$expected" ]]
KERNEL
      return
    fi
    sleep 5
  done
  echo "SSH did not become available during $phase" >&2
  return 1
}
poweroff_vm() {
  ssh "${ssh_args[@]}" sudo systemctl poweroff || true
  for _ in {1..60}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      wait "$log_pid" || true
      pid=
      log_pid=
      return
    fi
    sleep 2
  done
  echo 'Guest did not shut down' >&2
  return 1
}
boot_vm first-boot
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/first-boot.json"
# The imported digest can be the architecture manifest, rather than its signed index.
jq -e --arg tag "$installation_tag" '.status.booted.image.image.image == $tag' \
  "$state/first-boot.json" >/dev/null
installed_digest=$(jq -er '.status.booted.image.imageDigest' "$state/first-boot.json")
jq -e --arg installed "$installed_digest" --arg index "${source##*@}" \
  '$installed == $index or any(.manifests[]?; .digest == $installed)' \
  "$state/source-manifest.json" >/dev/null
ssh "${ssh_args[@]}" bash -s -- "$profile" <<'GUEST'
set -euo pipefail
echo 'Checking profile, SELinux and Nix daemon startup'
[[ $(cat /usr/share/finite/build-profile) == "$1" ]]
[[ $(getenforce) == Enforcing ]]
mountpoint /nix
/nix/var/nix/profiles/default/bin/nix store ping --store daemon
printf 'persistent-nix-state\n' | sudo tee /var/home/nix/finite-acceptance >/dev/null
jq -n --arg foundation "$(jq -r .foundation /usr/share/finite/profile.json)" \
  '{schema:2,foundation:$foundation,hardware:"generic-x86_64",packages:[],roles:[],identity:{}}' >"$HOME/profile.json"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export FINITE_NIX_COMMAND=/nix/var/nix/profiles/default/bin/nix
echo 'Building and activating the base Home Manager environment'
/usr/libexec/finite/home-init --profile "$HOME/profile.json"
printf '\n# VM acceptance customization\n' >>"$HOME/.config/home-manager/customize.nix"
GUEST
# Use a deliberately wrong public key, then restore policy even if the test fails.
echo 'Testing rejection with the wrong signing key'
ssh "${ssh_args[@]}" bash -s -- "$channel" <<'GUEST'
set -euo pipefail
work=$(mktemp -d)
trap 'sudo cp "$work/policy.json" /etc/containers/policy.json; sudo rm -f /etc/pki/containers/finite-acceptance-wrong.pub; rm -rf "$work"' EXIT
sudo cp /etc/containers/policy.json "$work/policy.json"
sudo chown "$(id -u):$(id -g)" "$work/policy.json"
COSIGN_PASSWORD='' cosign generate-key-pair --output-key-prefix "$work/wrong" >/dev/null
sudo install -m 0644 "$work/wrong.pub" /etc/pki/containers/finite-acceptance-wrong.pub
sudo restorecon /etc/pki/containers/finite-acceptance-wrong.pub
jq --arg key /etc/pki/containers/finite-acceptance-wrong.pub \
  '.transports.docker["ghcr.io/closure-labs/finite"][0].keyPath = $key' \
  "$work/policy.json" | sudo tee /etc/containers/policy.json >/dev/null
if sudo bootc switch --enforce-container-sigpolicy "$1" >"$work/rejection.log" 2>&1; then
  echo 'bootc accepted an image with the wrong signing key' >&2
  exit 1
fi
grep -Ei 'invalid signature|no matching signatures|none of the signatures|signature verification failed' "$work/rejection.log"
GUEST
echo 'Selecting the signed ongoing update channel'
ssh "${ssh_args[@]}" sudo bootc switch --enforce-container-sigpolicy "$channel"
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/staged.json"
jq -e '.status.staged != null' "$state/staged.json" >/dev/null
poweroff_vm
boot_vm updated
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/updated.json"
jq -e --arg channel "$channel" '.status.booted.image.image.image == $channel' \
  "$state/updated.json" >/dev/null
ssh "${ssh_args[@]}" bash -s <<'GUEST'
set -euo pipefail
[[ $(cat /var/home/nix/finite-acceptance) == persistent-nix-state ]]
grep -q 'VM acceptance customization' "$HOME/.config/home-manager/customize.nix"
/nix/var/nix/profiles/default/bin/nix store ping --store daemon
sudo bootc rollback
GUEST
poweroff_vm
boot_vm rollback
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/rollback.json"
initial=$(jq -er '.status.booted.ostree.checksum' "$state/first-boot.json")
jq -e --arg initial "$initial" '.status.booted.ostree.checksum == $initial' "$state/rollback.json" >/dev/null
jq -e --arg tag "$installation_tag" '.status.booted.image.image.image == $tag' \
  "$state/rollback.json" >/dev/null
ssh "${ssh_args[@]}" sudo journalctl -b -u finite-nix-seed -u finite-nix-selinux -u nix-daemon \
  >"$state/nix-journal.log"
poweroff_vm
jq -n --arg source "$source" --arg channel "$channel" --arg profile "$profile" \
  '{source:$source,updateChannel:$channel,profile:$profile,uefi:true,accepted:true}' >"$state/acceptance.json"
