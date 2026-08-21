{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-classify-changes";
  runtimeInputs = [pkgs.coreutils];
  text = ''
    component="''${1:?usage: purplefin-classify-changes COMPONENT}"
    required=false
    case "''${component}" in
      images | installer) ;;
      *) echo "unknown component: ''${component}" >&2; exit 2 ;;
    esac
    while IFS= read -r path; do
      case "''${component}:''${path}" in
        installer:.github/actions/build-installer/* | \
        installer:flake.lock | \
        installer:installer/Containerfile | installer:installer/rootfs/* | \
        installer:sources/image-builder.json | \
        installer:lib/ci-applications/installer-e2e.nix | \
        installer:lib/ci-applications/installer-smoke.nix | \
        installer:lib/installer-application.nix)
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
        images:secretspec.toml | \
        images:installer/* | images:tests/* | \
        images:lib/installer-application.nix | \
        images:lib/render-architecture.nix | \
        images:lib/repository-checks.nix | \
        images:modules/aspects/*/tests/* | \
        images:modules/repository/*)
          ;;
        images:*) required=true; break ;;
      esac
    done
    printf '%s\n' "''${required}"
  '';
}
