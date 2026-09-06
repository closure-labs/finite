#!/usr/bin/env bash
set -euo pipefail
script=$PWD/scripts/bluebuild/wait-nix.sh
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
export TEST_NIX_READINESS_ROOT=$test_root
mkdir "$test_root/bin"
cat >"$test_root/bin/systemctl" <<'MOCK'
set -euo pipefail
case "$1" in
is-active)
  # One socket is already active while the remaining initialization is pending.
  [[ $3 == determinate-nixd.socket || -e $TEST_NIX_READINESS_ROOT/ready ]]
  ;;
is-failed) [[ ${TEST_NIX_FAILED:-false} == true ]] ;;
--no-pager) echo 'fixture service status' ;;
*) echo "Unexpected systemctl mutation: $*" >&2; exit 99 ;;
esac
MOCK
cat >"$test_root/bin/sleep" <<'MOCK'
touch "$TEST_NIX_READINESS_ROOT/waited" "$TEST_NIX_READINESS_ROOT/ready"
MOCK
cat >"$test_root/bin/journalctl" <<'MOCK'
echo 'fixture service journal'
MOCK
for tool in "$test_root/bin/"*; do
  { printf '#!%s\n' "$(command -v bash)"; cat "$tool"; } >"$tool.patched"
  mv "$tool.patched" "$tool"
done
chmod +x "$test_root/bin/"*
export PATH="$test_root/bin:$PATH"
bash "$script" >"$test_root/success.log"
test -e "$test_root/waited"
rm "$test_root/ready" "$test_root/waited"
if TEST_NIX_FAILED=true bash "$script" >"$test_root/failure.log" 2>&1; then
  echo 'Readiness check accepted a failed initialization unit' >&2
  exit 1
fi
test ! -e "$test_root/waited"
grep -q 'fixture service status' "$test_root/failure.log"
grep -q 'fixture service journal' "$test_root/failure.log"
