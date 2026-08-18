#!/usr/bin/env bash
set -euo pipefail

: "${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
: "${PURPLEFIN_BASE_DIGEST:?PURPLEFIN_BASE_DIGEST is required}"
: "${PURPLEFIN_LOAD_BLUEFIN:?PURPLEFIN_LOAD_BLUEFIN is required}"
: "${PURPLEFIN_VERSION:?PURPLEFIN_VERSION is required}"

profile_matrix="${PURPLEFIN_GENERATED_ROOT}/bootc/generated/image-matrix.json"
profile_shard="${PROFILE_SHARD:?PROFILE_SHARD is required}"

usage() {
	echo "usage: purplefin-validate-image-shard [--check]" >&2
}

validate_contract() {
	jq -e '
		type == "array" and length > 0 and
		all(.[];
			type == "object" and
			(.profile | type == "string" and length > 0) and
			(.build_input | type == "string" and test("^[0-9a-f]{64}$")) and
			(.tags | type == "string" and length > 0) and
			(.stage == "root" or .stage == "hardware" or .stage == "role")
		) and
		([.[].profile] | length) == ([.[].profile] | unique | length)
	' <<<"${profile_shard}" >/dev/null || {
		echo "PROFILE_SHARD must contain unique, valid profile entries" >&2
		return 2
	}

	while IFS= read -r entry; do
		profile="$(jq -er '.profile' <<<"${entry}")"
		expected="$(jq -cer --arg profile "${profile}" '
			.[] | select(.profile == $profile) |
			{profile, build_input, tags, stage, parent}
		' "${profile_matrix}")" || {
			echo "Unknown profile in shard: ${profile}" >&2
			return 2
		}
		actual="$(jq -c '{profile, build_input, tags, stage, parent}' <<<"${entry}")"
		[[ "${actual}" == "${expected}" ]] || {
			echo "Shard contract for ${profile} does not match the generated graph" >&2
			return 2
		}
	done < <(jq -c '.[]' <<<"${profile_shard}")
}

cleanup_profile() {
	status=$?
	trap - EXIT
	if [[ -n "${archive:-}" ]]; then
		rm -f -- "${archive}"
		rmdir -- "${archive%/*}" 2>/dev/null || true
	fi
	for image in "${primary_image:-}" "${chunked_image:-}" "${built_image:-}"; do
		if [[ -n "${image}" ]]; then
			"${PURPLEFIN_PODMAN}" image rm --force "${image}" >/dev/null 2>&1 || true
		fi
	done
	exit "${status}"
}

validate_profile() {
	entry="$1"
	base_image="$2"
	cache_available="$3"
	profile="$(jq -er '.profile' <<<"${entry}")"
	build_input="$(jq -er '.build_input' <<<"${entry}")"
	started_at="$(date +%s)"
	archive=''
	built_image=''
	chunked_image=''
	primary_image="localhost/purplefin-validation:${profile}-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}"
	trap cleanup_profile EXIT

	cache_ref="${IMAGE_REF:?IMAGE_REF is required}-build-cache"
	cache_args=(--layers)
	if [[ "${cache_available}" == true ]]; then
		cache_args+=(--cache-from "${cache_ref}" --cache-ttl 168h)
	fi
	created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

	"${PURPLEFIN_BUILDAH}" bud \
		--file ./bootc/Containerfile \
		--pull=never \
		--network host \
		--security-opt label=disable \
		--build-context "purplefin-generated=${PURPLEFIN_GENERATED_ROOT}" \
		"${cache_args[@]}" \
		--label "io.purplefin.build.input=${build_input}" \
		--label "io.purplefin.build.profile=${profile}" \
		--label "io.purplefin.upstream.digest=${PURPLEFIN_BASE_DIGEST}" \
		--label "org.opencontainers.image.base.digest=${PURPLEFIN_BASE_DIGEST}" \
		--label "org.opencontainers.image.created=${created}" \
		--label "org.opencontainers.image.revision=${GITHUB_SHA:-local}" \
		--build-arg "BASE_REF=${base_image}" \
		--build-arg "BUILD_PROFILE=${profile}" \
		--build-arg "PURPLEFIN_VERSION=${PURPLEFIN_VERSION}" \
		--format docker \
		--tls-verify=true \
		--tag "${primary_image}" \
		.
	built_image="$("${PURPLEFIN_PODMAN}" image inspect --format '{{.Id}}' "${primary_image}")"

	preserved_labels="$({
		"${PURPLEFIN_PODMAN}" inspect "${primary_image}" |
			jq -c '
				.[0].Config.Labels // {} |
				with_entries(
					select(
						.key != "containers.bootc" and
						.key != "io.buildah.version" and
						(.key | startswith("ostree.") | not)
					)
				)
			'
	})"
	label_args=()
	while IFS= read -r label; do
		label_args+=(--label "${label}")
	done < <(jq -r 'to_entries[] | "\(.key)=\(.value)"' <<<"${preserved_labels}")

	output_dir="$(mktemp -d -p "${RUNNER_TEMP:-${TMPDIR:-/tmp}}" purplefin-rechunk.XXXXXX)"
	archive="${output_dir}/purplefin.oci"
	"${PURPLEFIN_PODMAN}" run --rm --pull=never --privileged \
		--mount "type=image,src=${primary_image},target=/rpm-ostree" \
		--volume "${output_dir}:/run/out" \
		--entrypoint /usr/bin/rpm-ostree \
		"${primary_image}" \
		compose build-chunked-oci \
			--max-layers 127 \
			--format-version=2 \
			"${label_args[@]}" \
			--bootc \
			--rootfs /rpm-ostree \
			--output oci-archive:/run/out/purplefin.oci

	chunked_image="$("${PURPLEFIN_PODMAN}" pull --quiet "oci-archive:${archive}")"
	"${PURPLEFIN_PODMAN}" inspect "${chunked_image}" |
		jq -e --argjson expected "${preserved_labels}" '
			(.[0].Config.Labels // {}) as $actual |
			$expected |
			to_entries |
			all(.[]; $actual[.key] == .value)
		' >/dev/null

	finished_at="$(date +%s)"
	if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
		{
			echo "### Profile ${profile}"
			echo
			echo "- Build input: \`${build_input}\`"
			echo "- Bluefin digest: \`${PURPLEFIN_BASE_DIGEST}\`"
			echo "- Registry cache available: \`${cache_available}\`"
			echo "- Full build and rechunk validation: \`$((finished_at - started_at))s\`"
		} >>"${GITHUB_STEP_SUMMARY}"
	fi
}

if [[ "${1:-}" == --profile ]]; then
	(( $# == 4 )) || {
		usage
		exit 2
	}
	validate_profile "$2" "$3" "$4"
	exit 0
fi

validate_contract
case "${1:-}" in
	"") ;;
	--check)
		jq -c '[.[].profile]' <<<"${profile_shard}"
		exit 0
		;;
	*)
		usage
		exit 2
		;;
esac

[[ "${UPSTREAM_BASE_DIGEST:?UPSTREAM_BASE_DIGEST is required}" == "${PURPLEFIN_BASE_DIGEST}" ]] || {
	echo "Planned Bluefin digest does not match the Nix lock" >&2
	exit 2
}
: "${PURPLEFIN_BUILDAH:?PURPLEFIN_BUILDAH is required}"
: "${PURPLEFIN_PODMAN:?PURPLEFIN_PODMAN is required}"
base_image="$("${PURPLEFIN_LOAD_BLUEFIN}")"
cache_ref="${IMAGE_REF:?IMAGE_REF is required}-build-cache"
cache_available=false
if skopeo list-tags "docker://${cache_ref}" >/dev/null 2>&1; then
	cache_available=true
fi

failures=()
while IFS= read -r entry; do
	profile="$(jq -er '.profile' <<<"${entry}")"
	echo "Validating ${profile} from the shared locked Bluefin image"
	if bash "$0" --profile "${entry}" "${base_image}" "${cache_available}"; then
		echo "${profile}: validation passed"
	else
		failures+=("${profile}")
		echo "${profile}: validation failed" >&2
	fi
done < <(jq -c '.[]' <<<"${profile_shard}")

if ((${#failures[@]} > 0)); then
	printf 'Failed profile validations: %s\n' "${failures[*]}" >&2
	exit 1
fi
