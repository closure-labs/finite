{
  pkgs,
  version,
}: let
  marker = pkgs.writeText "finite-home-template.json" (builtins.toJSON {
      schema = 1;
      generator = "finite-home-init";
      inherit version;
    }
    + "\n");
in
  pkgs.runCommand "finite-home-manager-template-${version}" {} ''
    cp -R ${../templates/home-manager}/. "$out/"
    chmod -R u+w "$out"
    cp ${marker} "$out/finite-template.json"
  ''
