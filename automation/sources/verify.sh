#!/usr/bin/env bash
source_name="${1:?usage: purplefin-source-verify SOURCE}"
case "${source_name}" in
  bluefin)
    image="${PURPLEFIN_BLUEFIN_IMAGE:?}"
    architecture="${PURPLEFIN_BLUEFIN_ARCHITECTURE:?}"
    digest="${PURPLEFIN_BLUEFIN_DIGEST:?}"
    skopeo inspect --retry-times 3 --override-arch "${architecture}" \
      "docker://${image}@${digest}" >/dev/null
    cosign verify \
      --certificate-oidc-issuer "${PURPLEFIN_BLUEFIN_ISSUER:?}" \
      --certificate-identity "${PURPLEFIN_BLUEFIN_IDENTITY:?}" \
      "${image}@${digest}" >/dev/null
    ;;
  image-builder)
    image="${PURPLEFIN_IMAGE_BUILDER_IMAGE:?}"
    architecture="${PURPLEFIN_IMAGE_BUILDER_ARCHITECTURE:?}"
    digest="${PURPLEFIN_IMAGE_BUILDER_DIGEST:?}"
    skopeo inspect --retry-times 3 --override-arch "${architecture}" \
      "docker://${image}@${digest}" >/dev/null
    ;;
  determinate-nix)
    installer="$(mktemp)"
    policy="$(mktemp)"
    trap 'rm -f -- "${installer}" "${policy}"' EXIT
    curl --fail --location --retry 3 --output "${installer}" \
      "${PURPLEFIN_DETERMINATE_NIX_INSTALLER_URL:?}"
    curl --fail --location --retry 3 --output "${policy}" \
      "${PURPLEFIN_DETERMINATE_NIX_POLICY_URL:?}"
    printf '%s  %s\n' "${PURPLEFIN_DETERMINATE_NIX_INSTALLER_SHA256:?}" "${installer}" |
      sha256sum --check --status
    printf '%s  %s\n' "${PURPLEFIN_DETERMINATE_NIX_POLICY_SHA256:?}" "${policy}" |
      sha256sum --check --status
    printf 'determinate-nix@%s\n' "${PURPLEFIN_DETERMINATE_NIX_VERSION:?}"
    exit 0
    ;;
  *)
    echo "Unknown OCI source: ${source_name}" >&2
    exit 2
    ;;
esac
printf '%s@%s\n' "${image}" "${digest}"
