# Keep the complete proof matrix; schedule at most two independent cases.
{
  catalog,
  foundation,
  lib,
  schedule ? builtins.parallel or (_: result: result),
}: let
  homeFlakeModule = import ./home-manager-flake-module.nix {inherit foundation;};
  mkCase = foundation: hardware: packages: roles: {
    schema = 2;
    inherit foundation hardware packages roles;
    identity = {
      username = "finite-check-${foundation}-${hardware}-${lib.concatStringsSep "-" packages}-${lib.concatStringsSep "-" roles}";
      homeDirectory = "/var/home/finite-check-${foundation}-${hardware}-${lib.concatStringsSep "-" packages}-${lib.concatStringsSep "-" roles}";
    };
  };
  firstFoundation = builtins.head catalog.foundationNames;
  firstHardware = builtins.head catalog.homeHardwareNames;
  cases =
    lib.concatMap (foundation: map (hardware: mkCase foundation hardware [] []) catalog.homeHardwareNames) catalog.foundationNames
    ++ map (role: mkCase firstFoundation firstHardware [] [role]) catalog.roleNames
    ++ [
      (mkCase (lib.last catalog.foundationNames) (lib.last catalog.homeHardwareNames) [] catalog.roleNames)
      (mkCase firstFoundation firstHardware catalog.packageNames [])
    ];
  paths = map (profile: let
    evaluated = lib.evalModules {
      modules = [homeFlakeModule {finite.homeProfile = profile;}];
    };
  in
    evaluated.config.flake.homeConfigurations.${profile.identity.username}.activationPackage.drvPath)
  cases;
  force = remaining:
    if remaining == []
    then true
    else let
      batch = lib.take 2 remaining;
      # The primitive starts weak evaluation in the background. Deep-force each
      # scheduled path, then force the same batch in the foreground so errors
      # cannot disappear. Finish this pair before scheduling the next one.
      checked = schedule (map (path: builtins.deepSeq path true) batch) (builtins.deepSeq batch true);
    in
      builtins.deepSeq checked (force (lib.drop 2 remaining));
in {
  inherit cases paths;
  evaluated = force paths;
}
