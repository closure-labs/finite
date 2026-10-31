#!/usr/bin/env bash
# Runs only inside the disposable build root, never on a workstation.
set -euo pipefail
test -f /ctx/plan.json
export CONFIG_DIRECTORY=/ctx/files IMAGE_REGISTRY=ghcr.io/closure-labs IMAGE_NAME=finite
profile=$(jq -er .profile /ctx/plan.json)
foundation=$(jq -er .foundation /ctx/plan.json)
test "$profile" = "${PROFILE:?}"
case "$profile:$foundation" in finite:bluefin|finite-dev:bluefin-dx) ;; *) exit 2 ;; esac

# Match the locked BlueBuild CLI's /opt lifecycle, not a new deployment model.
mkdir -p /var/roothome /var/opt /var/lib/alternatives /var/usrlocal /usr/lib/opt
shopt -s nullglob
opt_entries=(/opt/*)
if ((${#opt_entries[@]})); then mv -- "${opt_entries[@]}" /usr/lib/opt/; fi
rm -rf /opt
ln -s /usr/lib/opt /opt

install -Dm755 "$CONFIG_DIRECTORY/scripts/upstream-kernel.py" /usr/libexec/finite/check-upstream-kernel
python3 /usr/libexec/finite/check-upstream-kernel snapshot
bash "$CONFIG_DIRECTORY/scripts/nix-identities.sh"
while IFS= read -r repo; do
  install -m 0644 "$CONFIG_DIRECTORY/dnf/$repo" "/etc/yum.repos.d/$repo"
done < <(jq -er '.repos[]' /ctx/plan.json)
mapfile -t packages < <(jq -er '.packages[]' /ctx/plan.json)
dnf -y makecache
dnf -y install --setopt=install_weak_deps=True "${packages[@]}"
python3 "$CONFIG_DIRECTORY/scripts/security-remediate.py"
python3 "$CONFIG_DIRECTORY/scripts/tailscale-security.py"
cp -a "$CONFIG_DIRECTORY/system/." /
rm -f /.gitkeep
python3 /ctx/experiment/image-config.py payload /ctx
bash "$CONFIG_DIRECTORY/scripts/nix-install.sh"
bash "$CONFIG_DIRECTORY/scripts/authselect.sh"
mapfile -t units < <(jq -er '.systemUnits[]' /ctx/plan.json)
systemctl -f enable "${units[@]}"
mapfile -t units < <(jq -er '.userUnits[]' /ctx/plan.json)
systemctl --global -f enable "${units[@]}"
bash "$CONFIG_DIRECTORY/scripts/profile.sh" "$profile" "$foundation" generic-x86_64 "$profile"

# Same dracut semantics as BlueBuild initramfs@v1; no host-derived archive.
dracut=/usr/bin/dracut
if [[ -x /usr/libexec/rpm-ostree/wrapped/dracut ]]; then dracut=/usr/libexec/rpm-ostree/wrapped/dracut; fi
mapfile -t kernels < <(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)
test "${#kernels[@]}" = 1
log_config=$(mktemp /etc/dracut.conf.d/zzz-finite-experiment-XXXXXXXX.conf)
trap 'rm -f "$log_config"' EXIT
printf 'stdloglvl=4\nsysloglvl=0\nkmsgloglvl=0\nfileloglvl=0\n' >"$log_config"
"$dracut" --kver "${kernels[0]}" --force --add ostree --no-hostonly --reproducible "/usr/lib/modules/${kernels[0]}/initramfs.img"
chmod 0600 "/usr/lib/modules/${kernels[0]}/initramfs.img"
rm "$log_config"
trap - EXIT
python3 /usr/libexec/finite/check-upstream-kernel verify
python3 /ctx/experiment/image-config.py identity /ctx
bash "$CONFIG_DIRECTORY/scripts/finalize.sh"

# Preserve the previous builder's mutable-directory cleanup and rpmdb linkage.
for optdir in /usr/lib/opt/*; do
  opt=$(basename "$optdir")
  printf 'L+?  "%s"  -  -  -  -  %s\n' "/opt/$opt" "$optdir" >"/usr/lib/tmpfiles.d/99-bluebuild-optfix-$opt.conf"
done
rm -rf /tmp/* /opt
# Explicit image-root cleanup, matching the old non-hidden /var/* glob.
find /var -mindepth 1 -maxdepth 1 ! -name '.*' -exec rm -rf -- {} +
ln -s /var/opt /opt
for file in rpmdb.sqlite rpmdb.sqlite-shm rpmdb.sqlite-wal; do
  target="/usr/share/rpm/$file"
  link="/usr/lib/sysimage/rpm-ostree-base-db/$file"
  if [[ -f "$target" && -f "$link" ]]; then ln -f "$target" "$link"; fi
done
bash /ctx/verify-image.sh "$profile"
