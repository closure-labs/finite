#!/usr/bin/bash
set -euo pipefail

variant_dir=/tmp/src/finite
logo="${variant_dir}/finite-logo.png"
installer_app_id=org.bootcinstaller.Installer

install -Dm0644 "${variant_dir}/recipe.json" \
	/etc/bootc-installer/recipe.json
install -Dm0644 "${variant_dir}/ci-autoinstall.json" \
	/etc/bootc-installer/ci-autoinstall.json
# Dakota's upstream flag means "an offline payload is embedded" to
# bootc-installer. This ISO is intentionally a network installer.
rm -f \
	/etc/bootc-installer/live-iso-mode \
	/etc/xdg/autostart/tuna-installer.desktop
touch /etc/bootc-installer/finite-netinstall-mode
systemctl disable live-ready.service >/dev/null 2>&1 || true
systemctl mask bluefin-remove-installer.service >/dev/null 2>&1 || true
install -Dm0644 "${logo}" /usr/share/pixmaps/finite.png
install -Dm0644 "${logo}" /usr/share/bootc-installer/images/finite-logo.png
for size in 16 24 32 48 64 128 256 512; do
	install -Dm0644 "${logo}" \
		"/usr/share/icons/hicolor/${size}x${size}/apps/finite.png"
done
gtk-update-icon-cache /usr/share/icons/hicolor || true

install -d -m 0755 /usr/local/sbin
cat >/usr/local/sbin/finite-installer-apply-target <<'EOF'
#!/usr/bin/bash
set -euo pipefail

target_source=${1:-}
if [[ -z "${target_source}" ]]; then
	while IFS= read -r mountpoint; do
		candidate="${mountpoint}/finite/target.json"
		if [[ -s "${candidate}" ]]; then
			target_source=${candidate}
			break
		fi
	done < <(findmnt --raw --noheadings --types iso9660 --output TARGET)
fi
[[ -n "${target_source}" && -s "${target_source}" ]] || {
	echo 'Finite installer target configuration is missing from the ISO' >&2
	exit 1
}

install -d -m 0755 /run/finite-installer
install -m 0644 "${target_source}" /run/finite-installer/target.json
jq -e '
	.schema == 1 and
	(.payload_reference | test("^[a-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")) and
	(.payload_digest | test("^sha256:[0-9a-f]{64}$")) and
	(.update_reference | test("^[a-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$")) and
	((.payload_reference | split("@")[1]) == .payload_digest)
' /run/finite-installer/target.json >/dev/null

payload_reference="$(jq -er .payload_reference /run/finite-installer/target.json)"
update_reference="$(jq -er .update_reference /run/finite-installer/target.json)"
python3 - "${payload_reference}" "${update_reference}" <<'PY'
from pathlib import Path
import sys

payload, update = sys.argv[1:]
replacements = {"@@PAYLOAD_REFERENCE@@": payload, "@@UPDATE_REFERENCE@@": update}
for name in ("recipe.json", "ci-autoinstall.json", "images.json"):
    path = Path("/etc/bootc-installer") / name
    text = path.read_text()
    for old, new in replacements.items():
        text = text.replace(old, new)
    if "@@" in text:
        raise SystemExit(f"unresolved installer placeholder in {path}")
    temporary = path.with_suffix(path.suffix + ".finite-new")
    temporary.write_text(text)
    temporary.chmod(0o644)
    temporary.replace(path)
PY

jq -e --arg payload "${payload_reference}" --arg update "${update_reference}" '
	.image == $payload and
	.targetImgref == $update and
	.filesystem == "btrfs" and
	.bootloader == "grub2" and
	.composeFsBackend == false
' /etc/bootc-installer/ci-autoinstall.json >/dev/null
EOF
chmod 0755 /usr/local/sbin/finite-installer-apply-target

cat >/usr/local/sbin/finite-installer-preflight <<'EOF'
#!/usr/bin/bash
set -euo pipefail

mode=${1:-runtime}
recipe=${2:-/etc/bootc-installer/ci-autoinstall.json}
minimum_scratch_bytes=${FINITE_INSTALLER_MIN_SCRATCH_BYTES:-8589934592}
[[ "${minimum_scratch_bytes}" =~ ^[1-9][0-9]*$ ]]
[[ "${mode}" == runtime || "${mode}" == interactive || "${mode}" == assembly ]] || {
	echo "Unsupported Finite installer preflight mode: ${mode}" >&2
	exit 2
}

required_executables=(
	blkid
	btrfs
	bootc
	chroot
	efibootmgr
	findmnt
	fisherman
	getent
	jq
	lsblk
	mkfs.btrfs
	mkfs.ext4
	mkfs.fat
	mkfs.xfs
	mount
	partprobe
	podman
	sfdisk
	skopeo
	udevadm
	umount
	wipefs
	xfs_repair
)
missing=()
for executable in "${required_executables[@]}"; do
	command -v "${executable}" >/dev/null 2>&1 || missing+=("${executable}")
done
((${#missing[@]} == 0)) || {
	printf 'Finite installer preflight: missing executable(s): %s\n' "${missing[*]}" >&2
	exit 1
}
btrfs --version
mkfs.btrfs --version

payload_reference="$(jq -er '
	.image | select(test("^[a-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$"))
' "${recipe}")"
update_reference="$(jq -er '
	.targetImgref | select(test("^[a-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$"))
' "${recipe}")"
jq -e '
	.filesystem == "btrfs" and
	.bootloader == "grub2" and
	.composeFsBackend == false and
	.hostname == "finite"
' "${recipe}" >/dev/null

validation_recipe=${recipe}
temporary_recipe=
cleanup() {
	[[ -z "${temporary_recipe}" ]] || rm -f -- "${temporary_recipe}"
}
trap cleanup EXIT
if [[ "${mode}" != runtime ]]; then
	temporary_recipe="$(mktemp /var/tmp/finite-fisherman-preflight.XXXXXX.json)"
	jq '.disk = "/dev/null"' "${recipe}" >"${temporary_recipe}"
	validation_recipe=${temporary_recipe}
fi
fisherman validate "${validation_recipe}"

registry=${payload_reference%%/*}
getent ahosts "${registry}" >/dev/null
skopeo inspect --retry-times 3 "docker://${payload_reference}" >/dev/null

available_scratch_bytes="$(df --block-size=1 --output=avail /var/tmp | tail -n 1 | tr -d '[:space:]')"
[[ "${available_scratch_bytes}" =~ ^[0-9]+$ ]]
if ((available_scratch_bytes < minimum_scratch_bytes)); then
	printf 'Finite installer preflight: /var/tmp has %s bytes free; %s required\n' \
		"${available_scratch_bytes}" "${minimum_scratch_bytes}" >&2
	exit 1
fi

printf 'FINITE_INSTALLER_PREFLIGHT=ok mode=%s payload=%s update=%s scratch_bytes=%s\n' \
	"${mode}" "${payload_reference}" "${update_reference}" "${available_scratch_bytes}"
EOF
chmod 0755 /usr/local/sbin/finite-installer-preflight

cat >/usr/local/bin/finite-installer-launch <<'EOF'
#!/usr/bin/bash
set -euo pipefail

app_id=org.bootcinstaller.Installer
recipe=/run/host/etc/bootc-installer/recipe.json
installer_log="${HOME}/.var/app/${app_id}/cache/bootc-installer/installer-debug.log"
recipe_log="${HOME}/.cache/finite-installer/finite-installer.log"
fisherman_log="${HOME}/.cache/bootc-installer/fisherman-output.log"
preflight_log="${HOME}/.cache/bootc-installer/preflight.log"
autoinstall_host="${HOME}/.cache/finite-installer/ci-autoinstall.json"
autoinstall_sandbox="${HOME}/.cache/finite-installer/ci-autoinstall.json"
activation_marker='Installer::Main INFO: do_activate called'
activation_timeout_seconds=60
serial=/dev/ttyS0
command=(
	flatpak run
	--env=BOOTC_INSTALLER_DEBUG=1
	--env="BOOTC_CUSTOM_RECIPE=${recipe}"
	"${app_id}"
)
unattended=false
source_manifest_digest=
if grep -qw 'finite.installer.autoinstall=1' /proc/cmdline; then
	unattended=true
fi

install -d -m 0755 \
	"$(dirname "${installer_log}")" \
	"$(dirname "${recipe_log}")" \
	"$(dirname "${fisherman_log}")"
rm -f \
	"${installer_log}" \
	"${recipe_log}" \
	"${fisherman_log}" \
	"${preflight_log}" \
	"${autoinstall_host}"
: >"${installer_log}"
: >"${recipe_log}"
: >"${fisherman_log}"
if [[ "${unattended}" == true ]]; then
	# The installer Flatpak has host filesystem access and launches Fisherman
	# on the host with this same absolute path. Keep the writable one-shot
	# recipe outside both Flatpak's private XDG cache and bootc-installer's own
	# cache so both processes see it until upstream securely removes it.
	install -m 0644 \
		/etc/bootc-installer/ci-autoinstall.json "${autoinstall_host}"
	command+=(--autoinstall "${autoinstall_sandbox}")
fi

emit_marker() {
	printf '%s\n' "$1" | sudo tee "${serial}" >/dev/null
}

stop_installer() {
	[[ -n "${installer_pid:-}" ]] || return 0
	flatpak kill "${app_id}" >/dev/null 2>&1 ||
		kill -TERM "${installer_pid}" >/dev/null 2>&1 || true
	wait "${installer_pid}" >/dev/null 2>&1 || true
}

dump_guest_diagnostics() {
	local reason=$1 name path
	{
		echo "FINITE_DIAGNOSTICS_REASON=${reason}"
		for name in installer-debug.log finite-installer.log fisherman-output.log preflight.log; do
			case "${name}" in
				installer-debug.log) path=${installer_log} ;;
				finite-installer.log) path=${recipe_log} ;;
				fisherman-output.log) path=${fisherman_log} ;;
				preflight.log) path=${preflight_log} ;;
			esac
			echo "FINITE_DIAGNOSTIC_BEGIN=${name}"
			if [[ -f "${path}" ]]; then
				cat "${path}"
			else
				echo "Log was not created: ${path}"
			fi
			echo "FINITE_DIAGNOSTIC_END=${name}"
		done
		echo 'FINITE_DIAGNOSTIC_BEGIN=system-state.log'
		echo '--- lsblk ---'
		lsblk --fs --output-all || true
		echo '--- mounts ---'
		findmnt --real --output-all || true
		echo '--- disk space ---'
		df -hT || true
		echo '--- Podman storage ---'
		sudo podman system df || true
		echo '--- installer journals ---'
		sudo journalctl --boot --no-pager --lines 500 \
			--unit=finite-installer-bootstrap.service \
			--unit=finite-installer-target-config.service \
			--unit=gdm.service || true
		echo 'FINITE_DIAGNOSTIC_END=system-state.log'
	} | sudo tee "${serial}" >/dev/null
}

report_startup_error() {
	local error=$1
	stop_installer
	dump_guest_diagnostics "${error}"
	emit_marker "FINITE_INSTALLER_ERROR=${error}"
	if [[ "${unattended}" == true ]]; then
		sudo systemctl poweroff
	fi
	exit 1
}

if [[ "${unattended}" == true ]]; then
	scratch=/dev/vdb
	for _ in {1..30}; do
		[[ -b "${scratch}" ]] && break
		sleep 1
	done
	[[ -b "${scratch}" ]] || report_startup_error 'installer-scratch-disk-missing'
	sudo umount /var/tmp >/dev/null 2>&1 || true
	sudo mkfs.ext4 -F "${scratch}" || report_startup_error 'installer-scratch-format-failed'
	sudo mount "${scratch}" /var/tmp || report_startup_error 'installer-scratch-mount-failed'
	source_ref="$(
		jq -er '.image | select(test("@sha256:[0-9a-f]{64}$"))' \
			/etc/bootc-installer/ci-autoinstall.json
	)" || report_startup_error 'installer-source-reference-invalid'
	source_manifest_digest="${source_ref##*@}"
	[[ "${source_manifest_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] ||
		report_startup_error 'installer-source-digest-invalid'
	emit_marker "FINITE_INSTALLER_SOURCE_DIGEST=${source_manifest_digest}"
fi

preflight_mode=interactive
[[ "${unattended}" != true ]] || preflight_mode=runtime
if ! sudo /usr/local/sbin/finite-installer-preflight \
	"${preflight_mode}" /etc/bootc-installer/ci-autoinstall.json \
	> >(tee "${preflight_log}" | sudo tee "${serial}" >/dev/null) 2>&1; then
	report_startup_error 'installer-preflight-failed'
fi

"${command[@]}" &
installer_pid=$!
sudo /usr/bin/bash -c \
	'exec tail --pid="$1" --retry -n +1 -F "$2" "$3" "$4" >"$5" 2>&1' \
	-- "${installer_pid}" "${installer_log}" "${recipe_log}" \
	"${fisherman_log}" "${serial}" &
log_tail_pid=$!
cleanup() {
	kill -TERM "${log_tail_pid}" >/dev/null 2>&1 || true
	wait "${log_tail_pid}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

activation_deadline=$((SECONDS + activation_timeout_seconds))
while ! grep -Fq "${activation_marker}" "${installer_log}" 2>/dev/null; do
	if ! kill -0 "${installer_pid}" >/dev/null 2>&1; then
		set +e
		wait "${installer_pid}"
		installer_status=$?
		set -e
		report_startup_error "bootc-installer exited-before-activation status=${installer_status}"
	fi
	if ((SECONDS >= activation_deadline)); then
		if [[ -e "${installer_log}" ]]; then
			report_startup_error 'bootc-installer activation-timeout'
		else
			report_startup_error 'bootc-installer log-not-created'
		fi
	fi
	sleep 1
done
emit_marker 'FINITE_INSTALLER_READY=1'

if [[ "${unattended}" != true ]]; then
	set +e
	wait "${installer_pid}"
	installer_status=$?
	set -e
	if ((installer_status != 0)); then
		dump_guest_diagnostics "bootc-installer exited status=${installer_status}"
		emit_marker "FINITE_INSTALLER_ERROR=bootc-installer exited status=${installer_status}"
	fi
	exit "${installer_status}"
fi

# bootc-installer intentionally remains open on its Done screen. Treat its
# own result log as the unattended completion contract instead of waiting for
# flatpak run to exit, which would leave CI at the live login screen forever.
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
	dump_guest_diagnostics "bootc-installer exited-before-result status=${installer_status}"
	emit_marker "FINITE_INSTALLER_ERROR=bootc-installer exited-before-result status=${installer_status}"
	status=1
else
	stop_installer
	if [[ "${result}" == complete ]]; then
		if sudo /usr/local/sbin/finite-ci-post-install \
			> >(sudo tee "${serial}" >/dev/null) 2>&1; then
			dump_guest_diagnostics success
			emit_marker 'FINITE_INSTALLER_COMPLETE=1'
			status=0
		else
			dump_guest_diagnostics post-install-failed
			emit_marker 'FINITE_INSTALLER_ERROR=post-install-failed'
			status=1
		fi
	else
		dump_guest_diagnostics bootc-installer-reported-failure
		emit_marker 'FINITE_INSTALLER_ERROR=bootc-installer reported-failure'
		status=1
	fi
fi
sudo systemctl poweroff
exit "${status}"
EOF
chmod 0755 /usr/local/bin/finite-installer-launch

cat >/usr/local/sbin/finite-ci-post-install <<'EOF'
#!/usr/bin/bash
set -euo pipefail

work_root=/run/finite-ci-target
boot_root="${work_root}/boot"
system_root="${work_root}/system"
install -d -m 0755 "${boot_root}" "${system_root}"
cleanup() {
	[[ -z "${bound_var:-}" ]] || umount "${bound_var}" >/dev/null 2>&1 || true
	[[ -z "${file_contexts_tmp:-}" ]] || rm -f "${file_contexts_tmp}"
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
deployment_checksum=
mapfile -d '' deployment_roots < <(
	find "${system_root}/ostree/deploy" \
		-mindepth 3 -maxdepth 3 -type d \
		-path "${system_root}/ostree/deploy/*/deploy/*" -print0
)
((${#deployment_roots[@]} == 1)) || {
	printf 'Expected exactly one installed OSTree deployment; found %s\n' \
		"${#deployment_roots[@]}" >&2
	exit 1
}

for deployment_root in "${deployment_roots[@]}"; do
	deployment_name=${deployment_root##*/}
	[[ "${deployment_name}" =~ ^[0-9a-f]{64}\.[0-9]+$ ]] || {
		echo "Invalid installed OSTree deployment name: ${deployment_name}" >&2
		exit 1
	}
	deployment_checksum=${deployment_name%%.*}
	systemd_root="${deployment_root}/etc/systemd/system"
	policy_root="${deployment_root}/etc/selinux/targeted"
	contexts_root="${policy_root}/contexts/files"
	policy="${contexts_root}/file_contexts"
	home_policy="${contexts_root}/file_contexts.homedirs"
	local_policy="${contexts_root}/file_contexts.local"
	var_root="${deployment_root%/deploy/*}/var"
	[[ -s "${policy}" ]] || {
		echo "Installed SELinux file-context policy is missing: ${policy}" >&2
		exit 1
	}
	[[ -s "${home_policy}" ]] || {
		echo "Installed SELinux home-context policy is missing: ${home_policy}" >&2
		exit 1
	}
	mapfile -d '' policy_binaries < <(
		find "${policy_root}/policy" -maxdepth 1 -type f -name 'policy.*' -print0
	)
	((${#policy_binaries[@]} == 1)) || {
		printf 'Expected exactly one installed SELinux binary policy; found %s\n' \
			"${#policy_binaries[@]}" >&2
		exit 1
	}
	policy_binary=${policy_binaries[0]}
	policy_binary_chroot=${policy_binary#"${deployment_root}"}
	[[ -x "${deployment_root}/usr/bin/setfiles" ]] || {
		echo 'Installed SELinux setfiles executable is missing' >&2
		exit 1
	}
	file_contexts_tmp=$(mktemp "${contexts_root}/finite-ci-file-contexts.XXXXXX")
	file_contexts_chroot=${file_contexts_tmp#"${deployment_root}"}
	cat "${policy}" "${home_policy}" >"${file_contexts_tmp}"
	[[ ! -f "${local_policy}" ]] || cat "${local_policy}" >>"${file_contexts_tmp}"
	# Fisherman creates the target user through an offline chroot after bootc
	# deploys the image. The resulting account database and home directory do
	# not inherit the target policy labels, which prevents dbus-broker from
	# reading /etc/passwd on the first enforcing boot. restorecon intentionally
	# exits successfully when SELinux appears disabled, as it does inside a bare
	# deployment chroot without selinuxfs. Invoke the installed deployment's
	# setfiles name explicitly so it performs an offline relabel against that
	# deployment's own contexts and binary policy without requiring setfiles in
	# the smaller Dakota live root.
	# The stateful OSTree var tree lives outside the deployment, so bind it into
	# the alternate root while relabeling its home tree.
	install -d -m 0755 \
		"${systemd_root}" \
		"${systemd_root}/cloud-init.target.wants"
	cat >"${systemd_root}/finite-ci-installed-ready" <<'SCRIPT'
#!/usr/bin/bash
set -Eeuo pipefail

report_installed_error() {
	local status=$1 line=$2 unit
	trap - ERR
	set +e
	echo 'FINITE_INSTALLED_DIAGNOSTICS_BEGIN=1'
	printf 'failure_status=%s failure_line=%s\n' "${status}" "${line}"
	echo '--- failed units ---'
	systemctl --failed --no-pager
	echo '--- required unit status ---'
	for unit in \
		dbus.service \
		cloud-final.service \
		finite-nix-selinux.service \
		finite-nix-seed.service \
		nix.mount \
		nix-daemon.service \
		nix-daemon.socket \
		determinate-nixd.socket; do
		systemctl status --no-pager --lines 80 "${unit}"
	done
	echo '--- mounts ---'
	findmnt --real --output-all
	echo '--- SELinux contexts ---'
	getenforce
	ls -ldZ /etc /etc/passwd /etc/group /var/home /var/home/finiteci /nix
	echo '--- cloud-init ---'
	cloud-init status --long
	echo '--- journal ---'
	journalctl --boot --no-pager --lines 500
	echo 'FINITE_INSTALLED_DIAGNOSTICS_END=1'
	printf 'FINITE_INSTALLED_ERROR=status=%s line=%s\n' "${status}" "${line}"
	exit "${status}"
}
trap 'report_installed_error "$?" "${LINENO}"' ERR

status="$(/usr/bin/bootc status --json --format-version=1 | /usr/bin/jq -c .)"
hostname_value="$(hostname)"
sysroot_fstype="$(findmnt --noheadings --output FSTYPE /sysroot | tr -d '[:space:]')"
os_version="$(. /usr/lib/os-release; printf '%s' "${VERSION_ID}")"
grub2_ready=false
[[ -s /boot/grub2/grub.cfg ]] && grub2_ready=true
selinux_mode="$(getenforce)"
[[ "${selinux_mode}" == Enforcing ]]
# The currently published payload can enter an early-boot ordering cycle when
# its Nix sockets require /nix while sockets.target is ordered before the
# services that seed and mount it. Run after cloud-final has settled, then
# recover whichever Nix jobs systemd dropped while breaking that cycle. Newer
# payloads already have the corrected graph, so these starts are idempotent.
systemctl start nix.mount
# The published payload predates the persistent Nix file-context equivalence,
# so its seed restore labels the bind-mount backing tree as user home content.
# Register the standard SELinux path substitution and restore the complete
# tree before systemd needs to replace either persistent daemon socket.
if ! semanage fcontext -a -e /nix /var/home/nix 2>/dev/null; then
	semanage fcontext -m -e /nix /var/home/nix
fi
restorecon -RF /var/home/nix
# The legacy graph may have won the opposite side of the cycle and started the
# daemon directly while dropping both socket jobs. Stop that direct instance
# before normalizing on the socket-activated model used by the repaired image.
systemctl stop nix-daemon.service
systemctl start nix-daemon.socket determinate-nixd.socket
required_units=(
	dbus.service
	cloud-final.service
	finite-nix-selinux.service
	finite-nix-seed.service
	nix.mount
	nix-daemon.socket
	determinate-nixd.socket
)
systemctl is-active --quiet "${required_units[@]}"
cloud_status_exit=0
cloud_status="$(cloud-init status --format json)" || cloud_status_exit=$?
((cloud_status_exit == 0 || cloud_status_exit == 2))
jq -e '.status == "done" and (.errors | length) == 0' <<<"${cloud_status}" >/dev/null
finite_passwd="$(getent passwd finiteci)"
[[ -n "${finite_passwd}" ]]
finite_home="$(cut -d: -f6 <<<"${finite_passwd}")"
[[ "${finite_home}" == /var/home/finiteci ]]
[[ -d /var/home/finiteci ]]
matchpathcon -V /etc/passwd /etc/group /var/home/finiteci
mountpoint --quiet /nix
nix_executable=/nix/var/nix/profiles/default/bin/nix
[[ -x "${nix_executable}" ]]
nix_version="$("${nix_executable}" --version)"
[[ "${nix_version}" == 'nix (Determinate Nix '* ]]
"${nix_executable}" --max-jobs 2 --cores 4 store info --store daemon >/dev/null
systemctl is-active --quiet nix-daemon.service
printf 'FINITE_BOOTC_STATUS=%s\n' "${status}"
printf 'FINITE_HOSTNAME=%s\n' "${hostname_value}"
printf 'FINITE_USER_HOME=%s\n' "${finite_home}"
printf 'FINITE_SYSROOT_FSTYPE=%s\n' "${sysroot_fstype}"
printf 'FINITE_OS_VERSION=%s\n' "${os_version}"
printf 'FINITE_GRUB2_READY=%s\n' "${grub2_ready}"
printf 'FINITE_SELINUX_MODE=%s\n' "${selinux_mode}"
printf 'FINITE_DBUS_ACTIVE=true\n'
printf 'FINITE_CLOUD_INIT_STATUS=%s\n' "$(jq -r .status <<<"${cloud_status}")"
printf 'FINITE_NIX_VERSION=%s\n' "${nix_version}"
printf 'FINITE_INSTALLED_READY=1\n'
SCRIPT
	chmod 0755 "${systemd_root}/finite-ci-installed-ready"
	cat >"${systemd_root}/finite-ci-installed-ready.service" <<'UNIT'
[Unit]
Description=Finite installed-system validation marker
Wants=dbus.service cloud-final.service
After=dbus.service cloud-final.service systemd-user-sessions.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bash /etc/systemd/system/finite-ci-installed-ready
StandardOutput=tty
StandardError=tty
TTYPath=/dev/ttyS0

[Install]
WantedBy=cloud-init.target
UNIT
	ln -sfn ../finite-ci-installed-ready.service \
		"${systemd_root}/cloud-init.target.wants/finite-ci-installed-ready.service"
	chroot "${deployment_root}" /usr/bin/setfiles -C -F -m -v \
		-c "${policy_binary_chroot}" \
		"${file_contexts_chroot}" \
		/etc
	if [[ -d "${var_root}/home" ]]; then
		mount --bind "${var_root}" "${deployment_root}/var"
		bound_var="${deployment_root}/var"
		chroot "${deployment_root}" /usr/bin/setfiles -C -F -m -v \
			-c "${policy_binary_chroot}" \
			"${file_contexts_chroot}" \
			/var/home
		umount "${bound_var}"
		bound_var=
	fi
	rm -f "${file_contexts_tmp}"
	file_contexts_tmp=
done
printf 'FINITE_INSTALLER_DEPLOYMENT_CHECKSUM=%s\n' "${deployment_checksum}"
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

cat >/usr/lib/systemd/user/finite-installer.service <<'EOF'
[Unit]
Description=Launch the Finite installer in the live graphical session
ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/local/bin/finite-installer-launch

[Install]
WantedBy=graphical-session.target
EOF
systemctl --global enable finite-installer.service

# Reassert the live-session identity immediately before GDM starts.  Dakota
# writes the same autologin keys while assembling the container, but bootc's
# first-boot /etc and /var setup can replace those image-time defaults.  The
# AccountsService record also removes any ambiguity about the default GNOME
# session for the manually-created live user.
cat >/usr/local/sbin/finite-live-session-prepare <<'EOF'
#!/usr/bin/bash
set -euo pipefail

live_user=liveuser
id "${live_user}" >/dev/null
passwd --delete "${live_user}" >/dev/null

install -d -m 0755 /etc/gdm /var/lib/AccountsService/users
cat >/etc/gdm/custom.conf <<'GDM'
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=liveuser
DefaultSession=gnome.desktop
GDM
chmod 0644 /etc/gdm/custom.conf

cat >/var/lib/AccountsService/users/liveuser <<'ACCOUNT'
[User]
Session=gnome
XSession=gnome
SystemAccount=false
ACCOUNT
chmod 0600 /var/lib/AccountsService/users/liveuser
EOF
chmod 0755 /usr/local/sbin/finite-live-session-prepare
/usr/local/sbin/finite-live-session-prepare

install -d -m 0755 /etc/systemd/system/gdm.service.d
cat >/etc/systemd/system/gdm.service.d/20-finite-live-session.conf <<'EOF'
[Unit]
ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode
Requires=finite-installer-target-config.service
After=finite-installer-target-config.service

[Service]
ExecStartPre=/usr/local/sbin/finite-live-session-prepare
EOF

cat >/usr/lib/systemd/system/finite-installer-target-config.service <<'EOF'
[Unit]
Description=Apply the Finite installer target from the live ISO
ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode
Before=gdm.service finite-installer-bootstrap.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/finite-installer-apply-target
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=graphical.target
EOF
systemctl enable finite-installer-target-config.service

# GDM can establish the live graphical session without activating the generic
# graphical-session.target in the user's systemd manager.  Keep the user unit
# as the normal desktop integration, but also have the system manager start it
# once GNOME has imported a usable display into the live user's environment.
cat >/usr/local/sbin/finite-installer-bootstrap <<'EOF'
#!/usr/bin/bash
set -euo pipefail

live_user=liveuser
live_uid="$(id -u "${live_user}")"
runtime_dir="/run/user/${live_uid}"
deadline=$((SECONDS + 90))
user_systemctl=(
	sudo --user "${live_user}" --
	env
	"XDG_RUNTIME_DIR=${runtime_dir}"
	"DBUS_SESSION_BUS_ADDRESS=unix:path=${runtime_dir}/bus"
	systemctl --user
)

while ((SECONDS < deadline)); do
	if [[ -S "${runtime_dir}/bus" ]]; then
		# graphical-session.target can start the globally enabled user unit
		# before this system-level fallback observes a display variable.
		if "${user_systemctl[@]}" is-active --quiet finite-installer.service; then
			exit 0
		fi
		user_environment="$("${user_systemctl[@]}" show-environment 2>/dev/null || true)"
		if grep -Eq '^(DISPLAY|WAYLAND_DISPLAY)=' <<<"${user_environment}"; then
			if "${user_systemctl[@]}" start finite-installer.service; then
				exit 0
			fi
		fi
	fi
	sleep 1
done

{
	echo 'Finite installer bootstrap timed out waiting for a graphical live-user session'
	loginctl list-sessions --no-legend || true
	loginctl user-status "${live_user}" --no-pager || true
	getent passwd "${live_user}" || true
	passwd --status "${live_user}" || true
	echo '--- /etc/gdm/custom.conf ---'
	cat /etc/gdm/custom.conf || true
	systemctl --no-pager --full status gdm.service "user@${live_uid}.service" || true
	echo '--- GDM journal ---'
	journalctl --boot --unit gdm.service --no-pager --lines 200 || true
	echo '--- live-user journal ---'
	journalctl --boot "_UID=${live_uid}" --no-pager --lines 200 || true
} >/dev/ttyS0 2>&1
printf '%s\n' 'FINITE_INSTALLER_ERROR=liveuser-graphical-session-timeout' >/dev/ttyS0
exit 1
EOF
chmod 0755 /usr/local/sbin/finite-installer-bootstrap

cat >/usr/lib/systemd/system/finite-installer-bootstrap.service <<'EOF'
[Unit]
Description=Start the Finite installer in the live graphical session
ConditionPathExists=/etc/bootc-installer/finite-netinstall-mode
After=systemd-user-sessions.service gdm.service
Wants=gdm.service
Requires=finite-installer-target-config.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/finite-installer-bootstrap
RemainAfterExit=yes
TimeoutStartSec=100
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=graphical.target
EOF
systemctl enable finite-installer-bootstrap.service

printf 'f /etc/hostname 0644 - - - finite-live\n' \
	>/usr/lib/tmpfiles.d/live-hostname.conf
