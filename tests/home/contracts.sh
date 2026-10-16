#!/usr/bin/env bash
set -euo pipefail
profile_command="${1:?profile command is required}"
init_command="${2:?home init command is required}"
cloud_init_command="${3:?cloud-init command is required}"
template="${4:?consumer template is required}"
for required in flake.nix flake.lock foundation.json profile.json customize.nix modules/local.nix; do
  test -f "$template/$required"
done
# The image ships a small consumer, not an editable copy of upstream modules.
test ! -e "$template/modules/finite.nix"
jq -e '.compatibility == 1 and (.rev | test("^[0-9a-f]{40}$"))' "$template/foundation.json" >/dev/null
jq -e '.nodes[.root].inputs | keys == ["foundation"]' "$template/flake.lock" >/dev/null
jq -e 'all(.nodes[]; .locked.type? != "path")' "$template/flake.lock" >/dev/null
grep -qF 'inputs.foundation.lib.mkHomeConfiguration' "$template/flake.nix"
FINITE_SKIP_FOUNDATION_CHECK=true "$profile_command" \
  --foundation bluefin-dx --hardware dell-xps-9350-intel \
  --roles developer,support --packages jj,uv --format yaml |
  yq -o=json '.' | jq -e '.roles == ["developer", "support"] and .packages == ["jj", "uv"]' >/dev/null
test -x "$init_command"
test -x "$cloud_init_command"
python3 tests/home/foundation-integration.py
