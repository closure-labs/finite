{
  bluefin,
  bluefinArchive,
  generated,
  pkgs,
  version,
}: let
  exportArtifacts = pkgs.writeShellApplication {
    name = "purplefin-export-artifacts";
    runtimeInputs = [pkgs.coreutils];
    text = ''
      destination="''${1:-$PWD/artifacts}"
      for relative in bootc/generated installer/config/profiles; do
        target="''${destination}/''${relative}"
        mkdir -p "''${target}"
        chmod -R u+w "''${target}"
        cp -R ${generated}/"''${relative}"/. "''${target}/"
        chmod -R u+w "''${target}"
      done
      printf '%s\n' "''${destination}"
    '';
  };
  mkRepositoryApp = {
    name,
    script,
    runtimeInputs,
  }:
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      text = ''
        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          exit 2
        }
        cd "''${repo_root}"
        export PURPLEFIN_GENERATED_ROOT="${generated}"
        exec ${pkgs.bash}/bin/bash "''${repo_root}/${script}" "$@"
      '';
    };
in rec {
  inherit exportArtifacts;

  classifyChanges = pkgs.writeShellApplication {
    name = "purplefin-classify-changes";
    runtimeInputs = [pkgs.coreutils];
    text = ''
      component="''${1:?usage: purplefin-classify-changes COMPONENT}"
      required=false
      case "''${component}" in
        images | installer) ;;
        *) echo "unknown component: ''${component}" >&2; exit 2 ;;
      esac
      while IFS= read -r path; do
        case "''${component}:''${path}" in
          installer:.github/actions/build-installer/* | \
          installer:.github/workflows/build-installer.yml | \
          installer:.github/workflows/build.yml | \
          installer:flake.lock | installer:flake.nix | \
          installer:installer/Containerfile | installer:installer/rootfs/* | \
          installer:modules/* | installer:lib/* | \
          installer:tests/installer/*)
            required=true; break ;;
          images:README.md | images:LICENSE | images:docs/* | \
          images:.editorconfig | images:.github/actions/build-installer/* | \
          images:.github/dependabot.yml | \
          images:.github/workflows/build-installer.yml | \
          images:.github/workflows/cleanup.yml | \
          images:.github/workflows/queue-dependabot.yml | \
          images:.github/workflows/release.yml | \
          images:.github/workflows/update-flake-lock.yml | \
          images:.github/workflows/update-bluefin.yml | \
          images:.github/workflows/update-image-builder.yml | \
          images:automation/github/validate-trusted-update.sh | \
          images:secretspec.toml | \
          images:installer/* | images:tests/installer/* | \
          images:tests/repository/text-style.sh)
            ;;
          images:*) required=true; break ;;
        esac
      done
      printf '%s\n' "''${required}"
    '';
  };

  ci = pkgs.writeShellApplication {
    name = "purplefin-ci";
    runtimeInputs = [pkgs.nix];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      exec nix flake check "path:''${repo_root}" --print-build-logs "$@"
    '';
  };
  cacheChecks = pkgs.writeShellApplication {
    name = "purplefin-cache-checks";
    runtimeInputs = with pkgs; [cachix coreutils nix];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      if (( $# == 0 )); then
        set -- \
          "path:''${repo_root}#checks.x86_64-linux.shell" \
          "path:''${repo_root}#checks.x86_64-linux.repository" \
          "path:''${repo_root}#checks.x86_64-linux.documentation" \
          "path:''${repo_root}#checks.x86_64-linux.automation" \
          "path:''${repo_root}#checks.x86_64-linux.bootc" \
          "path:''${repo_root}#checks.x86_64-linux.aspects" \
          "path:''${repo_root}#checks.x86_64-linux.release" \
          "path:''${repo_root}#checks.x86_64-linux.workflows" \
          "path:''${repo_root}#checks.x86_64-linux.upstream"
      fi
      mapfile -t outputs < <(
        nix --accept-flake-config build \
          --no-link \
          --print-build-logs \
          --print-out-paths \
          "$@"
      )
      printf '%s\n' "''${outputs[@]}"
      if [[ "''${PURPLEFIN_CACHE_PUSH:-true}" == true && -n "''${CACHIX_AUTH_TOKEN:-}" ]]; then
        cachix push --omit-deriver purplefin "''${outputs[@]}"
      elif [[ "''${PURPLEFIN_CACHE_PUSH:-true}" == true ]]; then
        echo "CACHIX_AUTH_TOKEN is unavailable; built outputs were not pushed" >&2
      fi
    '';
  };
  localCache = pkgs.writeShellApplication {
    name = "purplefin-local-cache";
    runtimeInputs = with pkgs; [coreutils secretspec];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      if [[ -z "''${CACHIX_AUTH_TOKEN:-}" ]]; then
        token_file="''${HOME}/.other-fun-things/.cachix-purplefin-auth"
        if [[ ! -r "''${token_file}" ]]; then
          export PURPLEFIN_CACHE_PUSH=false
          exec ${cacheChecks}/bin/purplefin-cache-checks "$@"
        fi
        CACHIX_AUTH_TOKEN="$(<"''${token_file}")"
        export CACHIX_AUTH_TOKEN
      fi
      cd "''${repo_root}"
      exec secretspec run \
        --file "''${repo_root}/secretspec.toml" \
        --provider local \
        --profile local-cache \
        --reason "Purplefin local Nix cache" \
        --scope cachix \
        -- ${cacheChecks}/bin/purplefin-cache-checks "$@"
    '';
  };
  verifyBluefin = pkgs.writeShellApplication {
    name = "purplefin-verify-bluefin";
    runtimeInputs = [pkgs.cosign];
    text = ''
      image='${bluefin.image}@${bluefin.digest}'
      cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity '${bluefin.cosignIdentity}' \
        "''${image}" >/dev/null
      printf '%s\n' "''${image}"
    '';
  };
  loadBluefin = pkgs.writeShellApplication {
    name = "purplefin-load-bluefin";
    runtimeInputs = [pkgs.podman];
    text = ''
      podman load --input ${bluefinArchive} >/dev/null
      image='${bluefin.image}:${bluefin.tag}'
      podman image exists "''${image}"
      printf '%s\n' "''${image}"
    '';
  };
  updateBluefin = pkgs.writeShellApplication {
    name = "purplefin-update-bluefin";
    runtimeInputs = with pkgs; [coreutils cosign jq npins];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      lock="''${repo_root}/npins/sources.json"
      [[ -f "''${repo_root}/flake.nix" && -f "''${lock}" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      update_tmp="$(mktemp -d -p "''${repo_root}" .npins-update.XXXXXX)"
      trap 'rm -rf -- "''${update_tmp}"' EXIT
      export TMPDIR="''${update_tmp}"
      npins --directory "''${repo_root}/npins" update bluefin-stable
      image="$(jq -er '.pins["bluefin-stable"].image_name' "''${lock}")"
      tag="$(jq -er '.pins["bluefin-stable"].image_tag' "''${lock}")"
      architecture="$(jq -er '.pins["bluefin-stable"].arch' "''${lock}")"
      digest="$(jq -er '.pins["bluefin-stable"].image_digest' "''${lock}")"
      archive_hash="$(jq -er '.pins["bluefin-stable"].hash' "''${lock}")"
      [[ "''${image}" == '${bluefin.image}' ]]
      [[ "''${tag}" == '${bluefin.tag}' ]]
      [[ "''${architecture}" == '${bluefin.architecture}' ]]
      [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
      [[ "''${archive_hash}" =~ ^sha256-[A-Za-z0-9+/]{43}=$ ]]
      cosign verify \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        --certificate-identity '${bluefin.cosignIdentity}' \
        "''${image}@''${digest}" >/dev/null
      if (( $# == 0 )); then
        printf '%s\n' "''${digest}"
      elif (( $# == 1 )); then
        printf 'digest=%s\n' "''${digest}" >>"$1"
      else
        echo "usage: nix run .#update-bluefin [-- OUTPUT_FILE]" >&2
        exit 2
      fi
    '';
  };
  releaseNotes = mkRepositoryApp {
    name = "purplefin-release-notes";
    script = "automation/release/notes.sh";
    runtimeInputs = with pkgs; [bash coreutils gawk gnugrep gnused];
  };
  trustedUpdate = mkRepositoryApp {
    name = "purplefin-trusted-update";
    script = "automation/github/validate-trusted-update.sh";
    runtimeInputs = with pkgs; [bash coreutils gh jq];
  };
  imagePlan = mkRepositoryApp {
    name = "purplefin-image-plan";
    script = "bootc/builder/plan.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq podman skopeo];
  };
  ciPlan = pkgs.writeShellApplication {
    name = "purplefin-ci-plan";
    runtimeInputs = [pkgs.jq];
    text = ''
      (( $# == 1 )) || {
        echo "usage: nix run .#ci-plan -- GITHUB_OUTPUT" >&2
        exit 2
      }
      : "''${IMAGE_REF:?IMAGE_REF is required}"
      base_image='${bluefin.image}'
      base_tag='${bluefin.tag}'
      base_digest='${bluefin.digest}'
      base_ref="''${base_image}@''${base_digest}"
      profiles="$(jq -c . ${generated}/bootc/generated/image-matrix.json)"
      export BASE_DIGEST="''${base_digest}" BASE_REF="''${base_ref}"
      matrix="$(${imagePlan}/bin/purplefin-image-plan "''${profiles}")"
      root_base="$(jq -c 'first(.include[] | select(.stage == "root")) // {}' <<<"''${matrix}")"
      hardware_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"''${matrix}")"
      role_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"''${matrix}")"
      {
        printf 'base_image=%s\n' "''${base_image}"
        printf 'base_digest=%s\n' "''${base_digest}"
        printf 'base_tag=%s\n' "''${base_tag}"
        printf 'hardware_matrix=%s\n' "''${hardware_matrix}"
        printf 'has_hardware=%s\n' "$(jq -r '.include | length > 0' <<<"''${hardware_matrix}")"
        printf 'has_builds=%s\n' "$(jq -r '.include | length > 0' <<<"''${matrix}")"
        printf 'has_roles=%s\n' "$(jq -r '.include | length > 0' <<<"''${role_matrix}")"
        printf 'has_root_base=%s\n' "$(jq -r 'has("profile")' <<<"''${root_base}")"
        printf 'matrix=%s\n' "''${matrix}"
        printf 'role_matrix=%s\n' "''${role_matrix}"
        printf 'root_base=%s\n' "''${root_base}"
        printf 'version=%s\n' '${version}'
      } >>"$1"
    '';
  };
  imageReuse = mkRepositoryApp {
    name = "purplefin-image-reuse";
    script = "bootc/builder/reuse-image.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq skopeo];
  };
  installerSmoke = mkRepositoryApp {
    name = "purplefin-installer-smoke";
    script = "tests/installer/smoke.sh";
    runtimeInputs = with pkgs; [bash coreutils gnugrep qemu];
  };
  installerBuild = import ./installer-application.nix {
    inherit exportArtifacts installerSmoke pkgs;
  };
  imageBuild = pkgs.writeShellApplication {
    name = "purplefin-image-build";
    runtimeInputs = with pkgs; [bash coreutils jq podman];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      (( $# == 2 )) || {
        echo "usage: nix run .#image-build -- PROFILE IMAGE_TAG" >&2
        exit 2
      }
      cd "''${repo_root}"
      ${exportArtifacts}/bin/purplefin-export-artifacts "''${repo_root}" >/dev/null
      profile="$1"
      tag="$2"
      jq -e --arg profile "''${profile}" '.profiles[$profile]' \
        bootc/generated/profile-catalog.json >/dev/null || {
        echo "Unknown profile: ''${profile}" >&2
        exit 2
      }
      base_image="$(${loadBluefin}/bin/purplefin-load-bluefin)"
      exec podman build \
        --file bootc/Containerfile \
        --pull=never \
        --build-arg "BASE_REF=''${base_image}" \
        --build-arg "BUILD_PROFILE=''${profile}" \
        --build-arg "PURPLEFIN_VERSION=${version}" \
        --label "org.opencontainers.image.base.digest=${bluefin.digest}" \
        --tag "''${tag}" \
        .
    '';
  };
}
