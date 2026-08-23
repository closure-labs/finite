{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-update-home-release";
  # Preserve the Determinate Nix client supplied by the host instead of
  # shadowing it with the Nixpkgs client inside this application wrapper.
  runtimeInputs = with pkgs; [coreutils curl git gnugrep gnused jq];
  text = ''
    set -euo pipefail

    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Purplefin repository root" >&2
      exit 2
    }
    cd "''${repo_root}"

    output_file="''${1:-}"
    current_compact="$(${pkgs.gnugrep}/bin/grep -oE 'home-manager/0\.[0-9]{4}' flake.nix | head -n 1 | sed 's/.*\.//')"
    [[ "''${current_compact}" =~ ^[0-9]{4}$ ]] || {
      echo "Could not determine the current Home Manager release series" >&2
      exit 2
    }

    current_year="''${current_compact:0:2}"
    current_month="''${current_compact:2:2}"
    case "''${current_month}" in
      05) candidate_compact="''${current_year}11" ;;
      11) candidate_compact="$(printf '%02d05' "$((10#''${current_year} + 1))")" ;;
      *)
        echo "Unsupported Home Manager release month: ''${current_month}" >&2
        exit 2
        ;;
    esac

    current_release="''${current_compact:0:2}.''${current_compact:2:2}"
    candidate_release="''${candidate_compact:0:2}.''${candidate_compact:2:2}"

    emit_result() {
      local changed=$1 release=$2
      if [[ -n "''${output_file}" ]]; then
        {
          printf 'changed=%s\n' "''${changed}"
          printf 'release=%s\n' "''${release}"
        } >>"''${output_file}"
      else
        jq -cn \
          --argjson changed "''${changed}" \
          --arg release "''${release}" \
          '{source: "home-release", changed: $changed, release: $release}'
      fi
    }

    if ! git ls-remote --exit-code --heads \
      https://github.com/NixOS/nixpkgs.git \
      "refs/heads/nixos-''${candidate_release}" >/dev/null; then
      echo "Nixpkgs ''${candidate_release} is not available upstream yet"
      emit_result false "''${current_release}"
      exit 0
    fi
    if ! git ls-remote --exit-code --heads \
      https://github.com/nix-community/home-manager.git \
      "refs/heads/release-''${candidate_release}" >/dev/null; then
      echo "Home Manager ''${candidate_release} is not available upstream yet"
      emit_result false "''${current_release}"
      exit 0
    fi

    nixpkgs_url="https://flakehub.com/f/DeterminateSystems/nixpkgs-''${candidate_release}-chilled/0.1"
    home_manager_url="https://flakehub.com/f/nix-community/home-manager/0.''${candidate_compact}"
    if ! curl -fsSL --output /dev/null "''${nixpkgs_url}"; then
      echo "The chilled Nixpkgs ''${candidate_release} mirror is not available yet"
      emit_result false "''${current_release}"
      exit 0
    fi
    if ! curl -fsSL --output /dev/null "''${home_manager_url}"; then
      echo "The Home Manager ''${candidate_release} mirror is not available yet"
      emit_result false "''${current_release}"
      exit 0
    fi

    release_files=(
      flake.nix
      modules/outputs.nix
      lib/ci-applications/validate-locks.nix
      tests/repository/contracts.sh
      docs/ci-and-releases.md
      docs/configuration.md
      docs/installation.md
    )
    sed -i \
      -e "s/nixpkgs-''${current_release}-chilled/nixpkgs-''${candidate_release}-chilled/g" \
      -e "s@home-manager/0\.''${current_compact}@home-manager/0.''${candidate_compact}@g" \
      -e "s/Nixpkgs ''${current_release}/Nixpkgs ''${candidate_release}/g" \
      -e "s/Home Manager ''${current_release}/Home Manager ''${candidate_release}/g" \
      -e "s/matching ''${current_release} series/matching ''${candidate_release} series/g" \
      "''${release_files[@]}"

    if grep -F "nixpkgs-''${current_release}-chilled" "''${release_files[@]}" || \
      grep -F "home-manager/0.''${current_compact}" "''${release_files[@]}"; then
      echo "The previous release series remains in a managed release file" >&2
      exit 1
    fi

    nix --accept-flake-config flake update nixpkgs home-manager
    emit_result true "''${candidate_release}"
  '';
}
