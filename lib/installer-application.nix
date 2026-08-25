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
    buildah
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
        'finite-dakota-netinstaller-seed-v1' \
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
    [[ $# == 0 ]] || {
      echo 'usage: finite-installer-build [cache-input SOURCE_REVISION INSTALLER_SHA256 OVERLAY_DIGEST LIVE_DIGEST]' >&2
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
    live_image="localhost/finite-netinstaller:''${GITHUB_SHA}"
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

    overlay_digest="$(
      tar --create --file=- --format=gnu --group=0 --mtime='UTC 1970-01-01' \
        --numeric-owner --owner=0 --sort=name \
        installer/live installer/prepare-dakota-iso-source |
        sha256sum |
        cut -d' ' -f1
    )"
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

    started="''${SECONDS}"
    if seed_metadata="$(skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 "docker://''${seed_tag_ref}" 2>diagnostics/seed-inspect.log)"; then
      seed_digest="$(jq -er '.Digest' <<<"''${seed_metadata}")"
      seed_ref="''${seed_repository}@''${seed_digest}"
      DOCKER_CONFIG="''${cosign_config_dir}" cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity "https://github.com/''${GITHUB_REPOSITORY}/.github/workflows/build-installer.yml@refs/heads/main" \
        "''${seed_ref}" >/dev/null
      "''${root_podman[@]}" pull "''${auth_args[@]}" "''${seed_ref}"
      "''${root_podman[@]}" tag "''${seed_ref}" "''${seed_local}"
      seed_cache_hit=true
    else
      # Pull the exact tag+digest spelling used by the Containerfile so
      # --pull=never can resolve it from local storage without a name mismatch.
      "''${root_podman[@]}" pull --retry 3 "''${dakota_live_build_ref}"
      "''${root_podman[@]}" pull --retry 3 \
        "''${FINITE_INSTALLER_BUILDER_IMAGE}@''${FINITE_INSTALLER_BUILDER_DIGEST}"
      (
        cd "''${source_root}"
        "''${root_podman[@]}" build "''${auth_args[@]}" --layers \
          --cap-add sys_admin --security-opt label=disable --pull=never \
          --build-arg CACHE_BUST="''${installer_seed_input}" \
          --build-arg DEBUG=0 --build-arg INSTALLER_CHANNEL=stable \
          --build-arg LIVE_ROOT=dakota --build-arg REGISTRY=projectbluefin \
          --build-arg TAG="''${FINITE_DAKOTA_LIVE_TAG}@''${FINITE_DAKOTA_LIVE_DIGEST}" \
          --build-arg TARGET=finite \
          --label "io.finite.installer.seed.input=''${installer_seed_input}" \
          --label 'io.finite.installer.network-required=true' \
          --tag "''${seed_local}" --file live/Containerfile live
      ) 2>&1 | tee diagnostics/live-environment.log
      if [[ "''${CACHE_WRITE}" == true ]]; then
        "''${root_podman[@]}" push "''${auth_args[@]}" "''${seed_local}" "''${seed_tag_ref}"
        seed_digest="$(skopeo inspect --authfile "''${registry_auth_file}" --retry-times 3 \
          "docker://''${seed_tag_ref}" | jq -er '.Digest')"
        DOCKER_CONFIG="''${cosign_config_dir}" cosign sign --yes \
          "''${seed_repository}@''${seed_digest}"
        seed_published=true
      else
        seed_digest="$("''${root_podman[@]}" image inspect "''${seed_local}" --format '{{.Id}}')"
      fi
    fi

    target_layer="''${work_root}/target-layer"
    install -d -m 0755 "''${target_layer}"
    cat >"''${target_layer}/configure-target.py" <<'PY'
    from pathlib import Path
    import sys

    payload, update = sys.argv[1:]
    replacements = {"@@PAYLOAD_REFERENCE@@": payload, "@@UPDATE_REFERENCE@@": update}
    for name in ("recipe.json", "ci-autoinstall.json", "images.json"):
        path = Path("/etc/bootc-installer") / name
        text = path.read_text()
        for old, new in replacements.items():
            text = text.replace(old, new)
        if "@@" in text:
            raise SystemExit(f"unresolved installer placeholder in {path}")
        path.write_text(text)
    PY
    cat >"''${target_layer}/Containerfile" <<EOF
    FROM ''${seed_local}
    COPY configure-target.py /tmp/configure-target.py
    ARG PAYLOAD_REFERENCE
    ARG UPDATE_REFERENCE
    RUN python3 /tmp/configure-target.py "\''${PAYLOAD_REFERENCE}" "\''${UPDATE_REFERENCE}" && rm /tmp/configure-target.py
    EOF
    "''${root_podman[@]}" build --layers --pull=never \
      --build-arg PAYLOAD_REFERENCE="''${payload_ref}" \
      --build-arg UPDATE_REFERENCE="''${payload_update_ref}" \
      --label "io.finite.installer.payload.digest=''${payload_digest}" \
      --tag "''${live_image}" --file "''${target_layer}/Containerfile" \
      "''${target_layer}" 2>&1 | tee diagnostics/target-layer.log
    # The single-quoted validation program is evaluated inside the container.
    # shellcheck disable=SC2016
    "''${root_podman[@]}" run --rm --entrypoint /usr/bin/bash \
      "''${live_image}" -ceu \
      'test ! -e /etc/bootc-installer/live-iso-mode
       test -e /etc/bootc-installer/finite-netinstall-mode
       ! grep -R -Fq "@@" /etc/bootc-installer
       test "$(jq -r .image /etc/bootc-installer/ci-autoinstall.json)" = "$1"' \
      -- "''${payload_ref}"
    environment_seconds=$((SECONDS - started))

    started="''${SECONDS}"
    squashfs="''${work_root}/finite-live.squashfs"
    boot_tar="''${work_root}/finite-boot-files.tar"
    "''${root_exec[@]}" env PATH="''${PATH}" SUPERISO_COMPRESSION=lz4 \
      SUPERISO_TMPDIR="''${work_root}" \
      bash "''${source_root}/scripts/build-live-squashfs.sh" \
        "''${live_image}" "''${squashfs}" "''${boot_tar}" \
      2>&1 | tee diagnostics/squashfs-build.log
    "''${root_exec[@]}" chown "$(id -u):$(id -g)" "''${squashfs}" "''${boot_tar}"

    final_iso="output/finite-''${IMAGE_TAG}-$(<VERSION).iso"
    LIVE_TITLE='Finite Live' bash "''${source_root}/live/src/build-iso.sh" \
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
      -extract /EFI/efi.img diagnostics/efi.img >/dev/null 2>&1
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
      --arg seed_digest "''${seed_digest}" --arg seed_reference "''${seed_tag_ref}" \
      --argjson seed_cache_hit "''${seed_cache_hit}" \
      --arg payload "''${payload_ref}" --arg payload_digest "''${payload_digest}" \
      --arg payload_update_reference "''${payload_update_ref}" \
      --arg payload_source_revision "''${source_revision}" \
      --arg source_commit "''${GITHUB_SHA}" --arg source_repository "''${GITHUB_REPOSITORY}" \
      --arg version "$(<VERSION)" \
      '{
        schema_version: 5,
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
        seed: {reference: $seed_reference, digest: $seed_digest, cache_hit: $seed_cache_hit, payload_specific: false},
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
