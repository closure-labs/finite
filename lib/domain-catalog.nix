# Foundation owns Home Manager choices; Finite owns their image mapping.
{homeCatalog}: let
  foundations = map (entry:
    entry
    // {
      profiles.generic-x86_64 = {
        name =
          if entry.name == "bluefin"
          then "finite"
          else "finite-dev";
        order =
          if entry.name == "bluefin"
          then 40
          else 30;
      };
    })
  homeCatalog.foundations;
  hardware = map (entry: entry // {bootc = entry.name == "generic-x86_64";}) homeCatalog.hardware;
  toAttrs = entries:
    builtins.listToAttrs (map (entry: {
        inherit (entry) name;
        value = entry;
      })
      entries);
  profiles = builtins.sort (a: b: a.order < b.order) (map (entry: {
      inherit (entry.profiles.generic-x86_64) name order;
      foundation = entry.name;
      hardware = "generic-x86_64";
    })
    foundations);
in
  homeCatalog
  // {
    inherit foundations hardware;
    foundationsByName = toAttrs foundations;
    hardwareByName = toAttrs hardware;
    profilesByName = toAttrs profiles;
    bootcHardwareNames = ["generic-x86_64"];
    profileOrder = map (entry: entry.name) profiles;
  }
