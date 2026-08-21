{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-installer-e2e";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    gnugrep
    python3
    qemu_kvm
    xorriso
  ];
  text = ''
    set -euo pipefail

    iso="''${1:?usage: purplefin-installer-e2e ISO KICKSTART}"
    kickstart="''${2:?usage: purplefin-installer-e2e ISO KICKSTART}"
    [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
    [[ -s "''${kickstart}" ]] || { echo "Kickstart is missing: ''${kickstart}" >&2; exit 2; }
    qemu="''${PURPLEFIN_QEMU:-qemu-system-x86_64}"
    qemu_img="''${PURPLEFIN_QEMU_IMG:-qemu-img}"
    python="''${PURPLEFIN_PYTHON:-python3}"
    xorriso="''${PURPLEFIN_XORRISO:-xorriso}"
    # Hosted release runners can spend close to 30 minutes pulling and
    # installing the multi-gigabyte bootc payload after Anaconda becomes
    # ready. Keep this below the enclosing 120-minute job timeout while
    # leaving enough room for the installed-system boot assertion.
    install_timeout="''${PURPLEFIN_INSTALLER_E2E_INSTALL_TIMEOUT_SECONDS:-3600}"
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

    test_root="$(mktemp -d)"
    disk="''${test_root}/installed.qcow2"
    kernel="''${test_root}/vmlinuz"
    initrd="''${test_root}/initrd.img"
    served_kickstart="''${test_root}/purplefin-ci.ks"
    install_log="$(dirname -- "''${iso}")/qemu-install.log"
    boot_log="$(dirname -- "''${iso}")/qemu-installed-boot.log"
    server_log="$(dirname -- "''${iso}")/qemu-kickstart-server.log"
    qemu_pid=
    tail_pid=
    server_pid=
    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    cleanup_installer_e2e() {
      [[ -z "''${qemu_pid}" ]] || kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
      [[ -z "''${tail_pid}" ]] || kill -TERM "''${tail_pid}" >/dev/null 2>&1 || true
      [[ -z "''${server_pid}" ]] || kill -TERM "''${server_pid}" >/dev/null 2>&1 || true
      rm -rf -- "''${test_root}"
    }
    trap cleanup_installer_e2e EXIT
    "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G
    "''${xorriso}" -osirrox on -indev "''${iso}" \
      -extract /images/pxeboot/vmlinuz "''${kernel}" \
      -extract /images/pxeboot/initrd.img "''${initrd}" >/dev/null 2>&1
    cp -- "''${kickstart}" "''${served_kickstart}"

    port="$(
      "''${python}" -c \
        'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
    )"
    "''${python}" -m http.server "''${port}" \
      --bind 0.0.0.0 --directory "''${test_root}" >"''${server_log}" 2>&1 &
    server_pid=$!
    server_ready=false
    for _ in {1..50}; do
      if "''${python}" -c \
        'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1).read()' \
        "http://127.0.0.1:''${port}/purplefin-ci.ks" >/dev/null 2>&1; then
        server_ready=true
        break
      fi
      sleep 0.1
    done
    [[ "''${server_ready}" == true ]] || {
      cat "''${server_log}"
      echo 'Kickstart HTTP server did not become ready' >&2
      exit 1
    }

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
    kernel_cmdline="root=live:CDLABEL=Purplefin-Installer rd.live.image inst.stage2=hd:LABEL=Purplefin-Installer inst.text inst.ksstrict console=tty0 console=ttyS0,115200n8 selinux=0 ip=dhcp rd.neednet=1 inst.ks=http://10.0.2.2:''${port}/purplefin-ci.ks"
    timeout --signal=TERM --kill-after=20s "''${install_timeout}s" \
      "''${qemu}" "''${common_args[@]}" \
        -cdrom "''${iso}" \
        -kernel "''${kernel}" \
        -initrd "''${initrd}" \
        -append "''${kernel_cmdline}" \
      >"''${install_log}" 2>&1 || {
        status=$?
        cat "''${install_log}"
        cat "''${server_log}"
        echo "Unattended installer failed with status ''${status}" >&2
        exit "''${status}"
      }
    cat "''${install_log}"
    kill -TERM "''${server_pid}" >/dev/null 2>&1 || true
    wait "''${server_pid}" >/dev/null 2>&1 || true
    server_pid=
    cat "''${server_log}"

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
