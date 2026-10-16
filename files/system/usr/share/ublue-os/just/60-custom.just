# Keep Bluefin's update implementation and append the invoking user's Foundation update.
update:
    #!/usr/bin/env bash
    set -euo pipefail
    just --justfile /usr/share/ublue-os/just/update.just update
    if [[ "$EUID" == 0 ]]; then
        echo 'Run ujust update as your desktop user to include Foundation updates.' >&2
        exit 1
    fi
    if jq -e '.nodes[.root].inputs.foundation != null' "${XDG_CONFIG_HOME:-$HOME/.config}/home-manager/flake.lock" >/dev/null 2>&1; then
        finite-home-update
    else
        echo 'Home Manager uses the legacy configuration. Run finite-home-migrate to adopt Foundation.'
    fi
