{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-ci-gate";
  runtimeInputs = [pkgs.coreutils];
  text = ''
    exec ${pkgs.bash}/bin/bash ${../../automation/github/ci-gate.sh} "$@"
  '';
}
