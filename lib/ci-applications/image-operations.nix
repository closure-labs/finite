{
  generated,
  loadBluefin,
  pkgs,
  version,
}: rec {
  imageReuse = pkgs.writeShellApplication {
    name = "finite-image-reuse";
    runtimeInputs = with pkgs; [bash coreutils cosign jq skopeo];
    text = ''
         repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
         [[ -f "''${repo_root}/flake.nix" ]] || {
           echo "Run this command from the Finite repository root" >&2
           exit 2
         }
         cd "''${repo_root}"
         set -euo pipefail

         primary_tag="''${1:?usage: reuse-image.sh PRIMARY_TAG}"
         : "''${BUILD_INPUT:?BUILD_INPUT is required}"
         : "''${BUILD_PROFILE:?BUILD_PROFILE is required}"
         : "''${COSIGN_IDENTITY:?COSIGN_IDENTITY is required}"
         : "''${EXPECTED_PARENT_DIGEST:?EXPECTED_PARENT_DIGEST is required}"
         : "''${EXPECTED_REVISION:?EXPECTED_REVISION is required}"
         : "''${EXPECTED_UPSTREAM_DIGEST:?EXPECTED_UPSTREAM_DIGEST is required}"
         : "''${EXPECTED_VERSION:?EXPECTED_VERSION is required}"
         : "''${IMAGE_REF:?IMAGE_REF is required}"
      expected_foundation="$(jq -er --arg profile "''${BUILD_PROFILE}" '.profiles[$profile].foundation' ${generated}/bootc/generated/profile-catalog.json)"
      expected_hardware="$(jq -er --arg profile "''${BUILD_PROFILE}" '.profiles[$profile].hardware' ${generated}/bootc/generated/profile-catalog.json)"
      expected_kernel_release="$(jq -r --arg profile "''${BUILD_PROFILE}" '.profiles[$profile].kernelRelease // empty' ${generated}/bootc/generated/profile-catalog.json)"
      cosign_command="''${FINITE_COSIGN:-cosign}"
      skopeo_command="''${FINITE_SKOPEO:-skopeo}"

         published_ref="''${IMAGE_REF}:''${primary_tag}"
      if ! metadata="$("''${skopeo_command}" inspect --retry-times 3 "docker://''${published_ref}")"; then
           echo "''${BUILD_PROFILE}: no readable published image to reuse" >&2
           exit 0
         fi

         if ! digest="$(jq -er '.Digest' <<<"''${metadata}")" ||
           [[ ! "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
           echo "''${BUILD_PROFILE}: published image has no immutable digest to reuse" >&2
           exit 0
         fi

         if ! jq -e \
           --arg build_input "''${BUILD_INPUT}" \
           --arg foundation "''${expected_foundation}" \
           --arg hardware "''${expected_hardware}" \
           --arg kernel_release "''${expected_kernel_release}" \
           --arg parent_digest "''${EXPECTED_PARENT_DIGEST}" \
           --arg profile "''${BUILD_PROFILE}" \
           --arg revision "''${EXPECTED_REVISION}" \
           --arg upstream_digest "''${EXPECTED_UPSTREAM_DIGEST}" \
           --arg version "''${EXPECTED_VERSION}" '
             (.Labels // {}) as $labels |
             $labels["io.finite.build.input"] == $build_input and
             $labels["io.finite.build.profile"] == $profile and
             $labels["io.finite.foundation"] == $foundation and
             $labels["io.finite.hardware"] == $hardware and
             ($kernel_release == "" or $labels["ostree.linux"] == $kernel_release) and
             $labels["io.finite.upstream.digest"] == $upstream_digest and
             $labels["org.opencontainers.image.base.digest"] == $parent_digest and
             $labels["org.opencontainers.image.revision"] == $revision and
             $labels["org.opencontainers.image.version"] == $version
           ' <<<"''${metadata}" >/dev/null; then
           echo "''${BUILD_PROFILE}: published image does not match the requested build" >&2
           exit 0
         fi

         immutable_ref="''${IMAGE_REF}@''${digest}"
      if ! "''${cosign_command}" verify \
           --certificate-oidc-issuer https://token.actions.githubusercontent.com \
           --certificate-identity "''${COSIGN_IDENTITY}" \
           "''${immutable_ref}" >/dev/null; then
           echo "''${BUILD_PROFILE}: matching image is not signed by the trusted build workflow" >&2
           exit 0
         fi

         echo "''${BUILD_PROFILE}: reuse ''${immutable_ref}" >&2
         printf '%s\n' "''${digest}"
    '';
  };
  imageBuild = pkgs.writeShellApplication {
    name = "finite-image-build";
    runtimeInputs = with pkgs; [bash coreutils jq podman];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      (( $# == 2 )) || {
        echo "usage: nix run .#image-build -- PROFILE IMAGE_TAG" >&2
        exit 2
      }
      cd "''${repo_root}"
      profile="$1"
      tag="$2"
      jq -e --arg profile "''${profile}" '.profiles[$profile]' \
        ${generated}/bootc/generated/profile-catalog.json >/dev/null || {
        echo "Unknown profile: ''${profile}" >&2
        exit 2
      }
      upstream_image="$(jq -er --arg profile "''${profile}" '.[] | select(.profile == $profile) | .upstream.image' ${generated}/bootc/generated/image-matrix.json)"
      upstream_digest="$(jq -er --arg profile "''${profile}" '.[] | select(.profile == $profile) | .upstream.digest' ${generated}/bootc/generated/image-matrix.json)"
      foundation="$(jq -er --arg profile "''${profile}" '.profiles[$profile].foundation' ${generated}/bootc/generated/profile-catalog.json)"
      hardware="$(jq -er --arg profile "''${profile}" '.profiles[$profile].hardware' ${generated}/bootc/generated/profile-catalog.json)"
      kernel_release="$(jq -r --arg profile "''${profile}" '.profiles[$profile].kernelRelease // empty' ${generated}/bootc/generated/profile-catalog.json)"
      kernel_label=()
      if [[ -n "''${kernel_release}" ]]; then
        kernel_label+=(--label "ostree.linux=''${kernel_release}")
      fi
      if [[ "''${upstream_image}" == *bluefin-dx ]]; then
        source_name=bluefin-dx
      else
        source_name=bluefin
      fi
      base_image="$(${loadBluefin}/bin/finite-load-bluefin "''${source_name}")"
      exec podman build \
        --file bootc/Containerfile \
        --network host \
        --pull=never \
        --security-opt label=disable \
        --build-context finite-generated=${generated} \
        --build-arg "BASE_REF=''${base_image}" \
        --build-arg "BUILD_PROFILE=''${profile}" \
        --build-arg "FINITE_VERSION=${version}" \
        --label "io.finite.build.profile=''${profile}" \
        --label "io.finite.foundation=''${foundation}" \
        --label "io.finite.hardware=''${hardware}" \
        "''${kernel_label[@]}" \
        --label "io.finite.upstream.digest=''${upstream_digest}" \
        --label "org.opencontainers.image.base.digest=''${upstream_digest}" \
        --tag "''${tag}" \
      .
    '';
  };
}
