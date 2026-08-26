{
  bootcInstallerBundle,
  dakotaInstallerLock,
  dakotaIsoSource,
  generated,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "finite-installer-build";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    cosign
    dosfstools
    file
    findutils
    gh
    gnutar
    gnugrep
    gnused
    isomd5sum
    jq
    mtools
    oras
    podman
    python3
    rsync
    skopeo
    squashfsTools
    util-linux
    xorriso
  ];
  text = ''
    export FINITE_GENERATED_ROOT=${generated}
    export FINITE_DAKOTA_ISO_SOURCE=${dakotaIsoSource}
    export FINITE_BOOTC_INSTALLER_BUNDLE=${bootcInstallerBundle}
    export FINITE_DAKOTA_ISO_REVISION=${dakotaInstallerLock.iso_source.revision}
    export FINITE_BOOTC_INSTALLER_VERSION=${dakotaInstallerLock.installer.version}
    export FINITE_BOOTC_INSTALLER_SHA256=${dakotaInstallerLock.installer.sha256}
    export FINITE_DAKOTA_LIVE_IMAGE=${dakotaInstallerLock.live_image.image}
    export FINITE_DAKOTA_LIVE_TAG=${dakotaInstallerLock.live_image.tag}
    export FINITE_DAKOTA_LIVE_DIGEST=${dakotaInstallerLock.live_image.digest}
    export FINITE_DAKOTA_LIVE_ISSUER=${dakotaInstallerLock.live_image.cosign.issuer}
    export FINITE_DAKOTA_LIVE_IDENTITY=${dakotaInstallerLock.live_image.cosign.identity}
    export FINITE_INSTALLER_BUILDER_IMAGE=${dakotaInstallerLock.builder.image}
    export FINITE_INSTALLER_BUILDER_DIGEST=${dakotaInstallerLock.builder.digest}
    export FINITE_PODMAN=${pkgs.podman}/bin/podman
    set -euo pipefail

    seed_input() {
      local source_revision=$1 installer_sha256=$2 overlay_digest=$3 live_digest=$4
      printf '%s\n' \
        'finite-dakota-netinstaller-seed-v2' \
        "source-revision=''${source_revision}" \
        "installer-sha256=''${installer_sha256}" \
        "builder-digest=''${FINITE_INSTALLER_BUILDER_DIGEST}" \
        "overlay=''${overlay_digest}" \
        "live-digest=''${live_digest}" |
        sha256sum |
        cut -d' ' -f1
    }

    if [[ "''${1:-}" == cache-input ]]; then
      [[ $# == 5 ]] || {
        echo 'usage: finite-installer-build cache-input SOURCE_REVISION INSTALLER_SHA256 OVERLAY_DIGEST LIVE_DIGEST' >&2
        exit 2
      }
      seed_input "$2" "$3" "$4" "$5"
      exit
    fi
    mode="''${1:-build}"
    [[ "''${mode}" == build || "''${mode}" == cache-key ]] || {
      echo 'usage: finite-installer-build [cache-key | cache-input SOURCE_REVISION INSTALLER_SHA256 OVERLAY_DIGEST LIVE_DIGEST]' >&2
      exit 2
    }
    [[ $# -le 1 ]]

    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo 'Run this command from the Finite repository root' >&2
      exit 2
    }
    cd "''${repo_root}"

    overlay_digest="$({
      tar --create --file=- --format=gnu --group=0 --mtime='UTC 1970-01-01' \
        --numeric-owner --owner=0 --sort=name \
        installer/live installer/prepare-dakota-iso-source \
        lib/installer-application.nix \
        modules/aspects/base/rootfs/usr/share/finite/finite-logo.png
    } | sha256sum | cut -d' ' -f1)"
    if [[ "''${mode}" == cache-key ]]; then
      seed_input "''${FINITE_DAKOTA_ISO_REVISION}" \
        "''${FINITE_BOOTC_INSTALLER_SHA256}" "''${overlay_digest}" \
        "''${FINITE_DAKOTA_LIVE_DIGEST}"
      exit
    fi

    : "''${CACHE_WRITE:=false}"
    : "''${GH_TOKEN:?GH_TOKEN is required to verify attestations}"
    : "''${GHCR_TOKEN:?GHCR_TOKEN is required to inspect the Finite payload}"
    : "''${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
    : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
    : "''${GITHUB_SHA:?GITHUB_SHA is required}"
    : "''${IMAGE_REF:=ghcr.io/''${GITHUB_REPOSITORY}}"
    : "''${IMAGE_TAG:=bluefin-generic}"
    : "''${RUNNER_TEMP:=/tmp}"
    install -d -m 0755 diagnostics output
    command -v sudo >/dev/null 2>&1 || {
      echo 'sudo is required to build the installer' >&2
      exit 1
    }
    root_exec=(sudo)
    root_podman=("''${root_exec[@]}" "''${FINITE_PODMAN}")
    registry_auth_file="''${RUNNER_TEMP}/finite-installer-auth.json"
    cosign_config_dir="''${RUNNER_TEMP}/finite-installer-cosign"
    source_root="''${RUNNER_TEMP}/finite-dakota-iso-source"
    work_root="''${RUNNER_TEMP}/finite-dakota-iso-work"
    seed_local="localhost/finite-netinstaller-seed:''${GITHUB_SHA}"
    seed_repository="''${IMAGE_REF}-installer-seed"
    environment_seconds=0
    iso_seconds=0
    seed_cache_hit=false
    seed_cache_source=miss
    seed_published=false
    seed_digest=unresolved
    seed_registry_digest=
    payload_digest=unresolved
    payload_tag="''${IMAGE_TAG}"

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
        echo '# Installer output'
        find output -maxdepth 2 -printf '%M %u:%g %s %p\n' | sort
      } >diagnostics/runner-capacity-after.txt 2>&1
      for artifact in installer-manifest.json SHA256SUMS; do
        [[ ! -f "output/''${artifact}" ]] || cp "output/''${artifact}" diagnostics/
      done
      skopeo logout --authfile "''${registry_auth_file}" ghcr.io >/dev/null 2>&1 || true
      rm -f "''${registry_auth_file}"
      rm -rf "''${cosign_config_dir}"
      exit "''${status}"
    }
    trap collect_diagnostics EXIT

    printf '%s' "''${GHCR_TOKEN}" |
      skopeo login --authfile "''${registry_auth_file}" ghcr.io \
        --username "''${GITHUB_ACTOR}" --password-stdin
    install -d -m 0700 "''${cosign_config_dir}"
    printf '%s' "''${GHCR_TOKEN}" |
      DOCKER_CONFIG="''${cosign_config_dir}" cosign login ghcr.io \
        --username "''${GITHUB_ACTOR}" --password-stdin
    auth_args=(--authfile "''${registry_auth_file}")

    metadata="$(
      skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 \
        "docker://''${IMAGE_REF}:''${IMAGE_TAG}" \
        2>diagnostics/payload-inspect.log
    )"
    payload_digest="$(jq -er '.Digest' <<<"''${metadata}")"
    payload_architecture="$(jq -er '.Architecture' <<<"''${metadata}")"
    profile="$(jq -er '.Labels["io.finite.build.profile"]' <<<"''${metadata}")"
    foundation="$(jq -er '.Labels["io.finite.foundation"]' <<<"''${metadata}")"
    source_revision="$(jq -er '.Labels["org.opencontainers.image.revision"]' <<<"''${metadata}")"
    payload_source_url="$(jq -er '.Labels["org.opencontainers.image.source"]' <<<"''${metadata}")"
    payload_source_repository="''${payload_source_url#https://github.com/}"
    payload_source_repository="''${payload_source_repository%.git}"
    [[ "''${payload_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${payload_architecture}" == amd64 ]]
    [[ "''${source_revision}" =~ ^[0-9a-f]{40}$ ]]
    [[ "''${payload_source_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
    [[ "''${foundation}" == bluefin || "''${foundation}" == bluefin-dx ]]
    [[ "''${profile}" == "''${foundation}-generic" ]]
    jq -e --arg profile "''${profile}" '.profiles[$profile]' \
      "''${FINITE_GENERATED_ROOT}/bootc/generated/profile-catalog.json" >/dev/null
    payload_ref="''${IMAGE_REF}@''${payload_digest}"
    payload_update_ref="''${IMAGE_REF}:''${IMAGE_TAG}"
    skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 --raw \
      "docker://''${payload_ref}" >diagnostics/payload-manifest.json

    cosign_identity="https://github.com/''${payload_source_repository}/.github/workflows/build-profile.yml@refs/heads/main"
    DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity "''${cosign_identity}" \
      "''${payload_ref}" >/dev/null
    DOCKER_CONFIG="''${cosign_config_dir}" gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci --repo "''${payload_source_repository}" \
      --signer-workflow "''${payload_source_repository}/.github/workflows/build-profile.yml" \
      --source-digest "''${source_revision}"
    DOCKER_CONFIG="''${cosign_config_dir}" gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci --repo "''${payload_source_repository}" \
      --signer-workflow "''${payload_source_repository}/.github/workflows/attest-software-bill-of-materials.yml" \
      --source-digest "''${source_revision}" \
      --predicate-type https://spdx.dev/Document/v2.3

    dakota_live_ref="''${FINITE_DAKOTA_LIVE_IMAGE}@''${FINITE_DAKOTA_LIVE_DIGEST}"
    dakota_live_build_ref="''${FINITE_DAKOTA_LIVE_IMAGE}:''${FINITE_DAKOTA_LIVE_TAG}@''${FINITE_DAKOTA_LIVE_DIGEST}"
    DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
      --certificate-oidc-issuer "''${FINITE_DAKOTA_LIVE_ISSUER}" \
      --certificate-identity "''${FINITE_DAKOTA_LIVE_IDENTITY}" \
      "''${dakota_live_ref}" >/dev/null

    installer_seed_input="$(
      seed_input "''${FINITE_DAKOTA_ISO_REVISION}" \
        "''${FINITE_BOOTC_INSTALLER_SHA256}" "''${overlay_digest}" \
        "''${FINITE_DAKOTA_LIVE_DIGEST}"
    )"
    [[ "''${installer_seed_input}" =~ ^[0-9a-f]{64}$ ]]
    seed_tag="dakota-''${installer_seed_input}"
    seed_tag_ref="''${seed_repository}:''${seed_tag}"

    {
      echo '# Runner filesystem'
      df -h /
      echo
      echo '# Root Podman storage'
      "''${root_podman[@]}" system df
    } | tee diagnostics/runner-capacity-before.txt

    rm -rf "''${source_root}" "''${work_root}"
    install -d -m 0755 "''${work_root}"
    installer/prepare-dakota-iso-source \
      "''${FINITE_DAKOTA_ISO_SOURCE}" "''${source_root}" \
      "''${FINITE_BOOTC_INSTALLER_BUNDLE}" "''${FINITE_BOOTC_INSTALLER_SHA256}" \
      modules/aspects/base/rootfs/usr/share/finite/finite-logo.png \
      "''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}" \
      2>&1 | tee diagnostics/source-prepare.log

    target_config="''${work_root}/target.json"
    jq -n \
      --arg payload_reference "''${payload_ref}" \
      --arg payload_digest "''${payload_digest}" \
      --arg update_reference "''${payload_update_ref}" \
      '{
        schema: 1,
        payload_reference: $payload_reference,
        payload_digest: $payload_digest,
        update_reference: $update_reference
      }' >"''${target_config}"
    jq -e '
      .schema == 1 and
      ((.payload_reference | split("@")[1]) == .payload_digest) and
      (.update_reference | test(":[A-Za-z0-9._-]+$"))
    ' "''${target_config}" >/dev/null

    seed_cache_dir="''${FINITE_INSTALLER_SEED_CACHE_DIR:-''${work_root}/seed-cache}"
    install -d -m 0755 "''${seed_cache_dir}"
    squashfs="''${seed_cache_dir}/finite-live.squashfs"
    boot_tar="''${seed_cache_dir}/finite-boot-files.tar"
    seed_manifest="''${seed_cache_dir}/seed-manifest.json"
    seed_preflight="''${seed_cache_dir}/seed-preflight.log"

    validate_seed_cache() {
      local directory=$1 expected actual name
      jq -e --arg input "''${installer_seed_input}" '
        .schema == 1 and
        .input == $input and
        .compression == "lz4-fast" and
        .payload_specific == false and
        (.files["finite-live.squashfs"] | test("^[0-9a-f]{64}$")) and
        (.files["finite-boot-files.tar"] | test("^[0-9a-f]{64}$")) and
        (.files["seed-preflight.log"] | test("^[0-9a-f]{64}$"))
      ' "''${directory}/seed-manifest.json" >/dev/null || return 1
      for name in finite-live.squashfs finite-boot-files.tar seed-preflight.log; do
        [[ -s "''${directory}/''${name}" ]] || return 1
        expected="$(jq -er --arg name "''${name}" '.files[$name]' \
          "''${directory}/seed-manifest.json")"
        actual="$(sha256sum "''${directory}/''${name}" | cut -d' ' -f1)"
        [[ "''${actual}" == "''${expected}" ]] || return 1
      done
      grep -qF 'FINITE_INSTALLER_PREFLIGHT=ok mode=assembly' \
        "''${directory}/seed-preflight.log"
    }

    started="''${SECONDS}"
    local_seed_available=false
    if validate_seed_cache "''${seed_cache_dir}"; then
      local_seed_available=true
      seed_cache_hit=true
      seed_cache_source=github-actions
    else
      rm -f -- "''${squashfs}" "''${boot_tar}" "''${seed_manifest}" "''${seed_preflight}"
    fi

    registry_seed_available=false
    if seed_registry_digest="$(oras resolve --registry-config "''${registry_auth_file}" \
      "''${seed_tag_ref}" 2>diagnostics/seed-inspect.log)"; then
      [[ "''${seed_registry_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
      seed_registry_ref="''${seed_repository}@''${seed_registry_digest}"
      DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity-regexp \
          "^https://github.com/''${GITHUB_REPOSITORY}/\\.github/workflows/(build|build-installer)\\.yml@refs/heads/main$" \
        "''${seed_registry_ref}" >/dev/null
      registry_seed_available=true
    fi

    if [[ "''${local_seed_available}" != true && "''${registry_seed_available}" == true ]]; then
      oras pull --registry-config "''${registry_auth_file}" \
        --output "''${seed_cache_dir}" "''${seed_registry_ref}" \
        2>&1 | tee diagnostics/seed-pull.log
      validate_seed_cache "''${seed_cache_dir}"
      seed_cache_hit=true
      seed_cache_source=ghcr
    elif [[ "''${local_seed_available}" != true ]]; then
      # Pull the exact tag+digest spelling used by the Containerfile so
      # --pull=never resolves it without a mutable-name fallback.
      "''${root_podman[@]}" pull --retry 3 "''${dakota_live_build_ref}"
      "''${root_podman[@]}" pull --retry 3 \
        "''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}"
      (
        cd "''${source_root}"
        "''${root_podman[@]}" build "''${auth_args[@]}" --layers=false \
          --cap-add sys_admin --security-opt label=disable --pull=never \
          --build-arg DEBUG=0 --build-arg INSTALLER_CHANNEL=stable \
          --build-arg LIVE_ROOT=dakota --build-arg REGISTRY=projectbluefin \
          --build-arg TAG="''${FINITE_DAKOTA_LIVE_TAG}@''${FINITE_DAKOTA_LIVE_DIGEST}" \
          --build-arg TARGET=finite \
          --label "io.finite.installer.seed.input=''${installer_seed_input}" \
          --label 'io.finite.installer.network-required=true' \
          --tag "''${seed_local}" --file live/Containerfile live
      ) 2>&1 | tee diagnostics/live-environment.log

      "''${root_podman[@]}" run --rm --network host \
        --security-opt label=disable \
        --volume "''${target_config}:/run/finite-installer-target.json:ro" \
        --entrypoint /usr/bin/bash "''${seed_local}" -ceu \
        '/usr/local/sbin/finite-installer-apply-target /run/finite-installer-target.json
         /usr/local/sbin/finite-installer-preflight assembly \
           /etc/bootc-installer/ci-autoinstall.json' \
        2>&1 | tee diagnostics/seed-preflight.log "''${seed_preflight}"

      "''${root_exec[@]}" env PATH="''${PATH}" SUPERISO_COMPRESSION=lz4 \
        SUPERISO_TMPDIR="''${work_root}" \
        bash "''${source_root}/scripts/build-live-squashfs.sh" \
          "''${seed_local}" "''${squashfs}" "''${boot_tar}" \
        2>&1 | tee diagnostics/squashfs-build.log
      "''${root_exec[@]}" chown "$(id -u):$(id -g)" \
        "''${squashfs}" "''${boot_tar}"

      jq -n \
        --arg input "''${installer_seed_input}" \
        --arg squashfs_sha256 "$(sha256sum "''${squashfs}" | cut -d' ' -f1)" \
        --arg boot_sha256 "$(sha256sum "''${boot_tar}" | cut -d' ' -f1)" \
        --arg preflight_sha256 "$(sha256sum "''${seed_preflight}" | cut -d' ' -f1)" \
        '{
          schema: 1,
          input: $input,
          compression: "lz4-fast",
          payload_specific: false,
          preflight: "fisherman-validate-v1",
          files: {
            "finite-live.squashfs": $squashfs_sha256,
            "finite-boot-files.tar": $boot_sha256,
            "seed-preflight.log": $preflight_sha256
          }
        }' >"''${seed_manifest}"
      validate_seed_cache "''${seed_cache_dir}"
      seed_cache_source=built
    fi

    cp "''${seed_preflight}" diagnostics/seed-preflight.log
    seed_digest="sha256:$(sha256sum "''${seed_manifest}" | cut -d' ' -f1)"

    if [[ "''${CACHE_WRITE}" == true && "''${registry_seed_available}" != true ]]; then
      (
        cd "''${seed_cache_dir}"
        oras push --no-tty --registry-config "''${registry_auth_file}" \
          --artifact-type application/vnd.finite.installer.seed.v1 \
          "''${seed_tag_ref}" \
          'finite-live.squashfs:application/vnd.finite.installer.squashfs.v1' \
          'finite-boot-files.tar:application/vnd.finite.installer.boot-files.v1.tar' \
          'seed-manifest.json:application/vnd.finite.installer.seed-manifest.v1+json' \
          'seed-preflight.log:text/plain'
      ) 2>&1 | tee diagnostics/seed-push.log
      seed_registry_digest="$(oras resolve --registry-config "''${registry_auth_file}" \
        "''${seed_tag_ref}")"
      [[ "''${seed_registry_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
      seed_registry_ref="''${seed_repository}@''${seed_registry_digest}"
      DOCKER_CONFIG="''${cosign_config_dir}" cosign sign --yes "''${seed_registry_ref}"
      seed_published=true
      registry_seed_available=true
    fi
    seed_reference="''${seed_tag_ref}"
    [[ "''${registry_seed_available}" != true ]] || seed_reference="''${seed_registry_ref}"
    environment_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    # A cache hit reuses the proof generated with this exact seed input. A miss
    # ran Fisherman's own validator above before any squashfs or ISO assembly.
    validate_seed_cache "''${seed_cache_dir}"

    final_iso="output/finite-''${IMAGE_TAG}-$(<VERSION).iso"
    FINITE_TARGET_CONFIG="''${target_config}" LIVE_TITLE='Finite Live' \
      bash "''${source_root}/live/src/build-iso.sh" \
      "''${boot_tar}" "''${squashfs}" "''${final_iso}" \
      2>&1 | tee diagnostics/iso-build.log
    iso_sha256="$(sha256sum "''${final_iso}" | cut -d' ' -f1)"
    xorriso -indev "''${final_iso}" -report_system_area plain \
      >diagnostics/iso-system-area.txt 2>&1
    grep -qiF 'System area summary: MBR protective-msdos-label' diagnostics/iso-system-area.txt
    xorriso -osirrox on -indev "''${final_iso}" \
      -extract /images/pxeboot/vmlinuz output/vmlinuz \
      -extract /images/pxeboot/initrd.img output/initrd.img \
      -extract /boot/grub/loopback.cfg diagnostics/iso-loopback.cfg \
      -extract /finite/target.json diagnostics/iso-target.json \
      -extract /EFI/efi.img diagnostics/efi.img >/dev/null 2>&1
    cmp --silent "''${target_config}" diagnostics/iso-target.json
    mcopy -i diagnostics/efi.img ::/loader/entries/dakota-live.conf \
      diagnostics/systemd-boot-entry.conf
    grep -qF 'title   Finite Live' diagnostics/systemd-boot-entry.conf
    grep -qF 'root=live:LABEL=FINITE_LIVE rd.live.image' diagnostics/systemd-boot-entry.conf
    grep -qF 'console=ttyS0,115200n8' diagnostics/systemd-boot-entry.conf
    iso_seconds=$((SECONDS - started))

    jq -n \
      --arg iso "''${final_iso##*/}" --arg iso_sha256 "''${iso_sha256}" \
      --arg installer_sha256 "''${FINITE_BOOTC_INSTALLER_SHA256}" \
      --arg installer_version "''${FINITE_BOOTC_INSTALLER_VERSION}" \
      --arg installer_source_revision "''${FINITE_DAKOTA_ISO_REVISION}" \
      --arg installer_input "''${installer_seed_input}" \
      --arg live_reference "''${dakota_live_build_ref}" \
      --arg live_digest "''${FINITE_DAKOTA_LIVE_DIGEST}" \
      --arg seed_digest "''${seed_digest}" --arg seed_reference "''${seed_reference}" \
      --arg seed_registry_digest "''${seed_registry_digest}" \
      --arg seed_cache_source "''${seed_cache_source}" \
      --argjson seed_cache_hit "''${seed_cache_hit}" \
      --arg payload "''${payload_ref}" --arg payload_digest "''${payload_digest}" \
      --arg payload_update_reference "''${payload_update_ref}" \
      --arg payload_source_revision "''${source_revision}" \
      --arg source_commit "''${GITHUB_SHA}" --arg source_repository "''${GITHUB_REPOSITORY}" \
      --arg version "$(<VERSION)" \
      '{
        schema_version: 6,
        source: {repository: $source_repository, commit: $source_commit},
        version: $version,
        iso: {name: $iso, sha256: $iso_sha256, compression: "lz4", boot: "systemd-boot", volume_label: "FINITE_LIVE", efi_partition_type: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"},
        installer: {
          architecture: "projectbluefin/dakota-iso", source_revision: $installer_source_revision,
          application: "projectbluefin/bootc-installer", application_version: $installer_version,
          application_sha256: $installer_sha256, input: $installer_input,
          assembly: {application: "projectbluefin/dakota-iso"},
          live_root: {reference: $live_reference, digest: $live_digest},
          target_bootloader: "grub2", target_filesystem: "btrfs",
          network_required: true, offline: false
        },
        seed: {
          reference: $seed_reference, digest: $seed_digest,
          registry_digest: (if $seed_registry_digest == "" then null else $seed_registry_digest end),
          cache_hit: $seed_cache_hit, cache_source: $seed_cache_source,
          payload_specific: false, artifact: "application/vnd.finite.installer.seed.v1"
        },
        payload: {
          reference: $payload, digest: $payload_digest, install_source: $payload,
          update_reference: $payload_update_reference, embedded: false,
          source_revision: $payload_source_revision,
          sbom: {predicate_type: "https://spdx.dev/Document/v2.3", signer_workflow: "closure-labs/finite/.github/workflows/attest-software-bill-of-materials.yml"}
        }
      }' >output/installer-manifest.json
    {
      printf '%s  %s\n' "''${iso_sha256}" "''${final_iso}"
      sha256sum output/installer-manifest.json
    } >output/SHA256SUMS

    build_seconds="''${SECONDS}"
    iso_path="$(realpath "''${final_iso}")"
    if [[ -n "''${GITHUB_OUTPUT:-}" ]]; then
      {
        echo "iso-sha256=''${iso_sha256}"
        echo "payload-digest=''${payload_digest}"
        echo "payload-tag=''${payload_tag}"
        echo "iso-path=''${iso_path}"
        echo "installer-input=''${installer_seed_input}"
        echo "seed-cache-hit=''${seed_cache_hit}"
        echo "seed-cache-source=''${seed_cache_source}"
        echo "seed-digest=''${seed_digest}"
        echo "seed-published=''${seed_published}"
        echo "seed-reference=''${seed_reference}"
        echo "update-reference=''${payload_update_ref}"
        echo "environment-seconds=''${environment_seconds}"
        echo "iso-seconds=''${iso_seconds}"
        echo "build-seconds=''${build_seconds}"
      } >>"''${GITHUB_OUTPUT}"
    fi
  '';
}
