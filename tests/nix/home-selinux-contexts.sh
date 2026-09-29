#!/usr/bin/env bash
set -euo pipefail

script=files/system/usr/libexec/finite/fix-home-selinux-contexts
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
contexts="$temporary/contexts"
mkdir -p "$contexts"
cat >"$contexts/file_contexts.subs_dist" <<'EOF'
# Vendor mappings
/var/home /home
/var/roothome /root
EOF
printf '/var/home/nix /nix\n' >"$contexts/file_contexts.subs"
cp "$contexts/file_contexts.subs_dist" "$temporary/original"
printf '/home/[^/]+/.+ unconfined_u:object_r:user_home_t:s0\n' >"$contexts/file_contexts.homedirs"
bash "$script" "$contexts"
cmp "$contexts/file_contexts.subs_dist" "$temporary/original"

printf '/var/home/[^/]+/.+ unconfined_u:object_r:user_home_t:s0\n' >"$contexts/file_contexts.homedirs"
bash "$script" "$contexts"
grep -qxF '/home /var/home' "$contexts/file_contexts.subs_dist"
! grep -qxF '/var/home /home' "$contexts/file_contexts.subs_dist"
grep -qxF '/var/roothome /root' "$contexts/file_contexts.subs_dist"
grep -qxF '/var/home/nix /nix' "$contexts/file_contexts.subs"
cp "$contexts/file_contexts.subs_dist" "$temporary/corrected"
bash "$script" "$contexts"
cmp "$contexts/file_contexts.subs_dist" "$temporary/corrected"

printf '/home/custom/.+ unconfined_u:object_r:user_home_t:s0\n' >>"$contexts/file_contexts.homedirs"
if bash "$script" "$contexts" >/dev/null 2>&1; then
  echo 'Mixed home roots were silently rewritten' >&2
  exit 1
fi
cmp "$contexts/file_contexts.subs_dist" "$temporary/corrected"

# matchpathcon can accept default_t when the lookup policy itself is broken.
# The VM prerequisite must additionally verify the expected object types.
mkdir -p "$temporary/bin"
for command in restorecon matchpathcon ls; do
  printf '#!%s\nexit 0\n' "$BASH" >"$temporary/bin/$command"
done
{
  printf '#!%s\n' "$BASH"
  cat <<'EOF'
if [[ ${TEST_BAD_LABEL:-false} == true ]]; then
  echo system_u:object_r:default_t:s0
elif [[ $3 == /home/finite-test ]]; then
  echo unconfined_u:object_r:user_home_dir_t:s0
else
  echo unconfined_u:object_r:ssh_home_t:s0
fi
EOF
} >"$temporary/bin/stat"
chmod +x "$temporary/bin/"*
PATH="$temporary/bin:$PATH" bash scripts/bluebuild/check-vm-user-labels.sh
if TEST_BAD_LABEL=true PATH="$temporary/bin:$PATH" bash scripts/bluebuild/check-vm-user-labels.sh >/dev/null 2>&1; then
  echo 'The VM accepted default_t for its SSH account' >&2
  exit 1
fi
printf 'OSTree home SELinux context contracts passed\n'
