{
  programs.alejandra.enable = true;
  programs.deadnix.enable = true;

  projectRootFile = "flake.nix";

  settings.formatter.deadnix.priority = 1;
  settings.formatter.alejandra.priority = 2;
}
