# Keep Bluefin's update implementation and append the invoking user's Foundation update.
update:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ "$EUID" == 0 ]]; then
        echo 'Run ujust update as your desktop user to include Foundation updates.' >&2
        exit 1
    fi
    startup=/usr/libexec/finite/lib/update-shell-env
    [[ -r "$startup" ]] || { echo "Missing Finite update shell hook: $startup" >&2; exit 1; }
    guard_dir=$(mktemp -d)
    trap 'rm -rf -- "$guard_dir"' EXIT
    env BASH_ENV="$startup" FINITE_UPDATE_SHELL_MARKER="$guard_dir/started" \
        just --justfile /usr/share/ublue-os/just/update.just update
    [[ -f "$guard_dir/started" ]] || {
        echo 'Upstream update did not run the qualified Bash startup hook; Foundation was skipped.' >&2
        exit 1
    }
    if jq -e '.nodes[.root].inputs.foundation != null' "${XDG_CONFIG_HOME:-$HOME/.config}/home-manager/flake.lock" >/dev/null 2>&1; then
        finite-home-update
    else
        echo 'Home Manager uses the legacy configuration. Run finite-home-migrate to adopt Foundation.'
    fi
