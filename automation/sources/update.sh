#!/usr/bin/env bash
repo_root="${PURPLEFIN_SOURCE_ROOT:-$PWD}"
[[ -f "${repo_root}/flake.nix" ]] || {
  echo "Run this command from the Purplefin repository root" >&2
  exit 2
}
cd "${repo_root}" || exit
source_name="${1:?usage: purplefin-source-update SOURCE [OUTPUT_FILE]}"
output_file="${2:-}"
case "${source_name}" in
  flake)
    before="$(sha256sum flake.lock | cut -d' ' -f1)"
    nix flake update
    after="$(sha256sum flake.lock | cut -d' ' -f1)"
    changed=false
    [[ "${before}" == "${after}" ]] || changed=true
    digest="${after}"
    ;;
  bluefin | image-builder)
    lock="${repo_root}/sources/${source_name}.json"
    [[ -f "${lock}" ]]
    image="$(jq -er '.image' "${lock}")"
    tag="$(jq -er '.tag' "${lock}")"
    architecture="$(jq -er '.architecture' "${lock}")"
    current="$(jq -er '.digest' "${lock}")"
    digest="$(
      skopeo inspect --retry-times 3 --override-arch "${architecture}" \
        --format '{{.Digest}}' "docker://${image}:${tag}"
    )"
    [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    if [[ "${source_name}" == bluefin ]]; then
      issuer="$(jq -er '.cosign.issuer' "${lock}")"
      identity="$(jq -er '.cosign.identity' "${lock}")"
      cosign verify \
        --certificate-oidc-issuer "${issuer}" \
        --certificate-identity "${identity}" \
        "${image}@${digest}" >/dev/null
    fi
    changed=false
    if [[ "${current}" != "${digest}" ]]; then
      temporary="$(mktemp "${lock}.XXXXXX")"
      trap 'rm -f -- "${temporary}"' EXIT
      jq --arg digest "${digest}" '.digest = $digest' "${lock}" >"${temporary}"
      chmod --reference="${lock}" "${temporary}"
      mv -- "${temporary}" "${lock}"
      changed=true
    fi
    ;;
  determinate-nix)
    lock="${repo_root}/sources/determinate-nix.json"
    [[ -f "${lock}" ]]
    release="$(gh api repos/DeterminateSystems/nix-installer/releases/latest)"
    jq -e '.draft == false and .prerelease == false' <<<"${release}" >/dev/null
    tag="$(jq -er '.tag_name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))' <<<"${release}")"
    version="${tag#v}"
    asset="$(jq -ec '.assets[] | select(.name == "nix-installer-x86_64-linux")' <<<"${release}")"
    installer_url="$(jq -er .browser_download_url <<<"${asset}")"
    digest="$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' <<<"${asset}")"
    installer_sha256="${digest#sha256:}"
    policy_url="https://raw.githubusercontent.com/DeterminateSystems/nix-installer/${tag}/src/action/linux/selinux/determinate-nix.pp"
    policy_file="$(mktemp)"
    temporary="$(mktemp "${lock}.XXXXXX")"
    trap 'rm -f -- "${policy_file}" "${temporary}"' EXIT
    curl --fail --location --retry 3 --output "${policy_file}" "${policy_url}"
    policy_sha256="$(sha256sum "${policy_file}" | cut -d' ' -f1)"
    jq \
      --arg version "${version}" \
      --arg installer_url "${installer_url}" \
      --arg installer_sha256 "${installer_sha256}" \
      --arg policy_url "${policy_url}" \
      --arg policy_sha256 "${policy_sha256}" '
        .version = $version |
        .installer.url = $installer_url |
        .installer.sha256 = $installer_sha256 |
        .selinuxPolicy.url = $policy_url |
        .selinuxPolicy.sha256 = $policy_sha256
      ' "${lock}" >"${temporary}"
    changed=false
    if ! cmp --silent "${lock}" "${temporary}"; then
      chmod --reference="${lock}" "${temporary}"
      mv -- "${temporary}" "${lock}"
      changed=true
    fi
    ;;
  *)
    echo "Unknown source: ${source_name}" >&2
    exit 2
    ;;
esac
if [[ -n "${output_file}" ]]; then
  {
    printf 'changed=%s\n' "${changed}"
    printf 'digest=%s\n' "${digest}"
  } >>"${output_file}"
else
  jq -cn --arg source "${source_name}" --arg digest "${digest}" \
    --argjson changed "${changed}" \
    '{source: $source, changed: $changed, digest: $digest}'
fi
