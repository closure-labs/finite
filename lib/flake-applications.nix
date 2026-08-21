{
  bluefin,
  bluefinDx,
  devenv,
  determinateNix,
  generated,
  imageBuilder,
  pkgs,
  selfSource,
  version,
}: let
  upstreamLocks = {
    inherit bluefin;
    bluefin-dx = bluefinDx;
  };
  upstreamLocksFile = pkgs.writeText "purplefin-upstreams.json" (builtins.toJSON upstreamLocks);
  selfFlakeUri = "path:${builtins.unsafeDiscardStringContext (toString selfSource)}";
in rec {
  classifyChanges = import ./ci-applications/classify-changes.nix {inherit pkgs;};
  updateLocks = import ./ci-applications/update-locks.nix {
    inherit devenv pkgs;
  };

  githubActionsSecrets = pkgs.writeShellApplication {
    name = "purplefin-github-actions-secrets";
    runtimeInputs = [pkgs.secretspec];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/secretspec.toml" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      exec secretspec export \
        --file "''${repo_root}/secretspec.toml" \
        --format gha \
        --profile github-actions \
        --provider github-actions \
        --reason "Purplefin GitHub Actions secret mapping" \
        --scope github-actions
    '';
  };

  mkCheck = checks: let
    checkNames = builtins.attrNames checks;
    quotedNames = pkgs.lib.concatMapStringsSep " " pkgs.lib.escapeShellArg checkNames;
  in
    pkgs.writeShellApplication {
      name = "purplefin-ci-check";
      # Nix comes from the host's Determinate installation; do not shadow it
      # with the upstream Nixpkgs client inside this application wrapper.
      runtimeInputs = with pkgs; [cachix coreutils jq];
      text = ''
        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          exit 2
        }
        flake_uri="path:''${repo_root}"
        if [[ "''${GITHUB_ACTIONS:-false}" == true ]]; then
          # Keep checkout metadata out of checks such as treefmt, which create
          # their own temporary Git repository from the flake source.
          flake_uri="git+file://''${repo_root}"
        fi

        check_names=(${quotedNames})

        # Build only the declared checks explicitly so their proof paths are
        # guaranteed to be present for sizing and upload. Do this before the
        # build-free Flake validation because cold Devenv evaluation requires
        # import-from-derivation paths that the check build realizes.
        nix --accept-flake-config build \
          --keep-going \
          --no-link \
          --print-build-logs \
          "$@" \
          "''${flake_uri}#ci-checks"
        nix --accept-flake-config flake check \
          "''${flake_uri}" \
          --no-build \
          "$@"

        check_paths_json="$(
          nix --accept-flake-config eval --json \
            --apply 'checks: builtins.mapAttrs (_: check: check.outPath) checks' \
            "''${flake_uri}#checks.${pkgs.stdenv.hostPlatform.system}"
        )"
        max_closure_size=$((1024 * 1024))
        check_paths=()
        for name in "''${check_names[@]}"; do
          path="$(jq -er --arg name "''${name}" '.[$name]' <<<"''${check_paths_json}")"
          check_paths+=("''${path}")
          [[ -e "''${path}" ]] || {
            echo "The explicit check build did not realize ''${name}: ''${path}" >&2
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
          -- ${ciApplication}/bin/purplefin-ci-check "$@"
      '';
    };
  verifyBluefin = pkgs.writeShellApplication {
    name = "purplefin-verify-bluefin";
    runtimeInputs = [pkgs.cosign pkgs.jq];
    text = ''
      source_name="''${1:-bluefin}"
      jq -e --arg source "''${source_name}" '.[$source]' ${upstreamLocksFile} >/dev/null || {
        echo "Unknown Bluefin source: ''${source_name}" >&2
        exit 2
      }
      image="$(jq -er --arg source "''${source_name}" '.[$source].image + "@" + .[$source].digest' ${upstreamLocksFile})"
      issuer="$(jq -er --arg source "''${source_name}" '.[$source].cosign.issuer' ${upstreamLocksFile})"
      identity="$(jq -er --arg source "''${source_name}" '.[$source].cosign.identity' ${upstreamLocksFile})"
      cosign verify \
        --certificate-oidc-issuer "''${issuer}" \
        --certificate-identity "''${identity}" \
        "''${image}" >/dev/null
      printf '%s\n' "''${image}"
    '';
  };
  loadBluefin = pkgs.writeShellApplication {
    name = "purplefin-load-bluefin";
    runtimeInputs = with pkgs; [coreutils cosign jq skopeo];
    text = ''
      if [[ "''${CI:-}" == true && $EUID -ne 0 && -z "''${_PURPLEFIN_IN_USERNS:-}" ]]; then
        host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
        [[ -n "''${host_podman}" && "''${host_podman}" != /nix/store/* ]] || {
          echo "The CI runner's host Podman is required to enter rootless storage" >&2
          exit 1
        }
        exec env _PURPLEFIN_IN_USERNS=1 "''${host_podman}" unshare "$0" "$@"
      fi
      source_name="''${1:-bluefin}"
      ${verifyBluefin}/bin/purplefin-verify-bluefin "''${source_name}" >/dev/null
      locked_image="$(jq -er --arg source "''${source_name}" '.[$source].image' ${upstreamLocksFile})"
      locked_digest="$(jq -er --arg source "''${source_name}" '.[$source].digest' ${upstreamLocksFile})"
      locked_tag="$(jq -er --arg source "''${source_name}" '.[$source].tag' ${upstreamLocksFile})"
      locked_architecture="$(jq -er --arg source "''${source_name}" '.[$source].architecture' ${upstreamLocksFile})"
      source="docker://''${locked_image}@''${locked_digest}"
      image="''${locked_image}:''${locked_tag}"
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
      if [[ "''${loaded_digest}" != "''${locked_digest}" ]]; then
        skopeo copy \
          --override-arch "''${locked_architecture}" \
          --override-os linux \
          --preserve-digests \
          --retry-times 3 \
          "''${source}" \
          "''${storage_ref}" >&2
        loaded_digest="$(
          skopeo inspect --format '{{.Digest}}' "''${storage_ref}"
        )"
      fi
      [[ "''${loaded_digest}" == "''${locked_digest}" ]] || {
        echo "Loaded Bluefin digest ''${loaded_digest} does not match ''${locked_digest}" >&2
        exit 1
      }
      printf '%s\n' "''${image}"
    '';
  };
  sourceVerify = pkgs.writeShellApplication {
    name = "purplefin-source-verify";
    runtimeInputs = with pkgs; [cosign coreutils curl skopeo];
    text = ''
      export PURPLEFIN_BLUEFIN_ARCHITECTURE=${bluefin.architecture}
      export PURPLEFIN_BLUEFIN_DIGEST=${bluefin.digest}
      export PURPLEFIN_BLUEFIN_IMAGE=${bluefin.image}
      export PURPLEFIN_BLUEFIN_ISSUER=${bluefin.cosign.issuer}
      export PURPLEFIN_BLUEFIN_IDENTITY=${bluefin.cosign.identity}
      export PURPLEFIN_IMAGE_BUILDER_ARCHITECTURE=${imageBuilder.architecture}
      export PURPLEFIN_IMAGE_BUILDER_DIGEST=${imageBuilder.digest}
      export PURPLEFIN_IMAGE_BUILDER_IMAGE=${imageBuilder.image}
      export PURPLEFIN_DETERMINATE_NIX_INSTALLER_SHA256=${determinateNix.installer.sha256}
      export PURPLEFIN_DETERMINATE_NIX_INSTALLER_URL=${pkgs.lib.escapeShellArg determinateNix.installer.url}
      export PURPLEFIN_DETERMINATE_NIX_POLICY_SHA256=${determinateNix.selinuxPolicy.sha256}
      export PURPLEFIN_DETERMINATE_NIX_POLICY_URL=${pkgs.lib.escapeShellArg determinateNix.selinuxPolicy.url}
      export PURPLEFIN_DETERMINATE_NIX_FC_SHA256=${determinateNix.selinuxFileContexts.sha256}
      export PURPLEFIN_DETERMINATE_NIX_FC_URL=${pkgs.lib.escapeShellArg determinateNix.selinuxFileContexts.url}
      export PURPLEFIN_DETERMINATE_NIX_VERSION=${determinateNix.version}
      source_name="''${1:?usage: purplefin-source-verify SOURCE}"
      case "''${source_name}" in
        bluefin | bluefin-dx)
          image="$(jq -er --arg source "''${source_name}" '.[$source].image' ${upstreamLocksFile})"
          architecture="$(jq -er --arg source "''${source_name}" '.[$source].architecture' ${upstreamLocksFile})"
          digest="$(jq -er --arg source "''${source_name}" '.[$source].digest' ${upstreamLocksFile})"
          issuer="$(jq -er --arg source "''${source_name}" '.[$source].cosign.issuer' ${upstreamLocksFile})"
          identity="$(jq -er --arg source "''${source_name}" '.[$source].cosign.identity' ${upstreamLocksFile})"
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          cosign verify \
            --certificate-oidc-issuer "''${issuer}" \
            --certificate-identity "''${identity}" \
            "''${image}@''${digest}" >/dev/null
          ;;
        image-builder)
          image="''${PURPLEFIN_IMAGE_BUILDER_IMAGE:?}"
          architecture="''${PURPLEFIN_IMAGE_BUILDER_ARCHITECTURE:?}"
          digest="''${PURPLEFIN_IMAGE_BUILDER_DIGEST:?}"
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          ;;
        determinate-nix)
          installer="$(mktemp)"
          policy="$(mktemp)"
          file_contexts="$(mktemp)"
          trap 'rm -f -- "''${installer}" "''${policy}" "''${file_contexts}"' EXIT
          curl --fail --location --retry 3 --output "''${installer}" \
            "''${PURPLEFIN_DETERMINATE_NIX_INSTALLER_URL:?}"
          curl --fail --location --retry 3 --output "''${policy}" \
            "''${PURPLEFIN_DETERMINATE_NIX_POLICY_URL:?}"
          curl --fail --location --retry 3 --output "''${file_contexts}" \
            "''${PURPLEFIN_DETERMINATE_NIX_FC_URL:?}"
          printf '%s  %s\n' "''${PURPLEFIN_DETERMINATE_NIX_INSTALLER_SHA256:?}" "''${installer}" |
            sha256sum --check --status
          printf '%s  %s\n' "''${PURPLEFIN_DETERMINATE_NIX_POLICY_SHA256:?}" "''${policy}" |
            sha256sum --check --status
          printf '%s  %s\n' "''${PURPLEFIN_DETERMINATE_NIX_FC_SHA256:?}" "''${file_contexts}" |
            sha256sum --check --status
          printf 'determinate-nix@%s\n' "''${PURPLEFIN_DETERMINATE_NIX_VERSION:?}"
          exit 0
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
    runtimeInputs = with pkgs; [coreutils cosign curl diffutils gh jq skopeo];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}" || exit
      source_name="''${1:?usage: purplefin-source-update SOURCE [OUTPUT_FILE]}"
      output_file="''${2:-}"
      case "''${source_name}" in
        bluefin | bluefin-dx | image-builder)
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
          if [[ "''${source_name}" == bluefin || "''${source_name}" == bluefin-dx ]]; then
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
        determinate-nix)
          lock="''${repo_root}/sources/determinate-nix.json"
          [[ -f "''${lock}" ]]
          release="$(gh api repos/DeterminateSystems/nix-installer/releases/latest)"
          jq -e '.draft == false and .prerelease == false' <<<"''${release}" >/dev/null
          tag="$(jq -er '.tag_name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))' <<<"''${release}")"
          version="''${tag#v}"
          asset="$(jq -ec '.assets[] | select(.name == "nix-installer-x86_64-linux")' <<<"''${release}")"
          installer_url="$(jq -er .browser_download_url <<<"''${asset}")"
          digest="$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' <<<"''${asset}")"
          installer_sha256="''${digest#sha256:}"
          policy_url="https://raw.githubusercontent.com/DeterminateSystems/nix-installer/''${tag}/src/action/linux/selinux/determinate-nix.pp"
          file_contexts_url="https://raw.githubusercontent.com/DeterminateSystems/nix-installer/''${tag}/src/action/linux/selinux/nix.fc"
          policy_file="$(mktemp)"
          file_contexts_file="$(mktemp)"
          temporary="$(mktemp "''${lock}.XXXXXX")"
          trap 'rm -f -- "''${policy_file}" "''${file_contexts_file}" "''${temporary}"' EXIT
          curl --fail --location --retry 3 --output "''${policy_file}" "''${policy_url}"
          curl --fail --location --retry 3 --output "''${file_contexts_file}" "''${file_contexts_url}"
          policy_sha256="$(sha256sum "''${policy_file}" | cut -d' ' -f1)"
          file_contexts_sha256="$(sha256sum "''${file_contexts_file}" | cut -d' ' -f1)"
          jq \
            --arg version "''${version}" \
            --arg installer_url "''${installer_url}" \
            --arg installer_sha256 "''${installer_sha256}" \
            --arg policy_url "''${policy_url}" \
            --arg policy_sha256 "''${policy_sha256}" \
            --arg file_contexts_url "''${file_contexts_url}" \
            --arg file_contexts_sha256 "''${file_contexts_sha256}" '
              .version = $version |
              .installer.url = $installer_url |
              .installer.sha256 = $installer_sha256 |
              .selinuxPolicy.url = $policy_url |
              .selinuxPolicy.sha256 = $policy_sha256 |
              .selinuxFileContexts.url = $file_contexts_url |
              .selinuxFileContexts.sha256 = $file_contexts_sha256
            ' "''${lock}" >"''${temporary}"
          changed=false
          if ! cmp --silent "''${lock}" "''${temporary}"; then
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
  releaseNotes = pkgs.writeShellApplication {
    name = "purplefin-release-notes";
    runtimeInputs = with pkgs; [bash coreutils gawk gnugrep gnused];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      version="''${1:?usage: release-notes.sh VERSION [CHANGELOG]}"
      changelog="''${2:-CHANGELOG.md}"

      [[ "''${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        echo "Release notes require a stable semantic version: ''${version}" >&2
        exit 2
      }
      [[ -f "''${changelog}" ]] || {
        echo "Changelog does not exist: ''${changelog}" >&2
        exit 2
      }

      heading_prefix="## [''${version}] - "
      heading_count="$(grep -cF "''${heading_prefix}" "''${changelog}" || true)"
      [[ "''${heading_count}" -eq 1 ]] || {
        echo "Expected one changelog heading beginning with ''${heading_prefix}" >&2
        exit 2
      }

      escaped_version="''${version//./\\.}"
      grep -Eq "^## \\[''${escaped_version}\\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" \
        "''${changelog}" || {
        echo "Changelog release heading must include an ISO date" >&2
        exit 2
      }

      awk -v heading_prefix="''${heading_prefix}" '
        index($0, heading_prefix) == 1 {
          found = 1
          next
        }
        found && /^## \[/ {
          exit
        }
        found && /^\[[^]]+\]:/ {
          exit
        }
        found {
          if (!started && $0 == "") {
            next
          }
          started = 1
          lines[++count] = $0
        }
        END {
          if (!found) {
            exit 2
          }
          while (count > 0 && lines[count] == "") {
            count--
          }
          for (line = 1; line <= count; line++) {
            print lines[line]
          }
        }
      ' "''${changelog}"
    '';
  };
  trustedUpdate = pkgs.writeShellApplication {
    name = "purplefin-trusted-update";
    runtimeInputs = with pkgs; [bash coreutils gh jq];
    text = ''
          repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
          [[ -f "''${repo_root}/flake.nix" ]] || {
            echo "Run this command from the Purplefin repository root" >&2
            exit 2
          }
          cd "''${repo_root}"
          set -euo pipefail

          : "''${GH_TOKEN:?GH_TOKEN must be set}"
          : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
          : "''${PR_NUMBER:?PR_NUMBER must be set}"
          : "''${EXPECTED_BRANCH:?EXPECTED_BRANCH must be set}"
          : "''${EXPECTED_TITLE:?EXPECTED_TITLE must be set}"
          : "''${EXPECTED_AUTHOR:?EXPECTED_AUTHOR must be set}"
          : "''${DEFAULT_BRANCH:?DEFAULT_BRANCH must be set}"

          read_pr() {
            gh pr view "''${PR_NUMBER}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --json author,baseRefName,files,headRefName,headRefOid,headRepository,mergeStateStatus,state,title,url
          }

          validate_pr() {
            local candidate=$1
            [[ "$(jq -er '.state' <<<"''${candidate}")" == OPEN ]]
            [[ "$(jq -er '.title' <<<"''${candidate}")" == "''${EXPECTED_TITLE}" ]]
            [[ "$(jq -er '.author.login' <<<"''${candidate}")" == "''${EXPECTED_AUTHOR}" ]]
            [[ "$(jq -er '.baseRefName' <<<"''${candidate}")" == "''${DEFAULT_BRANCH}" ]]
            [[ "$(jq -er '.headRepository.nameWithOwner' <<<"''${candidate}")" == "''${GITHUB_REPOSITORY}" ]]
            [[ "$(jq -er '.headRefName' <<<"''${candidate}")" == "''${EXPECTED_BRANCH}" ]]
            if [[ -n "''${EXPECTED_FILES:-}" ]]; then
              jq -e --arg allowed "''${EXPECTED_FILES}" '
                ($allowed | split(",")) as $allowed_files |
                (.files | length) > 0 and
                all(.files[]; (.path as $path | $allowed_files | index($path)) != null)
              ' <<<"''${candidate}" >/dev/null || {
                echo 'Pull request changes files outside the declared automation scope' >&2
                return 1
              }
            fi
          }

          pr="$(read_pr)"
          validate_pr "''${pr}"
          if [[ "$(jq -er '.mergeStateStatus' <<<"''${pr}")" == BEHIND ]]; then
            gh pr update-branch "''${PR_NUMBER}" --repo "''${GITHUB_REPOSITORY}"
            pr="$(read_pr)"
            validate_pr "''${pr}"
          fi
          branch="$(jq -er '.headRefName' <<<"''${pr}")"
          head_sha="$(jq -er '.headRefOid' <<<"''${pr}")"
          pr_url="$(jq -er '.url' <<<"''${pr}")"

          dispatch_and_wait() {
            local workflow="$1"
            shift
            local previous_run_id run_id

            previous_run_id="$({
              gh run list \
                --repo "''${GITHUB_REPOSITORY}" \
                --workflow "''${workflow}" \
                --event workflow_dispatch \
                --branch "''${branch}" \
                --commit "''${head_sha}" \
                --limit 1 \
                --json databaseId \
                --jq '.[0].databaseId // empty'
            })"
            gh workflow run "''${workflow}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --ref "''${branch}" \
              "$@"

        run_id=""
            for _ in {1..24}; do
              run_id="$({
                gh run list \
                  --repo "''${GITHUB_REPOSITORY}" \
                  --workflow "''${workflow}" \
                  --event workflow_dispatch \
                  --branch "''${branch}" \
                  --commit "''${head_sha}" \
                  --limit 5 \
                  --json databaseId \
                  --jq ".[] | select((.databaseId | tostring) != \"''${previous_run_id}\") | .databaseId" |
                  head -n 1
              })"
              [[ -z "''${run_id}" ]] || break
              sleep 5
            done
            [[ -n "''${run_id}" ]] || {
              echo "Could not locate ''${workflow} validation run" >&2
              exit 1
            }

            gh run watch "''${run_id}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --exit-status
          }

      existing_ci_run=""
          for _ in {1..6}; do
            existing_ci_run="$({
              gh run list \
                --repo "''${GITHUB_REPOSITORY}" \
                --workflow build.yml \
                --event pull_request \
                --branch "''${branch}" \
                --commit "''${head_sha}" \
                --limit 1 \
                --json conclusion,databaseId,status \
                --jq '.[0] // empty'
            })"
            [[ -z "''${existing_ci_run}" ]] || break
            sleep 5
          done

          if [[ -n "''${existing_ci_run}" ]]; then
            existing_ci_run_id="$(jq -er '.databaseId' <<<"''${existing_ci_run}")"
            if [[ "$(jq -r '.conclusion // empty' <<<"''${existing_ci_run}")" == action_required ]]; then
              gh api \
                --method POST \
                "repos/''${GITHUB_REPOSITORY}/actions/runs/''${existing_ci_run_id}/approve"
            fi
            gh run watch "''${existing_ci_run_id}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --exit-status
          else
            dispatch_and_wait build.yml -f validate_only=true
          fi
          gh pr merge \
            --repo "''${GITHUB_REPOSITORY}" \
            --auto \
            --merge \
            --match-head-commit "''${head_sha}" \
            "''${pr_url}"
    '';
  };
  queueDependabot = pkgs.writeShellApplication {
    name = "purplefin-queue-dependabot";
    runtimeInputs = with pkgs; [bash gh jq];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${DEFAULT_BRANCH:?DEFAULT_BRANCH is required}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      : "''${GH_TOKEN:?GH_TOKEN is required}"

      pull_requests="$({
        gh api --paginate \
          "repos/''${GITHUB_REPOSITORY}/pulls?state=open&per_page=100" \
          --slurp
      })"

      jq -c \
        --arg branch "''${DEFAULT_BRANCH}" \
        --arg repository "''${GITHUB_REPOSITORY}" '
          add[] |
          select(.draft == false) |
          select(.user.login == "dependabot[bot]") |
          select(.head.repo.full_name == $repository) |
          select(.base.ref == $branch) |
          {sha: .head.sha, url: .html_url}
        ' <<<"''${pull_requests}" |
        while IFS= read -r pull_request; do
          head_sha="$(jq -er '.sha' <<<"''${pull_request}")"
          pr_url="$(jq -er '.url' <<<"''${pull_request}")"
          gh pr merge \
            --auto \
            --merge \
            --match-head-commit "''${head_sha}" \
            "''${pr_url}"
        done
    '';
  };
  packageCleanup = pkgs.writeShellApplication {
    name = "purplefin-package-cleanup";
    runtimeInputs = with pkgs; [bash gh jq];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${DRY_RUN:=true}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      : "''${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required}"

      owner="''${GITHUB_REPOSITORY_OWNER}"
      package="''${GITHUB_REPOSITORY#*/}"
      # Build and installer caches use isolated sibling packages. Querying only
      # the primary image package keeps cache retention outside this cleanup.
      obsolete_tags='["dale-cosmic","development-desktop-x86_64","support-lenovo-generic"]'

      delete_version() {
        local package_name="$1"
        local version_id="$2"
        if [[ "''${DRY_RUN}" != true ]]; then
          gh api --method DELETE \
            "/users/''${owner}/packages/container/''${package_name}/versions/''${version_id}"
        fi
      }

      versions="$({
        gh api --paginate "/users/''${owner}/packages/container/''${package}/versions?per_page=100" --slurp
      })"
      jq -c --argjson obsolete "''${obsolete_tags}" '
        add[] | . as $version | (.metadata.container.tags // []) as $tags |
        select(($tags | length) > 0) |
        select(all($tags[]; $obsolete | index(.) != null)) |
        {id: $version.id, tags: $tags}
      ' <<<"''${versions}" |
        while IFS= read -r candidate; do
          version_id="$(jq -r '.id' <<<"''${candidate}")"
          echo "Obsolete package version ''${version_id}: $(jq -r '.tags | join(", ")' <<<"''${candidate}")"
          delete_version "''${package}" "''${version_id}"
        done
    '';
  };
  ciGate = import ./ci-applications/ci-gate.nix {inherit pkgs validateCiPlan;};
  promoteImages = import ./ci-applications/promote-images.nix {inherit pkgs;};
  classifyCi = import ./ci-applications/classify-ci.nix {inherit classifyChanges pkgs;};
  imagePlan = import ./ci-applications/image-plan.nix {inherit pkgs;};
  shardPlan = import ./ci-applications/shard-plan.nix {inherit pkgs;};
  validateCiPlan = import ./ci-applications/validate-ci-plan.nix {inherit pkgs;};
  validateLocks = import ./ci-applications/validate-locks.nix {inherit pkgs;};
  buildCiPlan = import ./ci-applications/build-ci-plan.nix {
    inherit bluefin generated imagePlan pkgs shardPlan verifyBluefin version;
  };
  ciPrepare = import ./ci-applications/ci-prepare.nix {
    inherit buildCiPlan classifyCi pkgs validateCiPlan;
  };
  imageSign = import ./ci-applications/image-sign.nix {inherit pkgs;};
  imageReuse = pkgs.writeShellApplication {
    name = "purplefin-image-reuse";
    runtimeInputs = with pkgs; [bash coreutils cosign jq skopeo];
    text = ''
         repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
         [[ -f "''${repo_root}/flake.nix" ]] || {
           echo "Run this command from the Purplefin repository root" >&2
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
      cosign_command="''${PURPLEFIN_COSIGN:-cosign}"
      skopeo_command="''${PURPLEFIN_SKOPEO:-skopeo}"

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
           --arg parent_digest "''${EXPECTED_PARENT_DIGEST}" \
           --arg profile "''${BUILD_PROFILE}" \
           --arg revision "''${EXPECTED_REVISION}" \
           --arg upstream_digest "''${EXPECTED_UPSTREAM_DIGEST}" \
           --arg version "''${EXPECTED_VERSION}" '
             (.Labels // {}) as $labels |
             $labels["io.purplefin.build.input"] == $build_input and
             $labels["io.purplefin.build.profile"] == $profile and
             $labels["io.purplefin.upstream.digest"] == $upstream_digest and
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
  validateImageShard = import ./ci-applications/validate-image-shard.nix {
    inherit generated loadBluefin pkgs version;
  };
  installerE2e = import ./ci-applications/installer-e2e.nix {inherit pkgs;};
  installerSmoke = import ./ci-applications/installer-smoke.nix {inherit pkgs;};
  installerBuild = import ./installer-application.nix {
    inherit generated imageBuilder installerE2e installerSmoke pkgs;
  };
  sbomAttestation = pkgs.writeShellApplication {
    name = "purplefin-sbom-attestation";
    runtimeInputs = with pkgs; [coreutils gh jq];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      predicate_type='https://spdx.dev/Document/v2.3'
      maximum_size=$((16 * 1024 * 1024))

      usage() {
        cat >&2 <<'EOF'
      usage: sbom.sh extract OUTPUT
             sbom.sh generate OUTPUT
             sbom.sh validate SBOM
             sbom.sh equivalent LEFT RIGHT
      EOF
      }

      resolve_tool() {
        local override="$1"
        local command_name="$2"
        local resolved
        if [[ -n "''${override}" ]]; then
          resolved="''${override}"
        else
          resolved="$(command -v "''${command_name}" || true)"
        fi
        [[ -n "''${resolved}" && -x "''${resolved}" ]] || {
          echo "Required command is unavailable: ''${command_name}" >&2
          return 2
        }
        printf '%s\n' "''${resolved}"
      }

      validate_sbom() {
        local sbom="$1"
        local size
        [[ -f "''${sbom}" ]] || {
          echo "SBOM does not exist: ''${sbom}" >&2
          return 2
        }
        jq -e '
          type == "object" and
          (.spdxVersion | type == "string" and startswith("SPDX-")) and
          (.packages | type == "array") and
          any(.packages[]?; any(.externalRefs[]?; .referenceType == "purl")) and
          all(.packages[]?; all(.externalRefs[]?; .referenceType != "cpe23Type"))
        ' "''${sbom}" >/dev/null || {
          echo "SBOM is not a normalized SPDX package document: ''${sbom}" >&2
          return 1
        }
        size="$(wc -c <"''${sbom}")"
        if ((size > maximum_size)); then
          printf 'SBOM is %d bytes; actions/attest accepts at most %d bytes.\n' \
            "''${size}" "''${maximum_size}" >&2
          return 1
        fi
      }

      equivalent_sboms() {
        local left="$1"
        local right="$2"
        validate_sbom "''${left}"
        validate_sbom "''${right}"
        cmp --silent <(jq -Sc . "''${left}") <(jq -Sc . "''${right}")
      }

      extract_attestation() {
        local output="$1"
        local gh_command verification predicate
        : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        : "''${SBOM_SIGNER_WORKFLOW:?SBOM_SIGNER_WORKFLOW is required}"
        : "''${SBOM_SOURCE_DIGEST:?SBOM_SOURCE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]
        [[ "''${SBOM_SOURCE_DIGEST}" =~ ^[0-9a-f]{40}$ ]]

        gh_command="$(resolve_tool "''${PURPLEFIN_GH:-}" gh)"
        verification="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-verification.XXXXXX")"
        predicate="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-predicate.XXXXXX")"
        if ! "''${gh_command}" attestation verify \
          "oci://''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}" \
          --bundle-from-oci \
          --repo "''${GITHUB_REPOSITORY}" \
          --signer-workflow "''${SBOM_SIGNER_WORKFLOW}" \
          --source-digest "''${SBOM_SOURCE_DIGEST}" \
          --predicate-type "''${predicate_type}" \
          --format json >"''${verification}" 2>/dev/null; then
          rm -f -- "''${verification}" "''${predicate}"
          return 3
        fi
        if ! jq -ce \
          --arg digest "''${SBOM_IMAGE_DIGEST#sha256:}" \
          --arg predicate_type "''${predicate_type}" '
            [
              .[]?.verificationResult.statement |
              select(.predicateType == $predicate_type) |
              select(any(.subject[]?; .digest.sha256 == $digest)) |
              .predicate
            ] |
            unique |
            if length == 1 then
              .[0]
            else
              error("expected exactly one distinct verified SPDX predicate")
            end
          ' "''${verification}" >"''${predicate}"; then
          rm -f -- "''${verification}" "''${predicate}"
          return 1
        fi
        rm -f -- "''${verification}"
        if ! validate_sbom "''${predicate}"; then
          rm -f -- "''${predicate}"
          return 1
        fi
        mv -- "''${predicate}" "''${output}"
      }

      generate_sbom() {
        local output="$1"
        local repo_root podman_command syft_command nix_store_command
        local syft_store scan_image generated
        local -a auth_args syft_closure syft_mounts
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]

        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/.github/syft.yaml" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          return 2
        }
        podman_command="$(resolve_tool "''${PURPLEFIN_PODMAN:-}" podman)"
        syft_command="$(resolve_tool "''${PURPLEFIN_SYFT:-}" syft)"
        nix_store_command="$(resolve_tool "''${PURPLEFIN_NIX_STORE:-}" nix-store)"
        syft_store="''${PURPLEFIN_SYFT_STORE:-$(dirname "$(dirname "$(readlink -f "''${syft_command}")")")}"

        mapfile -t syft_closure < <(
          "''${nix_store_command}" --query --requisites "''${syft_store}"
        )
        syft_mounts=()
        for store_path in "''${syft_closure[@]}"; do
          syft_mounts+=(--volume "''${store_path}:''${store_path}:ro")
        done

        auth_args=()
        if [[ -n "''${REGISTRY_AUTH_FILE:-}" ]]; then
          auth_args+=(--authfile "''${REGISTRY_AUTH_FILE}")
        fi
        if [[ -n "''${SBOM_LOCAL_IMAGE:-}" ]]; then
          scan_image="''${SBOM_LOCAL_IMAGE}"
        else
          scan_image="$(''${podman_command} pull --quiet "''${auth_args[@]}" \
            "''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}")"
        fi

        generated="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-generated.XXXXXX")"
        if ! "''${podman_command}" run --rm --pull=never \
          --cpus 4 \
          --env SYFT_CACHE_DIR=/tmp/syft-cache \
          --memory 4g \
          --network none \
          --security-opt label=disable \
          --user 0 \
          --volume "''${repo_root}/.github/syft.yaml:/run/purplefin-syft.yaml:ro" \
          "''${syft_mounts[@]}" \
          --entrypoint "''${syft_command}" \
          "''${scan_image}" \
          scan dir:/ \
            --config /run/purplefin-syft.yaml \
            --exclude './nix/store/**' \
            --source-name "''${SBOM_IMAGE_REF}" \
            --source-version "''${SBOM_IMAGE_DIGEST}" \
            --output spdx-json |
          jq -c '
            .packages |= map(
              if has("externalRefs") then
                .externalRefs |= map(
                  select(.referenceType != "cpe23Type")
                ) |
                if (.externalRefs | length) == 0 then
                  del(.externalRefs)
                else
                  .
                end
              else
                .
              end
            )
          ' >"''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        if ! validate_sbom "''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        mv -- "''${generated}" "''${output}"
      }

      command="''${1:-}"
      [[ -n "''${command}" ]] || {
        usage
        exit 2
      }
      shift
      case "''${command}" in
        extract)
          (( $# == 1 )) || { usage; exit 2; }
          extract_attestation "$1"
          ;;
        generate)
          (( $# == 1 )) || { usage; exit 2; }
          generate_sbom "$1"
          ;;
        validate)
          (( $# == 1 )) || { usage; exit 2; }
          validate_sbom "$1"
          ;;
        equivalent)
          (( $# == 2 )) || { usage; exit 2; }
          equivalent_sboms "$1" "$2"
          ;;
        *) usage; exit 2 ;;
      esac
    '';
  };
  imageSbom = pkgs.writeShellApplication {
    name = "purplefin-image-sbom";
    runtimeInputs = with pkgs; [coreutils gh jq syft];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      predicate_type='https://spdx.dev/Document/v2.3'
      maximum_size=$((16 * 1024 * 1024))

      usage() {
        cat >&2 <<'EOF'
      usage: sbom.sh extract OUTPUT
             sbom.sh generate OUTPUT
             sbom.sh validate SBOM
             sbom.sh equivalent LEFT RIGHT
      EOF
      }

      resolve_tool() {
        local override="$1"
        local command_name="$2"
        local resolved
        if [[ -n "''${override}" ]]; then
          resolved="''${override}"
        else
          resolved="$(command -v "''${command_name}" || true)"
        fi
        [[ -n "''${resolved}" && -x "''${resolved}" ]] || {
          echo "Required command is unavailable: ''${command_name}" >&2
          return 2
        }
        printf '%s\n' "''${resolved}"
      }

      validate_sbom() {
        local sbom="$1"
        local size
        [[ -f "''${sbom}" ]] || {
          echo "SBOM does not exist: ''${sbom}" >&2
          return 2
        }
        jq -e '
          type == "object" and
          (.spdxVersion | type == "string" and startswith("SPDX-")) and
          (.packages | type == "array") and
          any(.packages[]?; any(.externalRefs[]?; .referenceType == "purl")) and
          all(.packages[]?; all(.externalRefs[]?; .referenceType != "cpe23Type"))
        ' "''${sbom}" >/dev/null || {
          echo "SBOM is not a normalized SPDX package document: ''${sbom}" >&2
          return 1
        }
        size="$(wc -c <"''${sbom}")"
        if ((size > maximum_size)); then
          printf 'SBOM is %d bytes; actions/attest accepts at most %d bytes.\n' \
            "''${size}" "''${maximum_size}" >&2
          return 1
        fi
      }

      equivalent_sboms() {
        local left="$1"
        local right="$2"
        validate_sbom "''${left}"
        validate_sbom "''${right}"
        cmp --silent <(jq -Sc . "''${left}") <(jq -Sc . "''${right}")
      }

      extract_attestation() {
        local output="$1"
        local gh_command verification predicate
        : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        : "''${SBOM_SIGNER_WORKFLOW:?SBOM_SIGNER_WORKFLOW is required}"
        : "''${SBOM_SOURCE_DIGEST:?SBOM_SOURCE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]
        [[ "''${SBOM_SOURCE_DIGEST}" =~ ^[0-9a-f]{40}$ ]]

        gh_command="$(resolve_tool "''${PURPLEFIN_GH:-}" gh)"
        verification="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-verification.XXXXXX")"
        predicate="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-predicate.XXXXXX")"
        if ! "''${gh_command}" attestation verify \
          "oci://''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}" \
          --bundle-from-oci \
          --repo "''${GITHUB_REPOSITORY}" \
          --signer-workflow "''${SBOM_SIGNER_WORKFLOW}" \
          --source-digest "''${SBOM_SOURCE_DIGEST}" \
          --predicate-type "''${predicate_type}" \
          --format json >"''${verification}" 2>/dev/null; then
          rm -f -- "''${verification}" "''${predicate}"
          return 3
        fi
        if ! jq -ce \
          --arg digest "''${SBOM_IMAGE_DIGEST#sha256:}" \
          --arg predicate_type "''${predicate_type}" '
            [
              .[]?.verificationResult.statement |
              select(.predicateType == $predicate_type) |
              select(any(.subject[]?; .digest.sha256 == $digest)) |
              .predicate
            ] |
            unique |
            if length == 1 then
              .[0]
            else
              error("expected exactly one distinct verified SPDX predicate")
            end
          ' "''${verification}" >"''${predicate}"; then
          rm -f -- "''${verification}" "''${predicate}"
          return 1
        fi
        rm -f -- "''${verification}"
        if ! validate_sbom "''${predicate}"; then
          rm -f -- "''${predicate}"
          return 1
        fi
        mv -- "''${predicate}" "''${output}"
      }

      generate_sbom() {
        local output="$1"
        local repo_root podman_command syft_command nix_store_command
        local syft_store scan_image generated
        local -a auth_args syft_closure syft_mounts
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]

        repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/.github/syft.yaml" ]] || {
          echo "Run this command from the Purplefin repository root" >&2
          return 2
        }
        podman_command="$(resolve_tool "''${PURPLEFIN_PODMAN:-}" podman)"
        syft_command="$(resolve_tool "''${PURPLEFIN_SYFT:-}" syft)"
        nix_store_command="$(resolve_tool "''${PURPLEFIN_NIX_STORE:-}" nix-store)"
        syft_store="''${PURPLEFIN_SYFT_STORE:-$(dirname "$(dirname "$(readlink -f "''${syft_command}")")")}"

        mapfile -t syft_closure < <(
          "''${nix_store_command}" --query --requisites "''${syft_store}"
        )
        syft_mounts=()
        for store_path in "''${syft_closure[@]}"; do
          syft_mounts+=(--volume "''${store_path}:''${store_path}:ro")
        done

        auth_args=()
        if [[ -n "''${REGISTRY_AUTH_FILE:-}" ]]; then
          auth_args+=(--authfile "''${REGISTRY_AUTH_FILE}")
        fi
        if [[ -n "''${SBOM_LOCAL_IMAGE:-}" ]]; then
          scan_image="''${SBOM_LOCAL_IMAGE}"
        else
          scan_image="$(''${podman_command} pull --quiet "''${auth_args[@]}" \
            "''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}")"
        fi

        generated="$(mktemp "''${TMPDIR:-/tmp}/purplefin-sbom-generated.XXXXXX")"
        if ! "''${podman_command}" run --rm --pull=never \
          --cpus 4 \
          --env SYFT_CACHE_DIR=/tmp/syft-cache \
          --memory 4g \
          --network none \
          --security-opt label=disable \
          --user 0 \
          --volume "''${repo_root}/.github/syft.yaml:/run/purplefin-syft.yaml:ro" \
          "''${syft_mounts[@]}" \
          --entrypoint "''${syft_command}" \
          "''${scan_image}" \
          scan dir:/ \
            --config /run/purplefin-syft.yaml \
            --exclude './nix/store/**' \
            --source-name "''${SBOM_IMAGE_REF}" \
            --source-version "''${SBOM_IMAGE_DIGEST}" \
            --output spdx-json |
          jq -c '
            .packages |= map(
              if has("externalRefs") then
                .externalRefs |= map(
                  select(.referenceType != "cpe23Type")
                ) |
                if (.externalRefs | length) == 0 then
                  del(.externalRefs)
                else
                  .
                end
              else
                .
              end
            )
          ' >"''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        if ! validate_sbom "''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        mv -- "''${generated}" "''${output}"
      }

      command="''${1:-}"
      [[ -n "''${command}" ]] || {
        usage
        exit 2
      }
      shift
      case "''${command}" in
        extract)
          (( $# == 1 )) || { usage; exit 2; }
          extract_attestation "$1"
          ;;
        generate)
          (( $# == 1 )) || { usage; exit 2; }
          generate_sbom "$1"
          ;;
        validate)
          (( $# == 1 )) || { usage; exit 2; }
          validate_sbom "$1"
          ;;
        equivalent)
          (( $# == 2 )) || { usage; exit 2; }
          equivalent_sboms "$1" "$2"
          ;;
        *) usage; exit 2 ;;
      esac
    '';
  };
  homeSwitch = pkgs.writeShellApplication {
    name = "purplefin-home-switch";
    runtimeInputs = with pkgs; [coreutils getent jq];
    text = ''
      profile=""
      hardware=""
      mode=switch
      while (( $# > 0 )); do
        case "$1" in
          --profile) profile="''${2:?--profile requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --check) mode=check; shift ;;
          --switch) mode=switch; shift ;;
          *) echo "usage: purplefin-home-switch --profile PROFILE [--hardware HARDWARE] [--check|--switch]" >&2; exit 2 ;;
        esac
      done
      [[ "''${profile}" =~ ^[a-z0-9._-]+$ ]] || {
        echo "A valid --profile is required" >&2
        exit 2
      }
      jq -e --arg profile "''${profile}" '.profiles[$profile]' \
        ${generated}/bootc/generated/home-profile-catalog.json >/dev/null || {
        echo "Unknown Home Manager profile: ''${profile}" >&2
        exit 2
      }
      if [[ -z "''${hardware}" && -r /usr/share/purplefin/profile.json ]]; then
        hardware="$(jq -r '.hardware // empty' /usr/share/purplefin/profile.json)"
      fi
      hardware="''${hardware:-generic-x86_64}"
      jq -e --arg profile "''${profile}" --arg hardware "''${hardware}" \
        '.profiles[$profile].hardware | index($hardware) != null' \
        ${generated}/bootc/generated/home-profile-catalog.json >/dev/null || {
        echo "Profile ''${profile} does not support hardware ''${hardware}" >&2
        exit 2
      }
      if [[ -r /usr/share/purplefin/build-profile && "''${PURPLEFIN_SKIP_FOUNDATION_CHECK:-false}" != true ]]; then
        foundation="$(</usr/share/purplefin/build-profile)"
        jq -e --arg profile "''${profile}" --arg foundation "''${foundation}" \
          '.profiles[$profile].foundations | index($foundation) != null' \
          ${generated}/bootc/generated/home-profile-catalog.json >/dev/null || {
          echo "Profile ''${profile} is incompatible with running foundation ''${foundation}" >&2
          exit 2
        }
      fi
      username="$(id -un)"
      home_directory="$(getent passwd "''${username}" | cut -d: -f6)"
      [[ -n "''${home_directory}" ]] || home_directory="''${HOME}"
      export PURPLEFIN_HOME_PROFILE="''${profile}"
      export PURPLEFIN_HOME_HARDWARE="''${hardware}"
      export PURPLEFIN_HOME_USERNAME="''${username}"
      export PURPLEFIN_HOME_DIRECTORY="''${home_directory}"
      expression='let
        flake = builtins.getFlake "${selfFlakeUri}";
      in
        (flake.lib.purplefin.mkHomeConfiguration {
          name = builtins.getEnv "PURPLEFIN_HOME_PROFILE";
          hardware = builtins.getEnv "PURPLEFIN_HOME_HARDWARE";
          username = builtins.getEnv "PURPLEFIN_HOME_USERNAME";
          homeDirectory = builtins.getEnv "PURPLEFIN_HOME_DIRECTORY";
        }).activationPackage'
      activation="$(nix --accept-flake-config build --impure --no-link --print-out-paths --expr "''${expression}")"
      printf 'Home profile %s for %s (%s) builds as %s\n' \
        "''${profile}" "''${username}" "''${hardware}" "''${activation}"
      [[ "''${mode}" == check ]] || exec "''${activation}/activate"
    '';
  };
  cloudInit = pkgs.writeShellApplication {
    name = "purplefin-cloud-init";
    runtimeInputs = with pkgs; [coreutils jq xorriso yq-go];
    text = ''
      profile=""
      hardware=""
      username=""
      output=""
      flake_uri="github:declarative-dale/purplefin"
      while (( $# > 0 )); do
        case "$1" in
          --profile) profile="''${2:?--profile requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --user) username="''${2:?--user requires a value}"; shift 2 ;;
          --output) output="''${2:?--output requires a value}"; shift 2 ;;
          --flake) flake_uri="''${2:?--flake requires a value}"; shift 2 ;;
          *) echo "usage: purplefin-cloud-init --profile PROFILE --hardware HARDWARE --user USER --output DIR [--flake URI]" >&2; exit 2 ;;
        esac
      done
      [[ "''${profile}" =~ ^[a-z0-9._-]+$ && "''${hardware}" =~ ^[a-z0-9._-]+$ ]] || {
        echo "Valid --profile and --hardware values are required" >&2
        exit 2
      }
      [[ "''${username}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
        echo "A valid existing --user is required" >&2
        exit 2
      }
      [[ -n "''${output}" ]] || { echo "--output is required" >&2; exit 2; }
      [[ ! -e "''${output}" ]] || { echo "Output already exists: ''${output}" >&2; exit 2; }
      foundation="$(jq -er --arg profile "''${profile}" --arg hardware "''${hardware}" '
        .profiles[$profile] as $profile |
        ($profile.hardware | index($hardware)) as $index |
        select($index != null) |
        $profile.foundations[$index]
      ' ${generated}/bootc/generated/home-profile-catalog.json)" || {
        echo "Profile ''${profile} does not support ''${hardware}" >&2
        exit 2
      }
      home_directory="/var/home/''${username}"
      workdir="$(mktemp -d)"
      trap 'rm -rf -- "''${workdir}"' EXIT
      jq -n \
        --arg flake "''${flake_uri}" \
        --arg hardware "''${hardware}" \
        --arg home "''${home_directory}" \
        --arg profile "''${profile}" \
        --arg user "''${username}" '
        {
          preserve_hostname: true,
          ssh_pwauth: false,
          runcmd: [[
            "runuser", "-u", $user, "--", "env", "HOME=" + $home,
            "/nix/var/nix/profiles/default/bin/nix", "run",
            $flake + "#home-switch", "--",
            "--profile", $profile, "--hardware", $hardware, "--switch"
          ]]
        }
      ' | yq -P >"''${workdir}/user-data.yaml"
      {
        printf '#cloud-config\n'
        cat "''${workdir}/user-data.yaml"
      } >"''${workdir}/user-data"
      instance_hash="$(sha256sum "''${workdir}/user-data" | cut -c1-16)"
      jq -n --arg id "purplefin-''${instance_hash}" --arg hostname purplefin \
        '{"instance-id": $id, "local-hostname": $hostname}' | yq -P >"''${workdir}/meta-data"
      jq -n \
        --arg foundation "''${foundation}" \
        --arg flake "''${flake_uri}" \
        --arg hardware "''${hardware}" \
        --arg profile "''${profile}" \
        --arg user "''${username}" \
        '{schema: 1, foundation: $foundation, flake: $flake, hardware: $hardware, profile: $profile, user: $user}' \
        >"''${workdir}/manifest.json"
      xorriso -as mkisofs -quiet -V cidata -J -R \
        -o "''${workdir}/seed.iso" "''${workdir}/user-data" "''${workdir}/meta-data"
      install -d "''${output}"
      install -m 0644 "''${workdir}/user-data" "''${workdir}/meta-data" \
        "''${workdir}/manifest.json" "''${workdir}/seed.iso" "''${output}/"
      printf 'Generated NoCloud seed for %s on %s at %s\n' \
        "''${profile}" "''${foundation}" "''${output}"
    '';
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
      upstream_image="$(jq -er --arg profile "''${profile}" '.[] | select(.profile == $profile) | .upstream.image' ${generated}/bootc/generated/image-matrix.json)"
      upstream_digest="$(jq -er --arg profile "''${profile}" '.[] | select(.profile == $profile) | .upstream.digest' ${generated}/bootc/generated/image-matrix.json)"
      if [[ "''${upstream_image}" == *bluefin-dx ]]; then
        source_name=bluefin-dx
      else
        source_name=bluefin
      fi
      base_image="$(${loadBluefin}/bin/purplefin-load-bluefin "''${source_name}")"
      exec podman build \
        --file bootc/Containerfile \
        --network host \
        --pull=never \
        --security-opt label=disable \
        --build-context purplefin-generated=${generated} \
        --build-arg "BASE_REF=''${base_image}" \
        --build-arg "BUILD_PROFILE=''${profile}" \
        --build-arg "PURPLEFIN_VERSION=${version}" \
        --label "io.purplefin.upstream.digest=''${upstream_digest}" \
        --label "org.opencontainers.image.base.digest=''${upstream_digest}" \
        --tag "''${tag}" \
      .
    '';
  };
}
