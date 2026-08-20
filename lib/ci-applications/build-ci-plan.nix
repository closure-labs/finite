{
  bluefin,
  generated,
  imagePlan,
  pkgs,
  shardPlan,
  verifyBluefin,
  version,
}:
pkgs.writeShellApplication {
  name = "purplefin-ci-build-plan";
  runtimeInputs = [pkgs.jq];
  text = ''
    set -euo pipefail

    classification="''${CLASSIFICATION:?CLASSIFICATION is required}"
    event_name="''${EVENT_NAME:?EVENT_NAME is required}"
    github_sha="''${GITHUB_SHA:?GITHUB_SHA is required}"
    github_ref="''${GITHUB_REF:-}"
    publication_trusted="''${CHECK_PUBLICATION_TRUST:-false}"
    [[ "''${github_sha}" =~ ^[0-9a-f]{40}$ ]] || {
      echo 'GITHUB_SHA must be a complete commit SHA' >&2
      exit 2
    }
    [[ "''${publication_trusted}" == true || "''${publication_trusted}" == false ]] || {
      echo 'CHECK_PUBLICATION_TRUST must be true or false' >&2
      exit 2
    }
    jq -e '
      .schema == 1 and
      (.diff.status == "classified" or .diff.status == "fallback" or .diff.status == "predetermined") and
      (.validation.images.required | type == "boolean") and
      (.validation.images.scope == "none" or .validation.images.scope == "changed" or .validation.images.scope == "all") and
      (.validation.installer.required | type == "boolean")
    ' <<<"''${classification}" >/dev/null || {
      echo 'Invalid CI classification contract' >&2
      exit 2
    }

    profiles="$(jq -c . ${generated}/bootc/generated/image-matrix.json)"
    matrix='{"include":[],"sbom_repair":[]}'
    root_base='{}'
    root_matrix='{"include":[]}'
    hardware_matrix='{"include":[]}'
    role_matrix='{"include":[]}'
    candidate_shards='{"include":[]}'
    base_sbom_matrix='{"include":[]}'
    hardware_sbom_matrix='{"include":[]}'
    role_sbom_matrix='{"include":[]}'

    if jq -e '.validation.images.required' <<<"''${classification}" >/dev/null; then
      : "''${IMAGE_REF:?IMAGE_REF is required}"
      ${verifyBluefin}/bin/purplefin-verify-bluefin bluefin >/dev/null
      ${verifyBluefin}/bin/purplefin-verify-bluefin bluefin-dx >/dev/null
      export EXPECTED_VERSION='${version}'
      matrix="$(${imagePlan}/bin/purplefin-image-plan "''${profiles}")"
      root_base="$(jq -c 'first(.include[] | select(.stage == "root")) // {}' <<<"''${matrix}")"
      root_matrix="$(jq -c '{include: [.include[] | select(.stage == "root")]}' <<<"''${matrix}")"
      hardware_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"''${matrix}")"
      role_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"''${matrix}")"
      candidate_shards="$(${shardPlan}/bin/purplefin-shard-plan "''${profiles}" "''${matrix}" 4)"
      sbom_matrix="$(jq -c --arg source_digest "''${github_sha}" --argjson profiles "''${profiles}" '
        ([.include[] | . + {
          source_digest: $source_digest,
          subject_tag: (.profile + "-candidate")
        }] + .sbom_repair) as $selected |
        {include: [
          $profiles[] as $decl |
          $selected[] |
          select(.profile == $decl.profile)
        ]}
      ' <<<"''${matrix}")"
      base_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "root")]}' <<<"''${sbom_matrix}")"
      hardware_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"''${sbom_matrix}")"
      role_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"''${sbom_matrix}")"
    fi

    jq -cn \
      --arg event "''${event_name}" \
      --arg ref "''${github_ref}" \
      --arg sha "''${github_sha}" \
      --arg version '${version}' \
      --arg image '${bluefin.image}' \
      --arg tag '${bluefin.tag}' \
      --arg digest '${bluefin.digest}' \
      --argjson classification "''${classification}" \
      --argjson trusted "''${publication_trusted}" \
      --argjson matrix "''${matrix}" \
      --argjson root_base "''${root_base}" \
      --argjson root "''${root_matrix}" \
      --argjson hardware "''${hardware_matrix}" \
      --argjson roles "''${role_matrix}" \
      --argjson shards "''${candidate_shards}" \
      --argjson base_sbom "''${base_sbom_matrix}" \
      --argjson hardware_sbom "''${hardware_sbom_matrix}" \
      --argjson role_sbom "''${role_sbom_matrix}" '
      ($matrix.include | length > 0) as $has_images |
      ($trusted and $has_images) as $publish |
      {
        schema_version: 1,
        source: {event: $event, ref: $ref, sha: $sha, version: $version},
        classification: $classification,
        base: {image: $image, tag: $tag, digest: $digest},
        validation: {
          images: {required: $has_images, targets: [$matrix.include[].profile]},
          installer: $classification.validation.installer
        },
        publication: {
          trusted: $trusted,
          builds: {
            any: $publish,
            root: ($trusted and ($root.include | length > 0)),
            hardware: ($trusted and ($hardware.include | length > 0)),
            roles: ($trusted and ($roles.include | length > 0))
          },
          sbom: {
            base: ($trusted and ($base_sbom.include | length > 0)),
            hardware: ($trusted and ($hardware_sbom.include | length > 0)),
            roles: ($trusted and ($role_sbom.include | length > 0))
          },
          promote: $publish
        },
        matrices: {
          all: $matrix,
          candidate_shards: $shards,
          root: $root,
          hardware: $hardware,
          roles: $roles,
          sbom: {base: $base_sbom, hardware: $hardware_sbom, roles: $role_sbom}
        },
        root_base: $root_base
      }
    '
  '';
}
