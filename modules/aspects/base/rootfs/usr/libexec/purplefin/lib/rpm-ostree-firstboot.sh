#!/usr/bin/env bash
# Shared helpers for Purplefin first-boot rpm-ostree tasks.

purplefin_firstboot_log() {
	printf 'purplefin-firstboot-rpm-ostree: %s\n' "$*" >&2
}

purplefin_firstboot_mark_reboot_required() {
	local marker="${PURPLEFIN_FIRSTBOOT_REBOOT_REQUIRED_FILE:-/run/purplefin/firstboot-rpm-ostree/reboot-required}"

	install -d -m 0755 "$(dirname "${marker}")"
	: >"${marker}"
}

purplefin_firstboot_pending_deployment_exists() {
	local status=0

	rpm-ostree status --pending-exit-77 >/dev/null 2>&1 || status=$?
	if ((status == 0)); then
		return 1
	fi

	((status == 77))
}

run_rpm_ostree() {
	local attempt output status
	local max_attempts="${PURPLEFIN_RPM_OSTREE_RETRIES:-10}"
	local retry_delay="${PURPLEFIN_RPM_OSTREE_RETRY_DELAY:-15}"

	for ((attempt = 1; attempt <= max_attempts; attempt++)); do
		if output="$(rpm-ostree "$@" 2>&1)"; then
			[[ -n "${output}" ]] && printf '%s\n' "${output}"
			if [[ "${output}" == *"Changes queued for next boot"* || "${output}" == *'Run "systemctl reboot" to start a reboot'* ]]; then
				purplefin_firstboot_mark_reboot_required
			fi
			return 0
		fi

		status=$?
		[[ -n "${output}" ]] && printf '%s\n' "${output}" >&2

		if [[ "${output}" != *"Transaction in progress"* ]] || ((attempt == max_attempts)); then
			return "${status}"
		fi

		purplefin_firstboot_log "rpm-ostree transaction already in progress; retrying in ${retry_delay}s (${attempt}/${max_attempts})"
		sleep "${retry_delay}"
	done
}
