{pkgs}:
pkgs.writeShellApplication {
  name = "finite-installer-e2e";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    gnugrep
    jq
    mtools
    OVMF.fd
    qemu_kvm
    util-linux
    xorriso
  ];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-installer-e2e install ISO STATE_ROOT
           finite-installer-e2e boot STATE_ROOT EXPECTED_DIGEST EXPECTED_REFERENCE
    EOF
    }

    phase="''${1:-}"
    case "''${phase}" in
      install)
        [[ $# == 3 ]] || { usage; exit 2; }
        iso=$2
        state_root=$3
        ;;
      boot)
        [[ $# == 4 ]] || { usage; exit 2; }
        state_root=$2
        expected_digest=$3
        expected_reference=$4
        ;;
      *) usage; exit 2 ;;
    esac

    qemu="''${FINITE_QEMU:-qemu-system-x86_64}"
    qemu_img="''${FINITE_QEMU_IMG:-qemu-img}"
    ovmf_code=${pkgs.OVMF.fd}/FV/OVMF_CODE.fd
    ovmf_vars_template=${pkgs.OVMF.fd}/FV/OVMF_VARS.fd
    install_timeout="''${FINITE_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-1800}"
    launcher_timeout="''${FINITE_INSTALLER_LAUNCH_TIMEOUT_SECONDS:-120}"
    boot_timeout="''${FINITE_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS:-300}"
    poll_interval="''${FINITE_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
    cpus="''${FINITE_INSTALLER_SMOKE_CPUS:-4}"
    memory_mb="''${FINITE_INSTALLER_SMOKE_MEMORY_MB:-6144}"
    for parameter in "''${install_timeout}" "''${launcher_timeout}" "''${boot_timeout}" "''${cpus}" "''${memory_mb}"; do
      [[ "''${parameter}" =~ ^[1-9][0-9]*$ ]] || {
        echo 'Installer E2E numeric parameters must be positive integers' >&2
        exit 2
      }
    done

    install -d -m 0755 "''${state_root}"
    diagnostics_dir="''${FINITE_INSTALLER_DIAGNOSTICS_DIR:-''${state_root}}"
    install -d -m 0755 "''${diagnostics_dir}"
    disk="''${state_root}/installed.qcow2"
    scratch_disk="''${state_root}/installer-scratch.qcow2"
    firmware_vars="''${state_root}/OVMF_VARS.fd"
    kernel="''${state_root}/vmlinuz"
    initrd="''${state_root}/initrd.img"
    install_log="''${diagnostics_dir}/qemu-install.log"
    boot_log="''${diagnostics_dir}/qemu-installed-boot.log"
    qemu_pid=
    tail_pid=

    terminate_and_reap() {
      local pid=$1
      [[ -n "''${pid}" ]] || return 0
      kill -TERM "''${pid}" >/dev/null 2>&1 || true
      wait "''${pid}" >/dev/null 2>&1 || true
    }
    print_logs() {
      local log
      for log in "''${install_log}" "''${boot_log}"; do
        [[ ! -f "''${log}" ]] || { echo "===== ''${log##*/} =====" >&2; cat "''${log}" >&2; }
      done
    }
    cleanup() {
      local status=$?
      set +e
      terminate_and_reap "''${qemu_pid}"
      terminate_and_reap "''${tail_pid}"
      ((status == 0)) || print_logs
      exit "''${status}"
    }
    trap cleanup EXIT

    prepare_firmware() {
      cp --force -- "''${ovmf_vars_template}" "''${firmware_vars}"
      chmod u+w "''${firmware_vars}"
    }
    acceleration=(-accel "tcg,thread=multi")
    [[ ! -r /dev/kvm || ! -w /dev/kvm ]] || acceleration=(-accel kvm)
    common_args=(
      "''${acceleration[@]}"
      -machine q35
      -m "''${memory_mb}"
      -smp "''${cpus}"
      -drive "if=pflash,format=raw,unit=0,readonly=on,file=''${ovmf_code}"
      -drive "if=pflash,format=raw,unit=1,file=''${firmware_vars}"
      -drive "file=''${disk},if=virtio,format=qcow2"
      -display none
      -serial stdio
      -nic "user,model=virtio-net-pci"
      -no-reboot
    )
    [[ -s "''${ovmf_code}" && -s "''${ovmf_vars_template}" ]] || {
      echo 'OVMF firmware is missing from the installer E2E environment' >&2
      exit 2
    }

    if [[ "''${phase}" == install ]]; then
      [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
      rm -f -- "''${disk}" "''${scratch_disk}" "''${firmware_vars}" "''${kernel}" "''${initrd}" "''${state_root}/install-complete"
      prepare_firmware
      "''${qemu_img}" create -q -f qcow2 "''${disk}" 64G
      "''${qemu_img}" create -q -f qcow2 "''${scratch_disk}" 16G
      xorriso -osirrox on -indev "''${iso}" \
        -extract /images/pxeboot/vmlinuz "''${kernel}" \
        -extract /images/pxeboot/initrd.img "''${initrd}" >/dev/null 2>&1

      echo 'Installing Finite with the Project Bluefin bootc installer'
      kernel_cmdline='root=live:LABEL=FINITE_LIVE rd.live.image rd.live.overlay.overlayfs=1 enforcing=0 console=tty0 console=ttyS0,115200n8 finite.installer.autoinstall=1'
      : >"''${install_log}"
      timeout --signal=TERM --kill-after=20s "''${install_timeout}s" \
        "''${qemu}" "''${common_args[@]}" \
          -drive "file=''${scratch_disk},if=virtio,format=qcow2" \
          -cdrom "''${iso}" \
          -kernel "''${kernel}" \
          -initrd "''${initrd}" \
          -append "''${kernel_cmdline}" \
        >"''${install_log}" 2>&1 &
      qemu_pid=$!
      tail --pid="''${qemu_pid}" -n +1 -F "''${install_log}" &
      tail_pid=$!
      launcher_deadline=$((SECONDS + launcher_timeout))
      launcher_ready=false
      while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
        if grep -Fq 'FINITE_INSTALLER_ERROR=' "''${install_log}"; then
          echo 'The bootc installer reported an error' >&2
          exit 1
        fi
        if grep -Fq 'FINITE_INSTALLER_READY=1' "''${install_log}"; then
          launcher_ready=true
        elif ((SECONDS >= launcher_deadline)); then
          echo "The graphical installer did not activate within ''${launcher_timeout} seconds" >&2
          exit 1
        fi
        sleep "''${poll_interval}"
      done
      set +e
      wait "''${qemu_pid}"; qemu_status=$?; qemu_pid=
      wait "''${tail_pid}"; tail_status=$?; tail_pid=
      set -e
      [[ "''${tail_status}" == 0 ]]
      [[ "''${qemu_status}" == 0 ]] || {
        echo "Installer VM failed with status ''${qemu_status}" >&2
        exit "''${qemu_status}"
      }
      [[ "''${launcher_ready}" == true ]] ||
        grep -Fq 'FINITE_INSTALLER_READY=1' "''${install_log}" || {
          echo 'The installer VM exited without its application-ready marker' >&2
          exit 1
        }
      grep -Fq 'FINITE_INSTALLER_COMPLETE=1' "''${install_log}" || {
        echo 'The installer VM exited without its completion marker' >&2
        exit 1
      }
      touch "''${state_root}/install-complete"
      exit 0
    fi

    [[ -s "''${disk}" && -f "''${state_root}/install-complete" ]] || {
      echo "Completed installer state is missing: ''${state_root}" >&2
      exit 2
    }
    [[ "''${expected_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${expected_reference}" =~ ^[a-z0-9._/-]+:[A-Za-z0-9._-]+$ ]]

    raw_disk="''${state_root}/installed.raw"
    "''${qemu_img}" convert -q -f qcow2 -O raw "''${disk}" "''${raw_disk}"
    sfdisk --json "''${raw_disk}" >"''${diagnostics_dir}/installed-partitions.json"
    jq -e '
      .partitiontable.label == "gpt" and
      (.partitiontable.partitions | length) == 3 and
      (.partitiontable.partitions[0].type | ascii_downcase) == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
    ' "''${diagnostics_dir}/installed-partitions.json" >/dev/null
    rm -f "''${raw_disk}"

    # A fresh variable store proves the installed disk is independently UEFI
    # bootable instead of relying on state left by the live environment.
    prepare_firmware
    echo 'Booting the installed Finite system'
    : >"''${boot_log}"
    timeout --signal=TERM --kill-after=10s "''${boot_timeout}s" \
      "''${qemu}" "''${common_args[@]}" -boot c >"''${boot_log}" 2>&1 &
    qemu_pid=$!
    tail --pid="''${qemu_pid}" -n +1 -F "''${boot_log}" &
    tail_pid=$!
    reached=false
    while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
      if grep -Fq 'FINITE_INSTALLED_READY=1' "''${boot_log}"; then
        reached=true
        terminate_and_reap "''${qemu_pid}"
        qemu_pid=
        break
      fi
      sleep "''${poll_interval}"
    done
    set +e
    [[ -z "''${qemu_pid}" ]] || { wait "''${qemu_pid}"; qemu_status=$?; qemu_pid=; }
    wait "''${tail_pid}"; tail_status=$?; tail_pid=
    set -e
    [[ "''${tail_status}" == 0 ]]
    [[ "''${reached}" == true ]] || {
      echo 'The installed system did not emit its ready marker' >&2
      exit 1
    }
    grep -Fq "''${expected_digest}" "''${boot_log}"
    grep -Fq "''${expected_reference}" "''${boot_log}"
  '';
}
