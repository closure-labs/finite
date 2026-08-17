#!/usr/bin/env bash
set -euo pipefail

rust_packages=(rust cargo rustfmt clippy)
optional_cargo_packages=(cargo-edit cargo-watch cargo-audit)
packages=("${rust_packages[@]}")

# Keep the profile portable across Fedora releases: install cargo add-ons only
# when the current build repositories provide an exact package match.
for package in "${optional_cargo_packages[@]}"; do
	if dnf5 -q repoquery --available --qf '%{name}\n' "${package}" | grep -qx "${package}"; then
	packages+=("${package}")
	fi
done

dnf5 -y install "${packages[@]}"
for package in "${packages[@]}"; do rpm -q "${package}"; done
