{
  pkgs,
  foundation,
  homeCatalog,
}:
pkgs.writeShellApplication {
  name = "finite-cloud-init";
  runtimeInputs = with pkgs; [python3 nix yq-go xorriso];
  text = ''
    exec python3 ${../scripts/home/seed.py} ${foundation}/lib/generate-profile.nix ${homeCatalog} "$@"
  '';
}
