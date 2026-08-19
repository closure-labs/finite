#!/usr/bin/env bash
component="${1:?usage: purplefin-classify-changes COMPONENT}"
required=false
case "${component}" in
  images | installer) ;;
  *) echo "unknown component: ${component}" >&2; exit 2 ;;
esac
while IFS= read -r path; do
  case "${component}:${path}" in
    installer:.github/actions/build-installer/* | \
    installer:.github/actions/setup-nix/* | \
    installer:.github/workflows/build-installer.yml | \
    installer:.github/workflows/build.yml | \
    installer:flake.lock | installer:flake.nix | \
    installer:installer/Containerfile | installer:installer/rootfs/* | \
    installer:sources/image-builder.json | installer:sources/determinate-nix.json | \
    installer:modules/* | installer:lib/* | \
    installer:tests/installer/*)
      required=true; break ;;
    images:README.md | images:LICENSE | images:docs/* | \
    images:.editorconfig | images:.github/actions/build-installer/* | \
    images:.github/dependabot.yml | \
    images:.github/workflows/build-installer.yml | \
    images:.github/workflows/cleanup.yml | \
    images:.github/workflows/queue-dependabot.yml | \
    images:.github/workflows/release.yml | \
    images:.github/workflows/update-flake-lock.yml | \
    images:.github/workflows/update-bluefin.yml | \
    images:.github/workflows/update-determinate-nix.yml | \
    images:.github/workflows/update-image-builder.yml | \
    images:automation/github/classify-ci.sh | \
    images:automation/github/validate-trusted-update.sh | \
    images:secretspec.toml | \
    images:installer/* | images:tests/installer/* | \
    images:tests/automation/* | \
    images:tests/repository/text-style.sh)
      ;;
    images:*) required=true; break ;;
  esac
done
printf '%s\n' "${required}"
