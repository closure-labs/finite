image := "ghcr.io/declarative-dale/purplefin"

default:
    @just --list

# Format Nix sources after removing unused Nix bindings.
format:
    deadnix --edit .
    alejandra .

# Check Nix formatting and unused bindings without modifying the source tree.
format-check:
    alejandra --check .
    deadnix --fail .

check:
    #!/usr/bin/env bash
    set -euo pipefail

    find bootc installer/overlay tests -type f \( -name '*.sh' -o -perm -111 \) -exec bash -n {} +

    tmpdir="$(mktemp -d)"
    refind_tmp="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}" "${refind_tmp}"' EXIT
    cp -a bootc/overlays/base/files/. "${tmpdir}/"
    cp -a bootc/overlays/roles/support/files/. "${tmpdir}/"
    cp -a bootc/components/devops/files/. "${tmpdir}/"
    cp -a bootc/overlays/hardware/dell-xps-9350-intel/files/. "${tmpdir}/"
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
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/bootc/overlays/base/files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/reboot-required" \
        bootc/overlays/base/files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -e "${firstboot_test}/markers/10-active.done"
    test ! -e "${firstboot_test}/markers/20-retired.done"

    install -d "${firstboot_test}/retired-markers"
    touch "${firstboot_test}/retired-markers/30-retired.done"
    env \
        PATH="${firstboot_test}/bin:${PATH}" \
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/bootc/overlays/base/files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/retired-tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/retired-markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/retired-reboot-required" \
        bootc/overlays/base/files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test ! -e "${firstboot_test}/retired-markers/30-retired.done"

    install -d "${firstboot_test}/pending-bin" "${firstboot_test}/pending-markers"
    printf '%s\n' '#!/usr/bin/env bash' 'exit 77' > "${firstboot_test}/pending-bin/rpm-ostree"
    chmod 0755 "${firstboot_test}/pending-bin/rpm-ostree"
    touch "${firstboot_test}/pending-markers/40-pending.done"
    env \
        PATH="${firstboot_test}/pending-bin:${PATH}" \
        PURPLEFIN_FIRSTBOOT_HELPER="${PWD}/bootc/overlays/base/files/usr/libexec/purplefin/lib/rpm-ostree-firstboot.sh" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_TASK_DIR="${firstboot_test}/pending-tasks" \
        PURPLEFIN_FIRSTBOOT_RPM_OSTREE_MARKER_DIR="${firstboot_test}/pending-markers" \
        PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE="${firstboot_test}/pending-reboot-required" \
        bootc/overlays/base/files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -e "${firstboot_test}/pending-markers/40-pending.done"

    # Den/Nix emits the only supported named-profile composition interface.
    test "$(jq '.profiles | length' bootc/generated/profile-catalog.json)" -eq 12

    for module in base developer support sales trainer executive it hardware-generic-x86_64 hardware-framework-laptop hardware-dell-xps-9350-intel; do
        test -x "bootc/modules/${module}.sh"
    done
    test -f VERSION
    grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' VERSION
    grep -qF 'ARG BUILD_PROFILE=base-generic' Containerfile
    grep -qF '/tmp/purplefin-build/build/full.sh "${BUILD_PROFILE}"' Containerfile
    grep -qxF 'bootc/build/plan.sh' .containerignore
    grep -qxF 'bootc/generated/image-matrix.json' .containerignore
    grep -qxF 'bootc/generated/upstream.json' .containerignore
    ! grep -qF 'bootc/generated/profile-catalog.json' .containerignore
    grep -qF 'profile_catalog="${build_root}/generated/profile-catalog.json"' bootc/build/full.sh
    test "$(jq -r '.profiles.dale.modules | join(" ")' bootc/generated/profile-catalog.json)" = 'base sales trainer support hardware-dell-xps-9350-intel'
    test "$(jq -r '.profiles.dale.deltaModules | join(" ")' bootc/generated/profile-catalog.json)" = 'sales trainer support'
    test "$(jq -r '.profiles["base-generic"].deltaModules | join(" ")' bootc/generated/profile-catalog.json)" = 'hardware-generic-x86_64'
    grep -qF 'ARG BASE_REF=ghcr.io/projectbluefin/bluefin:stable' Containerfile
    grep -qF 'FROM ${BASE_REF}' Containerfile
    grep -qF 'org.opencontainers.image.base.name="${BASE_REF}"' Containerfile
    grep -qF 'org.opencontainers.image.version="${PURPLEFIN_VERSION}"' Containerfile
    grep -qF 'Profile ${profile} must include exactly one hardware module' bootc/build/full.sh
    grep -qF 'printf '\''%s\n'\'' "${profile_modules[@]}" >/usr/share/purplefin/build-modules' bootc/lib/finalize-profile.sh
    grep -qF '/usr/share/purplefin/version' bootc/lib/finalize-profile.sh
    grep -qF 'purplefin_authselect_finalize' bootc/build/full.sh
    test -x bootc/overlays/base/files/usr/bin/purplefin-caffeinate
    test -f bootc/overlays/base/files/usr/lib/systemd/user/purplefin-caffeinate.service
    grep -qF 'ConditionACPower=true' bootc/overlays/base/files/usr/lib/systemd/user/purplefin-caffeinate.service
    grep -qF -- '--what=sleep:handle-lid-switch' bootc/overlays/base/files/usr/lib/systemd/user/purplefin-caffeinate.service

    # Base/common content is present in every named profile.
    grep -qF 'install -d -m 0755 /nix' bootc/modules/base.sh
    test -f bootc/overlays/base/manifests/Brewfile
    grep -qF 'marp-cli' bootc/overlays/base/manifests/Brewfile
    for formula in fzf neovim zsh-autosuggestions zsh-fast-syntax-highlighting zsh-history-substring-search zsh-vi-mode; do
        grep -qxF "brew \"${formula}\"" bootc/overlays/base/manifests/Brewfile
    done
    test -f bootc/overlays/base/manifests/flatpaks.preinstall
    for app_id in com.bitwarden.desktop it.mijorus.gearlever com.nextcloud.desktopclient.nextcloud hu.irl.cameractrls org.mozilla.firefox org.mozilla.thunderbird; do
        grep -qF "[Flatpak Preinstall ${app_id}]" bootc/overlays/base/manifests/flatpaks.preinstall
    done
    grep -qF '[Flatpak Preinstall org.mozilla.thunderbird]' bootc/overlays/roles/sales/manifests/flatpaks.preinstall
    ! rg -q 'org\.mozilla\.(Thunderbird|thunderbird_esr)' bootc/overlays/base/manifests/flatpaks.preinstall bootc/overlays/roles/sales/manifests/flatpaks.preinstall
    ! grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' bootc/overlays/base/manifests/flatpaks.preinstall
    ! grep -qF '[Flatpak Preinstall com.vscodium.codium]' bootc/overlays/base/manifests/flatpaks.preinstall
    for package in fuse fuse-libs git micro nm-connection-editor nm-connection-editor-desktop wireguard-tools; do
        grep -qF "${package}" bootc/modules/base.sh
    done
    for package in qemu-block-curl qemu-block-dmg qemu-block-iscsi qemu-block-nfs qemu-block-ssh qemu-img qemu-tools; do
        grep -qF "${package}" bootc/modules/base.sh
    done
    for package in podman-machine qemu-system-x86-core; do
        grep -qF "${package}" bootc/modules/base.sh
    done
    for helper in /usr/bin/qemu-system-x86_64 /usr/libexec/podman/gvproxy /usr/libexec/podman/virtiofsd; do
        grep -qF "${helper}" bootc/modules/base.sh
    done
    grep -qF 'dnf5 -y install "${base_packages[@]}"' bootc/modules/base.sh
    grep -qF 'dnf5 -y --setopt=install_weak_deps=False install "${base_qemu_packages[@]}" "${base_vm_packages[@]}"' bootc/modules/base.sh
    test -f bootc/config/independently-managed-rpms.list
    grep -Eq '^tailscale-stable[[:space:]]+tailscale$' bootc/config/independently-managed-rpms.list
    grep -Eq '^terra[[:space:]]+espanso-wayland$' bootc/config/independently-managed-rpms.list
    test -f bootc/lib/independently-managed-rpms.sh
    grep -qF 'purplefin_load_independently_managed_rpms' bootc/lib/finalize-profile.sh
    grep -qF 'upgrade "${installed_independently_managed_rpms[@]}"' bootc/lib/finalize-profile.sh
    test ! -e bootc/install-nextcloud-appimage.sh
    ! grep -qF 'install-nextcloud-appimage' bootc/modules/base.sh
    ! grep -qF '/usr/bin/nextcloud' bootc/modules/base.sh

    # Bitwarden remains common rather than belonging to a role or hardware profile.
    test ! -e bootc/overlays/base/files/usr/libexec/purplefin/install-bitwarden-cli-native
    test ! -e bootc/overlays/base/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-layer
    test -x bootc/overlays/base/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    grep -qF 'rpm -q bitwarden' bootc/overlays/base/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    grep -qF 'run_rpm_ostree uninstall bitwarden' bootc/overlays/base/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/05-bitwarden-desktop-flatpak-migration
    test ! -e bootc/overlays/base/files/usr/libexec/purplefin/update-bitwarden-flatpak
    test ! -e bootc/overlays/base/files/usr/lib/systemd/system/purplefin-bitwarden-flatpak-update.service
    test ! -e bootc/overlays/base/files/usr/lib/systemd/system/purplefin-bitwarden-flatpak-update.timer
    ! grep -qF 'purplefin-bitwarden-flatpak-update' bootc/modules/base.sh
    test -f bootc/overlays/base/files/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
    grep -qF '<action id="com.bitwarden.Bitwarden.unlock">' bootc/overlays/base/files/usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
    test -x bootc/packages/bitwarden-cli/install.sh
    test ! -e bootc/packages/bitwarden-cli/update.sh
    test ! -e .github/workflows/update-bitwarden-cli.yml
    test -f bootc/packages/bitwarden-cli/package.spec
    test -f bootc/packages/bitwarden-cli/package.env
    grep -qE '^BITWARDEN_CLI_VERSION=[0-9]+(\.[0-9]+)+$' bootc/packages/bitwarden-cli/package.env
    grep -qE '^BITWARDEN_CLI_SHA256=[0-9a-f]{64}$' bootc/packages/bitwarden-cli/package.env
    grep -qF 'github.com/bitwarden/clients/releases/download/cli-v${cli_version}/bw-linux-${cli_version}.zip' bootc/packages/bitwarden-cli/install.sh
    grep -qF 'sha256sum --check --strict' bootc/packages/bitwarden-cli/install.sh
    ! grep -qF 'https://vault.bitwarden.com/download/?app=cli&platform=linux' bootc/packages/bitwarden-cli/install.sh
    grep -qF 'rpmbuild -bb' bootc/packages/bitwarden-cli/install.sh
    grep -qF 'Name:           purplefin-bitwarden-cli' bootc/packages/bitwarden-cli/package.spec
    grep -qF '%global __os_install_post %{nil}' bootc/packages/bitwarden-cli/package.spec
    grep -qF 'packages/bitwarden-cli/install.sh' bootc/modules/base.sh
    grep -qF 'rpm -q purplefin-bitwarden-cli' bootc/modules/base.sh
    grep -qF "rpm -qf --qf '%{NAME}\\n' /usr/bin/bw" bootc/modules/base.sh
    grep -qF '### Migrating Bitwarden from the layered RPM' README.md

    # Support owns Espanso and RustConn and references the shared devops component.
    support_role=bootc/modules/support.sh
    support_root=bootc/overlays/roles/support
    grep -qF 'components/devops/apply.sh' "${support_role}"
    grep -qF 'purplefin_apply_role_overlay support' "${support_role}"
    grep -qF 'install espanso-wayland' "${support_role}"
    grep -qF 'setcap "cap_dac_override+p" "$(command -v espanso)"' "${support_role}"
    grep -qF 'systemctl --global enable espanso.service' "${support_role}"
    test -f "${support_root}/manifests/flatpaks.preinstall"
    grep -qF '[Flatpak Preinstall io.github.totoshko88.RustConn]' "${support_root}/manifests/flatpaks.preinstall"
    ! grep -qF '[Flatpak Preinstall com.vscodium.codium]' "${support_root}/manifests/flatpaks.preinstall"
    test -f "${support_root}/files/usr/lib/systemd/user/espanso.service"
    espanso_unit="${support_root}/files/usr/lib/systemd/user/espanso.service"
    grep -qxF 'After=graphical-session.target' "${espanso_unit}"
    grep -qxF 'PartOf=graphical-session.target' "${espanso_unit}"
    grep -qxF 'ExecStart=/usr/bin/espanso launcher' "${espanso_unit}"
    grep -qxF 'WantedBy=graphical-session.target' "${espanso_unit}"
    ! grep -qxF 'WantedBy=default.target' "${espanso_unit}"
    test ! -e bootc/overlays/base/files/usr/lib/systemd/user/espanso.service
    ! rg -q 'pam-u2f|pamu2fcfg|libfido2|opensc|pcsc-lite|pcscd|yubikey-manager|with-fingerprint|with-pam-u2f' bootc/modules/{developer,executive,it,sales,support,trainer}.sh

    # Every hardware selection receives the same biometric, security-key, and
    # smart-card baseline as part of its hardware phase.
    hardware_security=bootc/lib/hardware-security.sh
    test -f "${hardware_security}"
    grep -qF 'lib/hardware-security.sh' bootc/modules/hardware-generic-x86_64.sh
    grep -qF 'purplefin_apply_hardware_security' bootc/modules/hardware-generic-x86_64.sh
    for package in fprintd fprintd-pam libfprint pam-u2f pamu2fcfg libfido2 opensc pcsc-lite yubikey-manager; do
        grep -qE "^[[:space:]]*${package}$" "${hardware_security}"
    done
    grep -qF 'purplefin_authselect_request with-fingerprint with-pam-u2f' "${hardware_security}"
    grep -qF 'systemctl enable pcscd.socket' "${hardware_security}"
    ! rg -q 'dnf5 -y install fprintd libfprint|pam-u2f|pamu2fcfg|libfido2|opensc|pcsc-lite|pcscd|yubikey-manager|with-fingerprint|with-pam-u2f' \
        bootc/overlays/hardware/dell-xps-9350-intel/configure.sh

    # Devops is a reusable component referenced by support and development.
    development_role=bootc/modules/developer.sh
    devops_component=bootc/components/devops/apply.sh
    devops_root=bootc/components/devops
    devops_rpms="${devops_root}/manifests/rpms.list"
    test -x "${devops_component}"
    grep -qF 'components/devops/apply.sh' "${support_role}"
    grep -qF 'components/devops/apply.sh' "${development_role}"
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
    ghostty_skel="${devops_root}/files/etc/skel/.config/ghostty/config.ghostty"
    ghostty_shared="${devops_root}/files/usr/share/purplefin/ghostty/config.ghostty"
    test -f "${ghostty_skel}"
    test -f "${ghostty_shared}"
    cmp -s "${ghostty_skel}" "${ghostty_shared}"
    grep -qx 'copy-on-select = clipboard' "${ghostty_skel}"
    grep -qx 'right-click-action = paste' "${ghostty_skel}"
    grep -qx 'command = /usr/bin/zsh' "${ghostty_skel}"
    test -x "${devops_root}/files/usr/libexec/purplefin/install-ghostty-defaults"
    test -f "${devops_root}/files/usr/lib/systemd/user/purplefin-ghostty-defaults.service"
    zsh_shared="${devops_root}/files/usr/share/purplefin/zsh"
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
    zsh_installer="${devops_root}/files/usr/libexec/purplefin/install-zsh-defaults"
    zsh_configurer="${devops_root}/files/usr/libexec/purplefin/configure-zsh-defaults"
    zsh_service="${devops_root}/files/usr/lib/systemd/user/purplefin-zsh-defaults.service"
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

    hashicorp_repo="${devops_root}/files/etc/yum.repos.d/hashicorp.repo"
    test -f "${hashicorp_repo}"
    grep -qx '\[hashicorp\]' "${hashicorp_repo}"
    grep -qx 'baseurl=https://rpm.releases.hashicorp.com/fedora/\$releasever/\$basearch/stable' "${hashicorp_repo}"
    grep -qx 'gpgkey=https://rpm.releases.hashicorp.com/gpg' "${hashicorp_repo}"
    test -f "${devops_root}/files/usr/lib/tmpfiles.d/purplefin-openbao.conf"
    grep -qx 'd /var/lib/openbao 0700 openbao openbao - -' "${devops_root}/files/usr/lib/tmpfiles.d/purplefin-openbao.conf"
    ! rg -q 'dnf5.*(ghostty|ansible|packer|opentofu|openbao)|com\.vscodium\.codium' bootc/modules bootc/overlays/roles

    # Reapplying the component is a no-op, including across subprocesses.
    devops_state="${tmpdir}/devops-component-state"
    install -d "${devops_state}"
    touch "${devops_state}/devops.applied"
    component_output="$(
        PURPLEFIN_BUILD_ROOT="${PWD}/bootc" \
        PURPLEFIN_COMPONENT_STATE_DIR="${devops_state}" \
        "${devops_component}"
    )"
    test "${component_output}" = ':: Devops component already applied'

    test ! -e bootc/overlays/base/files/etc/skel/.config/ghostty/config.ghostty
    test ! -e bootc/overlays/base/files/etc/yum.repos.d/hashicorp.repo
    grep -qx 'excludepkgs=bitwarden\*' bootc/overlays/base/files/etc/yum.repos.d/terra.repo

    overlay_common=bootc/lib/overlay.sh
    grep -qF 'cp -a "${system_root}/." /' "${overlay_common}"
    grep -qF 'purplefin_apply_overlay roles "${role}" "purplefin-${role}"' "${overlay_common}"
    grep -qF 'component_root="${build_root}/components/${component}"' "${overlay_common}"
    grep -qF '/usr/share/flatpak/preinstall.d/${manifest_name}.preinstall' "${overlay_common}"

    # Bluefin's Tailscale integration is preserved while its RPM is updated independently.
    grep -qF 'tailscale-stable' bootc/config/independently-managed-rpms.list
    grep -qF 'espanso-wayland' bootc/config/independently-managed-rpms.list
    grep -qF 'independently_managed_rpm_repo_args' bootc/build/plan.sh
    test -f bootc/overlays/base/files/usr/share/plymouth/themes/spinner/watermark.png
    test -f bootc/overlays/base/files/usr/share/plymouth/themes/spinner/silverblue-watermark.png
    test -f bootc/overlays/base/files/usr/share/pixmaps/fedora-gdm-logo.png
    file bootc/overlays/base/files/usr/share/plymouth/themes/spinner/watermark.png | grep -q 'PNG image data, 149 x 43'
    file bootc/overlays/base/files/usr/share/plymouth/themes/spinner/silverblue-watermark.png | grep -q 'PNG image data, 149 x 43'
    file bootc/overlays/base/files/usr/share/pixmaps/fedora-gdm-logo.png | grep -q 'PNG image data, 150 x 61'
    cmp -s bootc/overlays/base/files/usr/share/plymouth/themes/spinner/watermark.png bootc/overlays/base/files/usr/share/plymouth/themes/spinner/silverblue-watermark.png
    for logo in bluefin chicken dolly karl; do
        test -f "bootc/overlays/base/files/usr/share/ublue-os/bluefin-logos/${logo}.png"
        file "bootc/overlays/base/files/usr/share/ublue-os/bluefin-logos/${logo}.png" | grep -q 'PNG image data, 1000 x 1000'
        cmp -s "bootc/overlays/base/files/usr/share/ublue-os/bluefin-logos/${logo}.png" bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    done
    ! grep -qF 'PURPLEFIN_DELL_IPU7_KERNEL_EVR' Containerfile
    ! grep -qF 'PURPLEFIN_DELL_MAINLINE_KERNEL_EVR' Containerfile
    ! grep -qF 'PURPLEFIN_OSTREE_LINUX' Containerfile Containerfile.derived
    ! grep -qF 'LABEL ostree.linux=' Containerfile Containerfile.derived
    test ! -e bootc/build/select-kernel.sh
    test "$(jq length bootc/generated/image-matrix.json)" -eq 12
    while IFS= read -r entry; do
        build_input="$(jq -r '.build_input' <<<"${entry}")"
        [[ "${build_input}" =~ ^[0-9a-f]{64}$ ]]
    done < <(jq -c '.[]' bootc/generated/image-matrix.json)
    ci_matrix="$(jq -r '.[] | [.profile, .stage, (.parent // "root"), .tags] | join("|")' bootc/generated/image-matrix.json)"
    test "${ci_matrix}" = "$(printf '%s\n' \
        'base|root|root|base' \
        'base-generic|hardware|base|generic-x86_64 latest base-generic-x86_64' \
        'base-dell-xps-9350-intel|hardware|base|base-dell-xps-9350-intel' \
        'sales-generic|role|base-generic|sales-generic' \
        'sales-dell-xps-9350-intel|role|base-dell-xps-9350-intel|sales-dell-xps-9350-intel' \
        'support-generic|role|base-generic|support-generic' \
        'support-dell-xps-9350-intel|role|base-dell-xps-9350-intel|support-dell-xps-9350-intel' \
        'dale|role|base-dell-xps-9350-intel|dale dell-xps-9350-intel' \
        'developer-generic|role|base-generic|developer-generic' \
        'trainer-generic|role|base-generic|trainer-generic' \
        'executive-generic|role|base-generic|executive-generic' \
        'it-generic|role|base-generic|it-generic')"
    test -f bootc/generated/profile-catalog.json
    test "$(jq -r '.upstream.image + ":" + .upstream.tag' bootc/generated/profile-catalog.json)" = 'ghcr.io/projectbluefin/bluefin:stable'
    test "$(jq -r '.profiles.dale.deltaModules | join(" ")' bootc/generated/profile-catalog.json)" = 'sales trainer support'
    test -f installer/config/profiles/dale.toml
    grep -qF 'mountpoint = "/"' installer/config/profiles/dale.toml
    test -x bootc/build/derived.sh
    test -f Containerfile.derived
    tests/derived-profile-build.sh
    ! grep -qF 'base-kernel:' .github/workflows/build.yml .github/workflows/build-profile.yml
    ! grep -qF 'ostree.linux=' .github/workflows/build-profile.yml
    grep -qF 'uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1' .github/workflows/build.yml
    grep -qF 'DeterminateSystems/flake-checker-action@de924abd783455e8429c858962b9e43062d19da1 # v13' .github/workflows/build.yml
    grep -qF 'bootc/build/plan.sh' .github/workflows/build.yml
    grep -qF 'org.opencontainers.image.base.digest=' .github/workflows/build-profile.yml
    grep -qF 'io.purplefin.build.input=' .github/workflows/build-profile.yml
    grep -qF 'io.purplefin.parent.digest=' .github/workflows/build-profile.yml
    grep -qF -- '--cache-from' .github/workflows/build-profile.yml
    grep -qF -- '--cache-to' .github/workflows/build-profile.yml
    grep -qF 'cache_ref="${IMAGE_REF}-build-cache"' .github/workflows/build-profile.yml
    grep -qF 'reference=${IMAGE_REF}-build-cache:*' .github/workflows/build-profile.yml
    grep -qF -- "--filter 'label=io.purplefin.build.profile'" .github/workflows/build-profile.yml
    grep -qF 'stage_ref=${IMAGE_REF}-stage-cache:' .github/workflows/build-profile.yml
    grep -qF 'sbom_repo=${IMAGE_REF}-sbom-cache' .github/workflows/build-profile.yml
    grep -qF 'remote_ref="${STAGE_REF}"' .github/workflows/build-profile.yml
    grep -qF 'output="docker://${remote_ref}"' .github/workflows/build-profile.yml
    grep -qF 'oras-project/setup-oras@1d808f7d7f6995cc68b7bf507bfe5c5446e1dc9d # v2.0.1' .github/workflows/build-profile.yml .github/workflows/release.yml
    grep -qF 'version: 1.3.3' .github/workflows/build-profile.yml .github/workflows/release.yml
    grep -qF 'syft-version: v1.51.0' .github/workflows/build-profile.yml
    grep -qF 'config: .github/syft.yaml' .github/workflows/build-profile.yml
    test -f .github/syft.yaml
    grep -qF 'TMPDIR:' .github/workflows/build-profile.yml
    grep -qF 'oras cp' .github/workflows/build-profile.yml
    grep -qF 'oras tag' .github/workflows/build-profile.yml .github/workflows/release.yml
    grep -qF -- '--artifact-type application/spdx+json' .github/workflows/build-profile.yml
    grep -qF 'io.purplefin.subject.digest=' .github/workflows/build-profile.yml
    ! grep -qF 'skopeo copy --all' .github/workflows/release.yml
    grep -qF -- '--draft' .github/workflows/release.yml
    grep -qF -- '--draft=false' .github/workflows/release.yml
    grep -qF 'inputs.runner' .github/workflows/build-profile.yml
    test -f .github/workflows/cache-warmer.yml
    grep -qF 'runs-on: purplefin-builder' .github/workflows/cache-warmer.yml
    grep -qF 'cache-only: true' .github/workflows/cache-warmer.yml
    grep -qF 'name: Warm rechunked $' .github/workflows/cache-warmer.yml
    grep -qF 'steps.image.outputs.ref' .github/workflows/build-profile.yml
    grep -qF 'steps.image.outputs.digest' .github/workflows/build-profile.yml
    grep -qF 'base-publish:' .github/workflows/build.yml
    grep -qF 'hardware-publish:' .github/workflows/build.yml
    grep -qF 'roles-publish:' .github/workflows/build.yml
    grep -qF 'DeterminateSystems/update-flake-lock@834c491b2ece4de0bbd00d85214bb5e83b4da5c6 # v28' .github/workflows/update-flake-lock.yml
    grep -qF 'DeterminateSystems/determinate-nix-action@61cbfe2efc2d4e7a8a6d56967c3c1058e846c858 # v3' .github/workflows/build.yml
    ! rg -q 'DeterminateSystems/nix-installer-action|DeterminateSystems/magic-nix-cache-action' .github/workflows
    grep -qF 'den.url = "github:denful/den";' flake.nix
    grep -qF 'den.aspects.profiles' nix/flake-modules/profiles.nix
    test ! -e bootc/profile-build-input.sh
    tests/image-build-planner.sh
    grep -qF 'buildah bud' .github/workflows/build-profile.yml
    grep -qF 'podman login' .github/workflows/build-profile.yml
    ! grep -qF 'podman push' .github/workflows/build-profile.yml
    grep -qF 'REGISTRY_AUTH_FILE=' .github/workflows/build-profile.yml
    ! rg -q 'ghcr.io/ublue-os/bluefin(:|\b)' Containerfile README.md Justfile .github/workflows
    ! rg -q 'actions/checkout@v4|redhat-actions/(buildah-build|podman-login|push-to-registry)' .github/workflows
    ! rg -q 'bootc-image-builder|--type bootc-installer|anaconda-iso' .github installer
    grep -qF 'bootc-generic-iso' .github/workflows/build-installer.yml
    grep -qF 'ghcr.io/osbuild/image-builder-cli@sha256:' .github/workflows/build-installer.yml
    test -z "$(find bootc/modules -maxdepth 1 -name 'legacy-*' -print -quit)"
    test -z "$(find bootc -maxdepth 2 \( -name '*no-ipu7*' -o -name 'desktop-x86_64.sh' -o -name 'lenovo-generic.sh' \) -print -quit)"
    ! grep -qF 'dracut --force "${kernel_modules_dir}/initramfs.img" "${kernel_version}"' bootc/build/full.sh
    grep -qF 'rm -f /boot/symvers-*.xz' bootc/lib/finalize-profile.sh
    grep -qF '/var/lib/rpm-state' bootc/lib/finalize-profile.sh
    grep -qF '/var/log/dnf5.log*' bootc/lib/finalize-profile.sh
    grep -qF 'installed_kernel_releases' bootc/lib/finalize-profile.sh
    test -x bootc/overlays/base/files/usr/libexec/purplefin/run-firstboot-rpm-ostree
    test -z "$(find bootc/overlays/base/files -iname '*ipu7*' -print -quit)"
    test -z "$(find bootc -iname '*librepods*' -print -quit)"
    ! rg -qi 'librepods' README.md bootc
    test -f bootc/lib/dell-xps-9350-common.sh
    grep -qF 'lib/dell-xps-9350-common.sh' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'purplefin_configure_dell_xps_9350_common' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/etc/plymouth
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/20-dell-ipu7-stable-kernel
    xps_profile_root=bootc/overlays/hardware/dell-xps-9350-intel/files
    xps_common_profile=bootc/lib/dell-xps-9350-common.sh
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
    ! rg -q 'purplefin-dell-lid-auth|dell-lid-is-open' bootc/overlays/base/files bootc/overlays/roles bootc/components
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
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/dell-ipu7-activate
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/dell-ipu7-rebind-sensor
    test -x bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.service
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path
    test -L bootc/overlays/hardware/dell-xps-9350-intel/files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.service
    test "$(readlink bootc/overlays/hardware/dell-xps-9350-intel/files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.service)" = '../../../../usr/lib/systemd/user/purplefin-firefox-pipewire-camera.service'
    test -L bootc/overlays/hardware/dell-xps-9350-intel/files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.path
    test "$(readlink bootc/overlays/hardware/dell-xps-9350-intel/files/etc/systemd/user/default.target.wants/purplefin-firefox-pipewire-camera.path)" = '../../../../usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path'
    grep -qF 'PathChanged=%h/.var/app/org.mozilla.firefox/config/mozilla/firefox/profiles.ini' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/systemd/user/purplefin-firefox-pipewire-camera.path
    firefox_test_root="${tmpdir}/firefox-profiles"
    install -d "${firefox_test_root}/Profile With Spaces"
    printf '%s\n' '[Profile0]' 'Path=Profile With Spaces' > "${firefox_test_root}/profiles.ini"
    printf '%s\n' 'user_pref("example.preserved", true);' 'user_pref("media.webrtc.camera.allow-pipewire", false);' > "${firefox_test_root}/Profile With Spaces/user.js"
    PURPLEFIN_FIREFOX_PROFILE_ROOT="${firefox_test_root}" bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    PURPLEFIN_FIREFOX_PROFILE_ROOT="${firefox_test_root}" bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/configure-firefox-pipewire-camera
    grep -qF 'user_pref("example.preserved", true);' "${firefox_test_root}/Profile With Spaces/user.js"
    test "$(grep -cF 'user_pref("media.webrtc.camera.allow-pipewire", true);' "${firefox_test_root}/Profile With Spaces/user.js")" = 1
    test "$(grep -cF '// Purplefin: expose the IPU7 libcamera source instead of raw V4L2 nodes.' "${firefox_test_root}/Profile With Spaces/user.js")" = 1
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/lib/dell-ipu7.sh
    grep -qF 'installed_kernel_core_record' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    ! grep -qF 'PURPLEFIN_OSTREE_LINUX' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    ! grep -Eq 'kernel-vanilla|mainline-kernel|remove_non_ipu7_runtime_kernels|validate_in_tree_cvs_module' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'purplefin_dell_ipu7_fix_pack_ref' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'CONFIG_CC_IS_CLANG=y' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'CONFIG_CC_IS_GCC=y' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'svp7500_make_args=(CC=gcc)' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'intel-cvs-1.0 intel_cvs.ko' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'ipu-bridge-patched-1.0 ipu-bridge.ko' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'hm1092-1.0 hm1092.ko' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'purplefin_dell_ipu7_int3472_patch_needed' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF -- '--rebuild "${initramfs_path}"' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    ! grep -qF -- '--no-hostonly' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF -- '--add-drivers "${initramfs_modules[*]}"' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'ipu7_firmware_path="$(purplefin_dell_ipu7_find_firmware)"' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF -- '--install "${ipu7_firmware_path}"' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF '$NF == firmware { found = 1 } END { exit !found }' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'Rebuilt initramfs does not contain Dell IPU7 firmware ${ipu7_firmware_path}' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    for module in ostree dmsquash-live dmsquash-live-autooverlay; do
        grep -qE "^[[:space:]]*${module}$" bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    done
    grep -qF 'Rebuilt initramfs lost required boot module ${module}' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'dnf5 -y remove --no-autoremove' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    for package in libcamera libcamera-ipa libcamera-tools pipewire-plugin-libcamera; do
        grep -qE "^[[:space:]]*${package}$" bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    done
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/systemd/system/purplefin-dell-ipu7-camera.service
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/udev/rules.d/99-purplefin-dell-ipu7-camera.rules
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/modprobe.d/purplefin-dell-ipu7.conf
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/modules-load.d/purplefin-dell-ipu7.conf
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/udev/rules.d/99-purplefin-svp7500-no-autosuspend.rules
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/udev/rules.d/99-purplefin-hm1092-ir-led.rules
    grep -qF 'ATTRS{idVendor}=="06cb"' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/udev/rules.d/99-purplefin-svp7500-no-autosuspend.rules
    grep -qF 'KERNEL=="*ir_flood_led*"' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/udev/rules.d/99-purplefin-hm1092-ir-led.rules
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'monitor.v4l2.rules' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.description = "ipu7"' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'monitor.libcamera.rules' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.description = "hm1092"' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'device.disabled = true' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'node.nick = "hm1092"' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    grep -qF 'node.disabled = true' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf
    spa-json-dump bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/wireplumber/wireplumber.conf.d/50-purplefin-dell-ipu7.conf >/dev/null
    ov02c10_tuning=bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/libcamera/ipa/simple/ov02c10.yaml
    test -f "${ov02c10_tuning}"
    grep -qF 'blackLevel: 4096' "${ov02c10_tuning}"
    grep -qF -- '- Ccm:' "${ov02c10_tuning}"
    grep -qF '0.0, 0.9, 0.0' "${ov02c10_tuning}"
    test -x bootc/overlays/hardware/dell-xps-9350-intel/build/install-libcamera-ov02c10-ipa.sh
    test -f bootc/overlays/hardware/dell-xps-9350-intel/build/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'REGISTER_CAMERA_SENSOR_HELPER("ov02c10", CameraSensorHelperOv02c10)' bootc/overlays/hardware/dell-xps-9350-intel/build/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'gain_ = AnalogueGainLinear{ 1, 0, 0, 16 };' bootc/overlays/hardware/dell-xps-9350-intel/build/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'blackLevel_ = 4096;' bootc/overlays/hardware/dell-xps-9350-intel/build/0001-libipa-add-ov02c10-helper.patch
    grep -qF 'source_sha256="27a6d776bb728bb8bd38c4594ff3ab7fadfce19583427de8442963ef2fe5ad04"' bootc/overlays/hardware/dell-xps-9350-intel/build/install-libcamera-ov02c10-ipa.sh
    grep -qF -- '-Dwerror=false' bootc/overlays/hardware/dell-xps-9350-intel/build/install-libcamera-ov02c10-ipa.sh
    grep -qF 'build/install-libcamera-ov02c10-ipa.sh' bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/etc/libcamera/configuration.yaml
    grep -qF -- '- /usr/lib64/libcamera/ipa-purplefin' bootc/overlays/hardware/dell-xps-9350-intel/files/etc/libcamera/configuration.yaml
    test ! -e bootc/overlays/hardware/generic-x86_64/files/etc/libcamera/configuration.yaml
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
        test ! -e "bootc/overlays/hardware/dell-xps-9350-intel/files/${obsolete}"
    done
    ! rg -q 'kernel-evr.denylist|7.1.2-355.vanilla.fc44|CONFIG_VIDEO_INTEL_CVS' bootc/overlays/hardware/dell-xps-9350-intel/files bootc/overlays/hardware/dell-xps-9350-intel/configure.sh
    grep -qF 'e4c95452339b2d9803974a899c4f2da6e143891d' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/lib/dell-ipu7.sh
    test ! -e bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/firstboot-rpm-ostree.d/50-dell-vates-plymouth-initramfs
    test -x bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/install-refind-theme
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/lib/systemd/system/purplefin-refind-theme.service
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_fedora.png
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/fonts/source-code-pro-extralight-14.png
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_win11.png
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_windows.png
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png
    test -f bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    cmp -s bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_purplefin.png
    cmp -s bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_fedora.png
    cmp -s bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_bluefin.png bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons/os_linux.png
    unexpected_refind_distro_icon="$(find bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/icons -type f -name 'os_*.png' ! -path '*/icons/os_win.png' ! -path '*/icons/os_win8.png' ! -path '*/icons/os_win11.png' ! -path '*/icons/os_windows.png' ! -path '*/icons/os_bluefin.png' ! -path '*/icons/os_purplefin.png' ! -path '*/icons/os_fedora.png' ! -path '*/icons/os_linux.png' -print -quit)"
    test -z "${unexpected_refind_distro_icon}"
    grep -qx 'icons_dir themes/rEFInd-Regular-Dark/icons' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf
    ! grep -q '^menuentry ' bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark/theme.conf

    # shellcheck source=/dev/null
    source bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/lib/dell-ipu7.sh
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

    refind_installer="bootc/overlays/hardware/dell-xps-9350-intel/files/usr/libexec/purplefin/install-refind-theme"
    refind_theme_source="bootc/overlays/hardware/dell-xps-9350-intel/files/usr/share/purplefin/refind/themes/rEFInd-Regular-Dark"
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
    base_digest="$(skopeo inspect --retry-times 3 "docker://${base_image}" | jq -er .Digest)"
    podman build \
        --pull=missing \
        --build-arg BASE_REF="ghcr.io/projectbluefin/bluefin@${base_digest}" \
        --build-arg BUILD_PROFILE='{{ profile }}' \
        --build-arg PURPLEFIN_VERSION="$(<VERSION)" \
        --label "org.opencontainers.image.base.digest=${base_digest}" \
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
