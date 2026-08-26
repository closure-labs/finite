{
  cacheName,
  devenv,
  pkgs,
  secretspec,
}: rec {
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
        nix --accept-flake-config build \
          --keep-going \
          --no-link \
          --print-build-logs \
          "$@" \
          "''${ci_checks_drv}^*"

        # Validate every standard output after realizing the IFD-backed checks.
        # This is a separate process so its evaluator heap is released before
        # the proof-path inspection below.
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
      runtimeInputs = [devenv secretspec];
      text = ''
        repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/flake.nix" ]] || {
          echo "Run this command from the Finite repository root" >&2
          exit 2
        }
        cd "''${repo_root}"
        exec secretspec run \
          --file "''${repo_root}/secretspec.toml" \
          --provider local \
          --profile local-cache \
          --reason "Finite local Nix cache" \
          --scope cachix \
          -- ${ciApplication}/bin/finite-ci-check "$@"
      '';
    };
}
