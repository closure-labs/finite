{
  bluefin,
  generated,
  imageBuilder,
  pkgs,
  version,
}: let
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
        exec ${pkgs.bash}/bin/bash "''${repo_root}/${script}" "$@"
      '';
    };
in rec {
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
          installer:sources/image-builder.json | \
          installer:modules/* | installer:lib/* | \
          installer:tests/installer/*)
            required=true; break ;;
          images:README.md | images:LICENSE | images:docs/* | \
          images:.editorconfig | images:.github/actions/build-installer/* | \
          images:.github/actions/setup-nix/* | \
          images:.github/dependabot.yml | \
          images:.github/workflows/build-installer.yml | \
          images:.github/workflows/cleanup.yml | \
          images:.github/workflows/queue-dependabot.yml | \
          images:.github/workflows/release.yml | \
          images:.github/workflows/update-flake-lock.yml | \
          images:.github/workflows/update-bluefin.yml | \
          images:.github/workflows/update-image-builder.yml | \
          images:automation/github/classify-ci.sh | \
          images:automation/github/validate-trusted-update.sh | \
          images:secretspec.toml | \
          images:installer/* | images:tests/installer/* | \
          images:tests/automation/* | \
          images:tests/repository/text-style.sh)
            ;;
          images:*) required=true; break ;;
        esac
      done
      printf '%s\n' "''${required}"
    '';
  };

  mkCi = checks: let
    checkNames = builtins.attrNames checks;
    quotedNames = pkgs.lib.concatMapStringsSep " " pkgs.lib.escapeShellArg checkNames;
    quotedPaths =
      pkgs.lib.concatMapStringsSep " " (
        name:
          pkgs.lib.escapeShellArg (
            builtins.unsafeDiscardStringContext (toString checks.${name})
          )
      )
      checkNames;
  in
    pkgs.writeShellApplication {
      name = "purplefin-ci";
      runtimeInputs = with pkgs; [cachix coreutils jq nix];
      text = ''
        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          exit 2
        }

        nix --accept-flake-config flake check \
          "git+file://''${repo_root}" \
          --print-build-logs \
          "$@"

        check_names=(${quotedNames})
        check_paths=(${quotedPaths})
        nix --accept-flake-config build --no-link "''${check_paths[@]}"
        max_closure_size=$((1024 * 1024))
        for index in "''${!check_paths[@]}"; do
          name="''${check_names[$index]}"
          path="''${check_paths[$index]}"
          [[ -e "''${path}" ]] || {
            echo "The completed Flake check did not realize ''${name}: ''${path}" >&2
            exit 1
          }
          closure_size="$(
            nix path-info --json --json-format 1 --closure-size "''${path}" |
              jq -er 'to_entries[0].value.closureSize'
          )"
          if (( closure_size > max_closure_size )); then
            printf '%s proof closure is %s bytes; cache limit is %s bytes\n' \
              "''${name}" "''${closure_size}" "''${max_closure_size}" >&2
            exit 1
          fi
          printf '%s\t%s bytes\t%s\n' "''${name}" "''${closure_size}" "''${path}"
        done

        if [[ "''${PURPLEFIN_CACHE_PUSH:-true}" == true && -n "''${CACHIX_AUTH_TOKEN:-}" ]]; then
          for path in "''${check_paths[@]}"; do
            cachix push --omit-deriver purplefin "''${path}"
          done
        elif [[ "''${PURPLEFIN_CACHE_PUSH:-true}" == true ]]; then
          echo "CACHIX_AUTH_TOKEN is unavailable; proof outputs were not pushed" >&2
        fi
      '';
    };
  mkLocalCache = ciApplication:
    pkgs.writeShellApplication {
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
          [[ -r "''${token_file}" ]] || {
            echo "CACHIX_AUTH_TOKEN is unset and ''${token_file} is unreadable" >&2
            exit 2
          }
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
          -- ${ciApplication}/bin/purplefin-ci "$@"
      '';
    };
  verifyBluefin = pkgs.writeShellApplication {
    name = "purplefin-verify-bluefin";
    runtimeInputs = [pkgs.cosign];
    text = ''
      image='${bluefin.image}@${bluefin.digest}'
      cosign verify \
        --certificate-oidc-issuer '${bluefin.cosign.issuer}' \
        --certificate-identity '${bluefin.cosign.identity}' \
        "''${image}" >/dev/null
      printf '%s\n' "''${image}"
    '';
  };
  loadBluefin = pkgs.writeShellApplication {
    name = "purplefin-load-bluefin";
    runtimeInputs = with pkgs; [coreutils cosign skopeo];
    text = ''
      if [[ "''${CI:-}" == true && $EUID -ne 0 && -z "''${_PURPLEFIN_IN_USERNS:-}" ]]; then
        host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
        [[ -n "''${host_podman}" && "''${host_podman}" != /nix/store/* ]] || {
          echo "The CI runner's host Podman is required to enter rootless storage" >&2
          exit 1
        }
        exec env _PURPLEFIN_IN_USERNS=1 "''${host_podman}" unshare "$0" "$@"
      fi
      ${verifyBluefin}/bin/purplefin-verify-bluefin >/dev/null
      source='docker://${bluefin.image}@${bluefin.digest}'
      image='${bluefin.image}:${bluefin.tag}'
      data_home="''${XDG_DATA_HOME:-''${HOME}/.local/share}"
      runtime_dir="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
      graph_root="''${CONTAINERS_STORAGE_GRAPHROOT:-''${data_home}/containers/storage}"
      run_root="''${CONTAINERS_STORAGE_RUNROOT:-''${runtime_dir}/containers}"
      storage_driver="''${CONTAINERS_STORAGE_DRIVER:-overlay}"
      storage_ref="containers-storage:[''${storage_driver}@''${graph_root}+''${run_root}]''${image}"
      install -d "''${graph_root}" "''${run_root}"
      loaded_digest="$(
        skopeo inspect --format '{{.Digest}}' "''${storage_ref}" 2>/dev/null || true
      )"
      if [[ "''${loaded_digest}" != '${bluefin.digest}' ]]; then
        skopeo copy \
          --override-arch '${bluefin.architecture}' \
          --override-os linux \
          --preserve-digests \
          --retry-times 3 \
          "''${source}" \
          "''${storage_ref}" >&2
        loaded_digest="$(
          skopeo inspect --format '{{.Digest}}' "''${storage_ref}"
        )"
      fi
      [[ "''${loaded_digest}" == '${bluefin.digest}' ]] || {
        echo "Loaded Bluefin digest ''${loaded_digest} does not match ${bluefin.digest}" >&2
        exit 1
      }
      printf '%s\n' "''${image}"
    '';
  };
  sourceVerify = pkgs.writeShellApplication {
    name = "purplefin-source-verify";
    runtimeInputs = with pkgs; [cosign coreutils skopeo];
    text = ''
      source_name="''${1:?usage: purplefin-source-verify SOURCE}"
      case "''${source_name}" in
        bluefin)
          image='${bluefin.image}'
          architecture='${bluefin.architecture}'
          digest='${bluefin.digest}'
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          cosign verify \
            --certificate-oidc-issuer '${bluefin.cosign.issuer}' \
            --certificate-identity '${bluefin.cosign.identity}' \
            "''${image}@''${digest}" >/dev/null
          ;;
        image-builder)
          image='${imageBuilder.image}'
          architecture='${imageBuilder.architecture}'
          digest='${imageBuilder.digest}'
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          ;;
        *)
          echo "Unknown OCI source: ''${source_name}" >&2
          exit 2
          ;;
      esac
      printf '%s@%s\n' "''${image}" "''${digest}"
    '';
  };
  sourceUpdate = pkgs.writeShellApplication {
    name = "purplefin-source-update";
    runtimeInputs = with pkgs; [coreutils cosign jq nix skopeo];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      source_name="''${1:?usage: purplefin-source-update SOURCE [OUTPUT_FILE]}"
      output_file="''${2:-}"
      case "''${source_name}" in
        flake)
          before="$(sha256sum flake.lock | cut -d' ' -f1)"
          nix flake update
          after="$(sha256sum flake.lock | cut -d' ' -f1)"
          changed=false
          [[ "''${before}" == "''${after}" ]] || changed=true
          digest="''${after}"
          ;;
        bluefin | image-builder)
          lock="''${repo_root}/sources/''${source_name}.json"
          [[ -f "''${lock}" ]]
          image="$(jq -er '.image' "''${lock}")"
          tag="$(jq -er '.tag' "''${lock}")"
          architecture="$(jq -er '.architecture' "''${lock}")"
          current="$(jq -er '.digest' "''${lock}")"
          digest="$(
            skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
              --format '{{.Digest}}' "docker://''${image}:''${tag}"
          )"
          [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
          if [[ "''${source_name}" == bluefin ]]; then
            issuer="$(jq -er '.cosign.issuer' "''${lock}")"
            identity="$(jq -er '.cosign.identity' "''${lock}")"
            cosign verify \
              --certificate-oidc-issuer "''${issuer}" \
              --certificate-identity "''${identity}" \
              "''${image}@''${digest}" >/dev/null
          fi
          changed=false
          if [[ "''${current}" != "''${digest}" ]]; then
            temporary="$(mktemp "''${lock}.XXXXXX")"
            trap 'rm -f -- "''${temporary}"' EXIT
            jq --arg digest "''${digest}" '.digest = $digest' "''${lock}" >"''${temporary}"
            chmod --reference="''${lock}" "''${temporary}"
            mv -- "''${temporary}" "''${lock}"
            changed=true
          fi
          ;;
        *)
          echo "Unknown source: ''${source_name}" >&2
          exit 2
          ;;
      esac
      if [[ -n "''${output_file}" ]]; then
        {
          printf 'changed=%s\n' "''${changed}"
          printf 'digest=%s\n' "''${digest}"
        } >>"''${output_file}"
      else
        jq -cn --arg source "''${source_name}" --arg digest "''${digest}" \
          --argjson changed "''${changed}" \
          '{source: $source, changed: $changed, digest: $digest}'
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
  queueDependabot = mkRepositoryApp {
    name = "purplefin-queue-dependabot";
    script = "automation/github/queue-dependabot.sh";
    runtimeInputs = with pkgs; [bash gh jq];
  };
  packageCleanup = mkRepositoryApp {
    name = "purplefin-package-cleanup";
    script = "automation/github/package-cleanup.sh";
    runtimeInputs = with pkgs; [bash gh jq];
  };
  classifyCi = mkRepositoryApp {
    name = "purplefin-classify-ci";
    script = "automation/github/classify-ci.sh";
    runtimeInputs = with pkgs; [bash classifyChanges coreutils git];
  };
  imagePlan = mkRepositoryApp {
    name = "purplefin-image-plan";
    script = "bootc/builder/plan.sh";
    runtimeInputs = with pkgs; [bash coreutils cosign jq podman skopeo];
  };
  shardPlan = mkRepositoryApp {
    name = "purplefin-shard-plan";
    script = "bootc/builder/shard-plan.sh";
    runtimeInputs = with pkgs; [bash jq];
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
      ${verifyBluefin}/bin/purplefin-verify-bluefin >/dev/null
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
      candidate_shards="$(${shardPlan}/bin/purplefin-shard-plan "''${matrix}" 4)"
      {
        printf 'base_image=%s\n' "''${base_image}"
        printf 'base_digest=%s\n' "''${base_digest}"
        printf 'base_tag=%s\n' "''${base_tag}"
        printf 'candidate_shards=%s\n' "''${candidate_shards}"
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
  validateImageShard = pkgs.writeShellApplication {
    name = "purplefin-validate-image-shard";
    runtimeInputs = with pkgs; [bash coreutils jq skopeo];
    text = ''
      export PURPLEFIN_GENERATED_ROOT=${generated}
      export PURPLEFIN_BASE_DIGEST='${bluefin.digest}'
      export PURPLEFIN_LOAD_BLUEFIN=${loadBluefin}/bin/purplefin-load-bluefin
      export PURPLEFIN_VERSION='${version}'
      if [[ "''${CI:-}" == true ]]; then
        host_buildah="$(PATH=/usr/local/bin:/usr/bin:/bin command -v buildah || true)"
        host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
        [[ -n "''${host_buildah}" && -n "''${host_podman}" ]] || {
          echo "The CI runner's host Buildah and Podman are required" >&2
          exit 1
        }
        export PURPLEFIN_BUILDAH="''${host_buildah}"
        export PURPLEFIN_PODMAN="''${host_podman}"
      else
        export PURPLEFIN_BUILDAH=${pkgs.buildah}/bin/buildah
        export PURPLEFIN_PODMAN=${pkgs.podman}/bin/podman
      fi
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      exec ${pkgs.bash}/bin/bash \
        "''${repo_root}/bootc/builder/validate-shard.sh" "$@"
    '';
  };
  installerSmoke = mkRepositoryApp {
    name = "purplefin-installer-smoke";
    script = "tests/installer/smoke.sh";
    runtimeInputs = with pkgs; [bash coreutils gnugrep qemu];
  };
  installerBuild = import ./installer-application.nix {
    inherit generated imageBuilder installerSmoke pkgs;
  };
  sbomAttestation = mkRepositoryApp {
    name = "purplefin-sbom-attestation";
    script = "bootc/builder/sbom.sh";
    runtimeInputs = with pkgs; [coreutils gh jq];
  };
  imageSbom = mkRepositoryApp {
    name = "purplefin-image-sbom";
    script = "bootc/builder/sbom.sh";
    runtimeInputs = with pkgs; [coreutils gh jq nix syft];
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
      profile="$1"
      tag="$2"
      jq -e --arg profile "''${profile}" '.profiles[$profile]' \
        ${generated}/bootc/generated/profile-catalog.json >/dev/null || {
        echo "Unknown profile: ''${profile}" >&2
        exit 2
      }
      base_image="$(${loadBluefin}/bin/purplefin-load-bluefin)"
      exec podman build \
        --file bootc/Containerfile \
        --network host \
        --pull=never \
        --security-opt label=disable \
        --build-context purplefin-generated=${generated} \
        --build-arg "BASE_REF=''${base_image}" \
        --build-arg "BUILD_PROFILE=''${profile}" \
        --build-arg "PURPLEFIN_VERSION=${version}" \
        --label "org.opencontainers.image.base.digest=${bluefin.digest}" \
        --tag "''${tag}" \
      .
    '';
  };
  mkWorkflowToolset = {
    name,
    paths,
    required,
  }:
    assert builtins.all (application: builtins.elem application paths) required;
      pkgs.buildEnv {
        inherit name paths;
        ignoreCollisions = true;
      };

  workflowCi = mkWorkflowToolset {
    name = "purplefin-workflow-ci";
    paths = with pkgs; [actionlint cachix classifyCi ciPlan coreutils git jq nix trustedUpdate zizmor];
    required = [classifyCi];
  };
  workflowImage = mkWorkflowToolset {
    name = "purplefin-workflow-image";
    paths = with pkgs; [ciPlan coreutils cosign gh imagePlan imageReuse imageSbom jq loadBluefin nix oras skopeo validateImageShard];
    required = [ciPlan imageReuse imageSbom loadBluefin validateImageShard];
  };
  workflowInstaller = mkWorkflowToolset {
    name = "purplefin-workflow-installer";
    paths = [installerBuild installerSmoke];
    required = [installerBuild];
  };
  workflowRelease = mkWorkflowToolset {
    name = "purplefin-workflow-release";
    paths = with pkgs; [coreutils cosign gh gzip jq nix oras releaseNotes sbomAttestation skopeo trustedUpdate];
    required = [releaseNotes sbomAttestation trustedUpdate];
  };
  workflowMaintenance = mkWorkflowToolset {
    name = "purplefin-workflow-maintenance";
    paths = with pkgs; [coreutils gh jq nix packageCleanup skopeo sourceUpdate trustedUpdate];
    required = [packageCleanup sourceUpdate trustedUpdate];
  };
}
