#!/usr/bin/bash
set -euo pipefail

variant_dir=/tmp/src/finite
logo="${variant_dir}/finite-logo.png"
installer_app_id=org.bootcinstaller.Installer

install -Dm0644 "${variant_dir}/iso.yaml" /usr/lib/image-builder/bootc/iso.yaml
install -Dm0644 "${variant_dir}/bootc-install-defaults.toml" \
	/usr/lib/bootc/install/00-defaults.toml
install -Dm0644 "${logo}" /usr/share/pixmaps/finite.png
install -Dm0644 "${logo}" /usr/share/bootc-installer/images/finite-logo.png
for size in 16 24 32 48 64 128 256 512; do
	install -Dm0644 "${logo}" \
		"/usr/share/icons/hicolor/${size}x${size}/apps/finite.png"
done
gtk-update-icon-cache /usr/share/icons/hicolor || true

cat >/usr/local/bin/finite-installer-launch <<'EOF'
#!/usr/bin/bash
set -euo pipefail

app_id=org.bootcinstaller.Installer
recipe=/run/host/etc/bootc-installer/recipe.json
command=(flatpak run --env="BOOTC_CUSTOM_RECIPE=${recipe}" "${app_id}")
if ! grep -qw 'finite.installer.autoinstall=1' /proc/cmdline; then
	exec "${command[@]}"
fi

command+=(--autoinstall /run/host/etc/bootc-installer/ci-autoinstall.json)
installer_log="${HOME}/.var/app/${app_id}/cache/bootc-installer/installer-debug.log"
install -d -m 0755 "$(dirname "${installer_log}")"
rm -f "${installer_log}"

# bootc-installer intentionally remains open on its Done screen.  Treat its
# own result log as the unattended completion contract instead of waiting for
# flatpak run to exit, which would leave CI at the live login screen forever.
"${command[@]}" &
installer_pid=$!
sudo tail --pid="${installer_pid}" --retry -n +1 -F "${installer_log}" \
	>/dev/ttyS0 2>&1 &
log_tail_pid=$!
result=
while kill -0 "${installer_pid}" >/dev/null 2>&1; do
	if grep -Fq 'Installation complete!' "${installer_log}" 2>/dev/null; then
		result=complete
		break
	fi
	if grep -Fq 'Installation failed!' "${installer_log}" 2>/dev/null; then
		result=failed
		break
	fi
	sleep 1
done

if [[ -z "${result}" ]]; then
	set +e
	wait "${installer_pid}"
	installer_status=$?
	set -e
	printf 'FINITE_INSTALLER_ERROR=bootc-installer exited-before-result status=%s\n' "${installer_status}" |
		sudo tee /dev/ttyS0 >/dev/null
	status=1
else
	flatpak kill "${app_id}" >/dev/null 2>&1 || kill -TERM "${installer_pid}" >/dev/null 2>&1 || true
	wait "${installer_pid}" >/dev/null 2>&1 || true
	if [[ "${result}" == complete ]]; then
		sudo /usr/local/sbin/finite-ci-post-install
		printf 'FINITE_INSTALLER_COMPLETE=1\n' | sudo tee /dev/ttyS0 >/dev/null
		status=0
	else
		printf 'FINITE_INSTALLER_ERROR=bootc-installer reported-failure\n' |
			sudo tee /dev/ttyS0 >/dev/null
		status=1
	fi
fi
kill -TERM "${log_tail_pid}" >/dev/null 2>&1 || true
wait "${log_tail_pid}" >/dev/null 2>&1 || true
sudo systemctl poweroff
exit "${status}"
EOF
chmod 0755 /usr/local/bin/finite-installer-launch

install -d -m 0755 /usr/local/sbin
cat >/usr/local/sbin/finite-ci-post-install <<'EOF'
#!/usr/bin/bash
set -euo pipefail

work_root=/run/finite-ci-target
boot_root="${work_root}/boot"
system_root="${work_root}/system"
install -d -m 0755 "${boot_root}" "${system_root}"
cleanup() {
	umount "${system_root}" >/dev/null 2>&1 || true
	umount "${boot_root}" >/dev/null 2>&1 || true
	rmdir "${system_root}" "${boot_root}" "${work_root}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

mount /dev/vda2 "${boot_root}"
for entry in "${boot_root}"/loader/entries/*.conf "${boot_root}"/EFI/loader/entries/*.conf; do
	[[ -f "${entry}" ]] || continue
	grep -qF 'console=ttyS0,115200n8' "${entry}" ||
		sed -i '/^options / s/$/ console=tty0 console=ttyS0,115200n8 systemd.journald.forward_to_console=yes/' "${entry}"
done

mount /dev/vda3 "${system_root}"
install -d -m 0755 \
	"${system_root}/etc/systemd/system" \
	"${system_root}/etc/systemd/system/multi-user.target.wants"
cat >"${system_root}/etc/systemd/system/finite-ci-installed-ready.service" <<'UNIT'
[Unit]
Description=Finite installed-system validation marker
After=systemd-user-sessions.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c 'status="$(/usr/bin/bootc status --json --format-version=1)"; printf "FINITE_BOOTC_STATUS=%%s\nFINITE_INSTALLED_READY=1\n" "$status"'
StandardOutput=tty
StandardError=tty
TTYPath=/dev/ttyS0

[Install]
WantedBy=multi-user.target
UNIT
ln -sfn ../finite-ci-installed-ready.service \
	"${system_root}/etc/systemd/system/multi-user.target.wants/finite-ci-installed-ready.service"
sync
EOF
chmod 0755 /usr/local/sbin/finite-ci-post-install

cat >/usr/share/applications/finite-installer.desktop <<EOF
[Desktop Entry]
Name=Finite Installer
Comment=Install Finite to your computer
Exec=/usr/local/bin/finite-installer-launch
Icon=finite
Terminal=false
Type=Application
Categories=GTK;System;Settings;
StartupNotify=true
X-Flatpak=${installer_app_id}
EOF

cat >/etc/xdg/autostart/tuna-installer.desktop <<'EOF'
[Desktop Entry]
Name=Finite Installer
Exec=/usr/local/bin/finite-installer-launch
Icon=finite
Type=Application
X-GNOME-Autostart-enabled=true
EOF

cat >/usr/lib/systemd/system/live-ready.service <<'EOF'
[Unit]
Description=Finite live installer ready marker
After=display-manager.service
Requires=display-manager.service

[Service]
Type=oneshot
ExecStart=/bin/echo FINITE_INSTALLER_READY=1
StandardOutput=tty
TTYPath=/dev/ttyS0

[Install]
WantedBy=multi-user.target
EOF
systemctl enable live-ready.service

printf 'f /etc/hostname 0644 - - - finite-live\n' \
	>/usr/lib/tmpfiles.d/live-hostname.conf
