{
  inputs,
  pkgs,
  ...
}: let
  weekly = inputs.nixpkgs-weekly.legacyPackages.${pkgs.stdenv.hostPlatform.system};
in {
  # This additive module is yours. Finite preserves it when the generated
  # Home Manager scaffold is upgraded.
  home.packages =
    (with pkgs; [
      # jq
    ])
    ++ (with weekly; [
      # example
    ]);

  services.flatpak.packages = [
    #   "org.gimp.GIMP"
  ];
}
