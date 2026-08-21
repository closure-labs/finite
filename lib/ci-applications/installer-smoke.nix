{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-installer-smoke";
  runtimeInputs = with pkgs; [bash coreutils gnugrep qemu_kvm];
  text = ''
    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Purplefin repository root" >&2
      exit 2
    }
    cd "''${repo_root}"
    set -euo pipefail

    iso="''${1:?usage: purplefin-installer-smoke ISO}"
    [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
    qemu="''${PURPLEFIN_QEMU:-qemu-system-x86_64}"
    qemu_img="''${PURPLEFIN_QEMU_IMG:-qemu-img}"
    timeout_seconds="''${PURPLEFIN_INSTALLER_SMOKE_TIMEOUT_SECONDS:-300}"
    poll_interval="''${PURPLEFIN_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
    cpus="''${PURPLEFIN_INSTALLER_SMOKE_CPUS:-4}"
    memory_mb="''${PURPLEFIN_INSTALLER_SMOKE_MEMORY_MB:-4096}"
    ready_marker='PURPLEFIN_INSTALLER_READY=1'
    [[ "''${timeout_seconds}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'PURPLEFIN_INSTALLER_SMOKE_TIMEOUT_SECONDS must be a positive integer' >&2
      exit 2
    }
    [[ "''${cpus}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'PURPLEFIN_INSTALLER_SMOKE_CPUS must be a positive integer' >&2
      exit 2
    }
    [[ "''${memory_mb}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'PURPLEFIN_INSTALLER_SMOKE_MEMORY_MB must be a positive integer' >&2
      exit 2
    }
    command -v "''${qemu}" >/dev/null
    command -v "''${qemu_img}" >/dev/null

    log="$(dirname -- "''${iso}")/qemu-boot.log"
    disk="$(mktemp --suffix=.qcow2)"
    qemu_pid=
    tail_pid=
    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    cleanup_installer_smoke() {
      [[ -z "''${qemu_pid}" ]] || kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
      [[ -z "''${tail_pid}" ]] || kill -TERM "''${tail_pid}" >/dev/null 2>&1 || true
      rm -f -- "''${disk}"
    }
    trap cleanup_installer_smoke EXIT
    "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G

    acceleration=(-accel "tcg,thread=multi")
    if [[ -r /dev/kvm && -w /dev/kvm ]]; then
      acceleration=(-accel kvm)
    fi

    : >"''${log}"
    timeout --signal=TERM --kill-after=10s "''${timeout_seconds}s" \
      "''${qemu}" \
        "''${acceleration[@]}" \
        -machine q35 \
        -m "''${memory_mb}" \
        -smp "''${cpus}" \
        -drive "file=''${disk},if=virtio,format=qcow2" \
        -cdrom "''${iso}" \
        -boot d \
        -display none \
        -serial stdio \
        -no-reboot >"''${log}" 2>&1 &
    qemu_pid=$!
    tail --pid="''${qemu_pid}" -n +1 -F "''${log}" &
    tail_pid=$!

    reached_installer=false
    while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
      if grep -Fq "''${ready_marker}" "''${log}"; then
        reached_installer=true
        kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
        break
      fi
      sleep "''${poll_interval}"
    done

    set +e
    wait "''${qemu_pid}"
    qemu_status=$?
    wait "''${tail_pid}"
    tail_status=$?
    set -e
    qemu_pid=
    tail_pid=

    [[ "''${tail_status}" == 0 ]] || {
      echo "QEMU log follower failed with status ''${tail_status}" >&2
      exit "''${tail_status}"
    }
    if [[ "''${reached_installer}" == true ]] ||
      grep -Fq "''${ready_marker}" "''${log}"; then
      exit 0
    fi

    case "''${qemu_status}" in
      0 | 124 | 143) ;;
      *) echo "QEMU failed with status ''${qemu_status}" >&2; exit "''${qemu_status}" ;;
    esac

    echo "The ISO booted but did not emit ''${ready_marker}" >&2
    exit 1
  '';
}
