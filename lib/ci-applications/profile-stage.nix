{
  generated,
  imageReuse,
  loadBluefin,
  pkgs,
  rechunkImage,
}:
pkgs.writeShellApplication {
  name = "finite-profile-stage";
  runtimeInputs = with pkgs; [buildah coreutils cosign jq podman skopeo];
  text = ''
    set -euo pipefail

    : "''${BUILD_INPUT:?BUILD_INPUT is required}"
    : "''${BUILD_PROFILE:?BUILD_PROFILE is required}"
    : "''${COSIGN_IDENTITY:?COSIGN_IDENTITY is required}"
    : "''${EXPECTED_REVISION:?EXPECTED_REVISION is required}"
    : "''${EXPECTED_UPSTREAM_DIGEST:?EXPECTED_UPSTREAM_DIGEST is required}"
    : "''${EXPECTED_VERSION:?EXPECTED_VERSION is required}"
    : "''${IMAGE_REF:?IMAGE_REF is required}"
    : "''${PARENT_IMAGE:?PARENT_IMAGE is required}"
    : "''${REGISTRY_AUTH_FILE:?REGISTRY_AUTH_FILE is required}"

    [[ "''${BUILD_INPUT}" =~ ^[0-9a-f]{64}$ ]] || {
      echo "Invalid build input: ''${BUILD_INPUT}" >&2
      exit 2
    }
    [[ "''${EXPECTED_REVISION}" =~ ^[0-9a-f]{40}$ ]] || {
      echo "Invalid expected revision: ''${EXPECTED_REVISION}" >&2
      exit 2
    }
    [[ "''${EXPECTED_UPSTREAM_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Invalid upstream digest: ''${EXPECTED_UPSTREAM_DIGEST}" >&2
      exit 2
    }

    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    generated_root="''${FINITE_GENERATED_ROOT:-${generated}}"
    profile_catalog="''${generated_root}/bootc/generated/profile-catalog.json"
    [[ -f "''${repo_root}/flake.nix" && -f "''${profile_catalog}" ]] || {
      echo "Finite source or generated profile catalog is unavailable" >&2
      exit 2
    }
    cd "''${repo_root}"

    podman_command="''${FINITE_PODMAN:-podman}"
    buildah_command="''${FINITE_BUILDAH:-buildah}"
    skopeo_command="''${FINITE_SKOPEO:-skopeo}"
    cosign_command="''${FINITE_COSIGN:-cosign}"
    reuse_command="''${FINITE_IMAGE_REUSE:-${imageReuse}/bin/finite-image-reuse}"
    load_command="''${FINITE_LOAD_BLUEFIN:-${loadBluefin}/bin/finite-load-bluefin}"
    rechunk_command="''${FINITE_RECHUNK_IMAGE:-${rechunkImage}/bin/finite-rechunk-image}"

    parent_digest="''${PARENT_DIGEST:-}"
    parent_profile="''${PARENT_PROFILE:-}"
    parent_tag="''${PARENT_TAG:-}"
    parent_from_lock="''${PARENT_FROM_LOCK:-false}"
    cache_write="''${CACHE_WRITE:-true}"
    upstream_source="''${UPSTREAM_SOURCE:-bluefin}"

    if [[ -n "''${parent_profile}" && -z "''${parent_digest}" ]]; then
      [[ -n "''${parent_tag}" ]] || {
        echo "A parent digest or tag is required for derived builds" >&2
        exit 2
      }
      parent_digest="$("''${skopeo_command}" inspect --retry-times 3 \
        --format '{{.Digest}}' "docker://''${PARENT_IMAGE}:''${parent_tag}")"
    fi
    [[ "''${parent_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Invalid parent digest: ''${parent_digest}" >&2
      exit 2
    }

    foundation="$(jq -er --arg profile "''${BUILD_PROFILE}" \
      '.profiles[$profile].foundation' "''${profile_catalog}")"
    hardware="$(jq -er --arg profile "''${BUILD_PROFILE}" \
      '.profiles[$profile].hardware' "''${profile_catalog}")"
    kernel_release="$(jq -r --arg profile "''${BUILD_PROFILE}" \
      '.profiles[$profile].kernelRelease // empty' "''${profile_catalog}")"
    candidate_tag="''${BUILD_PROFILE}-candidate"
    primary_image="''${IMAGE_REF}:''${candidate_tag}"

    reuse_started=$SECONDS
    reuse_hit=false
    reuse_digest=none
    if [[ "''${REUSE_EXISTING:-true}" == true ]]; then
      if candidate_digest="$(
        BUILD_INPUT="''${BUILD_INPUT}" \
        BUILD_PROFILE="''${BUILD_PROFILE}" \
        COSIGN_IDENTITY="''${COSIGN_IDENTITY}" \
        EXPECTED_PARENT_DIGEST="''${parent_digest}" \
        EXPECTED_REVISION="''${EXPECTED_REVISION}" \
        EXPECTED_UPSTREAM_DIGEST="''${EXPECTED_UPSTREAM_DIGEST}" \
        EXPECTED_VERSION="''${EXPECTED_VERSION}" \
        IMAGE_REF="''${IMAGE_REF}" \
          "''${reuse_command}" "''${candidate_tag}"
      )" && [[ "''${candidate_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        if image_id="$("''${podman_command}" pull --quiet \
          --authfile "''${REGISTRY_AUTH_FILE}" \
          "''${IMAGE_REF}@''${candidate_digest}")"; then
          "''${podman_command}" tag "''${image_id}" "''${primary_image}"
          reuse_hit=true
          reuse_digest="''${candidate_digest}"
        else
          echo "''${BUILD_PROFILE}: matching image could not be pulled; rebuilding" >&2
        fi
      fi
    fi
    reuse_seconds=$((SECONDS - reuse_started))

    upstream_load_seconds=0
    build_outcome=skipped
    build_seconds=0
    cache_available=false
    cache_ref="''${IMAGE_REF}-build-cache"
    rechunk_outcome=skipped
    rechunk_seconds=0
    rechunk_mode=not-run
    previous_build_digest=none
    staged_digest="''${reuse_digest}"

    if [[ "''${reuse_hit}" != true ]]; then
      if [[ "''${parent_from_lock}" == true ]]; then
        load_started=$SECONDS
        "''${load_command}" "''${upstream_source}" >/dev/null
        upstream_load_seconds=$((SECONDS - load_started))
      fi

      build_started=$SECONDS
      created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
      containerfile=./bootc/Containerfile
      cache_args=(--layers)
      parent_args=()
      kernel_label=()
      if [[ -n "''${kernel_release}" ]]; then
        kernel_label+=(--label "ostree.linux=''${kernel_release}")
      fi
      if [[ -n "''${parent_profile}" ]]; then
        containerfile=./bootc/Containerfile.derived
        parent_args+=(
          --label "io.finite.parent.digest=''${parent_digest}"
          --label "io.finite.parent.profile=''${parent_profile}"
          --build-arg "PARENT_PROFILE=''${parent_profile}"
        )
      fi
      base_ref="''${PARENT_IMAGE}@''${parent_digest}"
      pull_policy=always
      if [[ "''${parent_from_lock}" == true ]]; then
        [[ -n "''${parent_tag}" ]]
        base_ref="''${PARENT_IMAGE}:''${parent_tag}"
        pull_policy=never
      fi
      if "''${skopeo_command}" list-tags "docker://''${cache_ref}" >/dev/null 2>&1; then
        cache_available=true
        cache_args+=(--cache-from "''${cache_ref}" --cache-ttl 168h)
      fi
      if [[ "''${cache_write}" == true ]]; then
        cache_args+=(--cache-to "''${cache_ref}")
      fi

      "''${buildah_command}" bud \
        --file "''${containerfile}" \
        --pull="''${pull_policy}" \
        --build-context "finite-generated=''${generated_root}" \
        "''${cache_args[@]}" \
        "''${parent_args[@]}" \
        --label "io.finite.build.input=''${BUILD_INPUT}" \
        --label "io.finite.build.profile=''${BUILD_PROFILE}" \
        --label "io.finite.foundation=''${foundation}" \
        --label "io.finite.hardware=''${hardware}" \
        "''${kernel_label[@]}" \
        --label "io.finite.upstream.digest=''${EXPECTED_UPSTREAM_DIGEST}" \
        --label "org.opencontainers.image.base.digest=''${parent_digest}" \
        --label "org.opencontainers.image.created=''${created}" \
        --label "org.opencontainers.image.revision=''${EXPECTED_REVISION}" \
        --build-arg "BASE_REF=''${base_ref}" \
        --build-arg "BUILD_PROFILE=''${BUILD_PROFILE}" \
        --build-arg "FINITE_VERSION=''${EXPECTED_VERSION}" \
        --format docker \
        --tls-verify=true \
        --tag "''${primary_image}" \
        . >&2
      build_seconds=$((SECONDS - build_started))
      build_outcome=success

      previous_reference=
      previous_metadata="$("''${skopeo_command}" inspect --retry-times 3 \
        "docker://''${IMAGE_REF}:''${BUILD_PROFILE}" 2>/dev/null || true)"
      candidate_previous_digest="$(jq -r '.Digest // empty' <<<"''${previous_metadata}")"
      if [[ "''${candidate_previous_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] &&
        "''${cosign_command}" verify \
          --certificate-oidc-issuer https://token.actions.githubusercontent.com \
          --certificate-identity "''${COSIGN_IDENTITY}" \
          "''${IMAGE_REF}@''${candidate_previous_digest}" >/dev/null 2>&1; then
        previous_build_digest="''${candidate_previous_digest}"
        previous_reference="docker://''${IMAGE_REF}@''${candidate_previous_digest}"
      else
        echo "''${BUILD_PROFILE}: no verifiable previous build; using a full rechunk" >&2
      fi

      rechunk_args=(
        --source "''${primary_image}"
        --output "docker://''${primary_image}"
        --authfile "''${REGISTRY_AUTH_FILE}"
      )
      if [[ -n "''${previous_reference}" ]]; then
        rechunk_args+=(--previous-build "''${previous_reference}")
      fi
      rechunk_report="$(FINITE_PODMAN="''${podman_command}" \
        "''${rechunk_command}" "''${rechunk_args[@]}")"
      staged_digest="$(jq -er '.digest' <<<"''${rechunk_report}")"
      rechunk_mode="$(jq -er '.mode' <<<"''${rechunk_report}")"
      previous_build_digest="$(jq -er '.previous_build_digest' <<<"''${rechunk_report}")"
      rechunk_seconds="$(jq -er '.rechunk_seconds' <<<"''${rechunk_report}")"
      rechunk_outcome=success
    fi

    [[ "''${staged_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Staged image has an invalid digest: ''${staged_digest}" >&2
      exit 1
    }
    published_digest="$("''${skopeo_command}" inspect --retry-times 3 \
      --format '{{.Digest}}' "docker://''${primary_image}")"
    [[ "''${published_digest}" == "''${staged_digest}" ]] || {
      echo "Staged digest changed after publication" >&2
      exit 1
    }

    jq -cn \
      --arg profile "''${BUILD_PROFILE}" \
      --arg digest "''${staged_digest}" \
      --arg parent_digest "''${parent_digest}" \
      --argjson reuse_hit "''${reuse_hit}" \
      --arg reuse_digest "''${reuse_digest}" \
      --argjson reuse_seconds "''${reuse_seconds}" \
      --argjson upstream_load_seconds "''${upstream_load_seconds}" \
      --arg build_outcome "''${build_outcome}" \
      --argjson build_seconds "''${build_seconds}" \
      --argjson cache_available "''${cache_available}" \
      --arg cache_ref "''${cache_ref}" \
      --argjson cache_write "''${cache_write}" \
      --arg rechunk_outcome "''${rechunk_outcome}" \
      --argjson rechunk_seconds "''${rechunk_seconds}" \
      --arg rechunk_mode "''${rechunk_mode}" \
      --arg previous_build_digest "''${previous_build_digest}" '{
        schema: 1,
        profile: $profile,
        digest: $digest,
        parent_digest: $parent_digest,
        reuse_hit: $reuse_hit,
        reuse_digest: $reuse_digest,
        reuse_seconds: $reuse_seconds,
        upstream_load_seconds: $upstream_load_seconds,
        build_outcome: $build_outcome,
        build_seconds: $build_seconds,
        cache_available: $cache_available,
        cache_ref: $cache_ref,
        cache_write: $cache_write,
        rechunk_outcome: $rechunk_outcome,
        rechunk_seconds: $rechunk_seconds,
        rechunk_mode: $rechunk_mode,
        previous_build_digest: $previous_build_digest
      }'
  '';
}
