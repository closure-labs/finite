{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-ci-validate-locks";
  runtimeInputs = [pkgs.jq];
  text = ''
    set -euo pipefail
    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    cd "''${repo_root}"
    for lock in flake.lock devenv.lock; do
      [[ -f "''${lock}" ]] || {
        echo "Missing ''${lock}" >&2
        exit 2
      }
      jq -e '.version >= 7 and .nodes.root.inputs.nixpkgs and .nodes.root.inputs.devenv' \
        "''${lock}" >/dev/null
    done

    locked_rev() {
      local lock=$1 input=$2 node
      node="$(jq -er --arg input "''${input}" '.nodes.root.inputs[$input]' "''${lock}")"
      jq -er --arg node "''${node}" '.nodes[$node].locked.rev' "''${lock}"
    }
    original_url() {
      local lock=$1 input=$2 node
      node="$(jq -er --arg input "''${input}" '.nodes.root.inputs[$input]' "''${lock}")"
      jq -er --arg node "''${node}" '.nodes[$node].original.url' "''${lock}"
    }

    [[ "$(original_url flake.lock nixpkgs)" == \
      'https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0' ]]
    [[ "$(original_url flake.lock home-manager)" == \
      'https://flakehub.com/f/nix-community/home-manager/0' ]]
    [[ "$(original_url devenv.lock nixpkgs)" == \
      'https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0' ]]

    for input in nixpkgs devenv; do
      flake_rev="$(locked_rev flake.lock "''${input}")"
      devenv_rev="$(locked_rev devenv.lock "''${input}")"
      [[ "''${flake_rev}" == "''${devenv_rev}" ]] || {
        printf '%s lock revisions differ: flake.lock=%s devenv.lock=%s\n' \
          "''${input}" "''${flake_rev}" "''${devenv_rev}" >&2
        exit 1
      }
    done
  '';
}
