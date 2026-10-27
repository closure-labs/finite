{
  homeCatalog,
  pkgs,
  foundation,
}: let
  applications = foundation.lib.mkApplications {inherit pkgs;};
  cloudInit = assert foundation.lib.profileCapabilities.writeSchema == 3;
    import ./cloud-init-v3.nix {inherit pkgs foundation homeCatalog;};
in {
  inherit cloudInit;
  inherit (applications) homeBootstrap homeInit homeProfile homeUpdate homeMigrate;
}
