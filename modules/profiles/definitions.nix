{den, ...}: let
  inherit (den.aspects) features profiles;
in {
  den.aspects.profiles = {
    base.includes = [features.base];

    base-generic.includes = [
      profiles.base
      features.hardware.generic-x86_64
    ];

    base-dell-xps-9350-intel.includes = [
      profiles.base
      features.hardware.dell-xps-9350-intel
    ];

    sales-generic.includes = [
      profiles.base-generic
      features.roles.sales
    ];

    sales-dell-xps-9350-intel.includes = [
      profiles.base-dell-xps-9350-intel
      features.roles.sales
    ];

    support-generic.includes = [
      profiles.base-generic
      features.roles.support
    ];

    support-dell-xps-9350-intel.includes = [
      profiles.base-dell-xps-9350-intel
      features.roles.support
    ];

    dale.includes = [
      profiles.base-dell-xps-9350-intel
      features.roles.sales
      features.roles.trainer
      features.roles.support
    ];

    developer-generic.includes = [
      profiles.base-generic
      features.roles.developer
    ];

    trainer-generic.includes = [
      profiles.base-generic
      features.roles.trainer
    ];

    executive-generic.includes = [
      profiles.base-generic
      features.roles.executive
    ];

    it-generic.includes = [
      profiles.base-generic
      features.roles.it
    ];
  };

  purplefin.profiles = {
    base.tags = ["base"];

    base-generic = {
      parent = "base";
      tags = [
        "generic-x86_64"
        "latest"
        "base-generic-x86_64"
      ];
    };

    base-dell-xps-9350-intel = {
      parent = "base";
      tags = ["base-dell-xps-9350-intel"];
    };

    sales-generic = {
      parent = "base-generic";
      tags = ["sales-generic"];
    };

    sales-dell-xps-9350-intel = {
      parent = "base-dell-xps-9350-intel";
      tags = ["sales-dell-xps-9350-intel"];
    };

    support-generic = {
      parent = "base-generic";
      tags = ["support-generic"];
    };

    support-dell-xps-9350-intel = {
      parent = "base-dell-xps-9350-intel";
      tags = ["support-dell-xps-9350-intel"];
    };

    dale = {
      parent = "base-dell-xps-9350-intel";
      tags = [
        "dale"
        "dell-xps-9350-intel"
      ];
    };

    developer-generic = {
      parent = "base-generic";
      tags = ["developer-generic"];
    };

    trainer-generic = {
      parent = "base-generic";
      tags = ["trainer-generic"];
    };

    executive-generic = {
      parent = "base-generic";
      tags = ["executive-generic"];
    };

    it-generic = {
      parent = "base-generic";
      tags = ["it-generic"];
    };
  };
}
