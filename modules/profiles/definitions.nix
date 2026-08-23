{den, ...}: let
  inherit (den.aspects) features;
in {
  den.aspects.profiles = {
    bluefin-generic.includes = [features.base features.upstreams.bluefin features.hardware.generic-x86_64];
    bluefin-dell-xps-9350-intel.includes = [features.base features.upstreams.bluefin features.hardware.dell-xps-9350-intel];
    bluefin-dx-generic.includes = [features.base features.upstreams.bluefin-dx features.hardware.generic-x86_64];
    bluefin-dx-dell-xps-9350-intel.includes = [features.base features.upstreams.bluefin-dx features.hardware.dell-xps-9350-intel];
  };

  finite.profiles = {
    bluefin-generic.tags = ["bluefin-generic" "latest"];
    bluefin-dell-xps-9350-intel.tags = ["bluefin-dell-xps-9350-intel"];
    bluefin-dx-generic.tags = ["bluefin-dx-generic"];
    bluefin-dx-dell-xps-9350-intel.tags = ["bluefin-dx-dell-xps-9350-intel"];
  };

  finite.home = {
    foundations = {
      bluefin = {
        template = "home-bluefin";
        profiles = {
          generic-x86_64 = "bluefin-generic";
          dell-xps-9350-intel = "bluefin-dell-xps-9350-intel";
        };
      };
      bluefin-dx = {
        template = "home-bluefin-dx";
        profiles = {
          generic-x86_64 = "bluefin-dx-generic";
          dell-xps-9350-intel = "bluefin-dx-dell-xps-9350-intel";
        };
      };
    };
    hardware = {
      generic-x86_64 = {
        label = "Generic x86-64";
        aspect = features.hardware.generic-x86_64;
      };
      dell-xps-9350-intel = {
        label = "Dell XPS 13 9350 (Intel)";
        aspect = features.hardware.dell-xps-9350-intel;
      };
    };
    roles = {
      developer = {
        label = "Developer";
        order = 10;
        aspect = features.roles.developer;
      };
      sales = {
        label = "Sales";
        order = 20;
        aspect = features.roles.sales;
      };
      trainer = {
        label = "Trainer";
        order = 30;
        aspect = features.roles.trainer;
      };
      support = {
        label = "Support";
        order = 40;
        aspect = features.roles.support;
      };
      executive = {
        label = "Executive";
        order = 50;
        aspect = features.roles.executive;
      };
      it = {
        label = "IT";
        order = 60;
        aspect = features.roles.it;
      };
    };
  };
}
