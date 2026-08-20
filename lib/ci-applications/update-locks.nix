{
  devenv,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "purplefin-update-locks";
  # Preserve the Determinate Nix client supplied by the host instead of
  # shadowing it with the Nixpkgs client inside this application wrapper.
  runtimeInputs = with pkgs; [coreutils devenv jq];
  text = ''
    set -euo pipefail

    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Purplefin repository root" >&2
      exit 2
    }
    cd "''${repo_root}"

    output_file="''${1:-}"
    before="$({ sha256sum flake.lock; [[ ! -f devenv.lock ]] || sha256sum devenv.lock; } | sha256sum | cut -d' ' -f1)"
    nix --accept-flake-config flake update
    devenv update
    after="$({ sha256sum flake.lock; sha256sum devenv.lock; } | sha256sum | cut -d' ' -f1)"
    changed=false
    [[ "''${before}" == "''${after}" ]] || changed=true

    if [[ -n "''${output_file}" ]]; then
      {
        printf 'changed=%s\n' "''${changed}"
        printf 'digest=%s\n' "''${after}"
      } >>"''${output_file}"
    else
      jq -cn --arg digest "''${after}" --argjson changed "''${changed}" \
        '{source: "locks", changed: $changed, digest: $digest}'
    fi
  '';
}
