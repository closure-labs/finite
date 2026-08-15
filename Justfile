image := "ghcr.io/declarative-dale/purplefin"

default:
    @just --list

check:
    #!/usr/bin/env bash
    set -euo pipefail

    find build_files system_files/usr/libexec/purplefin profile_files installer/root -type f \( -name '*.sh' -o -perm -111 \) -exec bash -n {} +

    tmpdir="$(mktemp -d)"
    refind_tmp="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}" "${refind_tmp}"' EXIT
    cp -a system_files/. "${tmpdir}/"
    cp -a profile_files/roles/support/system_files/. "${tmpdir}/"
    cp -a profile_files/components/devops/system_files/. "${tmpdir}/"
    cp -a profile_files/dell-xps-9350-intel/system_files/. "${tmpdir}/"
    install -d "${tmpdir}/usr/lib/systemd/system"
    install -d "${tmpdir}/usr/bin" "${tmpdir}/usr/sbin"
    printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "${tmpdir}/usr/bin/true"
    cp "${tmpdir}/usr/bin/true" "${tmpdir}/usr/sbin/modprobe"
    chmod 0755 "${tmpdir}/usr/bin/true" "${tmpdir}/usr/sbin/modprobe"
    printf '%s\n' '[Unit]' 'Description=System Initialization' > "${tmpdir}/usr/lib/systemd/system/sysinit.target"
    printf '%s\n' '[Unit]' 'Description=Local File Systems' > "${tmpdir}/usr/lib/systemd/system/local-fs.target"
    printf '%s\n' '[Unit]' 'Description=Basic System' 'Requires=sysinit.target' 'After=sysinit.target' > "${tmpdir}/usr/lib/systemd/system/basic.target"
    printf '%s\n' '[Unit]' 'Description=Multi-User System' 'Requires=basic.target' 'After=basic.target' > "${tmpdir}/usr/lib/systemd/system/multi-user.target"
    printf '%s\n' '[Unit]' 'Description=udev settle stub' '[Service]' 'Type=oneshot' 'ExecStart=/usr/bin/true' > "${tmpdir}/usr/lib/systemd/system/systemd-udev-settle.service"
    printf '%s\n' '[Unit]' 'Description=module loader stub' '[Service]' 'Type=oneshot' 'ExecStart=/usr/bin/true' > "${tmpdir}/usr/lib/systemd/system/systemd-modules-load.service"
    printf '%s\n' '[Unit]' 'Description=display manager stub' '[Service]' 'Type=oneshot' 'ExecStart=/usr/bin/true' > "${tmpdir}/usr/lib/systemd/system/display-manager.service"
    printf '%s\n' '[Unit]' 'Description=UPower stub' '[Service]' 'Type=oneshot' 'ExecStart=/usr/bin/true' > "${tmpdir}/usr/lib/systemd/system/upower.service"
    printf '%s\n' '[Unit]' 'Description=Graphical session preparation' > "${tmpdir}/usr/lib/systemd/system/graphical-session-pre.target"
    printf '%s\n' '[Unit]' 'Description=Graphical session' > "${tmpdir}/usr/lib/systemd/system/graphical-session.target"
    cp "${tmpdir}/usr/lib/systemd/user/purplefin-dell-xps-9350-panel.service" "${tmpdir}/usr/lib/systemd/system/"
    install -d "${tmpdir}/usr/lib/systemd/system/graphical-session.target.wants"
    ln -s ../purplefin-dell-xps-9350-panel.service "${tmpdir}/usr/lib/systemd/system/graphical-session.target.wants/purplefin-dell-xps-9350-panel.service"
    systemd_verify_log="${tmpdir}/systemd-verify.log"
    if ! env -u XDG_RUNTIME_DIR SYSTEMD_BYPASS_USERDB=1 systemd-analyze verify --root="${tmpdir}" /usr/lib/systemd/system/purplefin-firstboot-rpm-ostree.service /usr/lib/systemd/system/purplefin-brew-bundle.service /usr/lib/systemd/system/purplefin-refind-theme.service /usr/lib/systemd/system/purplefin-dell-xps-9350-battery.service /usr/lib/systemd/system/graphical-session.target /usr/lib/systemd/system/purplefin-dell-xps-9350-panel.service 2>"${systemd_verify_log}"; then
        grep -qF 'Failed to turn off SO_PASSRIGHTS on user lookup socket' "${systemd_verify_log}"
        grep -qF 'Failed to enable SO_PASSCRED on handoff timestamp socket' "${systemd_verify_log}"
        unexpected_systemd_error="$(grep -Ev '^(Failed to turn off SO_PASSRIGHTS on user lookup socket, ignoring: Operation not permitted|Failed to enable SO_PASSCRED on handoff timestamp socket: Operation not permitted)$' "${systemd_verify_log}" || true)"
        test -z "${unexpected_systemd_error}"
        echo 'systemd-analyze verify skipped: sandbox blocks its userdb socket setup' >&2
    fi
    env -u XDG_RUNTIME_DIR udevadm verify --root="${tmpdir}"

    # Retired first-boot tasks lose their stale completion markers safely.
    firstboot_test="${tmpdir}/firstboot-test"
    install -d "${firstboot_test}/bin" "${firstboot_test}/markers" "${firstboot_test}/tasks"
    ln -s /usr/bin/true "${firstboot_test}/bin/rpm-ostree"
    ln -s /usr/bin/true "${firstboot_test}/tasks/10-active"
    touch "${firstboot_test}/markers/10-active.done" "${firstboot_test}/markers/20-retired.done"
    env \
        PATH="${firstboot_test}/bin:${PATH}" \
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/system_files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/reboot-required" \
        system_files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -e "${firstboot_test}/markers/10-active.done"
    test ! -e "${firstboot_test}/markers/20-retired.done"

    install -d "${firstboot_test}/retired-markers"
    touch "${firstboot_test}/retired-markers/30-retired.done"
    env \
        PATH="${firstboot_test}/bin:${PATH}" \
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/system_files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/retired-tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/retired-markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/retired-reboot-required" \
        system_files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test ! -e "${firstboot_test}/retired-markers/30-retired.done"

    install -d "${firstboot_test}/pending-bin" "${firstboot_test}/pending-markers"
    printf '%s\n' '#!/usr/bin/env bash' 'exit 77' > "${firstboot_test}/pending-bin/rpm-ostree"
    chmod 0755 "${firstboot_test}/pending-bin/rpm-ostree"
    touch "${firstboot_test}/pending-markers/40-pending.done"
    env \
        PATH="${firstboot_test}/pending-bin:${PATH}" \
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/system_files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/pending-tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/pending-markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/pending-reboot-required" \
        system_files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -e "${firstboot_test}/pending-markers/40-pending.done"

    # Named profiles are the only supported composition interface.
    for profile in base-generic base-dell-xps-9350-intel sales-generic sales-dell-xps-9350-intel support-generic support-dell-xps-9350-intel dale developer-generic trainer-generic executive-generic it-generic; do
        test -f "build_files/profiles/profiles/${profile}.conf"
        bash -n "build_files/profiles/profiles/${profile}.conf"
    done

    for module in base developer support sales trainer executive it hardware-generic-x86_64 hardware-framework-laptop hardware-dell-xps-9350-intel; do
        test -x "build_files/modules/${module}.sh"
    done
    test -f VERSION
    grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' VERSION
    grep -qF 'ARG BUILD_PROFILE=base-generic' Containerfile
    grep -qF '/tmp/purplefin-build/build.sh "${BUILD_PROFILE}"' Containerfile
    grep -qF 'profile_definition="${build_root}/profiles/profiles/${profile}.conf"' build_files/build.sh
    grep -qF 'modules=(base sales trainer support hardware-dell-xps-9350-intel)' build_files/profiles/profiles/dale.conf
    grep -qF 'ARG BASE_REF=ghcr.io/projectbluefin/bluefin:stable' Containerfile
    grep -qF 'FROM ${BASE_REF}' Containerfile
    grep -qF 'org.opencontainers.image.base.name="${BASE_REF}"' Containerfile
    grep -qF 'org.opencontainers.image.version="${PURPLEFIN_VERSION}"' Containerfile
    grep -qF 'Profile ${profile} must include exactly one hardware module' build_files/build.sh
    grep -qF 'printf '\''%s\n'\'' "${profile_modules[@]}" >/usr/share/purplefin/build-modules' build_files/lib/finalize-profile.sh
    grep -qF '/usr/share/purplefin/version' build_files/lib/finalize-profile.sh
    grep -qF 'purplefin_authselect_finalize' build_files/build.sh

    # Base/common content is present in every named profile.
    grep -qF 'install -d -m 0755 /nix' build_files/modules/base.sh
    test -f manifests/Brewfile
    grep -qF 'marp-cli' manifests/Brewfile
    for formula in fzf neovim zsh-autosuggestions zsh-fast-syntax-highlighting zsh-history-substring-search zsh-vi-mode; do
        grep -qxF "brew \"${formula}\"" manifests/Brewfile
    done
    test -f manifests/flatpaks.preinstall
    for app_id in com.bitwarden.desktop it.mijorus.gearlever com.nextcloud.desktopclient.nextcloud hu.irl.cameractrls org.mozilla.firefox org.mozilla.thunderbird; do
        grep -qF "[Flatpak Preinstall ${app_id}]" manifests/flatpaks.preinstall
    done
    grep -qF '[Flatpak Preinstall org.mozilla.thunderbird]' profile_files/modules/sales/manifests/flatpaks.preinstall
    ! rg -q 'org\.mozilla\.(Thunderbird|thunderbird_esr)' manifests/flatpaks.preinstall profile_files/modules/sales/manifests/flatpaks.preinstall
    ! grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' manifests/flatpaks.preinstall
    ! grep -qF '[Flatpak Preinstall com.vscodium.codium]' manifests/flatpaks.preinstall
    for package in fuse fuse-libs git micro nm-connection-editor nm-connection-editor-desktop wireguard-tools; do
        grep -qF "${package}" build_files/modules/base.sh
    done
    for package in qemu-block-curl qemu-block-dmg qemu-block-iscsi qemu-block-nfs qemu-block-ssh qemu-img qemu-tools; do
        grep -qF "${package}" build_files/modules/base.sh
    done
    for package in podman-machine qemu-system-x86-core; do
        grep -qF "${package}" build_files/modules/base.sh
    done
    for helper in /usr/bin/qemu-system-x86_64 /usr/libexec/podman/gvproxy /usr/libexec/podman/virtiofsd; do
        grep -qF "${helper}" build_files/modules/base.sh
    done
    grep -qF 'dnf5 -y install "${base_packages[@]}"' build_files/modules/base.sh
    grep -qF 'dnf5 -y --setopt=install_weak_deps=False install "${base_qemu_packages[@]}" "${base_vm_packages[@]}"' build_files/modules/base.sh
    test -f build_files/independently-managed-rpms.list
    grep -Eq '^tailscale-stable[[:space:]]+tailscale$' build_files/independently-managed-rpms.list
    grep -Eq '^terra[[:space:]]+espanso-wayland$' build_files/independently-managed-rpms.list
    test -f build_files/lib/independently-managed-rpms.sh
    grep -qF 'purplefin_load_independently_managed_rpms' build_files/lib/finalize-profile.sh
    grep -qF 'upgrade "${installed_independently_managed_rpms[@]}"' build_files/lib/finalize-profile.sh
    test ! -e build_files/install-nextcloud-appimage.sh
    ! grep -qF 'install-nextcloud-appimage' build_files/modules/base.sh
    ! grep -qF '/usr/bin/nextcloud' build_files/modules/base.sh

    # Bitwarden remains common rather than belonging to a role or hardware profile.
    test ! -e system_files/usr/libexec/purplefin/install-bitwarden-cli-native
    test ! -e system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-layer
    test -x system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    grep -qF 'rpm -q bitwarden' system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    grep -qF 'run_rpm_ostree uninstall bitwarden' system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    test ! -e system_files/usr/libexec/purplefin/update-bitwarden-flatpak
    test ! -e system_files/usr/lib/systemd/system/purplefin-bitwarden-flatpak-update.service
    test ! -e system_files/usr/lib/systemd/system/purplefin-bitwarden-flatpak-update.timer
    ! grep -qF 'purplefin-bitwarden-flatpak-update' build_files/modules/base.sh
    test -f system_files/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
    grep -qF '<action id="com.bitwarden.Bitwarden.unlock">' system_files/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
    test -x build_files/install-bitwarden-cli-rpm.sh
    test ! -e build_files/update-bitwarden-cli.sh
    test ! -e .github/workflows/update-bitwarden-cli.yml
    test -f build_files/bitwarden-cli.spec
    test -f build_files/bitwarden-cli.env
    grep -qE '^BITWARDEN_CLI_VERSION=[0-9]+(\.[0-9]+)+$' build_files/bitwarden-cli.env
    grep -qE '^BITWARDEN_CLI_SHA256=[0-9a-f]{64}$' build_files/bitwarden-cli.env
    grep -qF 'github.com/bitwarden/clients/releases/download/cli-v${cli_version}/bw-linux-${cli_version}.zip' build_files/install-bitwarden-cli-rpm.sh
    grep -qF 'sha256sum --check --strict' build_files/install-bitwarden-cli-rpm.sh
    ! grep -qF 'https://vault.bitwarden.com/download/?app=cli&platform=linux' build_files/install-bitwarden-cli-rpm.sh
    grep -qF 'rpmbuild -bb' build_files/install-bitwarden-cli-rpm.sh
    grep -qF 'Name:           purplefin-bitwarden-cli' build_files/bitwarden-cli.spec
    grep -qF '%global __os_install_post %{nil}' build_files/bitwarden-cli.spec
    grep -qF 'bash /tmp/purplefin-build/install-bitwarden-cli-rpm.sh' build_files/modules/base.sh
    grep -qF 'rpm -q purplefin-bitwarden-cli' build_files/modules/base.sh
    grep -qF "rpm -qf --qf '%{NAME}\\n' /usr/bin/bw" build_files/modules/base.sh
    grep -qF '### Migrating Bitwarden from the layered RPM' README.md

    # Support owns Espanso and RustConn and references the shared devops component.
    support_role=build_files/profiles/roles/support.sh
    support_root=profile_files/roles/support
    grep -qF '/tmp/purplefin-build/profiles/components/devops.sh' "${support_role}"
    grep -qF 'purplefin_apply_role_overlay support' "${support_role}"
    grep -qF 'install espanso-wayland' "${support_role}"
    grep -qF 'setcap "cap_dac_override+p" "$(command -v espanso)"' "${support_role}"
    grep -qF 'systemctl --global enable espanso.service' "${support_role}"
    test -f "${support_root}/manifests/flatpaks.preinstall"
    grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' "${support_root}/manifests/flatpaks.preinstall"
    ! grep -qF '[Flatpak Preinstall com.vscodium.codium]' "${support_root}/manifests/flatpaks.preinstall"
    test -f "${support_root}/system_files/usr/lib/systemd/user/espanso.service"
    espanso_unit="${support_root}/system_files/usr/lib/systemd/user/espanso.service"
    grep -qxF 'After=graphical-session.target' "${espanso_unit}"
    grep -qxF 'PartOf=graphical-session.target' "${espanso_unit}"
    grep -qxF 'ExecStart=/usr/bin/espanso launcher' "${espanso_unit}"
    grep -qxF 'WantedBy=graphical-session.target' "${espanso_unit}"
    ! grep -qxF 'WantedBy=default.target' "${espanso_unit}"
    test ! -e system_files/usr/lib/systemd/user/espanso.service
    ! rg -q 'pam-u2f|pamu2fcfg|libfido2|opensc|pcsc-lite|pcscd|yubikey-manager|with-fingerprint|with-pam-u2f' build_files/profiles/roles

    # Every hardware selection receives the same biometric, security-key, and
    # smart-card baseline as part of its hardware phase.
    hardware_security=build_files/profiles/lib/hardware-security.sh
    test -f "${hardware_security}"
    grep -qF 'source /tmp/purplefin-build/profiles/lib/hardware-security.sh' build_files/modules/hardware-generic-x86_64.sh
    grep -qF 'purplefin_apply_hardware_security' build_files/modules/hardware-generic-x86_64.sh
    for package in fprintd fprintd-pam libfprint pam-u2f pamu2fcfg libfido2 opensc pcsc-lite yubikey-manager; do
        grep -qE "^[[:space:]]*${package}$" "${hardware_security}"
    done
    grep -qF 'purplefin_authselect_request with-fingerprint with-pam-u2f' "${hardware_security}"
    grep -qF 'systemctl enable pcscd.socket' "${hardware_security}"
    ! rg -q 'dnf5 -y install fprintd libfprint|pam-u2f|pamu2fcfg|libfido2|opensc|pcsc-lite|pcscd|yubikey-manager|with-fingerprint|with-pam-u2f' \
        build_files/profiles/dell-xps-9350-intel.sh

    # Devops is a reusable component referenced by support and development.
    development_role=build_files/profiles/roles/development.sh
    devops_component=build_files/profiles/components/devops.sh
    devops_root=profile_files/components/devops
    devops_rpms="${devops_root}/manifests/rpms.list"
    test -x "${devops_component}"
    grep -qF '/tmp/purplefin-build/profiles/components/devops.sh' "${support_role}"
    grep -qF '/tmp/purplefin-build/profiles/components/devops.sh' "${development_role}"
    grep -qF 'purplefin_apply_role_overlay development' "${development_role}"
    grep -qF 'purplefin_apply_component_overlay "${component}"' "${devops_component}"
    grep -qF 'dnf5 -y install "${devops_packages[@]}"' "${devops_component}"
    grep -qF 'for command in ghostty ansible bao packer tofu' "${devops_component}"
    test -f "${devops_rpms}"
    test "$(grep -c '^[a-z0-9]' "${devops_rpms}")" -eq 5
    for package in ghostty ansible packer opentofu openbao; do
        grep -qxF "${package}" "${devops_rpms}"
    done
    grep -qF '[Flatpak Preinstall com.vscodium.codium]' "${devops_root}/manifests/flatpaks.preinstall"
    ! grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' "${devops_root}/manifests/flatpaks.preinstall"
    ghostty_skel="${devops_root}/system_files/etc/skel/.config/ghostty/config.ghostty"
    ghostty_shared="${devops_root}/system_files/usr/share/purplefin/ghostty/config.ghostty"
    test -f "${ghostty_skel}"
    test -f "${ghostty_shared}"
    cmp -s "${ghostty_skel}" "${ghostty_shared}"
    grep -qx 'copy-on-select = clipboard' "${ghostty_skel}"
    grep -qx 'right-click-action = paste' "${ghostty_skel}"
    grep -qx 'command = /usr/bin/zsh' "${ghostty_skel}"
    test -x "${devops_root}/system_files/usr/libexec/purplefin/install-ghostty-defaults"
    test -f "${devops_root}/system_files/usr/lib/systemd/user/purplefin-ghostty-defaults.service"
    zsh_shared="${devops_root}/system_files/usr/share/purplefin/zsh"
    for zsh_file in .zshenv .zshrc aliases.zsh bindings.zsh fzf.zsh plugins.zsh prompt.zsh starship.toml LICENSE; do
        test -f "${zsh_shared}/${zsh_file}"
    done
    for zsh_file in "${zsh_shared}"/.zshenv "${zsh_shared}"/.zshrc "${zsh_shared}"/*.zsh; do
        zsh -n "${zsh_file}"
    done
    grep -qF 'zsh-autosuggestions/zsh-autosuggestions.zsh' "${zsh_shared}/plugins.zsh"
    grep -qF 'zsh-history-substring-search/zsh-history-substring-search.zsh' "${zsh_shared}/plugins.zsh"
    grep -qF 'zsh-vi-mode.plugin.zsh' "${zsh_shared}/plugins.zsh"
    grep -qF 'zsh-fast-syntax-highlighting/fast-syntax-highlighting.plugin.zsh' "${zsh_shared}/plugins.zsh"
    ! grep -qF 'zplugin-update' "${zsh_shared}/plugins.zsh"
    ! grep -qF 'git clone' "${zsh_shared}/plugins.zsh"
    zsh_installer="${devops_root}/system_files/usr/libexec/purplefin/install-zsh-defaults"
    zsh_configurer="${devops_root}/system_files/usr/libexec/purplefin/configure-zsh-defaults"
    zsh_service="${devops_root}/system_files/usr/lib/systemd/user/purplefin-zsh-defaults.service"
    test -x "${zsh_installer}"
    test -x "${zsh_configurer}"
    test -f "${zsh_service}"
    ! grep -qF 'ConditionPathExists=' "${zsh_service}"
    grep -qF '/usr/libexec/purplefin/configure-zsh-defaults' "${devops_component}"
    grep -qF 'systemctl --global enable purplefin-zsh-defaults.service' "${devops_component}"

    zsh_home="${tmpdir}/zsh-home"
    env \
        HOME="${zsh_home}" \
        XDG_CONFIG_HOME="${zsh_home}/.config" \
        XDG_STATE_HOME="${zsh_home}/.local/state" \
        XDG_CACHE_HOME="${zsh_home}/.cache" \
        PURPLEFIN_ZSH_DEFAULTS_SOURCE="${PWD}/${zsh_shared}" \
        "${zsh_installer}"
    diff -qr "${zsh_shared}" "${zsh_home}/.config/zsh"
    cmp -s "${zsh_shared}/.zshenv" "${zsh_home}/.zshenv"
    test -d "${zsh_home}/.local/state/zsh"
    test -d "${zsh_home}/.cache/zsh"
    printf '%s\n' '# user configuration' > "${zsh_home}/.config/zsh/.zshrc"
    env \
        HOME="${zsh_home}" \
        XDG_CONFIG_HOME="${zsh_home}/.config" \
        XDG_STATE_HOME="${zsh_home}/.local/state" \
        XDG_CACHE_HOME="${zsh_home}/.cache" \
        PURPLEFIN_ZSH_DEFAULTS_SOURCE="${PWD}/${zsh_shared}" \
        "${zsh_installer}"
    grep -qxF '# user configuration' "${zsh_home}/.config/zsh/.zshrc"

    zshenv_test="${tmpdir}/zshenv-test"
    install -d "${zshenv_test}"
    touch "${zshenv_test}/zshenv" "${zshenv_test}/nested-zshenv"
    for iteration in 1 2; do
        PURPLEFIN_ZSHENV_PATHS="${zshenv_test}/zshenv:${zshenv_test}/nested-zshenv" "${zsh_configurer}"
    done
    for zshenv_file in "${zshenv_test}/zshenv" "${zshenv_test}/nested-zshenv"; do
        test "$(grep -cF '# Purplefin zsh configuration' "${zshenv_file}")" -eq 1
        grep -qF 'export ZDOTDIR="$XDG_CONFIG_HOME/zsh"' "${zshenv_file}"
    done

    hashicorp_repo="${devops_root}/system_files/etc/yum.repos.d/hashicorp.repo"
    test -f "${hashicorp_repo}"
    grep -qx '\[hashicorp\]' "${hashicorp_repo}"
    grep -qx 'baseurl=https://rpm.releases.hashicorp.com/fedora/\$releasever/\$basearch/stable' "${hashicorp_repo}"
    grep -qx 'gpgkey=https://rpm.releases.hashicorp.com/gpg' "${hashicorp_repo}"
    test -f "${devops_root}/system_files/usr/lib/tmpfiles.d/purplefin-openbao.conf"
    grep -qx 'd /var/lib/openbao 0700 openbao openbao - -' "${devops_root}/system_files/usr/lib/tmpfiles.d/purplefin-openbao.conf"
    ! rg -q 'dnf5.*(ghostty|ansible|packer|opentofu|openbao)|com\.vscodium\.codium' build_files/profiles/roles profile_files/roles
    test -z "$(find profile_files/roles/development -type f -print -quit 2>/dev/null)"

    # Reapplying the component is a no-op, including across subprocesses.
    devops_state="${tmpdir}/devops-component-state"
    install -d "${devops_state}"
    touch "${devops_state}/devops.applied"
    component_output="$(
        PURPLEFIN_BUILD_ROOT="${PWD}/build_files" \
        PURPLEFIN_COMPONENT_STATE_DIR="${devops_state}" \
        "${devops_component}"
    )"
    test "${component_output}" = ':: Devops component already applied'

    test ! -e system_files/etc/skel/.config/ghostty/config.ghostty
    test ! -e system_files/etc/yum.repos.d/hashicorp.repo
    grep -qx 'excludepkgs=bitwarden\*' system_files/etc/yum.repos.d/terra.repo

    overlay_common=build_files/profiles/lib/role-common.sh
    grep -qF 'cp -a "${system_root}/." /' "${overlay_common}"
    grep -qF 'purplefin_apply_overlay roles "${role}" "purplefin-${role}"' "${overlay_common}"
    grep -qF 'purplefin_apply_overlay components "${component}" "purplefin-component-${component}"' "${overlay_common}"
    grep -qF '/usr/share/flatpak/preinstall.d/${manifest_name}.preinstall' "${overlay_common}"

    # Bluefin's Tailscale integration is preserved while its RPM is updated independently.
    grep -qF 'tailscale-stable' build_files/independently-managed-rpms.list
    grep -qF 'espanso-wayland' build_files/independently-managed-rpms.list
    grep -qF 'independently_managed_rpm_repo_args' build_files/plan-image-builds.sh
    test -f system_files/usr/share/plymouth/themes/spinner/watermark.png
    test -f system_files/usr/share/plymouth/themes/spinner/silverblue-watermark.png
    test -f system_files/usr/share/pixmaps/fedora-gdm-logo.png
    file system_files/usr/share/plymouth/themes/spinner/watermark.png | grep -q 'PNG image data, 149 x 43'
    file system_files/usr/share/plymouth/themes/spinner/silverblue-watermark.png | grep -q 'PNG image data, 149 x 43'
    file system_files/usr/share/pixmaps/fedora-gdm-logo.png | grep -q 'PNG image data, 150 x 61'
    cmp -s system_files/usr/share/plymouth/themes/spinner/watermark.png system_files/usr/share/plymouth/themes/spinner/silverblue-watermark.png
    for logo in bluefin chicken dolly karl; do
        test -f "system_files/usr/share/ublue-os/bluefin-logos/${logo}.png"
        file "system_files/usr/share/ublue-os/bluefin-logos/${logo}.png" | grep -q 'PNG image data, 1000 x 1000'
        cmp -s "system_files/usr/share/ublue-os/bluefin-logos/${logo}.png" profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    done
    ! grep -qF 'PURPLEFIN_DELL_IPU7_KERNEL_EVR' Containerfile
    ! grep -qF 'PURPLEFIN_DELL_MAINLINE_KERNEL_EVR' Containerfile
    grep -qF 'PURPLEFIN_OSTREE_LINUX' Containerfile
    grep -qF 'LABEL ostree.linux="${PURPLEFIN_OSTREE_LINUX}"' Containerfile
    test -x build_files/select-ostree-linux.sh
    test "$(build_files/select-ostree-linux.sh dale 7.1.3-200.fc44.x86_64)" = '7.1.3-200.fc44.x86_64'
    test "$(build_files/select-ostree-linux.sh base-generic 7.0.11-200.fc44.x86_64)" = '7.0.11-200.fc44.x86_64'
    test "$(build_files/select-ostree-linux.sh support-dell-xps-9350-intel 7.2.0-200.fc44.x86_64)" = '7.2.0-200.fc44.x86_64'
    test "$(jq length build_files/image-matrix.json)" -eq 7
    test -x build_files/profile-build-input.sh
    while IFS= read -r entry; do
        profile="$(jq -r '.profile' <<<"${entry}")"
        tags="$(jq -r '.tags' <<<"${entry}")"
        build_input="$(build_files/profile-build-input.sh "${profile}" "${tags}")"
        [[ "${build_input}" =~ ^[0-9a-f]{64}$ ]]
    done < <(jq -c '.[]' build_files/image-matrix.json)
    ci_matrix="$(jq -r '.[] | [.profile, (.parent // "root"), .tags] | join("|")' build_files/image-matrix.json)"
    test "${ci_matrix}" = "$(printf '%s\n' \
        'base-generic|root|generic-x86_64 latest base-generic-x86_64' \
        'base-dell-xps-9350-intel|root|base-dell-xps-9350-intel' \
        'sales-generic|base-generic|sales-generic' \
        'sales-dell-xps-9350-intel|base-dell-xps-9350-intel|sales-dell-xps-9350-intel' \
        'support-generic|base-generic|support-generic' \
        'support-dell-xps-9350-intel|base-dell-xps-9350-intel|support-dell-xps-9350-intel' \
        'dale|base-dell-xps-9350-intel|dale dell-xps-9350-intel')"
    test -x build_files/build-derived.sh
    test -f Containerfile.derived
    tests/derived-profile-build.sh
    grep -qF 'PURPLEFIN_OSTREE_LINUX=' .github/workflows/build-profile.yml
    grep -qF 'ostree.linux=' .github/workflows/build-profile.yml
    grep -qF 'steps.kernel.outputs.release' .github/workflows/build-profile.yml
    grep -qF 'uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1' .github/workflows/build.yml
    grep -qF 'build_files/plan-image-builds.sh' .github/workflows/build.yml
    grep -qF 'org.opencontainers.image.base.digest=' .github/workflows/build-profile.yml
    grep -qF 'io.purplefin.build.input=' .github/workflows/build-profile.yml
    grep -qF 'io.purplefin.parent.digest=' .github/workflows/build-profile.yml
    grep -qF -- '--cache-from' .github/workflows/build-profile.yml
    grep -qF -- '--cache-to' .github/workflows/build-profile.yml
    grep -qF 'image: oci-archive:' .github/workflows/build-profile.yml
    grep -qF 'steps.rechunk.outputs.archive' .github/workflows/build-profile.yml
    grep -qF 'base-generic-publish:' .github/workflows/build.yml
    grep -qF 'derived-publish:' .github/workflows/build.yml
    tests/image-build-planner.sh
    grep -qF 'buildah bud' .github/workflows/build-profile.yml
    grep -qF 'podman login' .github/workflows/build-profile.yml
    grep -qF 'podman push' .github/workflows/build-profile.yml
    grep -qF 'REGISTRY_AUTH_FILE=' .github/workflows/build-profile.yml
    ! rg -q 'ghcr.io/ublue-os/bluefin(:|\b)' Containerfile README.md Justfile .github/workflows
    ! rg -q 'actions/checkout@v4|redhat-actions/(buildah-build|podman-login|push-to-registry)' .github/workflows
    ! rg -q 'bootc-image-builder|--type bootc-installer|anaconda-iso' .github installer
    grep -qF 'bootc-generic-iso' .github/workflows/build-installer.yml
    grep -qF 'ghcr.io/osbuild/image-builder-cli@sha256:' .github/workflows/build-installer.yml
    test -z "$(find build_files/modules -maxdepth 1 -name 'legacy-*' -print -quit)"
    test -z "$(find build_files/profiles -maxdepth 1 \( -name '*no-ipu7*' -o -name 'desktop-x86_64.sh' -o -name 'lenovo-generic.sh' \) -print -quit)"
    ! grep -qF 'dracut --force "${kernel_modules_dir}/initramfs.img" "${kernel_version}"' build_files/build.sh
    grep -qF 'rm -f /boot/symvers-*.xz' build_files/lib/finalize-profile.sh
    grep -qF '/var/lib/rpm-state' build_files/lib/finalize-profile.sh
    grep -qF '/var/log/dnf5.log*' build_files/lib/finalize-profile.sh
    grep -qF 'installed_kernel_releases' build_files/lib/finalize-profile.sh
    test -x system_files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -z "$(find system_files -iname '*ipu7*' -print -quit)"
    test -z "$(find system_files profile_files -iname '*librepods*' -print -quit)"
    ! rg -qi 'librepods' README.md build_files/profiles
    test -f build_files/profiles/lib/dell-xps-9350-common.sh
    grep -qF 'source /tmp/purplefin-build/profiles/lib/dell-xps-9350-common.sh' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'purplefin_configure_dell_xps_9350_common' build_files/profiles/dell-xps-9350-intel.sh
    test ! -e profile_files/dell-xps-9350-intel/system_files/etc/plymouth
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/20-dell-ipu7-stable-kernel
    xps_profile_root=profile_files/dell-xps-9350-intel/system_files
    xps_common_profile=build_files/profiles/lib/dell-xps-9350-common.sh
    lid_auth_helper="${xps_profile_root}/usr/libexec/purplefin/dell-lid-is-open"
    lid_auth_stack="${xps_profile_root}/etc/pam.d/purplefin-dell-lid-auth"
    password_auth_stack="${xps_profile_root}/etc/pam.d/purplefin-dell-password-auth"
    sudo_auth_stack="${xps_profile_root}/etc/pam.d/sudo"
    polkit_auth_stack="${xps_profile_root}/etc/pam.d/polkit-1"
    battery_helper="${xps_profile_root}/usr/libexec/purplefin/configure-dell-xps-9350-battery"
    battery_unit="${xps_profile_root}/usr/lib/systemd/system/purplefin-dell-xps-9350-battery.service"
    battery_hwdb="${xps_profile_root}/usr/lib/udev/hwdb.d/61-purplefin-dell-xps-9350-battery.hwdb"
    tuned_profile="${xps_profile_root}/usr/lib/tuned/profiles/purplefin-dell-xps-9350-performance/tuned.conf"
    panel_helper="${xps_profile_root}/usr/libexec/purplefin/dell-xps-9350-panel-policy"
    panel_unit="${xps_profile_root}/usr/lib/systemd/user/purplefin-dell-xps-9350-panel.service"
    panel_defaults="${xps_profile_root}/usr/share/purplefin/dell-xps-9350-panel.conf"
    panel_wants="${xps_profile_root}/etc/systemd/user/graphical-session.target.wants/purplefin-dell-xps-9350-panel.service"
    ambient_override="${xps_profile_root}/usr/share/glib-2.0/schemas/zz9-purplefin-dell-xps-9350.gschema.override"
    test -x "${lid_auth_helper}"
    test -f "${lid_auth_stack}"
    test -f "${password_auth_stack}"
    test -f "${sudo_auth_stack}"
    test -f "${polkit_auth_stack}"
    grep -qF 'LidClosed' "${lid_auth_helper}"
    grep -qF '/proc/acpi/button/lid' "${lid_auth_helper}"
    grep -qF 'lid-aware privilege authentication' "${xps_common_profile}"
    ! rg -q 'purplefin-dell-lid-auth|dell-lid-is-open' system_files profile_files/roles profile_files/components
    test -x "${battery_helper}"
    test -f "${battery_unit}"
    test -f "${battery_hwdb}"
    grep -qF 'XPS 13 9350' "${battery_helper}"
    grep -qF 'EnableChargeThreshold b true' "${battery_helper}"
    grep -qF 'ChargeThresholdEnabled' "${battery_helper}"
    grep -qF 'write_attribute "${charge_types_path}" Custom' "${battery_helper}"
    grep -qx 'Requires=upower.service' "${battery_unit}"
    grep -qx 'START_THRESHOLD=75' "${xps_profile_root}/usr/lib/purplefin/dell-xps-9350-battery.conf"
    grep -qx 'END_THRESHOLD=80' "${xps_profile_root}/usr/lib/purplefin/dell-xps-9350-battery.conf"
    systemd-hwdb --root="${tmpdir}" --strict update
    systemd-hwdb --root="${tmpdir}" query 'battery:BAT0:DELL TR7FC488:dmi:bvnDellInc.:svnDellInc.:pnXPS139350:' | grep -qx 'CHARGE_LIMIT=75,80'
    for expected_setting in include=balanced energy_performance_preference=performance boost=1 platform_profile=performance; do
        grep -qxF "${expected_setting}" "${tuned_profile}"
    done
    ! grep -Eq '^[[:space:]]*(min_perf_pct|\[vm([^]]*)?\]|\[disk\])[[:space:]]*(=|$)' "${tuned_profile}"
    test -x "${panel_helper}"
    test -f "${panel_unit}"
    grep -qx 'After=graphical-session-pre.target' "${panel_unit}"
    ! grep -qx 'After=graphical-session.target' "${panel_unit}"
    test -L "${panel_wants}"
    test "$(readlink "${panel_wants}")" = '../../../../usr/lib/systemd/user/purplefin-dell-xps-9350-panel.service'
    grep -qx 'PANEL_AC_MODE=1920x1200@120.000+vrr' "${panel_defaults}"
    grep -qx 'PANEL_BATTERY_MODE=1920x1200@60.000' "${panel_defaults}"
    grep -qF 'external_drm_connector_is_connected' "${panel_helper}"
    grep -qF 'AMBIENT_BRIGHTNESS_MIGRATION_ENABLED=true' "${panel_defaults}"
    grep -qF 'dell-xps-9350-ambient-brightness-v1' "${panel_helper}"
    grep -qx 'ambient-enabled=true' "${ambient_override}"
    grep -qF 'glib-compile-schemas --strict --dry-run "${schema_validation_dir}"' "${xps_common_profile}"
    grep -qF 'glib-compile-schemas "${schema_dir}"' "${xps_common_profile}"
    ! grep -qF 'glib-compile-schemas --strict /usr/share/glib-2.0/schemas' "${xps_common_profile}"
    schema_tmp="${tmpdir}/xps-schemas"
    install -d "${schema_tmp}"
    printf '%s\n' \
        '<?xml version="1.0" encoding="UTF-8"?>' \
        '<schemalist>' \
        '  <schema id="org.gnome.settings-daemon.plugins.power" path="/org/gnome/settings-daemon/plugins/power/">' \
        '    <key name="ambient-enabled" type="b"><default>true</default></key>' \
        '  </schema>' \
        '</schemalist>' > "${schema_tmp}/org.gnome.settings-daemon.plugins.power.gschema.xml"
    printf '%s\n' '[org.gnome.settings-daemon.plugins.power]' 'ambient-enabled=false' > "${schema_tmp}/zz0-base.gschema.override"
    cp "${ambient_override}" "${schema_tmp}/"
    glib-compile-schemas --strict "${schema_tmp}"
    GSETTINGS_SCHEMA_DIR="${schema_tmp}" GSETTINGS_BACKEND=memory gsettings get org.gnome.settings-daemon.plugins.power ambient-enabled | grep -qx true
    printf '%s\n' \
        '<?xml version="1.0" encoding="UTF-8"?>' \
        '<schemalist>' \
        '  <schema id="org.gnome.desktop.screensaver" path="/org/gnome/desktop/screensaver/">' \
        '    <key name="picture-uri" type="s">' \
        "      <default>''</default>" \
        '    </key>' \
        '  </schema>' \
        '</schemalist>' > "${schema_tmp}/org.gnome.desktop.screensaver.gschema.xml"
    printf '%s\n' \
        '[org.gnome.desktop.screensaver]' \
        "picture-uri='file:///usr/share/backgrounds/day.jpg'" \
        "picture-uri-dark='file:///usr/share/backgrounds/night.jpg'" \
        > "${schema_tmp}/10_org.gnome.desktop.screensaver.fedora.gschema.override"
    schema_compile_log="${schema_tmp}/compile.log"
    if LC_ALL=C glib-compile-schemas --strict "${schema_tmp}" 2>"${schema_compile_log}"; then
        echo 'strict aggregate schema compilation unexpectedly accepted an inherited invalid key' >&2
        exit 1
    fi
    grep -qF 'picture-uri-dark' "${schema_compile_log}"
    grep -qF -- '--strict was specified' "${schema_compile_log}"
    rm -f "${schema_tmp}/gschemas.compiled"
    LC_ALL=C glib-compile-schemas "${schema_tmp}" 2>"${schema_compile_log}"
    test -f "${schema_tmp}/gschemas.compiled"
    grep -qF 'picture-uri-dark' "${schema_compile_log}"
    grep -qF 'ignoring override for this key' "${schema_compile_log}"
    GSETTINGS_SCHEMA_DIR="${schema_tmp}" GSETTINGS_BACKEND=memory gsettings get org.gnome.settings-daemon.plugins.power ambient-enabled | grep -qx true
    GSETTINGS_SCHEMA_DIR="${schema_tmp}" GSETTINGS_BACKEND=memory gsettings get org.gnome.desktop.screensaver picture-uri | grep -qx "'file:///usr/share/backgrounds/day.jpg'"
    tests/dell-lid-auth.sh
    tests/dell-xps-9350-policies.sh
    test -f docs/dell-xps-9350-secure-boot.md
    grep -qF '`cvs` is not a replacement' docs/dell-xps-9350-secure-boot.md
    grep -qF 'updates/purplefin' docs/dell-xps-9350-secure-boot.md
    grep -qF 'source-provenance' docs/dell-xps-9350-secure-boot.md
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/dell-ipu7-activate
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/dell-ipu7-rebind-sensor
    test -x profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    test -f profile_files/dell-xps-9350-intel/system_files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.service
    test -f profile_files/dell-xps-9350-intel/system_files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path
    test -L profile_files/dell-xps-9350-intel/system_files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.service
    test "$(readlink profile_files/dell-xps-9350-intel/system_files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.service)" = '../../../../usr/lib/systemd/user/purplefin-firefox-pipewire-camera.service'
    test -L profile_files/dell-xps-9350-intel/system_files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.path
    test "$(readlink profile_files/dell-xps-9350-intel/system_files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.path)" = '../../../../usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path'
    grep -qF 'PathChanged=%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini' profile_files/dell-xps-9350-intel/system_files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path
    firefox_test_root="${tmpdir}/firefox-profiles"
    install -d "${firefox_test_root}/Profile With Spaces"
    printf '%s\n' '[Profile0]' 'Path=Profile With Spaces' > "${firefox_test_root}/profiles.ini"
    printf '%s\n' 'user_pref("example.preserved", true);' 'user_pref("media.webrtc.camera.allow-pipewire", false);' > "${firefox_test_root}/Profile With Spaces/user.js"
    PURPLEFIN_FIREFOX_PROFILE_ROOT="${firefox_test_root}" profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    PURPLEFIN_FIREFOX_PROFILE_ROOT="${firefox_test_root}" profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    grep -qF 'user_pref("example.preserved", true);' "${firefox_test_root}/Profile With Spaces/user.js"
    test "$(grep -cF 'user_pref("media.webrtc.camera.allow-pipewire", true);' "${firefox_test_root}/Profile With Spaces/user.js")" = 1
    test "$(grep -cF '// Purplefin: expose the IPU7 libcamera source instead of raw V4L2 nodes.' "${firefox_test_root}/Profile With Spaces/user.js")" = 1
    test -f profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/lib/dell-ipu7.sh
    grep -qF 'installed_kernel_core_record' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'PURPLEFIN_OSTREE_LINUX' build_files/profiles/dell-xps-9350-intel.sh
    ! grep -Eq 'kernel-vanilla|mainline-kernel|remove_non_ipu7_runtime_kernels|validate_in_tree_cvs_module' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'purplefin_dell_ipu7_fix_pack_ref' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'CONFIG_CC_IS_CLANG=y' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'CONFIG_CC_IS_GCC=y' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'svp7500_make_args=(CC=gcc)' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'intel-cvs-1.0 intel_cvs.ko' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'ipu-bridge-patched-1.0 ipu-bridge.ko' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'hm1092-1.0 hm1092.ko' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'purplefin_dell_ipu7_int3472_patch_needed' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF -- '--rebuild "${initramfs_path}"' build_files/profiles/dell-xps-9350-intel.sh
    ! grep -qF -- '--no-hostonly' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF -- '--add-drivers "${initramfs_modules[*]}"' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'ipu7_firmware_path="$(purplefin_dell_ipu7_find_firmware)"' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF -- '--install "${ipu7_firmware_path}"' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF '$NF == firmware { found = 1 } END { exit !found }' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'Rebuilt initramfs does not contain Dell IPU7 firmware ${ipu7_firmware_path}' build_files/profiles/dell-xps-9350-intel.sh
    for module in ostree dmsquash-live dmsquash-live-autooverlay; do
        grep -qE "^[[:space:]]*${module}$" build_files/profiles/dell-xps-9350-intel.sh
    done
    grep -qF 'Rebuilt initramfs lost required boot module ${module}' build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'dnf5 -y remove --no-autoremove' build_files/profiles/dell-xps-9350-intel.sh
    for package in libcamera libcamera-ipa libcamera-tools pipewire-plugin-libcamera; do
        grep -qE "^[[:space:]]*${package}$" build_files/profiles/dell-xps-9350-intel.sh
    done
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/lib/systemd/system/purplefin-dell-ipu7-camera.service
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/lib/udev/rules.d/99-purplefin-dell-ipu7-camera.rules
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/lib/modprobe.d/purplefin-dell-ipu7.conf
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/lib/modules-load.d/purplefin-dell-ipu7.conf
    test -f profile_files/dell-xps-9350-intel/system_files/usr/lib/udev/rules.d/99-purplefin-svp7500-no-autosuspend.rules
    test -f profile_files/dell-xps-9350-intel/system_files/usr/lib/udev/rules.d/99-purplefin-hm1092-ir-led.rules
    grep -qF 'ATTRS{idVendor}=="06cb"' profile_files/dell-xps-9350-intel/system_files/usr/lib/udev/rules.d/99-purplefin-svp7500-no-autosuspend.rules
    grep -qF 'KERNEL=="*ir_flood_led*"' profile_files/dell-xps-9350-intel/system_files/usr/lib/udev/rules.d/99-purplefin-hm1092-ir-led.rules
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'monitor.v4l2.rules' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.description = "ipu7"' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'monitor.libcamera.rules' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.description = "hm1092"' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.disabled = true' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'node.nick = "hm1092"' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'node.disabled = true' profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    spa-json-dump profile_files/dell-xps-9350-intel/system_files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf >/dev/null
    ov02c10_tuning=profile_files/dell-xps-9350-intel/system_files/usr/share/libcamera/ipa/simple/ov02c10.yaml
    test -f "${ov02c10_tuning}"
    grep -qF 'blackLevel: 4096' "${ov02c10_tuning}"
    grep -qF -- '- Ccm:' "${ov02c10_tuning}"
    grep -qF '0.0, 0.9, 0.0' "${ov02c10_tuning}"
    test -x build_files/install-libcamera-ov02c10-ipa.sh
    test -f build_files/libcamera/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'REGISTER_CAMERA_SENSOR_HELPER("ov02c10", CameraSensorHelperOv02c10)' build_files/libcamera/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'gain_ = AnalogueGainLinear{ 1, 0, 0, 16 };' build_files/libcamera/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'blackLevel_ = 4096;' build_files/libcamera/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'source_sha256="27a6d776bb728bb8bd38c4594ff3ab7fadfce19583427de8442963ef2fe5ad04"' build_files/install-libcamera-ov02c10-ipa.sh
    grep -qF -- '-Dwerror=false' build_files/install-libcamera-ov02c10-ipa.sh
    grep -qF '/tmp/purplefin-build/install-libcamera-ov02c10-ipa.sh' build_files/profiles/dell-xps-9350-intel.sh
    test -f profile_files/dell-xps-9350-intel/system_files/etc/libcamera/configuration.yaml
    grep -qF -- '- /usr/lib64/libcamera/ipa-purplefin' profile_files/dell-xps-9350-intel/system_files/etc/libcamera/configuration.yaml
    test ! -e profile_files/generic-x86_64/system_files/etc/libcamera/configuration.yaml
    for obsolete in \
        usr/libexec/purplefin/dell-ipu7-setup \
        usr/libexec/purplefin/dell-ipu7-patch-psys-debugfs \
        usr/libexec/purplefin/firstboot-rpm-ostree.d/30-dell-ipu7-build-deps \
        usr/libexec/purplefin/firstboot-rpm-ostree.d/40-dell-ipu7-dkms-userspace \
        usr/lib/systemd/system/purplefin-dell-ipu7-psys-load.service \
        usr/lib/systemd/system/purplefin-dell-ipu7-v4l2loopback-load.service \
        usr/lib/systemd/user/pipewire.service.d/10-purplefin-dell-ipu7-libcamera.conf \
        usr/lib/systemd/user/purplefin-dell-ipu7-v4l2loopback.service \
        etc/systemd/user/default.target.wants/purplefin-dell-ipu7-v4l2loopback.service; do
        test ! -e "profile_files/dell-xps-9350-intel/system_files/${obsolete}"
    done
    ! rg -q 'kernel-evr.denylist|7.1.2-355.vanilla.fc44|CONFIG_VIDEO_INTEL_CVS' profile_files/dell-xps-9350-intel/system_files build_files/profiles/dell-xps-9350-intel.sh
    grep -qF 'e4c95452339b2d9803974a899c4f2da6e143891d' profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/lib/dell-ipu7.sh
    test ! -e profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/firstboot-rpm-ostree.d/50-dell-vates-plymouth-initramfs
    test -x profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/install-refind-theme
    test -f profile_files/dell-xps-9350-intel/system_files/usr/lib/systemd/system/purplefin-refind-theme.service
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_fedora.png
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/fonts/source-code-pro-extralight-14.png
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_win11.png
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_windows.png
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png
    test -f profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    cmp -s profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    cmp -s profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_fedora.png
    cmp -s profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_linux.png
    unexpected_refind_distro_icon="$(find profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons -type f -name 'os_*.png' ! -path '*/icons/os_win.png' ! -path '*/icons/os_win8.png' ! -path '*/icons/os_win11.png' ! -path '*/icons/os_windows.png' ! -path '*/icons/os_bluefin.png' ! -path '*/icons/os_purplefin.png' ! -path '*/icons/os_fedora.png' ! -path '*/icons/os_linux.png' -print -quit)"
    test -z "${unexpected_refind_distro_icon}"
    grep -qx 'icons_dir themes/rEFInd-Regular-Dark/icons' profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf
    ! grep -q '^menuentry ' profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf

    # shellcheck source=/dev/null
    source profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/lib/dell-ipu7.sh
    test "$(purplefin_dell_ipu7_fix_pack_repo)" = 'https://github.com/jibsta210/svp7500-camera-fix-pack'
    test "$(purplefin_dell_ipu7_fix_pack_version)" = 'v1.0.2'
    test "$(purplefin_dell_ipu7_fix_pack_ref)" = 'e4c95452339b2d9803974a899c4f2da6e143891d'
    ipu7_firmware_root="${tmpdir}/firmware/intel/ipu"
    install -d "${ipu7_firmware_root}"
    printf 'test firmware\n' > "${ipu7_firmware_root}/ipu7_fw.bin.zst"
    test "$(PURPLEFIN_DELL_IPU7_FIRMWARE_ROOTS="${ipu7_firmware_root}" purplefin_dell_ipu7_find_firmware)" = "${ipu7_firmware_root}/ipu7_fw.bin.zst"
    test "$(purplefin_dell_ipu7_kernel_release_for_evr_arch '7.1.3-201.fc44' x86_64)" = '7.1.3-201.fc44.x86_64'
    ipu7_config="${tmpdir}/ipu7-kernel.config"
    required_ipu7_configs=(CONFIG_IPU_BRIDGE CONFIG_VIDEO_INTEL_IPU7 CONFIG_VIDEO_OV02C10 CONFIG_USB_USBIO CONFIG_GPIO_USBIO CONFIG_I2C_USBIO)
    printf '%s=m\n' "${required_ipu7_configs[@]}" > "${ipu7_config}"
    purplefin_dell_ipu7_validate_kernel_config_file "${ipu7_config}"
    for missing_config in "${required_ipu7_configs[@]}"; do
        grep -v "^${missing_config}=" "${ipu7_config}" > "${ipu7_config}.missing"
        if purplefin_dell_ipu7_validate_kernel_config_file "${ipu7_config}.missing" >/dev/null 2>&1; then
            echo "Dell IPU7 kernel config validator accepted missing ${missing_config}" >&2
            exit 1
        fi
    done
    printf '%s=y\n' "${required_ipu7_configs[@]}" > "${ipu7_config}.built-in"
    purplefin_dell_ipu7_validate_kernel_config_file "${ipu7_config}.built-in"

    refind_installer="profile_files/dell-xps-9350-intel/system_files/usr/libexec/purplefin/install-refind-theme"
    refind_theme_source="profile_files/dell-xps-9350-intel/system_files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark"
    mkdir -p "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons"
    printf '%s\n' 'timeout 5' > "${refind_tmp}/EFI/refind/refind.conf"
    printf '%s\n' 'replace-existing-target-icon' > "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons/os_linux.png"
    printf '%s\n' 'remove-stale-distro-icon' > "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons/os_ubuntu.png"
    for run in 1 2; do
        PURPLEFIN_REFIND_DIR="${refind_tmp}/EFI/refind" PURPLEFIN_REFIND_THEME_SOURCE="${PWD}/${refind_theme_source}" "${refind_installer}" >/dev/null 2>&1
    done
    cmp -s "${refind_theme_source}/icons/os_linux.png" "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons/os_linux.png"
    cmp -s "${refind_theme_source}/icons/os_win11.png" "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons/os_win11.png"
    test ! -e "${refind_tmp}/EFI/refind/themes/rEFInd-Regular-Dark/icons/os_ubuntu.png"
    test "$(grep -c '^include themes/rEFInd-Regular-Dark/theme.conf$' "${refind_tmp}/EFI/refind/refind.conf")" -eq 1

_build profile tag:
    #!/usr/bin/env bash
    set -euo pipefail
    base_image='ghcr.io/projectbluefin/bluefin:stable'
    base_metadata="$(skopeo inspect --retry-times 3 "docker://${base_image}")"
    base_digest="$(jq -er '.Digest' <<<"${base_metadata}")"
    base_kernel="$(jq -er '.Labels["ostree.linux"]' <<<"${base_metadata}")"
    target_kernel="$(build_files/select-ostree-linux.sh '{{ profile }}' "${base_kernel}")"
    podman build \
        --pull=missing \
        --build-arg BASE_REF="ghcr.io/projectbluefin/bluefin@${base_digest}" \
        --build-arg BUILD_PROFILE='{{ profile }}' \
        --build-arg PURPLEFIN_OSTREE_LINUX="${target_kernel}" \
        --build-arg PURPLEFIN_VERSION="$(<VERSION)" \
        --label "org.opencontainers.image.base.digest=${base_digest}" \
        --label "ostree.linux=${target_kernel}" \
        --tag '{{ tag }}' \
        .

build-generic:
    just _build base-generic {{ image }}:generic-x86_64

build-dell:
    just _build dale {{ image }}:dell-xps-9350-intel

build-base-generic:
    just _build base-generic {{ image }}:base-generic-x86_64

build-support-dell:
    just _build support-dell-xps-9350-intel {{ image }}:support-dell-xps-9350-intel

lint-generic:
    podman run --rm --entrypoint bootc {{ image }}:generic-x86_64 container lint

lint-dell:
    podman run --rm --entrypoint bootc {{ image }}:dell-xps-9350-intel container lint

lint-base-generic:
    podman run --rm --entrypoint bootc {{ image }}:base-generic-x86_64 container lint

lint-support-dell:
    podman run --rm --entrypoint bootc {{ image }}:support-dell-xps-9350-intel container lint
