{
  generated,
  pkgs,
  profiles,
  repositoryToolchain,
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
          images:.github/workflows/update-image-builder.yml | \
          images:automation/github/validate-trusted-update.sh | \
          images:installer/* | images:tests/installer/* | \
          images:tests/repository/text-style.sh)
            ;;
          images:*) required=true; break ;;
        esac
      done
      printf '%s\n' "''${required}"
    '';
  };

  ci = mkRepositoryApp {
    name = "purplefin-ci";
    script = "tests/ci.sh";
    runtimeInputs = repositoryToolchain ++ [classifyChanges];
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
  imageBuild = pkgs.writeShellApplication {
    name = "purplefin-image-build";
    runtimeInputs = with pkgs; [bash coreutils jq podman skopeo];
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
      base_image='${profiles.base.upstream.image}:${profiles.base.upstream.tag}'
      base_digest="$(skopeo inspect --retry-times 3 "docker://''${base_image}" | jq -er .Digest)"
      exec podman build \
        --file bootc/Containerfile \
        --pull=missing \
        --build-arg "BASE_REF=${profiles.base.upstream.image}@''${base_digest}" \
        --build-arg "BUILD_PROFILE=''${profile}" \
        --build-arg "PURPLEFIN_VERSION=${version}" \
        --label "org.opencontainers.image.base.digest=''${base_digest}" \
        --tag "''${tag}" \
        .
    '';
  };
}
