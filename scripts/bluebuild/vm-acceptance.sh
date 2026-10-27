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
phase_name="${3:-manual}"
[[ $phase_name =~ ^(manual|fresh|upgrade)$ ]]
local_validation=${FINITE_LOCAL_VM_VALIDATION:-false}
[[ $local_validation == true || $local_validation == false ]]
evidence="$PWD/.bluebuild/vm-$phase_name"
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
  if [[ -n $pid && -f $state/ssh-key ]]; then
    timeout 20s ssh -i "$state/ssh-key" -p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 finite-test@127.0.0.1 \
      sudo journalctl --no-pager -b >"$state/final-journal.log" 2>&1 || true
  fi
  if [[ -n $pid ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  if [[ -n $log_pid ]]; then kill "$log_pid" 2>/dev/null || true; wait "$log_pid" 2>/dev/null || true; fi
  # Installer/journal diagnostics can include kickstart content on failure.
  record_duration cleanup "$(($(monotonic_seconds) - cleanup_started))" "$result"
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
if [[ $phase_name == upgrade ]]; then
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
pid=
log_pid=
stream_console() {
  touch "$1"
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
wait "$log_pid" || true
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
  if [[ $phase == updated || ($phase == first-boot && $phase_name != upgrade) ]]; then
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
      ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/wait-nix.sh | tee "$state/$phase-nix.log"
      if [[ $check_security == true ]]; then
        ssh "${ssh_args[@]}" sudo bash -s <scripts/bluebuild/check-vm-security.sh \
          >"$state/$phase-security.log"
        ssh "${ssh_args[@]}" sudo python3 - <scripts/bluebuild/check-vm-desktop.py \
          >"$state/$phase-desktop.json"
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
activation_started=$(monotonic_seconds)
ssh "${ssh_args[@]}" bash -s -- "$profile" "$phase_name" <<'GUEST' | python3 scripts/bluebuild/guest-timings.py "$state/guest-timings.json"
set -euo pipefail
guest_now() {
  local uptime unused
  read -r uptime unused </proc/uptime
  printf '%s\n' "${uptime%.*}"
}
guest_stage=
guest_started=0
guest_finish() {
  local status=$1
  if [[ -n $guest_stage ]]; then
    printf 'FINITE_GUEST_STAGE %s %s %s\n' "$guest_stage" "$(($(guest_now) - guest_started))" "$status"
    guest_stage=
  fi
}
guest_begin() {
  guest_finish 0
  guest_stage=$1
  guest_started=$(guest_now)
}
trap 'guest_finish "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
guest_begin startup-checks
echo 'Checking profile, SELinux and Nix daemon startup'
[[ $(cat /usr/share/finite/build-profile) == "$1" ]]
[[ $(getenforce) == Enforcing ]]
mountpoint /nix
/nix/var/nix/profiles/default/bin/nix store ping --store daemon
printf 'persistent-nix-state\n' | sudo tee /var/home/nix/finite-acceptance >/dev/null
jq -n --arg foundation "$(jq -r .foundation /usr/share/finite/profile.json)" \
  '{schema:3,foundation:$foundation,hardware:"generic-x86_64",packages:[],roles:[],capabilities:[],identity:{}}' >"$HOME/profile.json"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export FINITE_NIX_COMMAND=/nix/var/nix/profiles/default/bin/nix
# Budget from the guest's CPUs/RAM, not the host runner. Preserve inherited config.
export NIX_CONFIG="${NIX_CONFIG:-}
$(python3 /var/lib/finite-vm/nix-resources.py --config)"
python3 /var/lib/finite-vm/nix-resources.py --verify --nix "$FINITE_NIX_COMMAND"
guest_begin homebrew-setup
echo 'Checking the desktop user and shared Homebrew initialization'
[[ $(id -u) == 1000 && $(id -g) == 1000 ]]
sudo systemctl start brew-setup.service
stat -c '%u:%g %a %n' /home/linuxbrew/.linuxbrew /home/linuxbrew/.linuxbrew/Homebrew
[[ -w /home/linuxbrew/.linuxbrew/Homebrew && -w /home/linuxbrew/.linuxbrew/Cellar ]]
guest_begin predecessor-preparation
if [[ $2 == upgrade ]]; then
  bash /var/lib/finite-vm/prepare-predecessor-home
fi
guest_begin home-init
echo 'Building and activating the base Home Manager environment'
FOUNDATION_TIMINGS=1 /usr/libexec/finite/home-init --profile "$HOME/profile.json" </dev/null 2>&1
GUEST
# Initializers and their children must not consume commands from bash -s stdin.
# Establish the fixture over a separate SSH request, then prove it exists before
# changing deployments so an uncreated marker cannot masquerade as data loss.
begin_stage persistence-customization
ssh "${ssh_args[@]}" python3 - >"$state/initialized-home.json" <<'HOME_INITIALIZED'
import hashlib
import json
from pathlib import Path

configuration = Path.home() / '.config/home-manager'
customization = configuration / 'customize.nix'
for name in ('flake.nix', 'flake.lock', 'profile.json', 'customize.nix'):
    if not (configuration / name).is_file():
        raise ValueError('Home initialization did not produce the required configuration file: ' + name)
if Path('/var/home/nix/finite-acceptance').read_text().rstrip('\n') != 'persistent-nix-state':
    raise ValueError('Nix persistence fixture was not initialized')
with customization.open('a') as output:
    output.write('\n# VM acceptance customization\n')
content = customization.read_bytes()
if b'VM acceptance customization' not in content:
    raise ValueError('Home customization fixture was not initialized')
print(json.dumps({'schema': 1, 'status': 'pass', 'checks': {'nixState': True, 'homeCustomization': True},
                  'customizationSha256': hashlib.sha256(content).hexdigest()}))
HOME_INITIALIZED
end_stage 0
# Historical combined initialization interval, retained for comparison.
record_duration home-activation "$(($(monotonic_seconds) - activation_started))"
if [[ -z $target ]]; then
  poweroff_vm
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
ssh "${ssh_args[@]}" python3 - >"$state/updated-home.json" <<'HOME_PERSISTENCE'
import json
from pathlib import Path
import sys

checks = {}
errors = []
for name, path, expected, exact in (
    ('nixState', Path('/var/home/nix/finite-acceptance'), 'persistent-nix-state', True),
    ('homeCustomization', Path.home() / '.config/home-manager/customize.nix', 'VM acceptance customization', False),
):
    try:
        content = path.read_text()
        matched = content.rstrip('\n') == expected if exact else expected in content
        checks[name] = matched
        if not matched:
            errors.append(f'{name}: persisted marker changed at {path}')
    except OSError as error:
        checks[name] = False
        errors.append(f'{name}: cannot read {path}: {error.strerror}')
print(json.dumps({'schema': 1, 'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks, 'errors': errors}))
for error in errors:
    print('Post-upgrade persistence check failed: ' + error, file=sys.stderr)
raise SystemExit(bool(errors))
HOME_PERSISTENCE
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
jq -n --arg source "$source" --arg channel "$channel" --arg profile "$qualification_profile" \
  --arg sourceProfile "$profile" \
  --arg target "$target" --argjson secure "${FINITE_SECURE_BOOT:-false}" \
  '{source:$source,target:$target,updateChannel:$channel,profile:$profile,sourceProfile:$sourceProfile,
    uefi:true,secureBoot:$secure,encryptedRoot:true,accepted:true}' >"$state/acceptance.json"
