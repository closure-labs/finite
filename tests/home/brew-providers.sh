#!/usr/bin/env bash
set -euo pipefail

status_script="${1:-templates/home-manager/modules/finite-brew-migration-status}"
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
export FINITE_BREW_JQ FINITE_BREW_READLINK
FINITE_BREW_JQ=$(command -v jq)
FINITE_BREW_READLINK=$(command -v readlink)
export TEST_BREW_PREFIX="$test_root/brew" TEST_BREW_LOG="$test_root/brew.log"
export TEST_BREW_INSTALLED=$'gh\nbbrew\nbash-preexec\nuutils-coreutils'
export FINITE_BREW_COMMAND="$test_root/brew-command"
export FINITE_BREW_POLICY="$test_root/policy.json"
mkdir -p "$TEST_BREW_PREFIX/bin" "$TEST_BREW_PREFIX/opt/bash-preexec/etc/profile.d" \
  "$TEST_BREW_PREFIX/opt/uutils-coreutils/libexec/uubin" "$test_root/host"
cat >"$FINITE_BREW_POLICY" <<'EOF'
{"packages":[
  {"formula":"gh","command":"gh"},
  {"formula":"valkyrie00/bbrew/bbrew","command":"bbrew"},
  {"formula":"bash-preexec","file":"opt/bash-preexec/etc/profile.d/bash-preexec.sh"},
  {"formula":"uutils-coreutils","command":"ls","binary":"opt/uutils-coreutils/libexec/uubin/ls"}
]}
EOF
{
  printf '#!%s\n' "$BASH"
  cat <<'EOF'
printf '%s\n' "$*" >>"$TEST_BREW_LOG"
case "$*" in
  --prefix) printf '%s\n' "$TEST_BREW_PREFIX" ;;
  'list --formula -1')
    if [[ -f "$TEST_BREW_PREFIX/.installed" ]]; then
      printf '%s\n' gh bbrew bash-preexec uutils-coreutils
    else
      printf '%s\n' "$TEST_BREW_INSTALLED"
    fi
    ;;
  'bundle install --no-upgrade --file '*)
    [[ "${FINITE_TEST_BREW_INSTALL_FAIL:-false}" != true ]] || exit 1
    [[ "$HOMEBREW_NO_AUTO_UPDATE" == 1 ]]
    grep -qF 'brew "valkyrie00/bbrew/bbrew"' "$5"
    printf '#!%s\nexit 0\n' "$BASH" >"$TEST_BREW_PREFIX/bin/gh"
    chmod +x "$TEST_BREW_PREFIX/bin/gh"
    touch "$TEST_BREW_PREFIX/opt/bash-preexec/etc/profile.d/bash-preexec.sh" "$TEST_BREW_PREFIX/.installed"
    ;;
  *) echo 'Unexpected Brew operation' >&2; exit 70 ;;
esac
EOF
} >"$FINITE_BREW_COMMAND"
chmod +x "$FINITE_BREW_COMMAND"
for binary in "$TEST_BREW_PREFIX/bin/gh" "$TEST_BREW_PREFIX/bin/bbrew" \
  "$TEST_BREW_PREFIX/opt/uutils-coreutils/libexec/uubin/ls" "$test_root/host/gh"; do
  printf '#!%s\nexit 0\n' "$BASH" >"$binary"
  chmod +x "$binary"
done
touch "$TEST_BREW_PREFIX/opt/bash-preexec/etc/profile.d/bash-preexec.sh"
brew_path="$TEST_BREW_PREFIX/opt/uutils-coreutils/libexec/uubin:$TEST_BREW_PREFIX/bin:$PATH"

# Preflight must accept installed alternatives even while the old generation
# still shadows them; the active-provider check must detect that distinction.
PATH="$test_root/host:$brew_path" "$BASH" "$status_script" --check-installed >"$test_root/preflight"
if PATH="$test_root/host:$brew_path" "$BASH" "$status_script" --check >"$test_root/shadowed"; then
  echo 'A shadowed Homebrew provider passed --check' >&2
  exit 1
fi
grep -qF "host:$test_root/host/gh" "$test_root/shadowed"
PATH="$brew_path" "$BASH" "$status_script" --check >"$test_root/healthy"
grep -qF "brew:$TEST_BREW_PREFIX/bin/gh" "$test_root/healthy"

if TEST_BREW_INSTALLED=$'bbrew\nbash-preexec\nuutils-coreutils' PATH="$brew_path" \
  "$BASH" "$status_script" --check-installed >"$test_root/missing-formula"; then
  echo 'A missing Brew formula passed the activation preflight' >&2
  exit 1
fi
grep -qF 'brew-missing' "$test_root/missing-formula"

rm "$TEST_BREW_PREFIX/bin/gh"
if PATH="$brew_path" "$BASH" "$status_script" --check-installed >"$test_root/missing-binary"; then
  echo 'A missing Brew executable passed the activation preflight' >&2
  exit 1
fi
grep -qF 'brew-command-missing' "$test_root/missing-binary"

rm "$TEST_BREW_PREFIX/opt/bash-preexec/etc/profile.d/bash-preexec.sh"
if PATH="$brew_path" "$BASH" "$status_script" --check-installed >"$test_root/missing-file"; then
  echo 'A missing Brew integration file passed the activation preflight' >&2
  exit 1
fi
grep -qF 'brew-file-missing' "$test_root/missing-file"

if FINITE_BREW_COMMAND="$test_root/absent" "$BASH" "$status_script" --check-installed >/dev/null 2>&1; then
  echo 'An absent Homebrew installation passed the activation preflight' >&2
  exit 1
fi

if grep -vE '^(--prefix|list --formula -1)$' "$TEST_BREW_LOG"; then
  echo 'The provider check invoked a mutating Brew operation' >&2
  exit 1
fi

bootstrap_script="$(dirname "$status_script")/finite-brew-bootstrap"
export TEST_BREW_INSTALLED=''
if FINITE_TEST_BREW_INSTALL_FAIL=true "$BASH" "$bootstrap_script" >/dev/null 2>&1; then
  echo 'Failed Brew installation was accepted' >&2
  exit 1
fi
test ! -e "$TEST_BREW_PREFIX/.installed"
"$BASH" "$bootstrap_script" >"$test_root/bootstrap"
test -e "$TEST_BREW_PREFIX/.installed"
PATH="$brew_path" "$BASH" "$status_script" --check >/dev/null
installs_before=$(grep -c '^bundle install ' "$TEST_BREW_LOG")
"$BASH" "$bootstrap_script" >/dev/null
[[ "$(grep -c '^bundle install ' "$TEST_BREW_LOG")" == "$installs_before" ]]
printf 'Homebrew provider contracts passed\n'
