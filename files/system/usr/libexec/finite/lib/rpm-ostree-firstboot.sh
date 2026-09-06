#!/usr/bin/env bash
# Shared helpers for Finite first-boot rpm-ostree tasks.

finite_firstboot_log() {
	printf 'finite-firstboot-rpm-ostree: %s\n' "$*" >&2
}

finite_firstboot_mark_reboot_required() {
	local marker="${FINITE_FIRSTBOOT_REBOOT_REQUIRED_FILE:-/run/finite/firstboot-rpm-ostree/reboot-required}"

	install -d -m 0755 "$(dirname "${marker}")"
	: >"${marker}"
}

finite_firstboot_pending_deployment_exists() {
	local status=0

	rpm-ostree status --pending-exit-77 >/dev/null 2>&1 || status=$?
	if ((status == 0)); then
		return 1
	fi

	((status == 77))
}

run_rpm_ostree() {
	local attempt output status
	local max_attempts="${FINITE_RPM_OSTREE_RETRIES:-10}"
	local retry_delay="${FINITE_RPM_OSTREE_RETRY_DELAY:-15}"

	for ((attempt = 1; attempt <= max_attempts; attempt++)); do
		if output="$(rpm-ostree "$@" 2>&1)"; then
			[[ -n "${output}" ]] && printf '%s\n' "${output}"
			if [[ "${output}" == *"Changes queued for next boot"* || "${output}" == *'Run "systemctl reboot" to start a reboot'* ]]; then
				finite_firstboot_mark_reboot_required
			fi
			return 0
		fi

		status=$?
		[[ -n "${output}" ]] && printf '%s\n' "${output}" >&2

		if [[ "${output}" != *"Transaction in progress"* ]] || ((attempt == max_attempts)); then
			return "${status}"
		fi

		finite_firstboot_log "rpm-ostree transaction already in progress; retrying in ${retry_delay}s (${attempt}/${max_attempts})"
		sleep "${retry_delay}"
	done
}
