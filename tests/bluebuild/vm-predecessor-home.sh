#!/usr/bin/env bash
set -euo pipefail

temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
export XDG_CONFIG_HOME="$temporary/config"
export FINITE_BREW_COMMAND="$temporary/brew"
export TEST_BREW_LOG="$temporary/brew.log"
{
  printf '#!%s\nset -euo pipefail\n' "$BASH"
  cat <<'MOCK'
[[ $HOMEBREW_NO_AUTO_UPDATE == 1 ]]
printf '%s\n' "$*" >>"$TEST_BREW_LOG"
case $* in
  'tap valkyrie00/bbrew') ;;
  'trust valkyrie00/bbrew') [[ ${TEST_TRUST_FAILURE:-false} != true ]] ;;
  *) exit 80 ;;
esac
MOCK
} >"$FINITE_BREW_COMMAND"
chmod +x "$FINITE_BREW_COMMAND"
script=scripts/bluebuild/prepare-vm-predecessor-home.sh
if TEST_TRUST_FAILURE=true bash "$script"; then
  echo 'Predecessor setup ignored failed tap trust' >&2
  exit 1
fi
test ! -e "$XDG_CONFIG_HOME/home-manager/customize.nix"
bash "$script"
grep -qF 'servicesStartTimeoutMs = lib.mkForce (15 * 60 * 1000)' "$XDG_CONFIG_HOME/home-manager/customize.nix"
cp "$XDG_CONFIG_HOME/home-manager/customize.nix" "$temporary/original"
if bash "$script" >/dev/null 2>&1; then
  echo 'Predecessor setup overwrote existing customization' >&2
  exit 1
fi
cmp "$temporary/original" "$XDG_CONFIG_HOME/home-manager/customize.nix"
printf 'Historical Home Manager fixture contracts passed\n'
