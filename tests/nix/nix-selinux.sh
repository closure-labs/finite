#!/usr/bin/env bash
set -euo pipefail

temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
export TEST_POLICY_ROOT="$temporary"
export FINITE_NIX_SELINUX_POLICY="$temporary/nix.pp"
export FINITE_HOME_CONTEXTS_COMMAND="$temporary/bin/fix-home"
printf 'test policy\n' >"$FINITE_NIX_SELINUX_POLICY"
mkdir -p "$temporary/bin" "$temporary/contexts" "$temporary/state"
printf '/home/[^/]+/.+ unconfined_u:object_r:user_home_t:s0\n' >"$temporary/contexts/file_contexts.homedirs"
printf '/var/home /home\n' >"$temporary/contexts/file_contexts.subs_dist"
export TEST_HOME_CONTEXTS_SCRIPT="$PWD/files/system/usr/libexec/finite/fix-home-selinux-contexts"
cat >"$temporary/bin/semodule" <<'MOCK'
printf 'semodule %s\n' "$*" >>"$TEST_POLICY_ROOT/commands"
case $1 in
  -l) [[ ! -e "$TEST_POLICY_ROOT/installed" ]] || echo 'nix 1.0' ;;
  -i)
    touch "$TEST_POLICY_ROOT/installed"
    printf '/var/home/[^/]+/.+ unconfined_u:object_r:user_home_t:s0\n' >"$TEST_POLICY_ROOT/contexts/file_contexts.homedirs"
    ;;
  *) exit 90 ;;
esac
MOCK
cat >"$temporary/bin/semanage" <<'MOCK'
printf 'semanage %s\n' "$*" >>"$TEST_POLICY_ROOT/commands"
[[ $* == 'fcontext -a -e /nix /var/home/nix' ]] || exit 91
if grep -qxF '/var/home /home' "$TEST_POLICY_ROOT/contexts/file_contexts.subs_dist"; then
  echo 'File spec /var/home/nix conflicts with parent equivalency' >&2
  exit 22
fi
if [[ ${TEST_POLICY_FAILURE:-false} == true ]]; then
  echo 'Original semanage transaction failure' >&2
  exit 42
fi
printf '/var/home/nix /nix\n' >"$TEST_POLICY_ROOT/contexts/file_contexts.subs"
MOCK
cat >"$temporary/bin/fix-home" <<'MOCK'
exec "$BASH" "$TEST_HOME_CONTEXTS_SCRIPT" "$TEST_POLICY_ROOT/contexts"
MOCK
for command in "$temporary/bin/"*; do
  { printf '#!%s\nset -euo pipefail\n' "$BASH"; cat "$command"; } >"$command.new"
  mv "$command.new" "$command"
  chmod +x "$command"
done
export PATH="$temporary/bin:$PATH"
script=files/system/usr/libexec/finite/install-determinate-nix-selinux-policy
bash "$script"
bash "$script"
[[ $(grep -c '^semodule -i ' "$temporary/commands") == 1 ]]
grep -qxF '/var/home/nix /nix' "$temporary/contexts/file_contexts.subs"
status=0
TEST_POLICY_FAILURE=true bash "$script" >"$temporary/failure" 2>&1 || status=$?
[[ $status == 42 ]]
grep -qF 'Original semanage transaction failure' "$temporary/failure"
! grep -qF 'fcontext -m' "$temporary/commands"

cp "$script" "$temporary/state/install-nix-policy"
cp "$temporary/bin/fix-home" "$temporary/state/fix-home-contexts"
fixture=scripts/bluebuild/prepare-vm-predecessor-policy.sh
if TEST_POLICY_FAILURE=true bash "$fixture" "$temporary/state" >/dev/null 2>&1; then
  echo 'Failed predecessor policy preparation was accepted' >&2
  exit 1
fi
test ! -e "$temporary/state/predecessor-labels-prepared"
bash "$fixture" "$temporary/state"
cp "$temporary/commands" "$temporary/once"
bash "$fixture" "$temporary/state"
cmp "$temporary/commands" "$temporary/once"
printf 'Nix SELinux migration and predecessor policy contracts passed\n'
