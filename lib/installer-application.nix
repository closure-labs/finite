{
  bluefinInstallerLock,
  bluefinIsoSource,
  bootcInstallerBundle,
  generated,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "finite-installer-build";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    cosign
    file
    findutils
    gh
    gnutar
    gnugrep
    gnused
    jq
    podman
    python3
    skopeo
    util-linux
    xorriso
  ];
  text = ''
    export FINITE_GENERATED_ROOT=${generated}
    export FINITE_BLUEFIN_ISO_SOURCE=${bluefinIsoSource}
    export FINITE_BOOTC_INSTALLER_BUNDLE=${bootcInstallerBundle}
    export FINITE_BLUEFIN_ISO_REVISION=${bluefinInstallerLock.iso_source.revision}
    export FINITE_BOOTC_INSTALLER_VERSION=${bluefinInstallerLock.installer.version}
    export FINITE_BOOTC_INSTALLER_SHA256=${bluefinInstallerLock.installer.sha256}
    export FINITE_INSTALLER_BUILDER_IMAGE=${bluefinInstallerLock.builder.image}
    export FINITE_INSTALLER_BUILDER_TAG=${bluefinInstallerLock.builder.tag}
    export FINITE_INSTALLER_BUILDER_DIGEST=${bluefinInstallerLock.builder.digest}
    export FINITE_IMAGE_BUILDER_VERSION=${bluefinInstallerLock.image_builder.version}
    export FINITE_IMAGE_BUILDER_IMAGE=${bluefinInstallerLock.image_builder.image}
    export FINITE_IMAGE_BUILDER_DIGEST=${bluefinInstallerLock.image_builder.digest}
    export FINITE_PODMAN=${pkgs.podman}/bin/podman
    set -euo pipefail

    seed_input() {
      local source_revision=$1 installer_sha256=$2 overlay_digest=$3 foundation=$4 foundation_digest=$5
      printf '%s\n' \
        'finite-bluefin-installer-seed-v1' \
        "source-revision=''${source_revision}" \
        "installer-sha256=''${installer_sha256}" \
        "builder-digest=''${FINITE_INSTALLER_BUILDER_DIGEST}" \
        "overlay=''${overlay_digest}" \
        "foundation=''${foundation}" \
        "foundation-digest=''${foundation_digest}" |
        sha256sum |
        cut -d' ' -f1
    }

    if [[ "''${1:-}" == cache-input ]]; then
      [[ $# == 6 ]] || {
        echo 'usage: finite-installer-build cache-input SOURCE_REVISION INSTALLER_SHA256 OVERLAY_DIGEST FOUNDATION FOUNDATION_DIGEST' >&2
        exit 2
      }
      seed_input "$2" "$3" "$4" "$5" "$6"
      exit
    fi
    [[ $# == 0 ]] || {
      echo 'usage: finite-installer-build [cache-input SOURCE_REVISION INSTALLER_SHA256 OVERLAY_DIGEST FOUNDATION FOUNDATION_DIGEST]' >&2
      exit 2
    }

    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo 'Run this command from the Finite repository root' >&2
      exit 2
    }
    cd "''${repo_root}"

    : "''${CACHE_WRITE:=false}"
    : "''${GH_TOKEN:?GH_TOKEN is required to verify attestations}"
    : "''${GHCR_TOKEN:?GHCR_TOKEN is required to read the Finite payload}"
    : "''${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
    : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
    : "''${GITHUB_SHA:?GITHUB_SHA is required}"
    : "''${IMAGE_REF:=ghcr.io/''${GITHUB_REPOSITORY}}"
    : "''${IMAGE_TAG:=bluefin-generic}"
    : "''${RUNNER_TEMP:=/tmp}"
    install -d -m 0755 diagnostics output
    if command -v run0 >/dev/null 2>&1; then
      root_exec=(run0)
    elif command -v sudo >/dev/null 2>&1; then
      # GitHub's Ubuntu 24.04 image currently ships systemd 255, before run0.
      root_exec=(sudo)
    else
      echo 'A root executor is required (run0 preferred; sudo supported for CI)' >&2
      exit 1
    fi
    root_podman=("''${root_exec[@]}" "''${FINITE_PODMAN}")
    registry_auth_file="''${RUNNER_TEMP}/finite-installer-auth.json"
    cosign_config_dir="''${RUNNER_TEMP}/finite-installer-cosign"
    source_root="''${RUNNER_TEMP}/finite-bluefin-iso-source"
    work_root="''${RUNNER_TEMP}/finite-bluefin-iso-work"
    live_image="localhost/finite-installer-seed:''${GITHUB_SHA}"
    image_builder_ref="''${FINITE_IMAGE_BUILDER_IMAGE}@''${FINITE_IMAGE_BUILDER_DIGEST}"
    seed_repository="''${IMAGE_REF}-installer-seed"
    environment_seconds=0
    iso_seconds=0
    seed_cache_hit=false
    seed_published=false
    seed_digest=unresolved
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
        echo '# Root Podman info'
        "''${root_podman[@]}" info --format json |
          jq '{graphDriverName: .store.graphDriverName, graphRoot: .store.graphRoot, graphStatus: .store.graphStatus}'
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
      skopeo login \
        --authfile "''${registry_auth_file}" \
        ghcr.io \
        --username "''${GITHUB_ACTOR}" \
        --password-stdin
    install -d -m 0700 "''${cosign_config_dir}"
    printf '%s' "''${GHCR_TOKEN}" |
      DOCKER_CONFIG="''${cosign_config_dir}" cosign login \
        ghcr.io \
        --username "''${GITHUB_ACTOR}" \
        --password-stdin
    auth_args=(--authfile "''${registry_auth_file}")

    metadata="$(
      skopeo inspect \
        --authfile "''${registry_auth_file}" \
        --retry-times 3 \
        "docker://''${IMAGE_REF}:''${IMAGE_TAG}" \
        2>diagnostics/payload-inspect.log
    )"
    payload_digest="$(jq -er '.Digest' <<<"''${metadata}")"
    profile="$(jq -er '.Labels["io.finite.build.profile"]' <<<"''${metadata}")"
    foundation="$(jq -er '.Labels["io.finite.foundation"]' <<<"''${metadata}")"
    source_revision="$(jq -er '.Labels["org.opencontainers.image.revision"]' <<<"''${metadata}")"
    payload_source_url="$(jq -er '.Labels["org.opencontainers.image.source"]' <<<"''${metadata}")"
    payload_source_repository="''${payload_source_url#https://github.com/}"
    payload_source_repository="''${payload_source_repository%.git}"
    [[ "''${payload_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${source_revision}" =~ ^[0-9a-f]{40}$ ]]
    [[ "''${payload_source_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
    [[ "''${foundation}" == bluefin || "''${foundation}" == bluefin-dx ]]
    jq -e --arg profile "''${profile}" '.profiles[$profile]' \
      "''${FINITE_GENERATED_ROOT}/bootc/generated/profile-catalog.json" >/dev/null
    payload_ref="''${IMAGE_REF}@''${payload_digest}"
    payload_update_ref="''${IMAGE_REF}:''${IMAGE_TAG}"
    foundation_tag="''${foundation}-generic"
    foundation_update_ref="''${IMAGE_REF}:''${foundation_tag}"

    foundation_metadata="$(
      skopeo inspect \
        --authfile "''${registry_auth_file}" \
        --retry-times 3 \
        "docker://''${foundation_update_ref}" \
        2>diagnostics/foundation-inspect.log
    )"
    foundation_digest="$(jq -er '.Digest' <<<"''${foundation_metadata}")"
    foundation_profile="$(jq -er '.Labels["io.finite.build.profile"]' <<<"''${foundation_metadata}")"
    [[ "''${foundation_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "''${foundation_profile}" == "''${foundation_tag}" ]]
    foundation_fedora_release="$({
      jq -r '
        [
          (try (.Labels["dev.hhd.rechunk.info"] | fromjson | .uniq |
            capture("^(?<release>[0-9]+)\\.").release) catch empty),
          (try (.Labels["ostree.linux"] |
            capture("\\.fc(?<release>[0-9]+)\\.").release) catch empty)
        ] | first // empty
      ' <<<"''${foundation_metadata}"
    })"
    if [[ ! "''${foundation_fedora_release}" =~ ^[0-9]+$ ]]; then
      echo 'Unable to derive the Fedora release from foundation image metadata' >&2
      exit 1
    fi
    image_builder_distro="fedora-''${foundation_fedora_release}"
    if [[ "''${profile}" != "''${foundation_profile}" ]]; then
      echo "Installer payload must be the generic foundation profile (expected ''${foundation_profile}, got ''${profile})" >&2
      exit 1
    fi
    foundation_ref="''${IMAGE_REF}@''${foundation_digest}"
    foundation_live_ref="''${foundation_update_ref}@''${foundation_digest}"

    cosign_identity="https://github.com/''${payload_source_repository}/.github/workflows/build-profile.yml@refs/heads/main"
    DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity "''${cosign_identity}" \
      "''${payload_ref}" >/dev/null
    DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity "''${cosign_identity}" \
      "''${foundation_ref}" >/dev/null
    DOCKER_CONFIG="''${cosign_config_dir}" gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci \
      --repo "''${payload_source_repository}" \
      --signer-workflow "''${payload_source_repository}/.github/workflows/build-profile.yml" \
      --source-digest "''${source_revision}"
    DOCKER_CONFIG="''${cosign_config_dir}" gh attestation verify "oci://''${payload_ref}" \
      --bundle-from-oci \
      --repo "''${payload_source_repository}" \
      --signer-workflow "''${payload_source_repository}/.github/workflows/attest-software-bill-of-materials.yml" \
      --source-digest "''${source_revision}" \
      --predicate-type https://spdx.dev/Document/v2.3

    overlay_digest="$(
      tar \
        --create \
        --file=- \
        --format=gnu \
        --group=0 \
        --mtime='UTC 1970-01-01' \
        --numeric-owner \
        --owner=0 \
        --sort=name \
        installer/live installer/prepare-bluefin-iso-source |
        sha256sum |
        cut -d' ' -f1
    )"
    installer_seed_input="$(
      seed_input \
        "''${FINITE_BLUEFIN_ISO_REVISION}" \
        "''${FINITE_BOOTC_INSTALLER_SHA256}" \
        "''${overlay_digest}" \
        "''${foundation}" \
        "''${foundation_digest}"
    )"
    [[ "''${installer_seed_input}" =~ ^[0-9a-f]{64}$ ]]
    seed_tag="''${foundation}-''${installer_seed_input}"
    seed_tag_ref="''${seed_repository}:''${seed_tag}"

    {
      echo '# Runner filesystem'
      df -h /
      echo
      echo '# Root Podman storage'
      "''${root_podman[@]}" system df
      echo
      echo '# Root Podman info'
      "''${root_podman[@]}" info --format json |
        jq '{graphDriverName: .store.graphDriverName, graphRoot: .store.graphRoot, graphStatus: .store.graphStatus}'
    } | tee diagnostics/runner-capacity-before.txt

    started="''${SECONDS}"
    "''${root_podman[@]}" pull "''${auth_args[@]}" "''${payload_ref}"
    "''${root_podman[@]}" tag "''${payload_ref}" "''${payload_update_ref}"
    if [[ "''${foundation_ref}" != "''${payload_ref}" ]]; then
      "''${root_podman[@]}" pull "''${auth_args[@]}" "''${foundation_ref}"
    fi
    "''${root_podman[@]}" tag "''${foundation_ref}" "''${foundation_update_ref}"

    rm -rf "''${source_root}" "''${work_root}"
    install -d -m 0755 "''${work_root}"
    installer/prepare-bluefin-iso-source \
      "''${FINITE_BLUEFIN_ISO_SOURCE}" \
      "''${source_root}" \
      "''${foundation_live_ref}" \
      "''${foundation_update_ref}" \
      "''${FINITE_BOOTC_INSTALLER_BUNDLE}" \
      "''${FINITE_BOOTC_INSTALLER_SHA256}" \
      modules/aspects/base/rootfs/usr/share/finite/finite-logo.png \
      "''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}"

    if seed_metadata="$(skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 "docker://''${seed_tag_ref}" 2>diagnostics/seed-inspect.log)"; then
      seed_digest="$(jq -er '.Digest' <<<"''${seed_metadata}")"
      seed_ref="''${seed_repository}@''${seed_digest}"
      DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity "https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/build-installer.yml@refs/heads/main" \
        "''${seed_ref}" >/dev/null
      "''${root_podman[@]}" pull "''${auth_args[@]}" "''${seed_ref}"
      "''${root_podman[@]}" tag "''${seed_ref}" "''${live_image}"
      seed_cache_hit=true
    else
      builder_ref="''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}"
      "''${root_podman[@]}" pull --retry 3 "''${builder_ref}"
      (
        cd "''${source_root}"
        "''${root_podman[@]}" build \
          "''${auth_args[@]}" \
          --layers=false \
          --cap-add sys_admin \
          --security-opt label=disable \
          --pull=never \
          --build-arg CACHE_BUST="''${installer_seed_input}" \
          --build-arg DEBUG=0 \
          --build-arg FINITE_FEDORA_RELEASE="''${foundation_fedora_release}" \
          --build-arg INSTALLER_CHANNEL=stable \
          --build-arg REGISTRY=closure-labs \
          --build-arg TAG="''${foundation_live_ref#*:}" \
          --build-arg TARGET=finite \
          --label "io.finite.installer.seed.input=''${installer_seed_input}" \
          --label "io.finite.foundation=''${foundation}" \
          --tag "''${live_image}" \
          --file live/Containerfile \
          live
      ) 2>&1 | tee diagnostics/live-environment.log
      if [[ "''${CACHE_WRITE}" == true ]]; then
        "''${root_podman[@]}" push "''${auth_args[@]}" "''${live_image}" "''${seed_tag_ref}"
        seed_digest="$(
          skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 "docker://''${seed_tag_ref}" |
            jq -er '.Digest'
        )"
        DOCKER_CONFIG="''${cosign_config_dir}" cosign sign --yes "''${seed_repository}@''${seed_digest}"
        seed_published=true
      else
        seed_digest="$("''${root_podman[@]}" image inspect "''${live_image}" --format '{{.Digest}}')"
        [[ "''${seed_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || seed_digest=local-only
      fi
    fi
    environment_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    "''${root_podman[@]}" pull --retry 3 "''${image_builder_ref}"
    # The single-quoted script is intentionally expanded by bash in the
    # live seed container, not by this outer installer process.
    # shellcheck disable=SC2016
    "''${root_podman[@]}" run --rm --entrypoint /usr/bin/bash \
      "''${live_image}" -ceu '
        test -x /usr/bin/bootc
        test -s /usr/lib/image-builder/bootc/iso.yaml
        test -s /usr/share/grub/unicode.pf2
        test -d /usr/lib/grub/i386-pc
        test -s /boot/efi/EFI/fedora/shimx64.efi
        test -s /boot/efi/EFI/fedora/mmx64.efi
        test -s /boot/efi/EFI/fedora/gcdx64.efi
        test -x /usr/bin/grub2-mkimage
        test -x /usr/bin/implantisomd5
        test -x /usr/bin/mksquashfs
        test -x /usr/bin/podman
        test -x /usr/bin/python3
        test -x /usr/bin/xorriso
        test -x /usr/bin/xorrisofs
        kernel_dir="$(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -print -quit)"
        test -n "''${kernel_dir}"
        test -s "''${kernel_dir}/vmlinuz"
        test -s "''${kernel_dir}/initramfs.img"
      '

    image_builder_output="''${work_root}/image-builder-output"
    image_builder_cache="''${work_root}/image-builder-cache"
    install -d -m 0755 "''${image_builder_output}" "''${image_builder_cache}"
    "''${root_podman[@]}" run --rm \
      --privileged \
      --security-opt label=disable \
      --volume /var/lib/containers/storage:/var/lib/containers/storage \
      --volume "''${image_builder_output}:/output" \
      --volume "''${image_builder_cache}:/var/cache/image-builder/store" \
      "''${image_builder_ref}" \
      --output-dir /output \
      build \
      --bootc-ref "''${live_image}" \
      --bootc-installer-payload-ref "''${payload_update_ref}" \
      --bootc-default-fs btrfs \
      --cache /var/cache/image-builder/store \
      --output-name finite-live.iso \
      --progress verbose \
      --seed 0 \
      --with-buildlog \
      --with-manifest \
      --with-metrics \
      bootc-generic-iso 2>&1 | tee diagnostics/iso-build.log
    find "''${image_builder_output}" -maxdepth 2 -type f \
      -printf '%s %p\n' | sort >diagnostics/image-builder-output.txt
    while IFS= read -r artifact; do
      cp "''${artifact}" "diagnostics/image-builder-''${artifact##*/}"
    done < <(
      find "''${image_builder_output}" -maxdepth 1 -type f \
        \( -name '*.json' -o -name '*.log' -o -name '*.buildlog' \) -print
    )

    final_iso="output/finite-''${IMAGE_TAG}-$(<VERSION).iso"
    "''${root_exec[@]}" cp "''${image_builder_output}/finite-live.iso" "''${final_iso}"
    "''${root_exec[@]}" chown "$(id -u):$(id -g)" "''${final_iso}"
    iso_sha256="$(sha256sum "''${final_iso}" | cut -d' ' -f1)"
    xorriso -indev "''${final_iso}" -report_system_area plain \
      >diagnostics/iso-system-area.txt 2>&1
    grep -qiF '28732ac11ff8d211ba4b00a0c93ec93b' diagnostics/iso-system-area.txt
    xorriso -osirrox on -indev "''${final_iso}" \
      -extract /images/pxeboot/vmlinuz output/vmlinuz \
      -extract /images/pxeboot/initrd.img output/initrd.img \
      -extract /EFI/BOOT/grub.cfg diagnostics/iso-grub.cfg \
      >/dev/null 2>&1
    grep -qF \
      'linux /images/pxeboot/vmlinuz root=live:LABEL=FINITE_LIVE rd.live.image' \
      diagnostics/iso-grub.cfg
    grep -qF 'console=ttyS0,115200n8' diagnostics/iso-grub.cfg
    iso_seconds=$((SECONDS - started))

    jq -n \
      --arg iso "''${final_iso##*/}" \
      --arg iso_sha256 "''${iso_sha256}" \
      --arg image_builder_version "''${FINITE_IMAGE_BUILDER_VERSION}" \
      --arg image_builder_reference "''${image_builder_ref}" \
      --arg image_builder_digest "''${FINITE_IMAGE_BUILDER_DIGEST}" \
      --arg image_builder_distro "''${image_builder_distro}" \
      --arg installer_sha256 "''${FINITE_BOOTC_INSTALLER_SHA256}" \
      --arg installer_version "''${FINITE_BOOTC_INSTALLER_VERSION}" \
      --arg installer_source_revision "''${FINITE_BLUEFIN_ISO_REVISION}" \
      --arg installer_input "''${installer_seed_input}" \
      --arg installer_builder "''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}" \
      --arg installer_builder_digest "''${FINITE_INSTALLER_BUILDER_DIGEST}" \
      --arg seed_digest "''${seed_digest}" \
      --arg seed_reference "''${seed_tag_ref}" \
      --argjson seed_cache_hit "''${seed_cache_hit}" \
      --arg payload "''${payload_ref}" \
      --arg payload_digest "''${payload_digest}" \
      --arg payload_update_reference "''${payload_update_ref}" \
      --arg payload_source_revision "''${source_revision}" \
      --arg source_commit "''${GITHUB_SHA}" \
      --arg source_repository "''${GITHUB_REPOSITORY}" \
      --arg version "$(<VERSION)" \
      '{
        schema_version: 4,
        source: {repository: $source_repository, commit: $source_commit},
        version: $version,
        iso: {
          name: $iso,
          sha256: $iso_sha256,
          compression: "zstd",
          boot: "grub2",
          volume_label: "FINITE_LIVE",
          efi_partition_type: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
        },
        installer: {
          architecture: "projectbluefin/dakota-iso",
          source_revision: $installer_source_revision,
          application: "projectbluefin/bootc-installer",
          application_version: $installer_version,
          application_sha256: $installer_sha256,
          input: $installer_input,
          assembly: {
            application: "osbuild/image-builder",
            version: $image_builder_version,
            reference: $image_builder_reference,
            digest: $image_builder_digest,
            distro: $image_builder_distro
          },
          builder: {
            reference: $installer_builder,
            digest: $installer_builder_digest,
            architecture: "amd64"
          },
          target_bootloader: "grub2",
          target_filesystem: "btrfs",
          offline: true
        },
        seed: {
          reference: $seed_reference,
          digest: $seed_digest,
          cache_hit: $seed_cache_hit,
          payload_specific: false
        },
        payload: {
          reference: $payload,
          digest: $payload_digest,
          embedded_reference: $payload_update_reference,
          update_reference: $payload_update_reference,
          source_revision: $payload_source_revision,
          sbom: {
            predicate_type: "https://spdx.dev/Document/v2.3",
            signer_workflow: "closure-labs/finite/.github/workflows/attest-software-bill-of-materials.yml"
          }
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
        echo "seed-digest=''${seed_digest}"
        echo "seed-published=''${seed_published}"
        echo "seed-reference=''${seed_tag_ref}"
        echo "update-reference=''${payload_update_ref}"
        echo "environment-seconds=''${environment_seconds}"
        echo "iso-seconds=''${iso_seconds}"
        echo "build-seconds=''${build_seconds}"
      } >>"''${GITHUB_OUTPUT}"
    fi
  '';
}
