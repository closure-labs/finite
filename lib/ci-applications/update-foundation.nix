{pkgs}:
pkgs.writeShellApplication {
  name = "finite-update-foundation";
  runtimeInputs = with pkgs; [python3 gh git];
  text = ''
    exec python3 ${../../scripts/ci}/update-foundation.py "$@"
  '';
}
