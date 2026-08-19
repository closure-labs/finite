{
  generated,
  imageBuilder,
  installerSmoke,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "purplefin-installer-build";
  runtimeInputs = with pkgs; [
    bash
    coreutils
    cosign
    findutils
    gh
    gnugrep
    jq
    podman
    skopeo
  ];
  text = ''
    export PURPLEFIN_GENERATED_ROOT=${generated}
    export PURPLEFIN_IMAGE_BUILDER_REF=${imageBuilder.image}@${imageBuilder.digest}
    export PURPLEFIN_INSTALLER_SMOKE=${installerSmoke}/bin/purplefin-installer-smoke
    export PURPLEFIN_PODMAN=${pkgs.podman}/bin/podman
    exec ${pkgs.bash}/bin/bash ${../automation/installer/build.sh} "$@"
  '';
}
