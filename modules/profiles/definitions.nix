{den, ...}: let
  inherit (den.aspects) features profiles;
in {
  den.aspects.profiles = {
    bluefin-generic.includes = [
      features.base
      features.upstreams.bluefin
      features.hardware.generic-x86_64
    ];
    bluefin-dell-xps-9350-intel.includes = [
      features.base
      features.upstreams.bluefin
      features.hardware.dell-xps-9350-intel
    ];
    bluefin-dx-generic.includes = [
      features.base
      features.upstreams.bluefin-dx
      features.hardware.generic-x86_64
    ];
    bluefin-dx-dell-xps-9350-intel.includes = [
      features.base
      features.upstreams.bluefin-dx
      features.hardware.dell-xps-9350-intel
    ];

    home-sales.includes = [features.base features.roles.sales];
    home-executive.includes = [features.base features.roles.executive];
    home-developer.includes = [features.base features.roles.developer];
    home-support.includes = [features.base features.roles.support];
    home-it.includes = [features.base features.roles.it];
    home-trainer.includes = [features.base features.roles.trainer];
    home-dale.includes = [
      features.base
      features.roles.sales
      features.roles.executive
      features.roles.developer
      features.roles.support
      features.roles.it
      features.roles.trainer
    ];
    home-elad.includes = [
      features.base
      features.roles.sales
      features.roles.executive
      features.roles.developer
      features.roles.support
      features.roles.it
      features.roles.trainer
    ];
  };

  purplefin.profiles = {
    bluefin-generic.tags = [
      "bluefin-generic"
      "base"
      "base-generic"
      "generic-x86_64"
      "base-generic-x86_64"
      "latest"
      "sales-generic"
      "executive-generic"
    ];
    bluefin-dell-xps-9350-intel.tags = [
      "bluefin-dell-xps-9350-intel"
      "base-dell-xps-9350-intel"
      "sales-dell-xps-9350-intel"
    ];
    bluefin-dx-generic.tags = [
      "bluefin-dx-generic"
      "developer-generic"
      "support-generic"
      "trainer-generic"
      "it-generic"
    ];
    bluefin-dx-dell-xps-9350-intel.tags = [
      "bluefin-dx-dell-xps-9350-intel"
      "support-dell-xps-9350-intel"
      "dale"
      "dell-xps-9350-intel"
    ];
  };

  purplefin.homeProfiles = {
    sales = {
      baseClass = "bluefin";
      roles = ["sales"];
      aspect = profiles.home-sales;
    };
    executive = {
      baseClass = "bluefin";
      roles = ["executive"];
      aspect = profiles.home-executive;
    };
    developer = {
      baseClass = "bluefin-dx";
      roles = ["developer"];
      aspect = profiles.home-developer;
    };
    support = {
      baseClass = "bluefin-dx";
      roles = ["support"];
      aspect = profiles.home-support;
    };
    it = {
      baseClass = "bluefin-dx";
      roles = ["it"];
      aspect = profiles.home-it;
    };
    trainer = {
      baseClass = "bluefin-dx";
      roles = ["trainer"];
      aspect = profiles.home-trainer;
    };
    dale = {
      baseClass = "bluefin-dx";
      hardware = ["dell-xps-9350-intel"];
      roles = ["sales" "executive" "developer" "support" "it" "trainer"];
      aspect = profiles.home-dale;
    };
    elad = {
      baseClass = "bluefin-dx";
      hardware = ["generic-x86_64"];
      roles = ["sales" "executive" "developer" "support" "it" "trainer"];
      aspect = profiles.home-elad;
    };
  };
}
