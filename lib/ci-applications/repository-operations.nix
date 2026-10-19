{
  cacheName,
  pkgs,
  secretspec,
}: rec {
  ciSecretsRun = pkgs.writeShellApplication {
    name = "finite-ci-secrets-run";
    runtimeInputs = [secretspec];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/secretspec.toml" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      profile="''${1:?usage: finite-ci-secrets-run PROFILE -- COMMAND}"
      shift
      case "$profile" in
        ci-options|cache-writer|image-signing|release-signing|release-publishing|release-set-publishing|repository-audit|repository-read|review-app|updater) ;;
        *) echo "Unsupported Finite SecretSpec profile" >&2; exit 2 ;;
      esac
      [[ "''${1:-}" == -- ]] || { echo "Expected -- before the child command" >&2; exit 2; }
      shift
      [[ $# -gt 0 ]] || { echo "A child command is required" >&2; exit 2; }
      version=$(secretspec --version)
      [[ $version =~ ^secretspec\ ([0-9]+)\.([0-9]+)\. ]] || {
        echo "Cannot identify the SecretSpec version" >&2; exit 2;
      }
      (( BASH_REMATCH[1] > 0 || BASH_REMATCH[2] >= 19 )) || {
        echo "Finite secret scopes require SecretSpec >= 0.19" >&2; exit 2;
      }
      provider="''${FINITE_SECRETS_PROVIDER:-local}"
      if [[ "''${GITHUB_ACTIONS:-false}" == true ]]; then provider=github-actions; fi
      case "$provider" in
        local|pass|github-actions) ;;
        *) echo "Use local/pass for developer tasks or github-actions for CI" >&2; exit 2 ;;
      esac
      # Legacy provider input aliases are not manifest output names, so the
      # CLI scope cannot remove them itself. New profiles use canonical names.
      unset GITHUB_ACTIONS_CACHIX_AUTH_TOKEN GITHUB_ACTIONS_MERGE_QUEUE_TOKEN
      if [[ "$profile" == release-publishing ]]; then
        # Resolve the composed CLI token, then discard its provider variable
        # before the controlled publisher receives the child environment.
        set -- bash -c 'unset MERGE_QUEUE_TOKEN; exec "$@"' finite-release-publishing "$@"
      fi
      exec secretspec run \
        --file "''${repo_root}/secretspec.toml" \
        --profile "$profile" --scope "$profile" --provider "$provider" \
        --reason "Finite $profile task" -- "$@"
    '';
  };

  ciSecretsOptions = pkgs.writeShellApplication {
    name = "finite-ci-secrets-options";
    runtimeInputs = [ciSecretsRun pkgs.python3];
    text = ''
      # Only nonsensitive feature flags persist between workflow steps. The
      # child scope removes any inherited signing/cache/updater credentials.
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      exec finite-ci-secrets-run ci-options -- python3 \
        "''${repo_root}/scripts/ci/ci-options.py" "$@"
    '';
  };

  githubActionsSecrets = pkgs.writeShellApplication {
    name = "finite-github-actions-secrets";
    runtimeInputs = [secretspec];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/secretspec.toml" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      exec secretspec export \
        --file "''${repo_root}/secretspec.toml" \
        --format gha \
        --profile github-actions \
        --provider github-actions \
        --reason "Finite GitHub Actions secret mapping" \
        --scope github-actions
    '';
  };

  fixNixHashes = pkgs.writeShellApplication {
    name = "finite-fix-nix-hashes";
    # determinate-nixd comes from the host's Determinate installation so the
    # repair command uses the same client that evaluated the failed check.
    runtimeInputs = with pkgs; [coreutils gh git];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${GH_TOKEN:?GH_TOKEN must be set}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
      : "''${PR_AUTHOR:?PR_AUTHOR must be set}"
      : "''${PR_HEAD_REF:?PR_HEAD_REF must be set}"
      : "''${PR_HEAD_REPOSITORY:?PR_HEAD_REPOSITORY must be set}"
      : "''${PR_HEAD_SHA:?PR_HEAD_SHA must be set}"

      [[ "''${PR_AUTHOR}" == 'dependabot[bot]' ]] || {
        printf 'Refusing to repair hashes for untrusted PR author %s\n' \
          "''${PR_AUTHOR}" >&2
        exit 2
      }
      [[ "''${PR_HEAD_REPOSITORY}" == "''${GITHUB_REPOSITORY}" ]] || {
        printf 'Refusing to push to foreign PR repository %s\n' \
          "''${PR_HEAD_REPOSITORY}" >&2
        exit 2
      }
      [[ "''${PR_HEAD_REF}" == dependabot/* ]] || {
        printf 'Refusing non-Dependabot branch %s\n' "''${PR_HEAD_REF}" >&2
        exit 2
      }
      [[ "''${PR_HEAD_SHA}" =~ ^[a-f0-9]{40}$ ]] || {
        printf 'Invalid pull-request head SHA: %s\n' "''${PR_HEAD_SHA}" >&2
        exit 2
      }
      git check-ref-format --branch "''${PR_HEAD_REF}" >/dev/null

      [[ -z "$(git status --porcelain)" ]] || {
        echo 'Trusted hash-fixer checkout must start clean' >&2
        exit 1
      }

      git fetch --no-tags --depth=1 origin "refs/heads/''${PR_HEAD_REF}"
      fetched_sha="$(git rev-parse FETCH_HEAD)"
      [[ "''${fetched_sha}" == "''${PR_HEAD_SHA}" ]] || {
        printf 'Fetched PR head %s, expected %s\n' \
          "''${fetched_sha}" "''${PR_HEAD_SHA}" >&2
        exit 1
      }
      git checkout --detach "''${PR_HEAD_SHA}"

      push_token="''${GH_TOKEN}"
      unset GH_TOKEN GITHUB_TOKEN
      determinate-nixd fix hashes --auto-apply

      if git diff --quiet; then
        echo 'Determinate Nix found no tracked hash repairs to commit'
        exit 0
      fi

      git add --update --ignore-removal .
      if git diff --cached --quiet; then
        echo 'Determinate Nix changed no tracked files eligible for repair'
        exit 0
      fi

      git config user.name 'github-actions[bot]'
      git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
      git commit -m '[dependabot skip] Automatically fix Nix hashes'

      export GH_TOKEN="''${push_token}"
      unset push_token
      gh auth setup-git
      git push \
        --force-with-lease="refs/heads/''${PR_HEAD_REF}:''${PR_HEAD_SHA}" \
        origin "HEAD:refs/heads/''${PR_HEAD_REF}"
    '';
  };

  mkCheck = checks: let
    checkNames = builtins.attrNames checks;
    quotedNames = pkgs.lib.concatMapStringsSep " " pkgs.lib.escapeShellArg checkNames;
  in
    pkgs.writeShellApplication {
      name = "finite-ci-check";
      # Nix comes from the host's Determinate installation; do not shadow it
      # with the upstream Nixpkgs client inside this application wrapper.
      runtimeInputs = with pkgs; [cachix coreutils jq];
      text = ''
        repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Finite repository root" >&2
          exit 2
        }
        flake_uri="path:''${repo_root}"
        if [[ "''${GITHUB_ACTIONS:-false}" == true ]]; then
          # Keep checkout metadata out of checks such as treefmt, which create
          # their own temporary Git repository from the flake source. Declare
          # the CI checkout shallow so Nix does not attempt to compute a
          # revCount that is unavailable at fetch-depth 1.
          flake_uri="git+file://''${repo_root}?shallow=1"
        fi

        check_names=(${quotedNames})

        # Evaluate the aggregate derivation in a short-lived client, then build
        # that derivation path without retaining the full Flake evaluator heap.
        # On a 16 GiB workstation the previous single `nix build flake#attr`
        # client held roughly 7.5 GiB while builders ran and exhausted zram.
        ci_checks_drv="$(
          nix --accept-flake-config eval --raw \
            "''${flake_uri}#ci-checks.drvPath"
        )"
        [[ "''${ci_checks_drv}" == /nix/store/*.drv ]]
        ci_checks_out="$(
          nix --accept-flake-config build \
            --keep-going \
            --no-link \
            --print-build-logs \
            --print-out-paths \
            "$@" \
            "''${ci_checks_drv}^*"
        )"
        [[ "''${ci_checks_out}" == /nix/store/* ]]

        # Validate every standard output after realizing the IFD-backed checks.
        # This is a separate process so its evaluator heap is released before
        # the proof-path inspection below.
        nix --accept-flake-config flake check \
          "''${flake_uri}" \
          --no-build \
          "$@"

        max_closure_size=$((1024 * 1024))
        check_paths=()
        for name in "''${check_names[@]}"; do
          path="$(readlink -f "''${ci_checks_out}/''${name}")"
          check_paths+=("''${path}")
          [[ -e "''${path}" ]] || {
            echo "The explicit check build did not realize ''${name}: ''${path}" >&2
            exit 1
          }
        done
        closure_sizes_json="$(
          nix path-info --json --json-format 1 --closure-size "''${check_paths[@]}"
        )"
        for index in "''${!check_names[@]}"; do
          name="''${check_names[''${index}]}"
          path="''${check_paths[''${index}]}"
          closure_size="$(jq -er --arg path "''${path}" '.[$path].closureSize' \
            <<<"''${closure_sizes_json}")"
          if (( closure_size > max_closure_size )); then
            printf '%s proof closure is %s bytes; cache limit is %s bytes\n' \
              "''${name}" "''${closure_size}" "''${max_closure_size}" >&2
            exit 1
          fi
          printf '%s\t%s bytes\t%s\n' "''${name}" "''${closure_size}" "''${path}"
        done

        if [[ -n "''${FINITE_CHECK_PROOFS_FILE:-}" ]]; then
          # The local wrapper owns this private, initially empty handoff file.
          # Never overwrite an existing verdict, follow links or publish paths
          # before all checks and closure-size validation have passed.
          [[ -f "$FINITE_CHECK_PROOFS_FILE" && ! -L "$FINITE_CHECK_PROOFS_FILE" &&
             -O "$FINITE_CHECK_PROOFS_FILE" && ! -s "$FINITE_CHECK_PROOFS_FILE" &&
             $(stat -c '%a' "$FINITE_CHECK_PROOFS_FILE") == 600 ]] || {
            echo "Check proof handoff must be an owned empty regular file with mode 0600" >&2
            exit 2
          }
          printf '%s\n' "''${check_paths[@]}" >"$FINITE_CHECK_PROOFS_FILE"
        fi

        if [[ "''${FINITE_CACHE_PUSH:-true}" == true && -n "''${CACHIX_AUTH_TOKEN:-}" ]]; then
          for path in "''${check_paths[@]}"; do
            cachix push --omit-deriver ${pkgs.lib.escapeShellArg cacheName} "''${path}"
          done
        elif [[ "''${FINITE_CACHE_PUSH:-true}" == true ]]; then
          echo "CACHIX_AUTH_TOKEN is unavailable; proof outputs were not pushed" >&2
        fi
      '';
    };
  mkLocalCache = ciApplication:
    pkgs.writeShellApplication {
      name = "finite-local-cache";
      runtimeInputs = [secretspec pkgs.cachix pkgs.coreutils];
      text = ''
        repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Finite repository root" >&2
          exit 2
        }
        cd "''${repo_root}"
        # Realization and checks cannot receive an inherited credential or
        # resolve pass. Only the final allowlisted upload resolves Cachix.
        unset CACHIX_AUTH_TOKEN COSIGN_PRIVATE_KEY COSIGN_PASSWORD GH_TOKEN GITHUB_TOKEN
        unset MERGE_QUEUE_TOKEN REGISTRY_TOKEN SECAUDIT_PEM SECAUDIT_CLIENTID
        unset GITHUB_ACTIONS_CACHIX_AUTH_TOKEN GITHUB_ACTIONS_MERGE_QUEUE_TOKEN
        umask 077
        proof_file=$(mktemp "''${TMPDIR:-/tmp}/finite-check-proofs.XXXXXX")
        # shellcheck disable=SC2329 # Invoked by EXIT, including signal exits.
        cleanup() { rm -f "$proof_file"; }
        trap cleanup EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        FINITE_CACHE_PUSH=false FINITE_CHECK_PROOFS_FILE="$proof_file" \
          ${ciApplication}/bin/finite-ci-check "$@"
        mapfile -t proof_paths <"$proof_file"
        [[ ''${#proof_paths[@]} -gt 0 ]] || { echo "No validated check proofs to publish" >&2; exit 2; }
        for path in "''${proof_paths[@]}"; do
          [[ $path =~ ^/nix/store/[a-z0-9]{32}-[^/[:space:]]+$ && -e $path ]] || {
            echo "Invalid validated proof store path" >&2; exit 2;
          }
        done
        provider="''${FINITE_SECRETS_PROVIDER:-local}"
        case "$provider" in
          local|pass) ;;
          *) echo "Local proof publishing requires the local/pass provider" >&2; exit 2 ;;
        esac
        secretspec run \
          --file "''${repo_root}/secretspec.toml" \
          --provider "$provider" \
          --profile local-cache \
          --reason "Finite validated local proof upload" \
          --scope cachix \
          -- cachix push --omit-deriver ${pkgs.lib.escapeShellArg cacheName} "''${proof_paths[@]}"
      '';
    };
}
