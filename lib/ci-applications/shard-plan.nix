{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-shard-plan";
  runtimeInputs = [pkgs.jq];
  text = ''
    exec ${pkgs.bash}/bin/bash ${../../automation/github/shard-plan.sh} "$@"
  '';
}
