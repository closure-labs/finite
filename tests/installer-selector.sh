#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper="${repo_root}/installer/root/usr/libexec/purplefin-installer/select-image"
catalog="${repo_root}/installer/catalog.tsv"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

mkdir -p "${tmpdir}/generic" "${tmpdir}/dell"
printf '%s\n' 'Generic Vendor' >"${tmpdir}/generic/sys_vendor"
printf '%s\n' 'Generic Device' >"${tmpdir}/generic/product_name"
printf '%s\n' 'Dell Inc.' >"${tmpdir}/dell/sys_vendor"
printf '%s\n' 'XPS 13 9350' >"${tmpdir}/dell/product_name"

generic_env=(PURPLEFIN_INSTALLER_CATALOG="${catalog}" PURPLEFIN_DMI_ROOT="${tmpdir}/generic")
dell_env=(PURPLEFIN_INSTALLER_CATALOG="${catalog}" PURPLEFIN_DMI_ROOT="${tmpdir}/dell")

test "$(env "${generic_env[@]}" "${helper}" detect-hardware)" = generic
test "$(env "${dell_env[@]}" "${helper}" detect-hardware)" = dell-xps-9350-intel
env "${generic_env[@]}" "${helper}" list-presets | grep -qx $'base\tBase'
env "${generic_env[@]}" "${helper}" list-presets | grep -qx $'sales\tSales'
env "${generic_env[@]}" "${helper}" list-presets | grep -qx $'support\tSupport'
! env "${generic_env[@]}" "${helper}" list-presets | grep -q '^dale'
env "${dell_env[@]}" "${helper}" list-presets | grep -qx $'dale\tDale'

while IFS=$'\t' read -r preset hardware profile tag label; do
    [[ ${preset} == \#* || -z ${preset} ]] && continue
    test -f "${repo_root}/build_files/profiles/profiles/${profile}.conf"
    grep -qxF "profile_name=${profile}" "${repo_root}/build_files/profiles/profiles/${profile}.conf"
    test -n "${tag}"
    test -n "${label}"
done <"${catalog}"
