{
  pkgs,
  lib,
  catalog,
  homeScaffold,
  version,
}: let
  determinate = builtins.fromJSON (builtins.readFile ../sources/determinate-nix.json);
  kernel = builtins.fromJSON (builtins.readFile ../sources/kernel-next.json);
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
  next = pkgs.runCommand "finite-next-image-payload-${version}" {} ''
    mkdir -p "$out/kernel-next"
    cp -R ${payload}/. "$out/"
    cp ${../sources/kernel-next.json} "$out/kernel-next/kernel-next.json"
    ${lib.concatMapStringsSep "\n" (package: ''
        cp ${fetch {
          url = "${kernel.baseUrl}/${package.file}";
          inherit (package) sha256;
        }} "$out/kernel-next/${package.file}"
      '')
      kernel.packages}
  '';
in {inherit payload next homeCatalog;}
