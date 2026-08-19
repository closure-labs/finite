#!/usr/bin/env bash
set -euo pipefail

if [[ "${CI:-}" == true ]]; then
  host_buildah="$(PATH=/usr/local/bin:/usr/bin:/bin command -v buildah || true)"
  host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
  [[ -n "${host_buildah}" && -n "${host_podman}" ]] || {
    echo "The CI runner's host Buildah and Podman are required" >&2
    exit 1
  }
  export PURPLEFIN_BUILDAH="${host_buildah}"
  export PURPLEFIN_PODMAN="${host_podman}"
else
  export PURPLEFIN_BUILDAH="${PURPLEFIN_DEFAULT_BUILDAH:?PURPLEFIN_DEFAULT_BUILDAH is required}"
  export PURPLEFIN_PODMAN="${PURPLEFIN_DEFAULT_PODMAN:?PURPLEFIN_DEFAULT_PODMAN is required}"
fi
repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
cd "${repo_root}" || exit
: "${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}"
: "${PURPLEFIN_BASE_DIGEST:?PURPLEFIN_BASE_DIGEST is required}"
: "${PURPLEFIN_LOAD_BLUEFIN:?PURPLEFIN_LOAD_BLUEFIN is required}"
: "${PURPLEFIN_VERSION:?PURPLEFIN_VERSION is required}"

profile_matrix="${PURPLEFIN_GENERATED_ROOT}/bootc/generated/image-matrix.json"
profile_shard="${PROFILE_SHARD:?PROFILE_SHARD is required}"

usage() {
  echo "usage: purplefin-validate-image-shard [--check]" >&2
}

declare -A validated_images=()
retained_images=()
cleanup_shard() {
	status=$?
	set +e
	for image in "${retained_images[@]:-}"; do
		[[ -z "${image}" ]] || "${PURPLEFIN_PODMAN:-podman}" image rm --force "${image}" >/dev/null 2>&1
	done
	exit "${status}"
}
trap cleanup_shard EXIT

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

validate_profile() {
	entry="$1"
	upstream_image="$2"
	cache_available="$3"
	profile="$(jq -er '.profile' <<<"${entry}")"
	build_input="$(jq -er '.build_input' <<<"${entry}")"
	started_at="$(date +%s)"
	archive=''
	chunked_image=''
	primary_image="localhost/purplefin-validation:${profile}-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}"
	parent_profile="$(jq -r '.parent // ""' <<<"${entry}")"
	containerfile=./bootc/Containerfile
	base_ref="${upstream_image}"
	parent_args=()
	if [[ -n "${parent_profile}" ]]; then
		containerfile=./bootc/Containerfile.derived
		if [[ -n "${validated_images["${parent_profile}"]:-}" ]]; then
			base_ref="${validated_images["${parent_profile}"]}"
		else
			parent_digest="$(jq -r '.parent_digest // ""' <<<"${entry}")"
			parent_tag="$(jq -r '.parent_tag // ""' <<<"${entry}")"
			[[ "${parent_digest}" =~ ^sha256:[0-9a-f]{64}$ && -n "${parent_tag}" ]] || {
				echo "${profile}: selected derived profile has no candidate or immutable published parent" >&2
				return 2
			}
			base_ref="${IMAGE_REF}@${parent_digest}"
			"${PURPLEFIN_PODMAN}" pull --quiet "${base_ref}" >/dev/null
		fi
		parent_args+=(--build-arg "PARENT_PROFILE=${parent_profile}")
	fi

	cache_ref="${IMAGE_REF:?IMAGE_REF is required}-build-cache"
	cache_args=(--layers)
	if [[ "${cache_available}" == true ]]; then
		cache_args+=(--cache-from "${cache_ref}" --cache-ttl 168h)
	fi
	created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

	"${PURPLEFIN_BUILDAH}" bud \
		--file "${containerfile}" \
		--pull=missing \
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
		"${parent_args[@]}" \
		--build-arg "BASE_REF=${base_ref}" \
		--build-arg "BUILD_PROFILE=${profile}" \
		--build-arg "PURPLEFIN_VERSION=${PURPLEFIN_VERSION}" \
		--format docker \
		--tls-verify=true \
		--tag "${primary_image}" \
		.
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
	chunked_tag="${primary_image}-chunked"
	"${PURPLEFIN_PODMAN}" tag "${chunked_image}" "${chunked_tag}"
	validated_images["${profile}"]="${chunked_tag}"
	retained_images+=("${primary_image}" "${chunked_image}" "${chunked_tag}")
	rm -f -- "${archive}"
	rmdir -- "${archive%/*}" 2>/dev/null || true
	archive=''

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

while IFS= read -r entry; do
	profile="$(jq -er '.profile' <<<"${entry}")"
	echo "Validating ${profile} from the shared locked Bluefin image"
	validate_profile "${entry}" "${base_image}" "${cache_available}"
	echo "${profile}: validation passed"
done < <(jq -c '.[]' <<<"${profile_shard}")
