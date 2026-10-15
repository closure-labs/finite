{
  pkgs,
  lib,
  catalog,
  homeScaffold,
  version,
}: let
  determinate = builtins.fromJSON (builtins.readFile ../sources/determinate-nix.json);
  fetch = asset: pkgs.fetchurl {inherit (asset) url sha256;};
  homeCatalog = pkgs.writeText "home-profile-catalog.json" (builtins.toJSON
    (import ./home-catalog.nix {
      domainCatalog = catalog;
      inherit lib version;
    }));
  payload = pkgs.runCommand "finite-image-payload-${version}" {} ''
    mkdir -p "$out/home-manager-template"
    cp -R ${homeScaffold}/. "$out/home-manager-template/"
    cp ${homeCatalog} "$out/home-profile-catalog.json"
    cp ${../VERSION} "$out/version"
    cp ${../sources/determinate-nix.json} "$out/determinate-nix.json"
    cp ${fetch determinate.installer} "$out/determinate-nix-installer"
    cp ${fetch determinate.selinuxPolicy} "$out/determinate-nix.pp"
    cp ${fetch determinate.selinuxFileContexts} "$out/nix.fc"
    chmod 0555 "$out/determinate-nix-installer"
  '';
in {inherit payload homeCatalog;}
