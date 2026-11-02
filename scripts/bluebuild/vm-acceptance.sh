#!/usr/bin/env bash
# This creates and destroys only a disk in an ephemeral GitHub-hosted runner.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite ]] || {
  echo 'Run VM acceptance through the finite hosted workflow.' >&2
  exit 2
}
artifact=$(realpath "${1:?ISO artifact directory required}")
monotonic_seconds() {
  local uptime _
  read -r uptime _ </proc/uptime
  printf '%s\n' "${uptime%.*}"
}
pilot=${FINITE_BOOTABILITY_PILOT:-false}
[[ $pilot == true || $pilot == false ]]
if [[ $pilot == true ]]; then
  [[ ${FINITE_SECURE_BOOT:-false} == true && ${3:-} == upgrade ]]
  python3 scripts/bluebuild/bootability-pilot.py preflight
fi
phase_name="${3:-manual}"
[[ $phase_name =~ ^(manual|fresh|upgrade)$ ]]
separate_functional=${FINITE_SEPARATE_FUNCTIONAL:-false}
[[ $separate_functional == true || $separate_functional == false ]]
local_validation=${FINITE_LOCAL_VM_VALIDATION:-false}
[[ $local_validation == true || $local_validation == false ]]
native_predecessor=${FINITE_NATIVE_NIX_PREDECESSOR:-}
if [[ -n $native_predecessor ]]; then
  [[ $local_validation == true && $phase_name == fresh && $pilot == false ]]
  [[ -f $native_predecessor/state.tar && -f $native_predecessor/provenance.json ]]
fi
evidence="$PWD/.bluebuild/vm-$phase_name"
if [[ $pilot == true ]]; then evidence="$PWD/.bluebuild/pilot-private"; fi
if [[ $local_validation == true ]]; then evidence="$PWD/.bluebuild/vm-local"; fi
# Raw logs, disk images, and credentials never enter an upload path, even if
# the runner kills this process before cleanup can sanitize diagnostics.
state=$(mktemp -d /tmp/finite-vm.XXXXXXXX)
chmod 0700 "$state"
record_duration() {
  python3 - "$state/timings.json" "$1" "$2" "${3:-0}" <<'TIMING'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
value = json.loads(path.read_text()) if path.exists() else {'schema': 1, 'seconds': {}}
value['seconds'][sys.argv[2]] = int(sys.argv[3])
value.setdefault('status', {})[sys.argv[2]] = int(sys.argv[4])
path.write_text(json.dumps(value, indent=2) + '\n')
TIMING
}
active_stage=
stage_started=0
begin_stage() {
  active_stage=$1
  stage_started=$(monotonic_seconds)
}
end_stage() {
  if [[ -n $active_stage ]]; then
    record_duration "$active_stage" "$(($(monotonic_seconds) - stage_started))" "${1:-0}"
    active_stage=
  fi
}
trap 'rm -rf "$state"' EXIT
rm -rf "$evidence"
(cd "$artifact" && sha256sum -c SHA256SUMS)
hook_sha=$(sha256sum files/installer/install_finite_fstab | cut -d' ' -f1)
jq -e --slurpfile expected sources/bluebuild-installer.json --slurpfile security sources/installer-security.json --arg hash "$hook_sha" '
  .installer.resolvedImage == ($expected[0].image + "@" + $expected[0].digest) and
  .installer.postInstallHook.sha256 == $hash and
  .installer.secureBootCertificateSha256 == $security[0].derSha256
' "$artifact/installation.json" >/dev/null || {
  echo 'Rebuild this ISO with the current locked installer before acceptance testing.' >&2
  exit 2
}
source=$(jq -er .image "$artifact/installation.json")
channel=$(jq -er .updateChannel "$artifact/installation.json")
installation_tag=$(jq -er .installationTag "$artifact/installation.json")
profile=$(jq -er .profile "$artifact/installation.json")
qualification_profile=${PROFILE:-$profile}
case "$phase_name:$qualification_profile:$profile" in
upgrade:finite:bluefin-generic|upgrade:finite-dev:bluefin-dx-generic) ;;
*) [[ $qualification_profile == "$profile" ]] ;;
esac
target="${2-$channel}"
if [[ -n $target ]]; then
  if [[ $target == "$channel" ]]; then
    target="ghcr.io/closure-labs/finite@$(skopeo inspect --format '{{.Digest}}' "docker://$channel")"
  fi
  [[ $target =~ ^ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
  cosign verify --new-bundle-format=false --key cosign.pub "$target" >"$state/target-signature.json"
  skopeo inspect --raw "docker://$target" >"$state/target-manifest.json"
fi
if [[ $local_validation == true ]]; then
  [[ -z $target && $phase_name == fresh ]]
  python3 - "$artifact/installation.json" <<'LOCAL_CONTEXT'
import json
from pathlib import Path
import sys
sys.path.insert(0, 'scripts/ci')
from local_vm import validate_context
validate_context(json.loads(Path(sys.argv[1]).read_text()))
LOCAL_CONTEXT
  cp "$artifact/source-manifest.json" "$state/source-manifest.json"
  [[ "sha256:$(sha256sum "$state/source-manifest.json" | cut -d' ' -f1)" == "${source##*@}" ]]
else
[[ $source =~ ^ghcr.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
[[ $channel =~ ^ghcr.io/closure-labs/finite:(finite|finite-dev)$ ]]
cosign verify --new-bundle-format=false --key cosign.pub "$source" >"$state/signature.json"
skopeo inspect --raw "docker://$source" >"$state/source-manifest.json"
fi
mapfile -t isos < <(find "$artifact" -maxdepth 1 -name '*.iso' -type f)
[[ ${#isos[@]} == 1 ]]
firmware_root=${FINITE_VM_FIRMWARE_DIR:-/usr/share/OVMF}
firmware=$firmware_root/OVMF_CODE_4M.fd
variables=$firmware_root/OVMF_VARS_4M.fd
secure_args=()
if [[ ${FINITE_SECURE_BOOT:-false} == true ]]; then
  firmware=$firmware_root/OVMF_CODE_4M.secboot.fd
  variables=$firmware_root/OVMF_VARS_4M.ms.fd
  secure_args=(-global 'driver=cfi.pflash01,property=secure,value=on')
fi
test -r "$firmware"
test -r "$variables"
test -e /dev/kvm
sudo chmod a+rw /dev/kvm
# Keep key material and the kickstart outside all artifact upload globs.
secrets="$state/secrets"
mkdir -m 0700 "$secrets"
openssl rand -hex 32 >"$secrets/luks-key"
luks_key=$(cat "$secrets/luks-key")
# GitHub masks accidental diagnostic echoes in the live job log as well.
printf '::add-mask::%s\n' "$luks_key"
pid=
log_pid=
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  end_stage "$result"
  local cleanup_started
  cleanup_started=$(monotonic_seconds)
  if [[ $pilot != true && -n $pid && -f $state/ssh-key ]]; then
    timeout 20s ssh -i "$state/ssh-key" -p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 finite-test@127.0.0.1 \
      sudo journalctl --no-pager -b >"$state/final-journal.log" 2>&1 || true
  fi
  if [[ -n $pid ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  if [[ -n $log_pid ]]; then kill "$log_pid" 2>/dev/null || true; wait "$log_pid" 2>/dev/null || true; fi
  # Installer/journal diagnostics can include kickstart content on failure.
  record_duration cleanup "$(($(monotonic_seconds) - cleanup_started))" "$result"
  if [[ $pilot == true ]]; then
    # Strict allowlist: no logs, disk, firmware variables, kickstart or keys.
    mkdir -p .bluebuild/bootability-pilot
    cp "$state/timings.json" .bluebuild/bootability-pilot/timings.json
    if [[ -f $state/pilot-receipt.json ]]; then
      cp "$state/pilot-receipt.json" .bluebuild/bootability-pilot/receipt.json
    fi
    rm -rf "$state" "$evidence"
    exit "$result"
  fi
  if ! python3 scripts/bluebuild/redact-vm-logs.py "$state" "$secrets/luks-key" "$evidence" --snapshot; then
    echo 'VM diagnostics could not be sanitized; withholding all VM artifacts.' >&2
    result=1
  fi
  rm -rf "$state"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ssh-keygen -q -t ed25519 -N '' -f "$state/ssh-key"
key=$(cat "$state/ssh-key.pub")
nix_resources=$(base64 -w0 scripts/ci/nix-resources.py)
diagnostics=$(base64 -w0 scripts/bluebuild/vm-diagnostics.sh)
user_labels=$(base64 -w0 scripts/bluebuild/check-vm-user-labels.sh)
home_contexts=$(base64 -w0 files/system/usr/libexec/finite/fix-home-selinux-contexts)
nix_policy=$(base64 -w0 files/system/usr/libexec/finite/install-determinate-nix-selinux-policy)
predecessor_policy=$(base64 -w0 scripts/bluebuild/prepare-vm-predecessor-policy.sh)
predecessor_home=$(base64 -w0 scripts/bluebuild/prepare-vm-predecessor-home.sh)
predecessor_enabled=false
if [[ $phase_name == upgrade && $pilot != true ]]; then
  predecessor_enabled=true
fi
cat >"$secrets/ks.cfg" <<KS
lang en_US.UTF-8
keyboard us
timezone America/Chicago
zerombr
clearpart --all --initlabel --drives=vda
autopart --encrypted --luks-version=luks2 --passphrase=$luks_key
bootloader --append="console=ttyS0,115200n8 rd.plymouth=0 plymouth.enable=0"
poweroff
rootpw --lock
# Bluefin initializes the shared Homebrew prefix for the first desktop user.
user --name=finite-test --uid=1000 --gid=1000 --groups=wheel --lock
sshkey --username=finite-test "$key"
%include /usr/share/anaconda/interactive-defaults.ks
%post --erroronfail
printf 'finite-test ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/finite-test
chmod 0440 /etc/sudoers.d/finite-test
mkdir -p /var/lib/finite-vm
printf '%s' '$user_labels' | base64 -d >/var/lib/finite-vm/check-user-labels.sh
printf '%s' '$home_contexts' | base64 -d >/var/lib/finite-vm/fix-home-contexts
chmod 0755 /var/lib/finite-vm/fix-home-contexts
printf '%s' '$nix_policy' | base64 -d >/var/lib/finite-vm/install-nix-policy
printf '%s' '$predecessor_policy' | base64 -d >/var/lib/finite-vm/prepare-predecessor-policy
printf '%s' '$predecessor_home' | base64 -d >/var/lib/finite-vm/prepare-predecessor-home
if [[ '$predecessor_enabled' == true ]]; then
cat >/etc/systemd/system/finite-vm-predecessor-policy.service <<'UNIT'
[Unit]
Description=Prepare historical Finite VM policy once
After=local-fs.target
Before=finite-nix-selinux.service
RequiresMountsFor=/var/lib/finite-vm
ConditionPathExists=!/var/lib/finite-vm/predecessor-labels-prepared
[Service]
Type=oneshot
ExecStart=/usr/bin/bash /var/lib/finite-vm/prepare-predecessor-policy
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console
[Install]
RequiredBy=finite-nix-selinux.service
UNIT
systemctl enable finite-vm-predecessor-policy.service
fi
# Label the installer-created account with the booted image's SELinux policy.
# A dedicated prerequisite fails closed instead of starting SSH with default_t keys.
cat >/etc/systemd/system/finite-vm-user-labels.service <<'UNIT'
[Unit]
Description=Label the Finite acceptance VM account
After=local-fs.target finite-nix-selinux.service
Before=sshd.service
RequiresMountsFor=/home/finite-test
[Service]
Type=oneshot
ExecStart=/usr/bin/bash /var/lib/finite-vm/check-user-labels.sh
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console
[Install]
RequiredBy=sshd.service
UNIT
systemctl enable sshd finite-vm-user-labels.service
mkdir -p /var/lib/finite-vm
printf '%s' '$nix_resources' | base64 -d >/var/lib/finite-vm/nix-resources.py
printf '%s' '$diagnostics' | base64 -d >/var/lib/finite-vm/diagnostics.sh
cat >/etc/systemd/system/finite-vm-diagnostics.service <<'UNIT'
[Unit]
Description=Finite acceptance VM serial diagnostics
[Service]
Type=oneshot
ExecStart=/usr/bin/bash /var/lib/finite-vm/diagnostics.sh
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=30
UNIT
cat >/etc/systemd/system/finite-vm-diagnostics.timer <<'UNIT'
[Unit]
Description=Collect Finite acceptance VM diagnostics after first boot
[Timer]
OnBootSec=90
[Install]
WantedBy=timers.target
UNIT
systemctl enable finite-vm-diagnostics.timer
%end
KS
if [[ -n $native_predecessor ]]; then
  python3 - "$secrets/ks.cfg" <<'PREDECESSOR_STATE'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
assert text.count('%end\n') == 1
text = text.replace('%end\n', '''
test ! -e /var/home/nix
mkdir -p /mnt/finite-native-predecessor
mount -o ro /dev/disk/by-label/FINITE-NIX-STATE /mnt/finite-native-predecessor
echo "$(jq -er .archiveSha256 /mnt/finite-native-predecessor/provenance.json)  /mnt/finite-native-predecessor/state.tar" | sha256sum -c -
mkdir /var/home/nix
tar -xf /mnt/finite-native-predecessor/state.tar --strip-components=1 -C /var/home/nix
jq -er .imageDigest /mnt/finite-native-predecessor/provenance.json >/var/home/nix/finite-predecessor-fixture
umount /mnt/finite-native-predecessor
%end
''')
path.write_text(text)
PREDECESSOR_STATE
  xorriso -as mkisofs -quiet -V FINITE-NIX-STATE -J -R -o "$state/native-predecessor.iso" "$native_predecessor"
fi
if [[ $pilot == true ]]; then
  # The account label helper must not wait on Nix functional initialization.
  # Leave all shipped OS services and their enablement untouched.
  sed -i 's/After=local-fs.target finite-nix-selinux.service/After=local-fs.target/' "$secrets/ks.cfg"
  sed -i '/systemctl enable finite-vm-diagnostics.timer/d' "$secrets/ks.cfg"
fi
bash scripts/bluebuild/prepare-vm-iso.sh "${isos[0]}" "$secrets/ks.cfg" "$state"
bash scripts/bluebuild/prepare-vm-firmware.sh "${isos[0]}" "$variables" "$state"
qemu-img create -f qcow2 "$state/disk.qcow2" 64G
# Exercise general-purpose NoCloud input in the candidate's ordinary desktop
# configuration. Never attach this probe to the historical predecessor.
mkdir "$state/nocloud"
printf 'instance-id: finite-security-probe\n' >"$state/nocloud/meta-data"
cat >"$state/nocloud/user-data" <<'NOCLOUD'
#cloud-config
write_files:
  - path: /var/lib/finite-nocloud-write-executed
    content: untrusted provisioning executed
runcmd:
  - [touch, /var/lib/finite-nocloud-command-executed]
NOCLOUD
xorriso -as mkisofs -quiet -V cidata -J -R -o "$state/nocloud.iso" \
  "$state/nocloud/user-data" "$state/nocloud/meta-data"

qemu_args=(
  -enable-kvm -machine 'q35,smm=on' -cpu host -smp 2 -m 4096 -display none -no-reboot
  "${secure_args[@]}"
  -drive "if=pflash,format=raw,readonly=on,file=$firmware"
  -drive "if=pflash,format=raw,file=$state/OVMF_VARS.fd"
  -drive "if=virtio,format=qcow2,file=$state/disk.qcow2"
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22" -device "virtio-net-pci,netdev=net0"
)
if [[ -n $native_predecessor ]]; then
  qemu_args+=(-drive "if=ide,index=3,media=cdrom,format=raw,readonly=on,file=$state/native-predecessor.iso")
fi
pid=
log_pid=
stream_console() {
  touch "$1"
  if [[ $pilot == true ]]; then return; fi
  tail --pid="$pid" -n +1 -F "$1" &
  log_pid=$!
}
# timeout also bounds Anaconda errors that leave the installer UI waiting.
printf 'Starting unattended UEFI installation at %s (45-minute limit)\n' "$(date -u +%FT%TZ)"
begin_stage installation
timeout 45m qemu-system-x86_64 "${qemu_args[@]}" -boot d -cdrom "$state/install.iso" \
  -serial "file:$state/install.log" &
pid=$!
stream_console "$state/install.log"
# Fail promptly if UEFI never reaches the kernel with our unattended arguments.
boot_deadline=$(($(monotonic_seconds) + 180))
until grep -qF 'inst.ks=cdrom:/ks.cfg' "$state/install.log"; do
  if ! kill -0 "$pid" 2>/dev/null || (($(monotonic_seconds) >= boot_deadline)); then
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
if [[ -n $log_pid ]]; then wait "$log_pid" || true; fi
pid=
log_pid=
if ((install_status != 0)); then
  echo "Installer exited with status $install_status; see install.log (124 means timeout)." >&2
  exit "$install_status"
fi
end_stage 0
printf 'Installer shut down at %s\n' "$(date -u +%FT%TZ)"
rm "$state/install.iso"
ssh_args=(-i "$state/ssh-key" -p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 finite-test@127.0.0.1)
boot_vm() {
  local phase=$1 started deadline remaining attempt_budget sleep_budget
  started=$(monotonic_seconds)
  deadline=$((started + 600))
  local -a provisioning_args=()
  local check_security=false
  if [[ $phase == updated || $phase == native-nix-reboot || ($phase == first-boot && $phase_name != upgrade) ]]; then
    provisioning_args=(-drive "if=ide,media=cdrom,format=raw,readonly=on,file=$state/nocloud.iso")
    check_security=true
  fi
  printf 'Booting %s at %s\n' "$phase" "$(date -u +%FT%TZ)"
  rm -f "$state/serial.sock" "$state/$phase-unlock.log"
  touch "$state/$phase.log"
  qemu-system-x86_64 "${qemu_args[@]}" "${provisioning_args[@]}" -boot c \
    -chardev "socket,id=serial0,path=$state/serial.sock,server=on,wait=on" \
    -serial chardev:serial0 &
  pid=$!
  python3 scripts/bluebuild/unlock-vm.py "$state/serial.sock" "$secrets/luks-key" \
    "$state/$phase.log" "$state/$phase-unlock.log" &
  log_pid=$!
  while (($(monotonic_seconds) < deadline)); do
    if ! kill -0 "$pid" 2>/dev/null || ! kill -0 "$log_pid" 2>/dev/null; then
      echo "VM or disk unlock helper exited during $phase; see $state/$phase.log" >&2
      return 1
    fi
    if grep -Eq 'Kernel panic - not syncing|dracut-initqueue.*Entering emergency mode|You are in emergency mode' "$state/$phase.log"; then
      echo "Fatal boot failure during $phase; see $phase.log" >&2
      return 1
    fi
    if grep -qF 'Perform MOK management' "$state/$phase.log"; then
      echo "Unexpected interactive MOK enrollment during $phase; check firmware-certificate.log" >&2
      return 1
    fi
    remaining=$((deadline - $(monotonic_seconds)))
    if ((remaining <= 0)); then break; fi
    attempt_budget=$((remaining < 10 ? remaining : 10))
    if timeout "${attempt_budget}s" ssh "${ssh_args[@]}" true 2>"$state/$phase-ssh.log"; then
      record_duration "$phase-ssh-ready" "$(($(monotonic_seconds) - started))"
      test -s "$state/$phase-unlock.log"
      ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/check-vm-encryption.sh \
        >"$state/$phase-encryption.log"
      printf 'SSH ready for %s at %s\n' "$phase" "$(date -u +%FT%TZ)"
      if [[ $pilot == true ]]; then
        ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/check-bootability-guest.sh >"$state/$phase-pilot.json"
        record_duration "$phase-boot-contracts" "$(($(monotonic_seconds) - started))"
        return
      fi
      ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/wait-nix.sh | tee "$state/$phase-nix.log"
      if [[ $check_security == true ]]; then
        ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/check-vm-security.sh \
          >"$state/$phase-security.log"
        ssh "${ssh_args[@]}" sudo python3 - <scripts/bluebuild/check-vm-desktop.py \
          >"$state/$phase-desktop.json"
        ssh "${ssh_args[@]}" sudo python3 - <scripts/bluebuild/check-native-nix-guest.py \
          >"$state/$phase-native-nix.json"
        ssh "${ssh_args[@]}" sudo bash -s -- /usr/lib/tmpfiles.d/finite-gdm.conf \
          <scripts/bluebuild/check-vm-gdm-labels.sh >"$state/$phase-gdm-labels.log" 2>&1 || {
            cat "$state/$phase-gdm-labels.log" >&2
            return 1
          }
      fi
      ssh "${ssh_args[@]}" sudo journalctl --no-pager -b -u systemd-remount-fs \
        >"$state/$phase-remount.log"
      ssh "${ssh_args[@]}" sudo journalctl --no-pager -b -u mcelog >"$state/$phase-mcelog.log"
      ssh "${ssh_args[@]}" systemctl --failed --no-pager >"$state/$phase-failed-units.log"
      ssh "${ssh_args[@]}" cat /etc/fstab >"$state/$phase-fstab.log"
      ssh "${ssh_args[@]}" findmnt --json >"$state/$phase-mounts.json"
      ssh "${ssh_args[@]}" systemctl is-active --quiet systemd-remount-fs.service
      if [[ ${FINITE_SECURE_BOOT:-false} == true ]]; then
        ssh "${ssh_args[@]}" env LC_ALL=C mokutil --sb-state | tee "$state/$phase-secure-boot.log" | grep -Fx 'SecureBoot enabled'
      fi
      certificate_sha=$(sha256sum "$state/sb_pubkey.der" | cut -d' ' -f1)
      ssh "${ssh_args[@]}" sudo bash -s -- "$certificate_sha" \
        <scripts/bluebuild/check-vm-mok.sh >"$state/$phase-mok.log" 2>&1
      ssh "${ssh_args[@]}" bash -s <<'KERNEL' | tee "$state/$phase-kernel.log"
set -euo pipefail
expected=$(jq -er .kernelRelease /usr/share/finite/profile.json)
running=$(uname -r)
printf 'Running kernel: %s; image kernel: %s\n' "$running" "$expected"
[[ $running == "$expected" ]]
KERNEL
      record_duration "$phase-boot-contracts" "$(($(monotonic_seconds) - started))"
      return
    fi
    remaining=$((deadline - $(monotonic_seconds)))
    if ((remaining <= 0)); then break; fi
    sleep_budget=$((remaining < 5 ? remaining : 5))
    sleep "$sleep_budget"
  done
  if grep -qF 'Permission denied' "$state/$phase-ssh.log"; then
    echo "SSH authentication rejected during $phase; see $phase-ssh.log and serial authentication diagnostics" >&2
  else
    echo "SSH did not become available during $phase; see $phase-ssh.log" >&2
  fi
  ssh -vv "${ssh_args[@]}" true >"$state/$phase-ssh-debug.log" 2>&1 || true
  return 1
}
poweroff_vm() {
  ssh "${ssh_args[@]}" sudo systemctl poweroff || true
  local deadline
  deadline=$(($(monotonic_seconds) + 120))
  while (($(monotonic_seconds) < deadline)); do
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
if [[ $pilot == true ]]; then
  [[ $local_validation == false ]]
  [[ $source != "$target" && -n $target ]]
  begin_stage signed-update
  python3 scripts/bluebuild/vm-upgrade.py "$state" "$evidence" "$secrets/luks-key" "$target" ssh "${ssh_args[@]}"
  ssh "${ssh_args[@]}" sudo bootc status --json >"$state/staged.json"
  jq -e '.status.staged != null' "$state/staged.json" >/dev/null
  end_stage
  poweroff_vm
  begin_stage candidate-reboot
  boot_vm updated
  ssh "${ssh_args[@]}" sudo bootc status --json >"$state/updated.json"
  end_stage
  # Firmware and enrollment checks are independent of functional initialization.
  ssh "${ssh_args[@]}" env LC_ALL=C mokutil --sb-state | grep -Fx 'SecureBoot enabled' >/dev/null
  certificate_sha=$(sha256sum "$state/sb_pubkey.der" | cut -d' ' -f1)
  ssh "${ssh_args[@]}" sudo bash -s -- "$certificate_sha" <scripts/bluebuild/check-vm-mok.sh >"$state/pilot-mok.log"
  python3 scripts/bluebuild/bootability-pilot.py receipt --state "$state" --source "$source" --target "$target"
  poweroff_vm
  exit 0
fi
# OS startup has no dependency realization. Keep it independent of Home Manager.
ssh "${ssh_args[@]}" bash -s -- "$profile" <<'OS_STARTUP'
set -euo pipefail
echo 'Checking profile, SELinux and Nix daemon startup'
[[ $(cat /usr/share/finite/build-profile) == "$1" ]]
[[ $(getenforce) == Enforcing ]]
mountpoint /nix
/nix/var/nix/profiles/default/bin/nix store ping --store daemon
printf 'persistent-nix-state\n' | sudo tee /var/home/nix/finite-acceptance >/dev/null
OS_STARTUP
functional_status=0
run_functional() {
  local operation=$1 status=0
  # An external shell retains set -e even though the caller records its status.
  bash scripts/bluebuild/vm-functional.sh "$operation" "$state" "$profile" "$phase_name" \
    "$secrets/luks-key" "${ssh_args[@]}" || status=$?
  if [[ $status != 0 ]]; then functional_status=1; fi
  jq -n --arg operation "$operation" --argjson status "$status" \
    '{schema:1,operation:$operation,exitCode:$status}' >"$state/functional-$operation.json"
}
finish_functional() {
  # ISO preservation must wait for this guest's functional success as well.
  if [[ -n ${GITHUB_OUTPUT:-} ]]; then
    if [[ $functional_status == 0 ]]; then
      echo 'functional_passed=true' >>"$GITHUB_OUTPUT"
    else
      echo 'functional_passed=false' >>"$GITHUB_OUTPUT"
    fi
  fi
  # Standalone/experimental callers retain the combined failure contract.
  # Only qualification's separate required functional gate may defer this verdict.
  if [[ $functional_status != 0 && $separate_functional != true ]]; then
    echo 'Required VM functional checks failed' >&2
    exit 1
  fi
}
activation_started=$(monotonic_seconds)
if [[ -n $native_predecessor ]]; then
  poweroff_vm
  boot_vm native-nix-reboot
fi
run_functional initialize
record_duration home-activation "$(($(monotonic_seconds) - activation_started))" "$functional_status"
if [[ -z $target ]]; then
  poweroff_vm
  finish_functional
  jq -n --arg source "$source" --arg profile "$profile" \
    --argjson secure "${FINITE_SECURE_BOOT:-false}" \
    --argjson validation "$local_validation" \
    '{source:$source,profile:$profile,secureBoot:$secure,encryptedRoot:true,accepted:true,validationOnly:$validation}' >"$state/acceptance.json"
  exit 0
fi
# Use a deliberately wrong public key, then restore policy even if the test fails.
echo 'Testing rejection with the wrong signing key'
ssh "${ssh_args[@]}" bash -s -- "$target" >"$state/signature-rejection.log" 2>&1 <<'GUEST'
set -euo pipefail
umask 077
work=$(mktemp -d)
cleanup() {
  result=$?
  set +e
  sudo cp "$work/policy.json" /etc/containers/policy.json || result=1
  if [[ -f $work/rejection.log ]]; then
    cat "$work/rejection.log" || result=1
  fi
  sudo rm -f /etc/pki/containers/finite-acceptance-wrong.pub || result=1
  rm -rf "$work" || result=1
  exit "$result"
}
sudo cp /etc/containers/policy.json "$work/policy.json"
trap cleanup EXIT
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
grep -Eqi 'invalid signature|no matching signatures|none of the signatures|signature verification failed|A signature was required, but no signature exists' "$work/rejection.log"
GUEST
echo 'Selecting the signed ongoing update channel'
upgrade_started=$(monotonic_seconds)
python3 scripts/bluebuild/vm-upgrade.py "$state" "$evidence" "$secrets/luks-key" \
  "$target" ssh "${ssh_args[@]}"
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/staged.json"
jq -e '.status.staged != null' "$state/staged.json" >/dev/null
record_duration upgrade-staging "$(($(monotonic_seconds) - upgrade_started))"
poweroff_vm
boot_vm updated
ssh "${ssh_args[@]}" bash -s -- "$qualification_profile" <<'GUEST'
set -euo pipefail
[[ $(cat /usr/share/finite/build-profile) == "$1" ]]
GUEST
ssh "${ssh_args[@]}" sudo bootc status --json >"$state/updated.json"
jq -e --arg channel "$target" '.status.booted.image.image.image == $channel' \
  "$state/updated.json" >/dev/null
updated_digest=$(jq -er '.status.booted.image.imageDigest' "$state/updated.json")
jq -e --arg installed "$updated_digest" --arg index "${target##*@}" \
  '$installed == $index or any(.manifests[]?; .digest == $installed)' \
  "$state/target-manifest.json" >/dev/null
# A failed initialization still leaves the independent OS persistence assertion
# mandatory. Actual Home Manager customization is checked separately below.
ssh "${ssh_args[@]}" bash -s <<'OS_PERSISTENCE'
set -euo pipefail
[[ $(cat /var/home/nix/finite-acceptance) == persistent-nix-state ]]
OS_PERSISTENCE
run_functional updated
ssh "${ssh_args[@]}" /nix/var/nix/profiles/default/bin/nix store ping --store daemon \
  >"$state/updated-nix-persistence.log" 2>&1 || {
  cat "$state/updated-nix-persistence.log" >&2
  echo 'Post-upgrade Nix daemon persistence check failed' >&2
  exit 1
}
ssh "${ssh_args[@]}" sudo bootc rollback
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
finish_functional
jq -n --arg source "$source" --arg channel "$channel" --arg profile "$qualification_profile" \
  --arg sourceProfile "$profile" \
  --arg target "$target" --argjson secure "${FINITE_SECURE_BOOT:-false}" \
  '{source:$source,target:$target,updateChannel:$channel,profile:$profile,sourceProfile:$sourceProfile,
    uefi:true,secureBoot:$secure,encryptedRoot:true,accepted:true}' >"$state/acceptance.json"
