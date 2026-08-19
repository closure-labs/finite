{
  bluefin,
  determinateNix,
  generated,
  imageBuilder,
  pkgs,
  version,
}: rec {
  classifyChanges = import ./ci-applications/classify-changes.nix {inherit pkgs;};

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
      export PURPLEFIN_DETERMINATE_NIX_VERSION=${determinateNix.version}
      source_name="''${1:?usage: purplefin-source-verify SOURCE}"
      case "''${source_name}" in
        bluefin)
          image="''${PURPLEFIN_BLUEFIN_IMAGE:?}"
          architecture="''${PURPLEFIN_BLUEFIN_ARCHITECTURE:?}"
          digest="''${PURPLEFIN_BLUEFIN_DIGEST:?}"
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          cosign verify \
            --certificate-oidc-issuer "''${PURPLEFIN_BLUEFIN_ISSUER:?}" \
            --certificate-identity "''${PURPLEFIN_BLUEFIN_IDENTITY:?}" \
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
          trap 'rm -f -- "''${installer}" "''${policy}"' EXIT
          curl --fail --location --retry 3 --output "''${installer}" \
            "''${PURPLEFIN_DETERMINATE_NIX_INSTALLER_URL:?}"
          curl --fail --location --retry 3 --output "''${policy}" \
            "''${PURPLEFIN_DETERMINATE_NIX_POLICY_URL:?}"
          printf '%s  %s\n' "''${PURPLEFIN_DETERMINATE_NIX_INSTALLER_SHA256:?}" "''${installer}" |
            sha256sum --check --status
          printf '%s  %s\n' "''${PURPLEFIN_DETERMINATE_NIX_POLICY_SHA256:?}" "''${policy}" |
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
    runtimeInputs = with pkgs; [coreutils cosign curl diffutils gh jq nix skopeo];
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
          policy_file="$(mktemp)"
          temporary="$(mktemp "''${lock}.XXXXXX")"
          trap 'rm -f -- "''${policy_file}" "''${temporary}"' EXIT
          curl --fail --location --retry 3 --output "''${policy_file}" "''${policy_url}"
          policy_sha256="$(sha256sum "''${policy_file}" | cut -d' ' -f1)"
          jq \
            --arg version "''${version}" \
            --arg installer_url "''${installer_url}" \
            --arg installer_sha256 "''${installer_sha256}" \
            --arg policy_url "''${policy_url}" \
            --arg policy_sha256 "''${policy_sha256}" '
              .version = $version |
              .installer.url = $installer_url |
              .installer.sha256 = $installer_sha256 |
              .selinuxPolicy.url = $policy_url |
              .selinuxPolicy.sha256 = $policy_sha256
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
              --json author,baseRefName,headRefName,headRefOid,headRepository,mergeStateStatus,state,title,url
          }

          validate_pr() {
            local candidate=$1
            [[ "$(jq -er '.state' <<<"''${candidate}")" == OPEN ]]
            [[ "$(jq -er '.title' <<<"''${candidate}")" == "''${EXPECTED_TITLE}" ]]
            [[ "$(jq -er '.author.login' <<<"''${candidate}")" == "''${EXPECTED_AUTHOR}" ]]
            [[ "$(jq -er '.baseRefName' <<<"''${candidate}")" == "''${DEFAULT_BRANCH}" ]]
            [[ "$(jq -er '.headRepository.nameWithOwner' <<<"''${candidate}")" == "''${GITHUB_REPOSITORY}" ]]
            [[ "$(jq -er '.headRefName' <<<"''${candidate}")" == "''${EXPECTED_BRANCH}" ]]
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
  ciGate = import ./ci-applications/ci-gate.nix {inherit pkgs;};
  promoteImages = import ./ci-applications/promote-images.nix {inherit pkgs;};
  classifyCi = import ./ci-applications/classify-ci.nix {inherit classifyChanges pkgs;};
  imagePlan = import ./ci-applications/image-plan.nix {inherit pkgs;};
  shardPlan = import ./ci-applications/shard-plan.nix {inherit pkgs;};
  ciPlan = pkgs.writeShellApplication {
    name = "purplefin-ci-plan";
    runtimeInputs = [pkgs.jq];
    text = ''
      (( $# == 1 )) || {
        echo "usage: nix run .#ci-plan -- GITHUB_OUTPUT" >&2
        exit 2
      }
      classification="''${CLASSIFICATION:?CLASSIFICATION is required}"
      jq -e '
        .schema == 1 and
        (.diff.status == "classified" or .diff.status == "fallback" or .diff.status == "predetermined") and
        (.validation.images.required | type == "boolean") and
        (.validation.images.scope == "none" or
          .validation.images.scope == "changed" or
          .validation.images.scope == "all") and
        (.validation.installer.required | type == "boolean")
      ' <<<"''${classification}" >/dev/null || {
        echo 'Invalid CI classification contract' >&2
        exit 2
      }

      base_image='${bluefin.image}'
      base_tag='${bluefin.tag}'
      base_digest='${bluefin.digest}'
      base_ref="''${base_image}@''${base_digest}"
      profiles="$(jq -c . ${generated}/bootc/generated/image-matrix.json)"
      matrix='{"include":[],"sbom_repair":[]}'
      root_base='{}'
      hardware_matrix='{"include":[]}'
      role_matrix='{"include":[]}'
      candidate_shards='{"include":[]}'
      base_sbom_matrix='{"include":[]}'
      hardware_sbom_matrix='{"include":[]}'
      role_sbom_matrix='{"include":[]}'

      if jq -e '.validation.images.required' <<<"''${classification}" >/dev/null; then
        : "''${IMAGE_REF:?IMAGE_REF is required}"
        : "''${GITHUB_SHA:?GITHUB_SHA is required}"
        ${verifyBluefin}/bin/purplefin-verify-bluefin >/dev/null
        export BASE_DIGEST="''${base_digest}" BASE_REF="''${base_ref}" EXPECTED_VERSION='${version}'
        matrix="$(${imagePlan}/bin/purplefin-image-plan "''${profiles}")"
        root_base="$(jq -c 'first(.include[] | select(.stage == "root")) // {}' <<<"''${matrix}")"
        hardware_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"''${matrix}")"
        role_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"''${matrix}")"
        candidate_shards="$(${shardPlan}/bin/purplefin-shard-plan "''${profiles}" "''${matrix}" 4)"
        sbom_matrix="$(jq -c --arg source_digest "''${GITHUB_SHA}" \
          --argjson profiles "''${profiles}" '
          ([.include[] | . + {
            source_digest: $source_digest,
            subject_tag: (.profile + "-candidate")
          }] + .sbom_repair) as $selected |
          {include: [
            $profiles[] as $decl |
            $selected[] |
            select(.profile == $decl.profile)
          ]}
        ' <<<"''${matrix}")"
        base_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "root")]}' <<<"''${sbom_matrix}")"
        hardware_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "hardware")]}' <<<"''${sbom_matrix}")"
        role_sbom_matrix="$(jq -c '{include: [.include[] | select(.stage == "role")]}' <<<"''${sbom_matrix}")"
      fi

      lifecycle="$(jq -cn \
        --argjson classification "''${classification}" \
        --argjson base_sbom "''${base_sbom_matrix}" \
        --argjson hardware "''${hardware_matrix}" \
        --argjson hardware_sbom "''${hardware_sbom_matrix}" \
        --argjson matrix "''${matrix}" \
        --argjson role "''${role_matrix}" \
        --argjson role_sbom "''${role_sbom_matrix}" \
        --argjson root "''${root_base}" '
        {
          schema: 1,
          classification: $classification,
          validation: {
            images: {
              required: ($matrix.include | length > 0),
              targets: [$matrix.include[].profile]
            },
            installer: $classification.validation.installer
          },
          publication: {
            builds: {
              any: ($matrix.include | length > 0),
              root: ($root | has("profile")),
              hardware: ($hardware.include | length > 0),
              roles: ($role.include | length > 0)
            },
            sbom: {
              base: ($base_sbom.include | length > 0),
              hardware: ($hardware_sbom.include | length > 0),
              roles: ($role_sbom.include | length > 0)
            },
            promote: ($matrix.include | length > 0)
          }
        }
      ')"
      {
        printf 'base_image=%s\n' "''${base_image}"
        printf 'base_digest=%s\n' "''${base_digest}"
        printf 'base_tag=%s\n' "''${base_tag}"
        printf 'base_sbom_matrix=%s\n' "''${base_sbom_matrix}"
        printf 'candidate_shards=%s\n' "''${candidate_shards}"
        printf 'hardware_matrix=%s\n' "''${hardware_matrix}"
        printf 'hardware_sbom_matrix=%s\n' "''${hardware_sbom_matrix}"
        printf 'lifecycle=%s\n' "''${lifecycle}"
        printf 'matrix=%s\n' "''${matrix}"
        printf 'role_matrix=%s\n' "''${role_matrix}"
        printf 'role_sbom_matrix=%s\n' "''${role_sbom_matrix}"
        printf 'root_base=%s\n' "''${root_base}"
        printf 'version=%s\n' '${version}'
      } >>"$1"
    '';
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
    inherit bluefin generated loadBluefin pkgs version;
  };
  installerSmoke = pkgs.writeShellApplication {
    name = "purplefin-installer-smoke";
    runtimeInputs = with pkgs; [bash coreutils gnugrep qemu_kvm];
    text = ''
      repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Purplefin repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      iso="''${1:?usage: boot-installer-iso.sh ISO}"
      [[ -s "''${iso}" ]] || { echo "Installer ISO is missing: ''${iso}" >&2; exit 2; }
      qemu="''${PURPLEFIN_QEMU:-qemu-system-x86_64}"
      qemu_img="''${PURPLEFIN_QEMU_IMG:-qemu-img}"
      timeout_seconds="''${PURPLEFIN_INSTALLER_SMOKE_TIMEOUT_SECONDS:-300}"
      poll_interval="''${PURPLEFIN_INSTALLER_SMOKE_POLL_INTERVAL_SECONDS:-1}"
      ready_pattern='anaconda|installation.*started|starting.*installer'
      [[ "''${timeout_seconds}" =~ ^[1-9][0-9]*$ ]] || {
        echo 'PURPLEFIN_INSTALLER_SMOKE_TIMEOUT_SECONDS must be a positive integer' >&2
        exit 2
      }
      command -v "''${qemu}" >/dev/null
      command -v "''${qemu_img}" >/dev/null

      log="$(dirname -- "''${iso}")/qemu-boot.log"
      disk="$(mktemp --suffix=.qcow2)"
      qemu_pid=
      tail_pid=
      # Invoked indirectly by the EXIT trap.
      # shellcheck disable=SC2329
      cleanup_installer_smoke() {
        [[ -z "''${qemu_pid}" ]] || kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
        [[ -z "''${tail_pid}" ]] || kill -TERM "''${tail_pid}" >/dev/null 2>&1 || true
        rm -f -- "''${disk}"
      }
      trap cleanup_installer_smoke EXIT
      "''${qemu_img}" create -q -f qcow2 "''${disk}" 32G

      acceleration=(-accel "tcg,thread=multi")
      if [[ -r /dev/kvm && -w /dev/kvm ]]; then
        acceleration=(-accel kvm)
      fi

      : >"''${log}"
      timeout --signal=TERM --kill-after=10s "''${timeout_seconds}s" \
        "''${qemu}" \
          "''${acceleration[@]}" \
          -machine q35 \
          -m 4096 \
          -smp 2 \
          -drive "file=''${disk},if=virtio,format=qcow2" \
          -cdrom "''${iso}" \
          -boot d \
          -display none \
          -serial stdio \
          -no-reboot >"''${log}" 2>&1 &
      qemu_pid=$!
      tail --pid="''${qemu_pid}" -n +1 -F "''${log}" &
      tail_pid=$!

      reached_installer=false
      while kill -0 "''${qemu_pid}" >/dev/null 2>&1; do
        if grep -Eqi "''${ready_pattern}" "''${log}"; then
          reached_installer=true
          kill -TERM "''${qemu_pid}" >/dev/null 2>&1 || true
          break
        fi
        sleep "''${poll_interval}"
      done

      set +e
      wait "''${qemu_pid}"
      qemu_status=$?
      wait "''${tail_pid}"
      tail_status=$?
      set -e
      qemu_pid=
      tail_pid=

      [[ "''${tail_status}" == 0 ]] || {
        echo "QEMU log follower failed with status ''${tail_status}" >&2
        exit "''${tail_status}"
      }
      if [[ "''${reached_installer}" == true ]] ||
        grep -Eqi "''${ready_pattern}" "''${log}"; then
        exit 0
      fi

      case "''${qemu_status}" in
        0 | 124 | 143) ;;
        *) echo "QEMU failed with status ''${qemu_status}" >&2; exit "''${qemu_status}" ;;
      esac

      echo 'The ISO booted but did not reach the Anaconda installer' >&2
      exit 1
    '';
  };
  installerBuild = import ./installer-application.nix {
    inherit generated imageBuilder installerSmoke pkgs;
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
    runtimeInputs = with pkgs; [coreutils gh jq nix syft];
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

  workflowPrepare = mkWorkflowToolset {
    name = "purplefin-workflow-prepare";
    paths = with pkgs; [classifyCi ciPlan coreutils git jq];
    required = [classifyCi ciPlan];
  };
  workflowGate = mkWorkflowToolset {
    name = "purplefin-workflow-gate";
    paths = [ciGate];
    required = [ciGate];
  };
  workflowValidation = mkWorkflowToolset {
    name = "purplefin-workflow-validation";
    paths = [validateImageShard];
    required = [validateImageShard];
  };
  workflowPublish = mkWorkflowToolset {
    name = "purplefin-workflow-publish";
    paths = with pkgs; [coreutils cosign gh imageReuse imageSign jq loadBluefin nix promoteImages skopeo];
    required = [imageReuse imageSign loadBluefin promoteImages];
  };
  workflowSbom = mkWorkflowToolset {
    name = "purplefin-workflow-sbom";
    paths = with pkgs; [coreutils cosign gh imageSbom jq skopeo];
    required = [imageSbom];
  };
  workflowInstaller = mkWorkflowToolset {
    name = "purplefin-workflow-installer";
    paths = [installerBuild];
    required = [installerBuild];
  };
  workflowRelease = mkWorkflowToolset {
    name = "purplefin-workflow-release";
    paths = with pkgs; [coreutils cosign gh gzip jq nix oras releaseNotes sbomAttestation skopeo trustedUpdate];
    required = [releaseNotes sbomAttestation trustedUpdate];
  };
}
