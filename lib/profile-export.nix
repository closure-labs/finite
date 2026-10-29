{
  pkgs,
  foundation,
  homeCatalog,
}:
pkgs.writeShellApplication {
  name = "finite-profile-export";
  runtimeInputs = with pkgs; [python3 nix yq-go];
  text = ''
    exec python3 ${../scripts/home}/profile-export.py ${foundation}/lib/generate-profile.nix ${homeCatalog} "$@"
  '';
}
