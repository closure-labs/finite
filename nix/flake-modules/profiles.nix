{den, ...}: let
  inherit (den.aspects) features;
in {
  den.aspects.profiles = {
    base = {
      includes = [features.base];
      bootc.purplefin = {
        profileName = "base";
        tags = ["base"];
      };
    };

    base-generic = {
      includes = [
        features.base
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "base-generic";
        parent = "base";
        tags = [
          "generic-x86_64"
          "latest"
          "base-generic-x86_64"
        ];
      };
    };

    base-dell-xps-9350-intel = {
      includes = [
        features.base
        features.hardware-dell-xps-9350-intel
      ];
      bootc.purplefin = {
        profileName = "base-dell-xps-9350-intel";
        parent = "base";
        tags = ["base-dell-xps-9350-intel"];
      };
    };

    sales-generic = {
      includes = [
        features.base
        features.sales
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "sales-generic";
        parent = "base-generic";
        tags = ["sales-generic"];
      };
    };

    sales-dell-xps-9350-intel = {
      includes = [
        features.base
        features.sales
        features.hardware-dell-xps-9350-intel
      ];
      bootc.purplefin = {
        profileName = "sales-dell-xps-9350-intel";
        parent = "base-dell-xps-9350-intel";
        tags = ["sales-dell-xps-9350-intel"];
      };
    };

    support-generic = {
      includes = [
        features.base
        features.support
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "support-generic";
        parent = "base-generic";
        tags = ["support-generic"];
      };
    };

    support-dell-xps-9350-intel = {
      includes = [
        features.base
        features.support
        features.hardware-dell-xps-9350-intel
      ];
      bootc.purplefin = {
        profileName = "support-dell-xps-9350-intel";
        parent = "base-dell-xps-9350-intel";
        tags = ["support-dell-xps-9350-intel"];
      };
    };

    dale = {
      includes = [
        features.base
        features.sales
        features.trainer
        features.support
        features.hardware-dell-xps-9350-intel
      ];
      bootc.purplefin = {
        profileName = "dale";
        parent = "base-dell-xps-9350-intel";
        tags = [
          "dale"
          "dell-xps-9350-intel"
        ];
      };
    };

    developer-generic = {
      includes = [
        features.base
        features.developer
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "developer-generic";
        parent = "base-generic";
        tags = ["developer-generic"];
      };
    };

    trainer-generic = {
      includes = [
        features.base
        features.trainer
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "trainer-generic";
        parent = "base-generic";
        tags = ["trainer-generic"];
      };
    };

    executive-generic = {
      includes = [
        features.base
        features.executive
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "executive-generic";
        parent = "base-generic";
        tags = ["executive-generic"];
      };
    };

    it-generic = {
      includes = [
        features.base
        features.it
        features.hardware-generic-x86_64
      ];
      bootc.purplefin = {
        profileName = "it-generic";
        parent = "base-generic";
        tags = ["it-generic"];
      };
    };
  };
}
