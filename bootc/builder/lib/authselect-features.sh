#!/usr/bin/env bash
# Aggregate authselect features requested by independently applied role and hardware layers.

purplefin_authselect_state_dir="${PURPLEFIN_AUTHSELECT_STATE_DIR:-/tmp/purplefin-authselect-features.d}"

purplefin_authselect_reset() {
	rm -rf "${purplefin_authselect_state_dir}"
	install -d -m 0755 "${purplefin_authselect_state_dir}"
}

purplefin_authselect_request() {
	local feature

	install -d -m 0755 "${purplefin_authselect_state_dir}"
	for feature in "$@"; do
		if [[ ! "${feature}" =~ ^with-[a-z0-9-]+$ ]]; then
			echo "Invalid authselect feature request: ${feature}" >&2
			return 2
		fi
		: > "${purplefin_authselect_state_dir}/${feature}"
	done
}

purplefin_authselect_finalize() {
	local feature
	local requested_features=()
	local selected_features=(
		with-silent-lastlog
		with-mdns4
	)

	if [[ -d "${purplefin_authselect_state_dir}" ]]; then
		mapfile -t requested_features < <(
			find "${purplefin_authselect_state_dir}" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort
		)
	fi
	# Requests are now held in memory. Remove build-only marker state before
	# authselect runs so both successful and failed finalization leave /tmp clean.
	rm -rf "${purplefin_authselect_state_dir}"

	if ((${#requested_features[@]} == 0)); then
		echo ":: No role or hardware authselect features requested"
		return 0
	fi

	for feature in "${requested_features[@]}"; do
		if [[ ! "${feature}" =~ ^with-[a-z0-9-]+$ ]]; then
			echo "Invalid aggregated authselect feature: ${feature}" >&2
			return 2
		fi
		selected_features+=("${feature}")
	done

	command -v authselect >/dev/null 2>&1 || {
		echo "authselect is required by requested authentication features" >&2
		return 1
	}

	echo ":: Finalizing authselect features: ${selected_features[*]}"
	authselect select local "${selected_features[@]}" --force
}
