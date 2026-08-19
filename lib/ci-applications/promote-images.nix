{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-promote-images";
  runtimeInputs = with pkgs; [coreutils cosign gh jq oras skopeo];
  text = ''
    exec ${pkgs.bash}/bin/bash ${../../automation/github/promote-images.sh} "$@"
  '';
}
