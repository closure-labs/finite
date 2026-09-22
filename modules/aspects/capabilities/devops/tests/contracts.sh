#!/usr/bin/env bash
set -euo pipefail

aspect_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
module="templates/home-manager/modules/aspects/capabilities/devops/home.nix"
rootfs="templates/home-manager/modules/aspects/capabilities/devops/rootfs"

for file in .zshrc aliases.zsh bindings.zsh fzf.zsh prompt.zsh starship.toml LICENSE; do
	test -f "${rootfs}/usr/share/finite/zsh/${file}"
done
grep -qF 'paths = [pkgs.ghostty];' "${module}"
grep -qF -- "--replace-fail 'DBusActivatable=true' 'DBusActivatable=false'" "${module}"
grep -qF '"ghostty/config.ghostty".text' "${module}"
# shellcheck disable=SC2016 # Ghostty must start the Home Manager Zsh package.
grep -qF '"command = ${config.programs.zsh.package}/bin/zsh"' "${module}"
if grep -qF '"ghostty/config".source' "${module}"; then
	echo 'The devops aspect still deploys the superseded Ghostty config path' >&2
	exit 1
fi
grep -qF 'openbao' "${module}"
grep -qF 'enableZshIntegration = true' "${module}"
grep -qF 'src = pkgs.zsh-vi-mode' "${module}"
test ! -e "${rootfs}/usr/share/finite/zsh/plugins.zsh"
test ! -e "${aspect_root}/apply.sh"
shopt -s nullglob dotglob
manifests=("${aspect_root}"/manifests/*)
test "${#manifests[@]}" -eq 0
