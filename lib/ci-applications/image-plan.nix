{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-image-plan";
  runtimeInputs = with pkgs; [coreutils cosign gh jq podman skopeo];
  text = ''
    export PURPLEFIN_MANAGED_RPMS_LIBRARY=${../../bootc/builder/lib/independently-managed-rpms.sh}
    export PURPLEFIN_MANAGED_RPMS_MANIFEST=${../../modules/aspects/base/independently-managed-rpms.list}
    exec ${pkgs.bash}/bin/bash ${../../automation/github/image-plan.sh} "$@"
  '';
}
