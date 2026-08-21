{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-installer-e2e";
  runtimeInputs = with pkgs; [bash coreutils gnugrep qemu_kvm];
  text = ''
    set -euo pipefail

    iso="''${1:?usage: purplefin-installer-e2e ISO}"
    [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
    qemu="''${PURPLEFIN_QEMU:-qemu-system-x86_64}"
    qemu_img="''${PURPLEFIN_QEMU_IMG:-qemu-img}"
    install_timeout="''${PURPLEFIN_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-1800}"
    boot_timeout="''${PURPLEFIN_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS:-300}"
    poll_interval="''${PURPLEFIN_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
    cpus="''${PURPLEFIN_INSTALLER_SMOKE_CPUS:-4}"
    memory_mb="''${PURPLEFIN_INSTALLER_SMOKE_MEMORY_MB:-4096}"
    ready_marker='PURPLEFIN_INSTALLED_READY=1'
    for parameter in "''${install_timeout}" "''${boot_timeout}" "''${cpus}" "''${memory_mb}"; do
      [[ "''${parameter}" =~ ^[1-9][0-9]*$ ]] || {
        echo 'Installer E2E numeric parameters must be positive integers' >&2
        exit 2
      }
    done

    disk="$(mktemp --suffix=.qcow2)"
    install_log="$(dirname -- "''${iso}")/qemu-install.log"
    boot_log="$(dirname -- "''${iso}")/qemu-installed-boot.log"
    qemu_pid=
    tail_pid=
    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    cleanup_installer_e2e() {
      [[ -z "''${qemu_pid}" ]] || kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
      [[ -z "''${tail_pid}" ]] || kill -TERM "''${tail_pid}" >/dev/null 2>&1 || true
      rm -f -- "''${disk}"
    }
    trap cleanup_installer_e2e EXIT
    "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G

    acceleration=(-accel "tcg,thread=multi")
    if [[ -r /dev/kvm && -w /dev/kvm ]]; then
      acceleration=(-accel kvm)
    fi
    common_args=("''${acceleration[@]}")
    common_args+=(
      -machine q35
      -m "''${memory_mb}"
      -smp "''${cpus}"
      -drive "file=''${disk},if=virtio,format=qcow2"
      -display none
      -serial stdio
      -nic "user,model=virtio-net-pci"
      -no-reboot
    )

    echo 'Installing Purplefin onto the disposable virtual disk'
    timeout --signal=TERM --kill-after=20s "''${install_timeout}s" \
      "''${qemu}" "''${common_args[@]}" -cdrom "''${iso}" -boot d \
      >"''${install_log}" 2>&1 || {
        status=$?
        cat "''${install_log}"
        echo "Unattended installer failed with status ''${status}" >&2
        exit "''${status}"
      }
    cat "''${install_log}"

    echo 'Booting the installed Purplefin system'
    : >"''${boot_log}"
    timeout --signal=TERM --kill-after=10s "''${boot_timeout}s" \
      "''${qemu}" "''${common_args[@]}" -boot c >"''${boot_log}" 2>&1 &
    qemu_pid=$!
    tail --pid="''${qemu_pid}" -n +1 -F "''${boot_log}" &
    tail_pid=$!

    reached_installed_system=false
    while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
      if grep -Fq "''${ready_marker}" "''${boot_log}"; then
        reached_installed_system=true
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

    [[ "''${tail_status}" == 0 ]] || exit "''${tail_status}"
    if [[ "''${reached_installed_system}" == true ]] ||
      grep -Fq "''${ready_marker}" "''${boot_log}"; then
      exit 0
    fi
    case "''${qemu_status}" in
      0 | 124 | 143) ;;
      *) echo "Installed-system QEMU failed with status ''${qemu_status}" >&2; exit "''${qemu_status}" ;;
    esac
    echo "The installed system did not emit ''${ready_marker}" >&2
    exit 1
  '';
}
