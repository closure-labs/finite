{
  exportArtifacts,
  installerSmoke,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "purplefin-installer-build";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    cosign
    findutils
    gh
    gnugrep
    jq
    podman
    skopeo
  ];
  text = ''
    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo 'Run this command from the Purplefin repository root' >&2
      exit 2
    }
    cd "''${repo_root}"

    : "''${CACHE_WRITE:=false}"
    : "''${GH_TOKEN:?GH_TOKEN is required to verify attestations}"
    : "''${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
    : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
    : "''${GITHUB_SHA:?GITHUB_SHA is required}"
    : "''${IMAGE_BUILDER:?IMAGE_BUILDER is required}"
    : "''${IMAGE_REF:=ghcr.io/''${GITHUB_REPOSITORY}}"
    : "''${IMAGE_TAG:=base-generic-x86_64}"
    : "''${RUNNER_TEMP:=/tmp}"

    install -d -m 0755 diagnostics output
    root_podman=(sudo ${pkgs.podman}/bin/podman)
    registry_auth_file="''${RUNNER_TEMP}/purplefin-installer-auth.json"
    cache_ref="''${IMAGE_REF}-installer-cache"
    cache_available=false
    environment_seconds=0
    image_builder_seconds=0
    smoke_seconds=0
    payload_digest=unresolved
    payload_tag=unresolved

    collect_diagnostics() {
      local status=$?
      set +e
      {
        echo '# Runner filesystem'
        df -h /
        echo
        echo '# Root Podman storage'
        "''${root_podman[@]}" system df
        echo
        echo '# Root Podman images'
        "''${root_podman[@]}" images --digests
        echo
        echo '# Installer output'
        find output -maxdepth 2 -printf '%M %u:%g %s %p\n' | sort
      } >diagnostics/runner-capacity-after.txt 2>&1
      for artifact in installer-manifest.json SHA256SUMS; do
        [[ ! -f "output/''${artifact}" ]] || cp "output/''${artifact}" diagnostics/
      done
      if [[ "''${CACHE_WRITE}" == true ]]; then
        "''${root_podman[@]}" logout --authfile "''${registry_auth_file}" ghcr.io >/dev/null 2>&1
        rm -f "''${registry_auth_file}"
      fi
      exit "''${status}"
    }
    trap collect_diagnostics EXIT

    ${exportArtifacts}/bin/purplefin-export-artifacts "''${repo_root}" >/dev/null

    metadata="$(skopeo inspect --retry-times 3 "docker://''${IMAGE_REF}:''${IMAGE_TAG}")"
    payload_digest="$(jq -er '.Digest' <<<"''${metadata}")"
    profile="$(jq -er '.Labels["io.purplefin.build.profile"]' <<<"''${metadata}")"
    source_revision="$(jq -er '.Labels["org.opencontainers.image.revision"]' <<<"''${metadata}")"
    [[ "''${payload_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${source_revision}" =~ ^[0-9a-f]{40}$ ]]
    test -f "installer/config/profiles/''${profile}.toml"
    payload_ref="''${IMAGE_REF}@''${payload_digest}"
    payload_embed_ref="''${IMAGE_REF}:''${IMAGE_TAG}"
    payload_tag="''${IMAGE_TAG}"
    cosign_identity="https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml@refs/heads/main"
    cosign verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity "''${cosign_identity}" \
      "''${payload_ref}" >/dev/null
    gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci \
      --repo "''${GITHUB_REPOSITORY}" \
      --signer-workflow "''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
      --source-digest "''${source_revision}"
    gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci \
      --repo "''${GITHUB_REPOSITORY}" \
      --signer-workflow "''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
      --source-digest "''${source_revision}" \
      --predicate-type https://spdx.dev/Document/v2.3

    auth_args=()
    cache_args=(--layers)
    if [[ "''${CACHE_WRITE}" == true ]]; then
      : "''${GHCR_TOKEN:?GHCR_TOKEN is required when CACHE_WRITE=true}"
      printf '%s' "''${GHCR_TOKEN}" |
        "''${root_podman[@]}" login \
          --authfile "''${registry_auth_file}" \
          ghcr.io \
          --username "''${GITHUB_ACTOR}" \
          --password-stdin
      auth_args+=(--authfile "''${registry_auth_file}")
    fi
    if skopeo list-tags "docker://''${cache_ref}" >/dev/null 2>&1; then
      cache_available=true
      cache_args+=(--cache-from "''${cache_ref}" --cache-ttl 336h)
    fi
    if [[ "''${CACHE_WRITE}" == true ]]; then
      cache_args+=(--cache-to "''${cache_ref}")
    fi

    {
      echo '# Runner filesystem'
      df -h /
      echo
      echo '# Root Podman storage'
      "''${root_podman[@]}" system df
    } | tee diagnostics/runner-capacity-before.txt

    started="''${SECONDS}"
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${payload_ref}"
    "''${root_podman[@]}" tag "''${payload_ref}" "''${payload_embed_ref}"
    "''${root_podman[@]}" build "''${auth_args[@]}" "''${cache_args[@]}" \
      --file installer/Containerfile \
      --pull=never \
      --build-context installer-rootfs=installer/rootfs \
      --build-arg "BASE_REF=''${payload_ref}" \
      --build-arg "INSTALLER_PAYLOAD_SOURCE_REF=''${payload_embed_ref}" \
      --build-arg "INSTALLER_PAYLOAD_TARGET_REF=''${payload_ref}" \
      --tag "localhost/purplefin-installer:''${GITHUB_SHA}" \
      . 2>&1 | tee diagnostics/installer-environment.log
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${IMAGE_BUILDER}"
    environment_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    "''${root_podman[@]}" run --rm --privileged \
      --security-opt label=disable \
      --volume "''${PWD}/output:/output" \
      --volume /var/lib/containers/storage:/var/lib/containers/storage \
      "''${IMAGE_BUILDER}" \
      build \
        --bootc-ref "localhost/purplefin-installer:''${GITHUB_SHA}" \
        --bootc-installer-payload-ref "''${payload_embed_ref}" \
        --bootc-default-fs ext4 \
        bootc-generic-iso 2>&1 | tee diagnostics/image-builder.log
    sudo chown -R "$(id -u):$(id -g)" output
    iso="$(find output -type f -name '*.iso' -print -quit)"
    [[ -n "''${iso}" ]]
    final_iso="output/purplefin-''${IMAGE_TAG}-$(<VERSION).iso"
    mv "''${iso}" "''${final_iso}"
    iso_sha256="$(sha256sum "''${final_iso}" | cut -d' ' -f1)"
    installer_image_id="$(
      "''${root_podman[@]}" image inspect \
        --format '{{.Id}}' \
        "localhost/purplefin-installer:''${GITHUB_SHA}"
    )"
    installer_image_id="''${installer_image_id#sha256:}"
    [[ "''${installer_image_id}" =~ ^[0-9a-f]{64}$ ]]
    installer_image_id="sha256:''${installer_image_id}"
    image_builder_digest="''${IMAGE_BUILDER##*@}"
    [[ "''${image_builder_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    jq -n \
      --arg image_builder "''${IMAGE_BUILDER}" \
      --arg image_builder_digest "''${image_builder_digest}" \
      --arg installer_environment_image_id "''${installer_image_id}" \
      --arg iso "''${final_iso##*/}" \
      --arg iso_sha256 "''${iso_sha256}" \
      --arg payload "''${payload_ref}" \
      --arg payload_digest "''${payload_digest}" \
      --arg payload_sbom_predicate 'https://spdx.dev/Document/v2.3' \
      --arg payload_signer_workflow "''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
      --arg payload_source_revision "''${source_revision}" \
      --arg source_commit "''${GITHUB_SHA}" \
      --arg source_repository "''${GITHUB_REPOSITORY}" \
      --arg version "$(<VERSION)" \
      '{
        schema_version: 1,
        source: {repository: $source_repository, commit: $source_commit},
        version: $version,
        iso: {name: $iso, sha256: $iso_sha256},
        installer_environment: {image_id: $installer_environment_image_id},
        image_builder: {reference: $image_builder, digest: $image_builder_digest},
        payload: {
          reference: $payload,
          digest: $payload_digest,
          source_revision: $payload_source_revision,
          sbom: {
            predicate_type: $payload_sbom_predicate,
            signer_workflow: $payload_signer_workflow
          }
        }
      }' >output/installer-manifest.json
    sha256sum "''${final_iso}" output/installer-manifest.json >output/SHA256SUMS
    image_builder_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    ${installerSmoke}/bin/purplefin-installer-smoke "''${final_iso}" 2>&1 |
      tee diagnostics/qemu-smoke.log
    smoke_seconds=$((SECONDS - started))

    if [[ -n "''${GITHUB_OUTPUT:-}" ]]; then
      {
        echo "iso-sha256=''${iso_sha256}"
        echo "payload-digest=''${payload_digest}"
        echo "payload-tag=''${payload_tag}"
      } >>"''${GITHUB_OUTPUT}"
    fi
    if [[ -n "''${GITHUB_STEP_SUMMARY:-}" ]]; then
      {
        echo '### Installer validation'
        echo
        echo '| Property | Value |'
        echo '| --- | --- |'
        echo "| Payload tag | \`''${payload_tag}\` |"
        echo "| Payload digest | \`''${payload_digest}\` |"
        echo "| Installer image | \`''${installer_image_id}\` |"
        echo "| ISO SHA-256 | \`''${iso_sha256}\` |"
        echo "| Registry cache available | \`''${cache_available}\` |"
        echo "| Registry cache updated | \`''${CACHE_WRITE}\` |"
        echo "| Environment build | \`success\` (''${environment_seconds}s) |"
        echo "| Image Builder | \`success\` (''${image_builder_seconds}s) |"
        echo "| QEMU smoke boot | \`success\` (''${smoke_seconds}s) |"
      } >>"''${GITHUB_STEP_SUMMARY}"
    fi
  '';
}
