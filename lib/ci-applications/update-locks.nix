{
  devenv,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "finite-update-locks";
  # Preserve the Determinate Nix client supplied by the host instead of
  # shadowing it with the Nixpkgs client inside this application wrapper.
  runtimeInputs = (with pkgs; [coreutils devenv jq]) ++ [(pkgs.python3.withPackages (p: [p.pyyaml]))];
  text = ''
    set -euo pipefail

    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Finite repository root" >&2
      exit 2
    }
    cd "''${repo_root}"

    output_file="''${1:-}"
    before="$({ sha256sum flake.lock; [[ ! -f devenv.lock ]] || sha256sum devenv.lock; } | sha256sum | cut -d' ' -f1)"
    # Public dependency refreshes must not resolve the interactive Cachix
    # requirement or inherit the updater's write credential.
    unset_public_credentials() {
      unset CACHIX_AUTH_TOKEN FINITE_CACHIX_TOKEN COSIGN_PRIVATE_KEY COSIGN_PASSWORD
      unset GH_TOKEN GITHUB_TOKEN MERGE_QUEUE_TOKEN RELEASE_PUBLISH_TOKEN REGISTRY_TOKEN
      unset SECAUDIT_PEM SECAUDIT_CLIENTID FINITE_REVIEW_PRIVATE_KEY
    }
    # Foundation has a separate exact-main CI qualification and provenance
    # transaction. A general refresh must not advance it implicitly.
    inputs_json=$(jq -ce '.nodes[.root].inputs | keys | map(select(. != "foundation"))' flake.lock)
    mapfile -t update_inputs < <(jq -r '.[]' <<<"$inputs_json")
    [[ "''${#update_inputs[@]}" -gt 0 ]] || {
      echo "No general flake inputs to update" >&2
      exit 2
    }
    (unset_public_credentials; nix --accept-flake-config flake update "''${update_inputs[@]}")

    devenv_update_root=$(mktemp -d)
    trap 'rm -rf "$devenv_update_root"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    python3 - "$repo_root/devenv.yaml" "$devenv_update_root" <<'PYTHON'
    import json
    from pathlib import Path
    import sys
    import yaml

    configuration = yaml.safe_load(Path(sys.argv[1]).read_text())
    configuration["secretspec"] = {"enable": False}
    directory = Path(sys.argv[2])
    (directory / "devenv.yaml").write_text(json.dumps(configuration) + "\n")
    (directory / "devenv.nix").write_text("{ ... }: {}\n")
    PYTHON
    cp devenv.lock "$devenv_update_root/devenv.lock"
    (
      unset_public_credentials
      cd "$devenv_update_root"
      devenv update
    )
    jq -e 'type == "object"' "$devenv_update_root/devenv.lock" >/dev/null
    cp "$devenv_update_root/devenv.lock" devenv.lock
    for lock in flake.lock devenv.lock; do
      jq -e 'type == "object"' "$lock" >/dev/null
      if [[ "$(tail -c 1 "$lock" | od -An -tx1 | tr -d '[:space:]')" != 0a ]]; then
        printf '\n' >>"$lock"
      fi
    done
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
