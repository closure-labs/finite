#!/usr/bin/env bash
set -euo pipefail

profiles_json="${1:?usage: plan-image-builds.sh PROFILES_JSON}"
: "${BASE_DIGEST:?BASE_DIGEST is required}"
: "${BASE_REF:?BASE_REF is required}"
: "${EXPECTED_VERSION:?EXPECTED_VERSION is required}"
: "${IMAGE_REF:?IMAGE_REF is required}"
cosign_command="${PURPLEFIN_COSIGN:-cosign}"
gh_command="${PURPLEFIN_GH:-gh}"
podman_command="${PURPLEFIN_PODMAN:-podman}"
skopeo_command="${PURPLEFIN_SKOPEO:-skopeo}"

# shellcheck source=bootc/builder/lib/independently-managed-rpms.sh
source "${PURPLEFIN_MANAGED_RPMS_LIBRARY:?PURPLEFIN_MANAGED_RPMS_LIBRARY is required}"
purplefin_load_independently_managed_rpms \
	"${PURPLEFIN_MANAGED_RPMS_MANIFEST:?PURPLEFIN_MANAGED_RPMS_MANIFEST is required}"

force_rebuild="${FORCE_REBUILD:-false}"
check_rpm_updates="${CHECK_RPM_UPDATES:-true}"
check_publication_trust="${CHECK_PUBLICATION_TRUST:-false}"
selected='[]'
sbom_repairs='[]'
declare -A published_digests=()
declare -A published_parent_digests=()
probe_root="$(mktemp -d)"
trap 'rm -rf -- "${probe_root}"' EXIT
base_inventory="${probe_root}/base-rpms"

add_profile() {
	local entry="$1"
	local reason="$2"
	local reuse_existing="${3:-true}"
	local profile

	profile="$(jq -r '.profile' <<<"${entry}")"
	echo "${profile}: build (${reason})" >&2
	entry="$(jq -c --argjson reuse_existing "${reuse_existing}" \
		'. + {reuse_existing: $reuse_existing}' <<<"${entry}")"
	selected="$(jq -c --argjson entry "${entry}" '. + [$entry]' <<<"${selected}")"
}

add_sbom_repair() {
	local entry="$1" digest="$2" source_digest="$3"
	entry="$(jq -c --arg digest "${digest}" --arg source_digest "${source_digest}" '
		. + {
			digest: $digest,
			source_digest: $source_digest,
			subject_tag: (.tags | split(" ")[0])
		}' <<<"${entry}")"
	sbom_repairs="$(jq -c --argjson entry "${entry}" '. + [$entry]' <<<"${sbom_repairs}")"
}

ensure_base_inventory() {
	if [[ -s "${base_inventory}" ]]; then
		return 0
	fi

	echo "Pulling ${BASE_REF} for the shared RPM baseline" >&2
	"${podman_command}" pull --quiet "${BASE_REF}" >&2
	"${podman_command}" run --rm --pull=never --entrypoint rpm "${BASE_REF}" \
		-qa --qf $'%{NAME}\t%{EVR}\t%{ARCH}\n' >"${base_inventory}"
	LC_ALL=C sort -o "${base_inventory}" "${base_inventory}"
}

while IFS= read -r entry; do
	profile="$(jq -r '.profile' <<<"${entry}")"
	build_input="$(jq -r '.build_input' <<<"${entry}")"
	primary_tag="$(jq -r '.tags | split(" ")[0]' <<<"${entry}")"
	published_ref="${IMAGE_REF}:${primary_tag}"
	[[ "${build_input}" =~ ^[0-9a-f]{64}$ ]] || { echo "Invalid build input for ${profile}" >&2; exit 2; }

	if [[ "${force_rebuild}" == true ]]; then
		add_profile "${entry}" 'manual force rebuild' false
		continue
	fi

  if ! metadata="$("${skopeo_command}" inspect --retry-times 3 "docker://${published_ref}")"; then
		add_profile "${entry}" 'published image is missing or unreadable'
		continue
	fi
	published_digest="$(jq -er '.Digest' <<<"${metadata}")" || {
		add_profile "${entry}" 'published image has no immutable digest'
		continue
	}
	published_digests["${profile}"]="${published_digest}"
	published_parent_digests["${profile}"]="$(jq -r '.Labels["io.purplefin.parent.digest"] // ""' <<<"${metadata}")"

  published_input="$(jq -r '.Labels["io.purplefin.build.input"] // ""' <<<"${metadata}")"
  published_base="$(jq -r '.Labels["io.purplefin.upstream.digest"] // .Labels["org.opencontainers.image.base.digest"] // ""' <<<"${metadata}")"
  published_parent_profile="$(jq -r '.Labels["io.purplefin.parent.profile"] // ""' <<<"${metadata}")"
  published_profile="$(jq -r '.Labels["io.purplefin.build.profile"] // ""' <<<"${metadata}")"
  published_revision="$(jq -r '.Labels["org.opencontainers.image.revision"] // ""' <<<"${metadata}")"
  published_version="$(jq -r '.Labels["org.opencontainers.image.version"] // ""' <<<"${metadata}")"
  expected_parent_profile="$(jq -r '.parent // ""' <<<"${entry}")"

	if [[ "${published_input}" != "${build_input}" ]]; then
		add_profile "${entry}" 'build inputs changed'
		continue
	fi
  if [[ "${published_base}" != "${BASE_DIGEST}" ]]; then
    add_profile "${entry}" 'Bluefin base digest changed'
    continue
  fi
  if [[ "${published_profile}" != "${profile}" ||
    "${published_parent_profile}" != "${expected_parent_profile}" ||
    "${published_version}" != "${EXPECTED_VERSION}" ]]; then
    add_profile "${entry}" 'published identity labels are incomplete' false
    continue
  fi
	if [[ "${check_publication_trust}" == true ]]; then
		: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for publication verification}"
		if [[ ! "${published_revision}" =~ ^[0-9a-f]{40}$ ]] ||
      ! "${cosign_command}" verify \
				--certificate-oidc-issuer https://token.actions.githubusercontent.com \
				--certificate-identity "https://github.com/${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml@refs/heads/main" \
				"${IMAGE_REF}@${published_digest}" >/dev/null 2>&1 ||
      ! "${gh_command}" attestation verify "oci://${IMAGE_REF}@${published_digest}" \
				--bundle-from-oci --repo "${GITHUB_REPOSITORY}" \
				--signer-workflow "${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
				--source-digest "${published_revision}" \
				--predicate-type https://slsa.dev/provenance/v1 >/dev/null 2>&1; then
			add_profile "${entry}" 'published security metadata is incomplete' false
			continue
		fi
    if ! "${gh_command}" attestation verify "oci://${IMAGE_REF}@${published_digest}" \
			--bundle-from-oci --repo "${GITHUB_REPOSITORY}" \
			--signer-workflow "${GITHUB_REPOSITORY}/.github/workflows/attest-software-bill-of-materials.yml" \
			--source-digest "${published_revision}" \
			--predicate-type https://spdx.dev/Document/v2.3 >/dev/null 2>&1; then
			echo "${profile}: repair software bill of materials attestation" >&2
			add_sbom_repair "${entry}" "${published_digest}" "${published_revision}"
		fi
	fi
	if [[ "${check_rpm_updates}" != true ]]; then
		echo "${profile}: skip (build inputs and Bluefin base are current)" >&2
		continue
	fi

	# The matrix job pulls only its own previous image and exact Bluefin base.
	# The expensive build runs only when a layered or independently managed RPM
	# has an upgrade.
	if ! ensure_base_inventory; then
		add_profile "${entry}" 'Bluefin RPM baseline could not be read'
		continue
	fi
	if ! "${podman_command}" pull --quiet "${published_ref}" >&2; then
		add_profile "${entry}" 'published image could not be pulled for its RPM probe'
		continue
	fi

	profile_inventory="${probe_root}/${profile}-rpms"
	layered_packages="${probe_root}/${profile}-layered-package-names"
	if ! "${podman_command}" run --rm --pull=never --entrypoint rpm "${published_ref}" \
		-qa --qf $'%{NAME}\t%{EVR}\t%{ARCH}\n' >"${profile_inventory}"; then
		add_profile "${entry}" 'published RPM inventory could not be read'
		continue
	fi
	LC_ALL=C sort -o "${profile_inventory}" "${profile_inventory}"
	comm -13 "${base_inventory}" "${profile_inventory}" |
		cut -f 1 |
		LC_ALL=C sort -u >"${layered_packages}"
	mapfile -t packages < <(
		for package in "${independently_managed_rpms[@]}"; do
			awk -F '\t' -v package="${package}" '$1 == package { found = 1 } END { exit !found }' \
				"${profile_inventory}" && printf '%s\n' "${package}"
		done
		cat "${layered_packages}"
	)
	mapfile -t packages < <(printf '%s\n' "${packages[@]}" | LC_ALL=C sort -u)
	if ((${#packages[@]} == 0)); then
		echo "${profile}: skip (inputs and base are current; no managed RPMs)" >&2
		continue
	fi

	upgrade_log="$(mktemp)"
	set +e
	"${podman_command}" run --rm --pull=never --entrypoint dnf5 "${published_ref}" \
		-y -q --refresh "${independently_managed_rpm_repo_args[@]}" \
		check-upgrade "${packages[@]}" >"${upgrade_log}" 2>&1
	upgrade_status=$?
	set -e

	case "${upgrade_status}" in
		0)
			echo "${profile}: skip (inputs, base, and installed RPMs are current)" >&2
		;;
		100)
			sed "s/^/${profile}: /" "${upgrade_log}" >&2
			add_profile "${entry}" 'installed RPM updates are available' false
		;;
		*)
			sed "s/^/${profile}: /" "${upgrade_log}" >&2
			add_profile "${entry}" "RPM probe failed with status ${upgrade_status}" false
		;;
	esac
	# Keep the exact base tag for a possible build, but discard the old
	# profile's unique layer before Buildah creates its replacement.
	"${podman_command}" image rm "${published_ref}" >/dev/null 2>&1 || true
	rm -f "${upgrade_log}"
done < <(jq -c '.[]' <<<"${profiles_json}")

# Repair a partially completed staged publish. If a parent was replaced but a
# child still names the old immutable parent, the child must be rebuilt even
# when its own source hash is unchanged.
while IFS=$'\t' read -r profile parent_profile; do
	if jq -e --arg profile "${profile}" 'any(.[]; .profile == $profile)' <<<"${selected}" >/dev/null; then
		continue
	fi
	parent_digest="${published_digests[${parent_profile}]:-}"
	child_parent_digest="${published_parent_digests[${profile}]:-}"
	if [[ "${parent_digest}" =~ ^sha256:[0-9a-f]{64}$ && "${child_parent_digest}" != "${parent_digest}" ]]; then
		entry="$(jq -c --arg profile "${profile}" '.[] | select(.profile == $profile)' <<<"${profiles_json}")"
		add_profile "${entry}" "published parent ${parent_profile} changed"
	fi
done < <(jq -r '.[] | select(.parent != null) | [.profile, .parent] | @tsv' <<<"${profiles_json}")

# A source change in a staged base invalidates every image derived from that
# base through every descendant. Repeat to close the complete graph rather than
# assuming there is only one derived level.
changed=true
while [[ "${changed}" == true ]]; do
	changed=false
	selected_snapshot="${selected}"
	while IFS= read -r parent_profile; do
		while IFS= read -r child; do
			child_profile="$(jq -r '.profile' <<<"${child}")"
			if ! jq -e --arg profile "${child_profile}" 'any(.[]; .profile == $profile)' <<<"${selected}" >/dev/null; then
				add_profile "${child}" "parent ${parent_profile} is being rebuilt"
				changed=true
			fi
		done < <(jq -c --arg parent "${parent_profile}" '.[] | select(.parent == $parent)' <<<"${profiles_json}")
	done < <(jq -r '.[].profile' <<<"${selected_snapshot}")
done

while IFS=$'\t' read -r profile parent_profile; do
	if jq -e --arg profile "${parent_profile}" 'any(.[]; .profile == $profile)' <<<"${selected}" >/dev/null; then
		parent_tag="${parent_profile}-candidate"
	else
		parent_tag="$(jq -er --arg profile "${parent_profile}" '.[] | select(.profile == $profile) | .tags | split(" ")[0]' <<<"${profiles_json}")"
	fi
	selected="$(jq -c --arg profile "${profile}" --arg tag "${parent_tag}" \
		'map(if .profile == $profile then . + {parent_tag: $tag} else . end)' <<<"${selected}")"
	if jq -e --arg profile "${parent_profile}" 'any(.[]; .profile == $profile)' <<<"${selected}" >/dev/null; then
		continue
	fi
	parent_digest="${published_digests[${parent_profile}]:-}"
	[[ "${parent_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
		echo "Selected profile ${profile} has no current immutable parent ${parent_profile}" >&2
		exit 2
	}
	selected="$(jq -c --arg profile "${profile}" --arg digest "${parent_digest}" \
		'map(if .profile == $profile then . + {parent_digest: $digest} else . end)' <<<"${selected}")"
done < <(jq -r '.[] | select(.parent != null) | [.profile, .parent] | @tsv' <<<"${selected}")

# Restore declaration order so workflow plans and logs remain deterministic.
selected="$(jq -cn --argjson profiles "${profiles_json}" --argjson chosen "${selected}" \
	'[ $profiles[] as $profile | $chosen[] | select(.profile == $profile.profile) ]')"
sbom_repairs="$(jq -cn --argjson profiles "${profiles_json}" --argjson repairs "${sbom_repairs}" \
	--argjson chosen "${selected}" '
	[
		$profiles[] as $profile |
		$repairs[] |
		select(.profile == $profile.profile) |
		select(.profile as $name | all($chosen[]; .profile != $name))
	]
')"

jq -cn --argjson include "${selected}" --argjson sbom_repair "${sbom_repairs}" \
	'{include: $include, sbom_repair: $sbom_repair}'
