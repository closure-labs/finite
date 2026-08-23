{pkgs}:
pkgs.writeShellApplication {
  name = "finite-promote-images";
  runtimeInputs = with pkgs; [coreutils cosign gh jq oras skopeo];
  text = ''
    set -euo pipefail

    : "''${BUILD_MATRIX:?BUILD_MATRIX is required}"
    : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
    : "''${GITHUB_SHA:?GITHUB_SHA is required}"
    : "''${IMAGE_REF:?IMAGE_REF is required}"
    : "''${REGISTRY_AUTH_FILE:?REGISTRY_AUTH_FILE is required}"
    : "''${VERSION:?VERSION is required}"
    cosign_command="''${FINITE_COSIGN:-cosign}"
    gh_command="''${FINITE_GH:-gh}"
    oras_command="''${FINITE_ORAS:-oras}"
    skopeo_command="''${FINITE_SKOPEO:-skopeo}"

    declare -A digests=()
    while IFS= read -r entry; do
      profile="$(jq -er '.profile' <<<"''${entry}")"
      build_input="$(jq -er '.build_input' <<<"''${entry}")"
      parent="$(jq -r '.parent // ""' <<<"''${entry}")"
      upstream_digest="$(jq -er '.upstream.digest | select(test("^sha256:[0-9a-f]{64}$"))' <<<"''${entry}")"
      metadata="$("''${skopeo_command}" inspect --retry-times 3 "docker://''${IMAGE_REF}:''${profile}-candidate")"
      digest="$(jq -er '.Digest' <<<"''${metadata}")"
      [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
      digests["''${profile}"]="''${digest}"
      expected_parent="''${upstream_digest}"
      if [[ -n "''${parent}" ]]; then
        expected_parent="''${digests[''${parent}]:-$(jq -r '.parent_digest // ""' <<<"''${entry}")}"
      fi
      [[ "''${expected_parent}" =~ ^sha256:[0-9a-f]{64}$ ]]
      jq -e --arg build_input "''${build_input}" --arg parent_digest "''${expected_parent}" \
        --arg profile "''${profile}" --arg revision "''${GITHUB_SHA}" \
        --arg upstream_digest "''${upstream_digest}" --arg version "''${VERSION}" '
        (.Labels // {}) as $labels |
        $labels["io.finite.build.input"] == $build_input and
        $labels["io.finite.build.profile"] == $profile and
        $labels["io.finite.upstream.digest"] == $upstream_digest and
        $labels["org.opencontainers.image.base.digest"] == $parent_digest and
        $labels["org.opencontainers.image.revision"] == $revision and
        $labels["org.opencontainers.image.version"] == $version
      ' <<<"''${metadata}" >/dev/null
      immutable_ref="''${IMAGE_REF}@''${digest}"
      "''${cosign_command}" verify --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity "https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml@refs/heads/main" \
        "''${immutable_ref}" >/dev/null
      "''${gh_command}" attestation verify "oci://''${immutable_ref}" --bundle-from-oci \
        --repo "''${GITHUB_REPOSITORY}" \
        --signer-workflow "''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
        --source-digest "''${GITHUB_SHA}" \
        --predicate-type https://slsa.dev/provenance/v1 >/dev/null
      "''${gh_command}" attestation verify "oci://''${immutable_ref}" --bundle-from-oci \
        --repo "''${GITHUB_REPOSITORY}" \
        --signer-workflow "''${GITHUB_REPOSITORY}/.github/workflows/attest-software-bill-of-materials.yml" \
        --source-digest "''${GITHUB_SHA}" \
        --predicate-type https://spdx.dev/Document/v2.3 >/dev/null
    done < <(jq -c '.include[]' <<<"''${BUILD_MATRIX}")

    while IFS= read -r entry; do
      profile="$(jq -er '.profile' <<<"''${entry}")"
      read -r -a tags <<<"$(jq -er '.tags' <<<"''${entry}")"
      "''${oras_command}" tag --registry-config "''${REGISTRY_AUTH_FILE}" \
        "''${IMAGE_REF}@''${digests[''${profile}]}" "''${tags[@]}"
    done < <(jq -c '.include[]' <<<"''${BUILD_MATRIX}")
  '';
}
