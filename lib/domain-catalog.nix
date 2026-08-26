let
  foundations = [
    {
      name = "bluefin";
      label = "Bluefin";
      order = 10;
      template = "home-bluefin";
      profiles = {
        generic-x86_64 = {
          name = "bluefin-generic";
          order = 40;
          tags = ["bluefin-generic" "latest"];
        };
        dell-xps-9350-intel = {
          name = "bluefin-dell-xps-9350-intel";
          order = 10;
          tags = ["bluefin-dell-xps-9350-intel"];
        };
      };
    }
    {
      name = "bluefin-dx";
      label = "Bluefin DX";
      order = 20;
      template = "home-bluefin-dx";
      profiles = {
        generic-x86_64 = {
          name = "bluefin-dx-generic";
          order = 30;
          tags = ["bluefin-dx-generic"];
        };
        dell-xps-9350-intel = {
          name = "bluefin-dx-dell-xps-9350-intel";
          order = 20;
          tags = ["bluefin-dx-dell-xps-9350-intel"];
        };
      };
    }
  ];
  hardware = [
    {
      name = "generic-x86_64";
      label = "Generic x86-64";
      order = 10;
      bootc = true;
      homeManager = true;
    }
    {
      name = "dell-xps-9350-intel";
      label = "Dell XPS 13 9350 (Intel)";
      order = 20;
      bootc = true;
      homeManager = true;
    }
    {
      name = "framework-laptop";
      label = "Framework Laptop";
      order = 30;
      bootc = true;
      homeManager = false;
    }
  ];
  roles = [
    {
      name = "developer";
      label = "Developer";
      order = 10;
      homeCompatible = false;
    }
    {
      name = "sales";
      label = "Sales";
      order = 20;
      homeCompatible = true;
    }
    {
      name = "trainer";
      label = "Trainer";
      order = 30;
      homeCompatible = true;
    }
    {
      name = "support";
      label = "Support";
      order = 40;
      homeCompatible = true;
    }
    {
      name = "executive";
      label = "Executive";
      order = 50;
      homeCompatible = false;
    }
    {
      name = "it";
      label = "IT";
      order = 60;
      homeCompatible = false;
    }
  ];
  names = entries: map (entry: entry.name) entries;
  toAttrs = entries:
    builtins.listToAttrs (
      map (entry: {
        inherit (entry) name;
        value = entry;
      })
      entries
    );
  homeHardware = builtins.filter (entry: entry.homeManager) hardware;
  bootcHardware = builtins.filter (entry: entry.bootc) hardware;
  profileEntries = builtins.sort (left: right: left.order < right.order) (
    builtins.concatLists (
      map (
        foundation:
          map (
            hardwareName: let
              profile = foundation.profiles.${hardwareName};
            in
              profile
              // {
                foundation = foundation.name;
                hardware = hardwareName;
                parent = null;
              }
          )
          (names homeHardware)
      )
      foundations
    )
  );
in {
  inherit foundations hardware roles;
  foundationsByName = toAttrs foundations;
  hardwareByName = toAttrs hardware;
  rolesByName = toAttrs roles;
  profilesByName = toAttrs profileEntries;
  foundationNames = names foundations;
  templateNames = map (foundation: foundation.template) foundations;
  bootcHardwareNames = names bootcHardware;
  homeHardwareNames = names homeHardware;
  roleNames = names roles;
  homeCompatibleRoleNames = names (builtins.filter (role: role.homeCompatible) roles);
  profileOrder = names profileEntries;
}
