{
  bluefin,
  generated,
  loadBluefin,
  pkgs,
  version,
}:
pkgs.writeShellApplication {
  name = "purplefin-validate-image-shard";
  runtimeInputs = with pkgs; [coreutils jq skopeo];
  text = ''
    export PURPLEFIN_GENERATED_ROOT=${generated}
    export PURPLEFIN_BASE_DIGEST=${bluefin.digest}
    export PURPLEFIN_LOAD_BLUEFIN=${loadBluefin}/bin/purplefin-load-bluefin
    export PURPLEFIN_VERSION=${version}
    export PURPLEFIN_DEFAULT_BUILDAH=${pkgs.buildah}/bin/buildah
    export PURPLEFIN_DEFAULT_PODMAN=${pkgs.podman}/bin/podman
    exec ${pkgs.bash}/bin/bash ${../../automation/github/validate-image-shard.sh} "$@"
  '';
}
