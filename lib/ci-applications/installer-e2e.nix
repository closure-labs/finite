{pkgs}:
pkgs.writeShellApplication {
  name = "finite-installer-e2e";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    gnugrep
    OVMF.fd
    python3
    qemu_kvm
    xorriso
  ];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-installer-e2e install ISO KICKSTART STATE_ROOT
           finite-installer-e2e boot STATE_ROOT
    EOF
    }

    phase="''${1:-}"
    case "''${phase}" in
      install)
        [[ $# == 4 ]] || { usage; exit 2; }
        iso=$2
        kickstart=$3
        state_root=$4
        ;;
      boot)
        [[ $# == 2 ]] || { usage; exit 2; }
        state_root=$2
        ;;
      *)
        usage
        exit 2
        ;;
    esac

    qemu="''${FINITE_QEMU:-qemu-system-x86_64}"
    qemu_img="''${FINITE_QEMU_IMG:-qemu-img}"
    python="''${FINITE_PYTHON:-python3}"
    xorriso="''${FINITE_XORRISO:-xorriso}"
    ovmf_code="${pkgs.OVMF.fd}/FV/OVMF_CODE.fd"
    ovmf_vars_template="${pkgs.OVMF.fd}/FV/OVMF_VARS.fd"
    kickstart_timeout="''${FINITE_INSTALLER_E2E_KICKSTART_TIMEOUT_SECONDS:-180}"
    install_timeout="''${FINITE_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-1200}"
    boot_timeout="''${FINITE_INSTALLER_E2E_BOOT_TIMEOUT_SECONDS:-180}"
    poll_interval="''${FINITE_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
    cpus="''${FINITE_INSTALLER_SMOKE_CPUS:-4}"
    memory_mb="''${FINITE_INSTALLER_SMOKE_MEMORY_MB:-4096}"
    ready_marker='FINITE_INSTALLED_READY=1'
    for parameter in \
      "''${kickstart_timeout}" \
      "''${install_timeout}" \
      "''${boot_timeout}" \
      "''${cpus}" \
      "''${memory_mb}"; do
      [[ "''${parameter}" =~ ^[1-9][0-9]*$ ]] || {
        echo 'Installer E2E numeric parameters must be positive integers' >&2
        exit 2
      }
    done

    install -d -m 0755 "''${state_root}"
    diagnostics_dir="''${FINITE_INSTALLER_DIAGNOSTICS_DIR:-''${state_root}}"
    install -d -m 0755 "''${diagnostics_dir}"
    disk="''${state_root}/installed.qcow2"
    firmware_vars="''${state_root}/OVMF_VARS.fd"
    kernel="''${state_root}/vmlinuz"
    initrd="''${state_root}/initrd.img"
    served_kickstart="''${state_root}/finite-ci.ks"
    health_check="''${state_root}/server-ready"
    install_log="''${diagnostics_dir}/qemu-install.log"
    boot_log="''${diagnostics_dir}/qemu-installed-boot.log"
    server_log="''${diagnostics_dir}/qemu-kickstart-server.log"
    qemu_pid=
    tail_pid=
    server_pid=

    terminate_and_reap() {
      local pid=$1
      [[ -n "''${pid}" ]] || return 0
      kill -TERM "''${pid}" >/dev/null 2>&1 || true
      wait "''${pid}" >/dev/null 2>&1 || true
    }

    prepare_firmware_vars() {
      cp --force -- "''${ovmf_vars_template}" "''${firmware_vars}"
      chmod u+w "''${firmware_vars}"
    }

    print_phase_logs() {
      local log
      for log in "''${install_log}" "''${boot_log}" "''${server_log}"; do
        if [[ -f "''${log}" ]]; then
          echo "===== ''${log##*/} =====" >&2
          cat "''${log}" >&2
        fi
      done
    }

    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    cleanup_installer_e2e() {
      local status=$?
      set +e
      terminate_and_reap "''${qemu_pid}"
      terminate_and_reap "''${tail_pid}"
      terminate_and_reap "''${server_pid}"
      if ((status != 0)); then
        print_phase_logs
      fi
      exit "''${status}"
    }
    trap cleanup_installer_e2e EXIT

    acceleration=(-accel "tcg,thread=multi")
    if [[ -r /dev/kvm && -w /dev/kvm ]]; then
      acceleration=(-accel kvm)
    fi
    common_args=("''${acceleration[@]}")
    common_args+=(
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
      [[ -s "''${kickstart}" ]] || { echo "Kickstart is missing: ''${kickstart}" >&2; exit 2; }
      rm -f -- \
        "''${disk}" \
        "''${firmware_vars}" \
        "''${kernel}" \
        "''${initrd}" \
        "''${state_root}/install-complete"
      prepare_firmware_vars
      "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G
      "''${xorriso}" -osirrox on -indev "''${iso}" \
        -extract /images/pxeboot/vmlinuz "''${kernel}" \
        -extract /images/pxeboot/initrd.img "''${initrd}" >/dev/null 2>&1
      cp -- "''${kickstart}" "''${served_kickstart}"
      printf 'ready\n' >"''${health_check}"

      port="$(
        "''${python}" -c \
          'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
      )"
      : >"''${server_log}"
      "''${python}" -m http.server "''${port}" \
        --bind 0.0.0.0 --directory "''${state_root}" >"''${server_log}" 2>&1 &
      server_pid=$!
      server_ready=false
      for _ in {1..50}; do
        if "''${python}" -c \
          'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1).read()' \
          "http://127.0.0.1:''${port}/server-ready" >/dev/null 2>&1; then
          server_ready=true
          break
        fi
        sleep 0.1
      done
      [[ "''${server_ready}" == true ]] || {
        echo 'Kickstart HTTP server did not become ready' >&2
        exit 1
      }

      echo 'Installing Finite onto the disposable virtual disk'
      kernel_cmdline="root=live:CDLABEL=Finite-Installer rd.live.image inst.stage2=hd:LABEL=Finite-Installer inst.text inst.ksstrict console=tty0 console=ttyS0,115200n8 selinux=0 ip=dhcp rd.neednet=1 inst.ks=http://10.0.2.2:''${port}/finite-ci.ks"
      : >"''${install_log}"
      timeout --signal=TERM --kill-after=20s "''${install_timeout}s" \
        "''${qemu}" "''${common_args[@]}" \
          -cdrom "''${iso}" \
          -kernel "''${kernel}" \
          -initrd "''${initrd}" \
          -append "''${kernel_cmdline}" \
        >"''${install_log}" 2>&1 &
      qemu_pid=$!
      tail --pid="''${qemu_pid}" -n +1 -F "''${install_log}" &
      tail_pid=$!

      kickstart_fetched=false
      kickstart_deadline=$((SECONDS + kickstart_timeout))
      while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
        if grep -Fq '"GET /finite-ci.ks ' "''${server_log}"; then
          kickstart_fetched=true
          break
        fi
        if ((SECONDS >= kickstart_deadline)); then
          echo "The guest did not fetch finite-ci.ks within ''${kickstart_timeout}s" >&2
          exit 1
        fi
        sleep "''${poll_interval}"
      done
      if [[ "''${kickstart_fetched}" != true ]] &&
        grep -Fq '"GET /finite-ci.ks ' "''${server_log}"; then
        kickstart_fetched=true
      fi
      [[ "''${kickstart_fetched}" == true ]] || {
        echo 'The installer exited before fetching finite-ci.ks' >&2
        exit 1
      }

      set +e
      wait "''${qemu_pid}"
      qemu_status=$?
      wait "''${tail_pid}"
      tail_status=$?
      set -e
      qemu_pid=
      tail_pid=
      terminate_and_reap "''${server_pid}"
      server_pid=
      [[ "''${tail_status}" == 0 ]] || {
        echo "Installer log follower failed with status ''${tail_status}" >&2
        exit "''${tail_status}"
      }
      if [[ "''${qemu_status}" == 124 ]]; then
        echo "Unattended installation timed out after ''${install_timeout}s" >&2
        exit 124
      fi
      [[ "''${qemu_status}" == 0 ]] || {
        echo "Unattended installer failed with status ''${qemu_status}" >&2
        exit "''${qemu_status}"
      }
      touch "''${state_root}/install-complete"
      print_phase_logs
      exit 0
    fi

    [[ -s "''${disk}" && -f "''${state_root}/install-complete" ]] || {
      echo "Completed installer state is missing: ''${state_root}" >&2
      exit 2
    }
    # The direct-kernel installer boot leaves a transient OVMF Boot#### entry
    # that cannot exist during the disk-only boot. Start the validation boot
    # from clean firmware variables so OVMF discovers the installed loader.
    prepare_firmware_vars
    echo 'Booting the installed Finite system'
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
        terminate_and_reap "''${qemu_pid}"
        qemu_pid=
        break
      fi
      sleep "''${poll_interval}"
    done

    set +e
    if [[ -n "''${qemu_pid}" ]]; then
      wait "''${qemu_pid}"
      qemu_status=$?
      qemu_pid=
    else
      qemu_status=143
    fi
    wait "''${tail_pid}"
    tail_status=$?
    set -e
    tail_pid=

    [[ "''${tail_status}" == 0 ]] || {
      echo "Installed-system log follower failed with status ''${tail_status}" >&2
      exit "''${tail_status}"
    }
    if [[ "''${reached_installed_system}" == true ]] ||
      grep -Fq "''${ready_marker}" "''${boot_log}"; then
      print_phase_logs
      exit 0
    fi
    if [[ "''${qemu_status}" == 124 ]]; then
      echo "Installed-system boot timed out after ''${boot_timeout}s" >&2
      exit 124
    fi
    case "''${qemu_status}" in
      0 | 143) ;;
      *) echo "Installed-system QEMU failed with status ''${qemu_status}" >&2; exit "''${qemu_status}" ;;
    esac
    echo "The installed system did not emit ''${ready_marker}" >&2
    exit 1
  '';
}
