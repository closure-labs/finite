# Pure fixtures protect matrix coverage, nested failures and upstream fallback.
let
  catalog = {
    foundationNames = ["base" "dev"];
    homeHardwareNames = ["generic" "laptop"];
    roleNames = ["editor" "browser"];
    packageNames = ["terminal" "tools"];
  };
  last = values: builtins.elemAt values (builtins.length values - 1);
  min = a: b:
    if a < b
    then a
    else b;
  slice = start: count: values:
    builtins.genList (i: builtins.elemAt values (start + i)) (min count (builtins.length values - start));
  lib = {
    inherit last;
    concatStringsSep = builtins.concatStringsSep;
    concatMap = f: values: builtins.concatLists (map f values);
    take = count: values: slice 0 count values;
    drop = count: values: slice (min count (builtins.length values)) (builtins.length values) values;
    evalModules = args: let
      profile = (builtins.elemAt args.modules 1).finite.homeProfile;
    in {
      config.flake.homeConfigurations.${profile.identity.username}.activationPackage.drvPath = builtins.toJSON profile;
    };
  };
  serial = _: result: result;
  make = extra:
    import ../../lib/home-proofs.nix ({
        inherit catalog lib;
        foundation = {};
      }
      // extra);
  baseline = make {schedule = serial;};
  paired = make {};
  brokenLib =
    lib
    // {
      evalModules = args: let
        result = lib.evalModules args;
        profile = (builtins.elemAt args.modules 1).finite.homeProfile;
      in {
        config.flake.homeConfigurations.${profile.identity.username}.activationPackage.drvPath =
          if profile.roles == ["editor"]
          then throw "Broken role proof must fail the aggregate"
          else result.config.flake.homeConfigurations.${profile.identity.username}.activationPackage.drvPath;
      };
    };
  throws = schedule:
    !(builtins.tryEval
      (make {
        inherit schedule;
        lib = brokenLib;
      }).evaluated).success;
  profiles = map builtins.fromJSON paired.paths;
in
  assert baseline.evaluated && paired.evaluated;
  assert baseline.paths == paired.paths;
  assert builtins.length profiles == 8;
  assert map (p: [p.foundation p.hardware]) (lib.take 4 profiles)
  == [
    ["base" "generic"]
    ["base" "laptop"]
    ["dev" "generic"]
    ["dev" "laptop"]
  ];
  assert map (p: p.roles) (lib.drop 4 profiles) == [["editor"] ["browser"] ["editor" "browser"] []];
  assert (last profiles).packages == ["terminal" "tools"];
  assert (builtins.elemAt profiles 6).foundation == "dev";
  assert (builtins.elemAt profiles 6).hardware == "laptop";
  assert (builtins.head profiles).identity
  == {
    username = "finite-check-base-generic--";
    homeDirectory = "/var/home/finite-check-base-generic--";
  };
  assert throws serial;
  assert throws (builtins.parallel or serial); true
