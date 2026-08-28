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
        next-x86_64 = {
          name = "bluefin-next";
          order = 10;
          tags = ["bluefin-next"];
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
        next-x86_64 = {
          name = "bluefin-dx-next";
          order = 20;
          tags = ["bluefin-dx-next"];
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
      imageHardware = ["generic-x86_64" "next-x86_64"];
    }
    {
      name = "next-x86_64";
      label = "Next kernel x86-64";
      order = 20;
      bootc = true;
      homeManager = false;
      imageHardware = [];
    }
    {
      name = "dell-xps-9350-intel";
      label = "Dell XPS 13 9350 (Intel)";
      order = 30;
      bootc = false;
      homeManager = true;
      imageHardware = ["generic-x86_64" "next-x86_64"];
    }
    {
      name = "framework-laptop";
      label = "Framework Laptop";
      order = 40;
      bootc = true;
      homeManager = false;
      imageHardware = [];
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
  packages = [
    {
      name = "hack-font";
      label = "Hack Nerd Font";
      description = "Hack font patched with Nerd Fonts glyphs";
      order = 10;
    }
    {
      name = "herdr";
      label = "Herdr";
      description = "Terminal process manager";
      order = 20;
    }
    {
      name = "jj";
      label = "Jujutsu";
      description = "Jujutsu version-control system (jj)";
      order = 30;
    }
    {
      name = "opencode";
      label = "OpenCode";
      description = "Open-source coding agent";
      order = 40;
    }
    {
      name = "uv";
      label = "uv";
      description = "Python package and project manager";
      order = 50;
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
          builtins.attrValues (
            builtins.mapAttrs (
              hardwareName: profile:
                profile
                // {
                  foundation = foundation.name;
                  hardware = hardwareName;
                  parent = null;
                }
            )
            foundation.profiles
          )
      )
      foundations
    )
  );
in {
  inherit foundations hardware packages roles;
  foundationsByName = toAttrs foundations;
  hardwareByName = toAttrs hardware;
  packagesByName = toAttrs packages;
  rolesByName = toAttrs roles;
  profilesByName = toAttrs profileEntries;
  foundationNames = names foundations;
  templateNames = map (foundation: foundation.template) foundations;
  bootcHardwareNames = names bootcHardware;
  homeHardwareNames = names homeHardware;
  packageNames = names packages;
  roleNames = names roles;
  homeCompatibleRoleNames = names (builtins.filter (role: role.homeCompatible) roles);
  profileOrder = names profileEntries;
}
