{
  fedoraBootc,
  generated,
  imageBuilder,
  installerE2e,
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
    gnutar
    gnugrep
    gnused
    jq
    podman
    skopeo
  ];
  text = ''
    export PURPLEFIN_GENERATED_ROOT=${generated}
    export PURPLEFIN_INSTALLER_BASE_REF=${fedoraBootc.image}@${fedoraBootc.digest}
    export PURPLEFIN_IMAGE_BUILDER_REF=${imageBuilder.image}@${imageBuilder.digest}
    export PURPLEFIN_INSTALLER_E2E_APP=${installerE2e}/bin/purplefin-installer-e2e
    export PURPLEFIN_INSTALLER_SMOKE=${installerSmoke}/bin/purplefin-installer-smoke
    export PURPLEFIN_PODMAN=${pkgs.podman}/bin/podman
    set -euo pipefail

    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo 'Run this command from the Purplefin repository root' >&2
      exit 2
    }
    cd "''${repo_root}" || exit

    : "''${CACHE_WRITE:=false}"
    : "''${PURPLEFIN_INSTALLER_E2E:=false}"
    [[ "''${PURPLEFIN_INSTALLER_E2E}" == true || "''${PURPLEFIN_INSTALLER_E2E}" == false ]] || {
      echo 'PURPLEFIN_INSTALLER_E2E must be true or false' >&2
      exit 2
    }
    : "''${GH_TOKEN:?GH_TOKEN is required to verify attestations}"
    : "''${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
    : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
    : "''${GITHUB_SHA:?GITHUB_SHA is required}"
    image_builder="''${PURPLEFIN_IMAGE_BUILDER_REF:?PURPLEFIN_IMAGE_BUILDER_REF is required}"
    installer_base="''${PURPLEFIN_INSTALLER_BASE_REF:?PURPLEFIN_INSTALLER_BASE_REF is required}"
    squashfs_stage="''${repo_root}/installer/osbuild-stages/org.osbuild.squashfs"
    squashfs_stage_lock="''${repo_root}/installer/osbuild-stages/lock.json"
    test -x "''${squashfs_stage}"
    test -f "''${squashfs_stage_lock}"
    image_builder_digest="''${image_builder##*@}"
    locked_image_builder_digest="$(jq -er .image_builder_digest "''${squashfs_stage_lock}")"
    locked_squashfs_stage_sha256="$(jq -er .override_sha256 "''${squashfs_stage_lock}")"
    upstream_squashfs_stage_sha256="$(jq -er .upstream_sha256 "''${squashfs_stage_lock}")"
    squashfs_compression_level="$(jq -er .zstd_compression_level "''${squashfs_stage_lock}")"
    [[ "''${image_builder_digest}" == "''${locked_image_builder_digest}" ]] || {
      echo 'The squashfs stage override has not been audited for the pinned Image Builder digest' >&2
      exit 2
    }
    actual_override_sha256="$(sha256sum "''${squashfs_stage}" | cut -d' ' -f1)"
    [[ "''${actual_override_sha256}" == "''${locked_squashfs_stage_sha256}" ]] || {
      echo 'The squashfs stage override differs from its audited lock' >&2
      exit 2
    }
    [[ "''${upstream_squashfs_stage_sha256}" =~ ^[0-9a-f]{64}$ ]]
    [[ "''${squashfs_compression_level}" =~ ^[0-9]+$ ]]
    : "''${IMAGE_REF:=ghcr.io/''${GITHUB_REPOSITORY}}"
    : "''${IMAGE_TAG:=base-generic-x86_64}"
    : "''${RUNNER_TEMP:=/tmp}"

    install -d -m 0755 diagnostics output
    root_podman=(sudo "''${PURPLEFIN_PODMAN:?PURPLEFIN_PODMAN is required}")
    registry_auth_file="''${RUNNER_TEMP}/purplefin-installer-auth.json"
    cosign_config_dir="''${RUNNER_TEMP}/purplefin-installer-cosign"
    cache_ref="''${IMAGE_REF}-installer-cache"
    cache_available=false
    environment_cache_hit=false
    environment_cache_ref=unresolved
    environment_input=unresolved
    environment_seconds=0
    image_builder_seconds=0
    image_builder_pull_pid=
    image_builder_cache_root="''${RUNNER_TEMP}/purplefin-image-builder-cache"
    install -d -m 0755 \
      "''${image_builder_cache_root}/rpmmd" \
      "''${image_builder_cache_root}/store"
    smoke_seconds=0
    e2e_seconds=0
    payload_digest=unresolved
    payload_tag=unresolved

    collect_diagnostics() {
      local status=$?
      set +e
      if [[ -n "''${image_builder_pull_pid}" ]]; then
        kill -TERM "''${image_builder_pull_pid}" >/dev/null 2>&1 || true
        wait "''${image_builder_pull_pid}" >/dev/null 2>&1 || true
      fi
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
        rm -rf "''${cosign_config_dir}"
      fi
      exit "''${status}"
    }
    trap collect_diagnostics EXIT

    metadata="$(skopeo inspect --retry-times 3 "docker://''${IMAGE_REF}:''${IMAGE_TAG}")"
    payload_digest="$(jq -er '.Digest' <<<"''${metadata}")"
    profile="$(jq -er '.Labels["io.purplefin.build.profile"]' <<<"''${metadata}")"
    source_revision="$(jq -er '.Labels["org.opencontainers.image.revision"]' <<<"''${metadata}")"
    [[ "''${payload_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${source_revision}" =~ ^[0-9a-f]{40}$ ]]
    test -f "''${PURPLEFIN_GENERATED_ROOT:?PURPLEFIN_GENERATED_ROOT is required}/installer/config/profiles/''${profile}.toml"
    payload_ref="''${IMAGE_REF}@''${payload_digest}"
    payload_embed_ref="''${IMAGE_REF}:''${IMAGE_TAG}"
    payload_tag="''${IMAGE_TAG}"
    installer_context_digest="$(
      tar \
        --create \
        --file=- \
        --format=gnu \
        --group=0 \
        --mtime='UTC 1970-01-01' \
        --numeric-owner \
        --owner=0 \
        --sort=name \
        installer/Containerfile installer/rootfs |
        sha256sum |
        cut -d' ' -f1
    )"
    environment_input="$(
      printf '%s\n' \
        'purplefin-installer-environment-v2' \
        "base=''${installer_base}" \
        "context=''${installer_context_digest}" \
        "payload=''${payload_ref}" \
        "payload-embed=''${payload_embed_ref}" |
        sha256sum |
        cut -d' ' -f1
    )"
    [[ "''${environment_input}" =~ ^[0-9a-f]{64}$ ]]
    environment_cache_ref="''${cache_ref}:environment-''${environment_input}"
    cosign_identity="https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml@refs/heads/main"
    environment_cache_identity_regex="^https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/(build|build-installer)\\.yml@refs/heads/main$"
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
      --signer-workflow "''${GITHUB_REPOSITORY}/.github/workflows/attest-software-bill-of-materials.yml" \
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
      install -d -m 0700 "''${cosign_config_dir}"
      printf '%s' "''${GHCR_TOKEN}" |
        DOCKER_CONFIG="''${cosign_config_dir}" cosign login \
          ghcr.io \
          --username "''${GITHUB_ACTOR}" \
          --password-stdin
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
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${image_builder}" \
      >diagnostics/image-builder-pull.log 2>&1 &
    image_builder_pull_pid=$!
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${installer_base}"
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${payload_ref}"
    "''${root_podman[@]}" tag "''${payload_ref}" "''${payload_embed_ref}"
    environment_cache_metadata="$({
      skopeo inspect --retry-times 3 "docker://''${environment_cache_ref}" 2>/dev/null || true
    })"
    environment_cache_digest="$(jq -r '.Digest // empty' <<<"''${environment_cache_metadata}")"
    immutable_environment_cache_ref="''${cache_ref}@''${environment_cache_digest}"
    if [[ "''${environment_cache_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] &&
      jq -e \
        --arg input "''${environment_input}" \
        '(.Labels // {})["io.purplefin.installer.input"] == $input' \
        <<<"''${environment_cache_metadata}" >/dev/null &&
      cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity-regexp "''${environment_cache_identity_regex}" \
        "''${immutable_environment_cache_ref}" >/dev/null 2>&1; then
      environment_cache_hit=true
      echo "Reusing exact installer environment ''${immutable_environment_cache_ref}" |
        tee diagnostics/installer-environment.log
      "''${root_podman[@]}" pull "''${auth_args[@]}" "''${immutable_environment_cache_ref}"
      "''${root_podman[@]}" tag \
        "''${immutable_environment_cache_ref}" \
        "localhost/purplefin-installer:''${GITHUB_SHA}"
    else
      "''${root_podman[@]}" build "''${auth_args[@]}" "''${cache_args[@]}" \
        --file installer/Containerfile \
        --pull=never \
        --security-opt label=disable \
        --build-context installer-rootfs=installer/rootfs \
        --build-arg "BASE_REF=''${installer_base}" \
        --build-arg "INSTALLER_PAYLOAD_SOURCE_REF=''${payload_embed_ref}" \
        --build-arg "INSTALLER_PAYLOAD_TARGET_REF=''${payload_ref}" \
        --label "io.purplefin.installer.input=''${environment_input}" \
        --tag "localhost/purplefin-installer:''${GITHUB_SHA}" \
        installer 2>&1 | tee diagnostics/installer-environment.log
      if [[ "''${CACHE_WRITE}" == true ]]; then
        "''${root_podman[@]}" tag \
          "localhost/purplefin-installer:''${GITHUB_SHA}" \
          "''${environment_cache_ref}"
        "''${root_podman[@]}" push \
          "''${auth_args[@]}" \
          "''${environment_cache_ref}" 2>&1 |
          tee -a diagnostics/installer-environment.log
        environment_cache_digest="$(
          skopeo inspect --retry-times 3 "docker://''${environment_cache_ref}" |
            jq -er .Digest
        )"
        [[ "''${environment_cache_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
        DOCKER_CONFIG="''${cosign_config_dir}" cosign sign --yes \
          "''${cache_ref}@''${environment_cache_digest}"
      fi
    fi
    set +e
    wait "''${image_builder_pull_pid}"
    image_builder_pull_status=$?
    set -e
    image_builder_pull_pid=
    cat diagnostics/image-builder-pull.log
    [[ "''${image_builder_pull_status}" == 0 ]] || {
      echo "Image Builder pull failed with status ''${image_builder_pull_status}" >&2
      exit "''${image_builder_pull_status}"
    }
    actual_squashfs_stage_sha256="$(
      "''${root_podman[@]}" run --rm \
        --entrypoint /usr/bin/sha256sum \
        "''${image_builder}" \
        /usr/lib/osbuild/stages/org.osbuild.squashfs |
        cut -d' ' -f1
    )"
    [[ "''${actual_squashfs_stage_sha256}" == "''${upstream_squashfs_stage_sha256}" ]] || {
      echo 'The pinned Image Builder squashfs stage differs from the audited override source' >&2
      exit 2
    }
    environment_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    "''${root_podman[@]}" run --rm --privileged \
      --security-opt label=disable \
      --volume "''${PWD}/output:/output" \
      --volume /var/lib/containers/storage:/var/lib/containers/storage \
      --volume "''${image_builder_cache_root}/store:/var/cache/image-builder/store" \
      --volume "''${image_builder_cache_root}/rpmmd:/var/cache/image-builder/rpmmd" \
      --volume "''${squashfs_stage}:/usr/lib/osbuild/stages/org.osbuild.squashfs:ro" \
      "''${image_builder}" \
      build \
        --cache /var/cache/image-builder/store \
        --rpmmd-cache /var/cache/image-builder/rpmmd \
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
    [[ "''${image_builder_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    jq -n \
      --arg image_builder "''${image_builder}" \
      --arg image_builder_digest "''${image_builder_digest}" \
      --arg squashfs_override_sha256 "''${locked_squashfs_stage_sha256}" \
      --arg squashfs_stage_sha256 "''${upstream_squashfs_stage_sha256}" \
      --argjson squashfs_zstd_level "''${squashfs_compression_level}" \
      --arg installer_base "''${installer_base}" \
      --arg installer_base_digest "''${installer_base##*@}" \
      --arg installer_environment_input "''${environment_input}" \
      --arg installer_environment_image_id "''${installer_image_id}" \
      --argjson installer_environment_cache_hit "''${environment_cache_hit}" \
      --arg iso "''${final_iso##*/}" \
      --arg iso_sha256 "''${iso_sha256}" \
      --arg payload "''${payload_ref}" \
      --arg payload_digest "''${payload_digest}" \
      --arg payload_sbom_predicate 'https://spdx.dev/Document/v2.3' \
      --arg payload_signer_workflow "''${GITHUB_REPOSITORY}/.github/workflows/attest-software-bill-of-materials.yml" \
      --arg payload_source_revision "''${source_revision}" \
      --arg source_commit "''${GITHUB_SHA}" \
      --arg source_repository "''${GITHUB_REPOSITORY}" \
      --arg version "$(<VERSION)" \
      '{
        schema_version: 1,
        source: {repository: $source_repository, commit: $source_commit},
        version: $version,
        iso: {name: $iso, sha256: $iso_sha256},
        installer_environment: {
          base: {reference: $installer_base, digest: $installer_base_digest},
          image_id: $installer_environment_image_id,
          input: $installer_environment_input,
          cache_hit: $installer_environment_cache_hit
        },
        image_builder: {
          reference: $image_builder,
          digest: $image_builder_digest,
          squashfs: {
            method: "zstd",
            level: $squashfs_zstd_level,
            override_sha256: $squashfs_override_sha256,
            upstream_stage_sha256: $squashfs_stage_sha256
          }
        },
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
    {
      printf '%s  %s\n' "''${iso_sha256}" "''${final_iso}"
      sha256sum output/installer-manifest.json
    } >output/SHA256SUMS
    image_builder_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    "''${PURPLEFIN_INSTALLER_SMOKE:?PURPLEFIN_INSTALLER_SMOKE is required}" "''${final_iso}" 2>&1 |
      tee diagnostics/qemu-smoke.log
    smoke_seconds=$((SECONDS - started))

    if [[ "''${PURPLEFIN_INSTALLER_E2E}" == true ]]; then
      started="''${SECONDS}"
      e2e_root="$(mktemp -d -p "''${RUNNER_TEMP}" purplefin-installer-e2e.XXXXXX)"
      e2e_kickstart="''${e2e_root}/purplefin-ci.ks"
      sed \
        -e "s|@@INSTALLER_PAYLOAD_SOURCE_REF@@|''${payload_embed_ref}|g" \
        -e "s|@@INSTALLER_PAYLOAD_TARGET_REF@@|''${payload_ref}|g" \
        installer/ci-unattended.ks.in >"''${e2e_kickstart}"
      "''${PURPLEFIN_INSTALLER_E2E_APP:?PURPLEFIN_INSTALLER_E2E_APP is required}" \
        "''${final_iso}" "''${e2e_kickstart}" 2>&1 | tee diagnostics/qemu-e2e.log
      for e2e_log in output/qemu-*.log; do
        [[ ! -f "''${e2e_log}" ]] || cp "''${e2e_log}" diagnostics/
      done
      rm -rf -- "''${e2e_root}"
      e2e_seconds=$((SECONDS - started))
    fi

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
        echo "| Installer input | \`''${environment_input}\` |"
        echo "| Exact environment cache hit | \`''${environment_cache_hit}\` |"
        echo "| ISO SHA-256 | \`''${iso_sha256}\` |"
        echo "| Registry cache available | \`''${cache_available}\` |"
        echo "| Registry cache updated | \`''${CACHE_WRITE}\` |"
        echo "| Environment build | \`success\` (''${environment_seconds}s) |"
        echo "| Image Builder | \`success\` (''${image_builder_seconds}s) |"
        echo "| QEMU smoke boot | \`success\` (''${smoke_seconds}s) |"
        echo "| Unattended install and boot | \`''${PURPLEFIN_INSTALLER_E2E}\` (''${e2e_seconds}s) |"
      } >>"''${GITHUB_STEP_SUMMARY}"
    fi
  '';
}
