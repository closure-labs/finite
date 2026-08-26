{pkgs}:
pkgs.writeShellApplication {
  name = "finite-installer-smoke";
  runtimeInputs = with pkgs; [bash coreutils gnugrep OVMF.fd qemu_kvm];
  text = ''
    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Finite repository root" >&2
      exit 2
    }
    cd "''${repo_root}"
    set -euo pipefail

    iso="''${1:?usage: finite-installer-smoke ISO}"
    [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
    qemu="''${FINITE_QEMU:-qemu-system-x86_64}"
    qemu_img="''${FINITE_QEMU_IMG:-qemu-img}"
    timeout_seconds="''${FINITE_INSTALLER_SMOKE_TIMEOUT_SECONDS:-300}"
    poll_interval="''${FINITE_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
    cpus="''${FINITE_INSTALLER_SMOKE_CPUS:-4}"
    memory_mb="''${FINITE_INSTALLER_SMOKE_MEMORY_MB:-11264}"
    ready_marker='FINITE_INSTALLER_READY=1'
    ovmf_code="${pkgs.OVMF.fd}/FV/OVMF_CODE.fd"
    ovmf_vars_template="${pkgs.OVMF.fd}/FV/OVMF_VARS.fd"
    [[ "''${timeout_seconds}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'FINITE_INSTALLER_SMOKE_TIMEOUT_SECONDS must be a positive integer' >&2
      exit 2
    }
    [[ "''${cpus}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'FINITE_INSTALLER_SMOKE_CPUS must be a positive integer' >&2
      exit 2
    }
    [[ "''${memory_mb}" =~ ^[1-9][0-9]*$ ]] || {
      echo 'FINITE_INSTALLER_SMOKE_MEMORY_MB must be a positive integer' >&2
      exit 2
    }
    command -v "''${qemu}" >/dev/null
    command -v "''${qemu_img}" >/dev/null

    log="$(dirname -- "''${iso}")/qemu-boot.log"
    disk="$(mktemp --suffix=.qcow2)"
    firmware_vars="$(mktemp --suffix=.fd)"
    qemu_pid=
    tail_pid=
    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    cleanup_installer_smoke() {
      [[ -z "''${qemu_pid}" ]] || kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
      [[ -z "''${tail_pid}" ]] || kill -TERM "''${tail_pid}" >/dev/null 2>&1 || true
      rm -f -- "''${disk}" "''${firmware_vars}"
    }
    trap cleanup_installer_smoke EXIT
    "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G
    cp "''${ovmf_vars_template}" "''${firmware_vars}"
    chmod u+w "''${firmware_vars}"

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
        -drive "if=pflash,format=raw,unit=0,readonly=on,file=''${ovmf_code}" \
        -drive "if=pflash,format=raw,unit=1,file=''${firmware_vars}" \
        -drive "file=''${disk},if=virtio,format=qcow2" \
        -vga none \
        -device virtio-vga \
        -cdrom "''${iso}" \
        -boot d \
        -display none \
        -serial stdio \
        -no-reboot >"''${log}" 2>&1 &
    qemu_pid=$!
    tail --pid="''${qemu_pid}" -n +1 -F "''${log}" &
    tail_pid=$!

    reached_installer=false
    installer_error=false
    while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
      if grep -Fq "''${ready_marker}" "''${log}"; then
        reached_installer=true
        kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
        break
      fi
      if grep -Fq 'FINITE_INSTALLER_ERROR=' "''${log}"; then
        installer_error=true
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

    if [[ "''${installer_error}" == true ]]; then
      echo 'The live installer launcher reported an error' >&2
      exit 1
    fi

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
