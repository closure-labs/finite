#!/usr/bin/env bash
set -euo pipefail

profiles_json="${1:?usage: plan-image-builds.sh PROFILES_JSON}"
: "${BASE_DIGEST:?BASE_DIGEST is required}"
: "${BASE_REF:?BASE_REF is required}"
: "${BUILD_INPUT:?BUILD_INPUT is required}"
: "${IMAGE_REF:?IMAGE_REF is required}"

force_rebuild="${FORCE_REBUILD:-false}"
check_rpm_updates="${CHECK_RPM_UPDATES:-true}"
selected='[]'
probe_root="$(mktemp -d)"
trap 'rm -rf -- "${probe_root}"' EXIT
base_inventory="${probe_root}/base-rpms"

add_profile() {
	local entry="$1"
	local reason="$2"
	local profile

	profile="$(jq -r '.profile' <<<"${entry}")"
	echo "${profile}: build (${reason})" >&2
	selected="$(jq -c --argjson entry "${entry}" '. + [$entry]' <<<"${selected}")"
}

ensure_base_inventory() {
	if [[ -s "${base_inventory}" ]]; then
		return 0
	fi

	echo "Pulling ${BASE_REF} for the shared RPM baseline" >&2
	podman pull --quiet "${BASE_REF}" >&2
	podman run --rm --pull=never --entrypoint rpm "${BASE_REF}" \
		-qa --qf $'%{NAME}\t%{EVR}\t%{ARCH}\n' >"${base_inventory}"
	LC_ALL=C sort -o "${base_inventory}" "${base_inventory}"
}

while IFS= read -r entry; do
	profile="$(jq -r '.profile' <<<"${entry}")"
	primary_tag="$(jq -r '.tags | split(" ")[0]' <<<"${entry}")"
	published_ref="${IMAGE_REF}:${primary_tag}"

	if [[ "${force_rebuild}" == true ]]; then
		add_profile "${entry}" 'manual force rebuild'
		continue
	fi

	if ! metadata="$(skopeo inspect --retry-times 3 "docker://${published_ref}")"; then
		add_profile "${entry}" 'published image is missing or unreadable'
		continue
	fi

	published_input="$(jq -r '.Labels["io.purplefin.build.input"] // ""' <<<"${metadata}")"
	published_base="$(jq -r '.Labels["org.opencontainers.image.base.digest"] // ""' <<<"${metadata}")"

	if [[ "${published_input}" != "${BUILD_INPUT}" ]]; then
		add_profile "${entry}" 'build inputs changed'
		continue
	fi
	if [[ "${published_base}" != "${BASE_DIGEST}" ]]; then
		add_profile "${entry}" 'Bluefin base digest changed'
		continue
	fi
	if [[ "${check_rpm_updates}" != true ]]; then
		echo "${profile}: skip (build inputs and Bluefin base are current)" >&2
		continue
	fi

	# The matrix job pulls only its own previous image and exact Bluefin base.
	# The expensive build runs only when an RPM layered on top has an upgrade.
	if ! ensure_base_inventory; then
		add_profile "${entry}" 'Bluefin RPM baseline could not be read'
		continue
	fi
	if ! podman pull --quiet "${published_ref}" >&2; then
		add_profile "${entry}" 'published image could not be pulled for its RPM probe'
		continue
	fi

	profile_inventory="${probe_root}/${profile}-rpms"
	layered_packages="${probe_root}/${profile}-layered-package-names"
	if ! podman run --rm --pull=never --entrypoint rpm "${published_ref}" \
		-qa --qf $'%{NAME}\t%{EVR}\t%{ARCH}\n' >"${profile_inventory}"; then
		add_profile "${entry}" 'published RPM inventory could not be read'
		continue
	fi
	LC_ALL=C sort -o "${profile_inventory}" "${profile_inventory}"
	comm -13 "${base_inventory}" "${profile_inventory}" |
		cut -f 1 |
		LC_ALL=C sort -u >"${layered_packages}"
	mapfile -t packages <"${layered_packages}"
	if ((${#packages[@]} == 0)); then
		echo "${profile}: skip (inputs and base are current; no layered RPMs)" >&2
		continue
	fi

	upgrade_log="$(mktemp)"
	set +e
	podman run --rm --pull=never --entrypoint dnf5 "${published_ref}" \
		-q --refresh check-upgrade "${packages[@]}" >"${upgrade_log}" 2>&1
	upgrade_status=$?
	set -e

	case "${upgrade_status}" in
		0)
			echo "${profile}: skip (inputs, base, and installed RPMs are current)" >&2
		;;
		100)
			sed "s/^/${profile}: /" "${upgrade_log}" >&2
			add_profile "${entry}" 'installed RPM updates are available'
		;;
		*)
			sed "s/^/${profile}: /" "${upgrade_log}" >&2
			add_profile "${entry}" "RPM probe failed with status ${upgrade_status}"
		;;
	esac
	# Keep the exact base tag for a possible build, but discard the old
	# profile's unique layer before Buildah creates its replacement.
	podman image rm "${published_ref}" >/dev/null 2>&1 || true
	rm -f "${upgrade_log}"
done < <(jq -c '.[]' <<<"${profiles_json}")

jq -cn --argjson include "${selected}" '{include: $include}'
