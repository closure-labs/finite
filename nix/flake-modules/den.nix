{inputs, ...}: {
  imports = [inputs.den.flakeModule];

  den.classes.bootc.description = "Purplefin bootc image composition";

  den.aspects.features = {
    base = {
      bootc = ../modules/base.nix;
      homeManager = ../home/common.nix;
    };

    hardware-generic-x86_64.bootc = ../modules/hardware/generic-x86_64.nix;
    hardware-dell-xps-9350-intel.bootc = ../modules/hardware/dell-xps-9350-intel.nix;

    developer.bootc = ../modules/roles/developer.nix;
    executive.bootc = ../modules/roles/executive.nix;
    it.bootc = ../modules/roles/it.nix;
    sales = {
      bootc = ../modules/roles/sales.nix;
      homeManager = ../home/roles/sales.nix;
    };
    support = {
      bootc = ../modules/roles/support.nix;
      homeManager = ../home/roles/support.nix;
    };
    trainer = {
      bootc = ../modules/roles/trainer.nix;
      homeManager = ../home/roles/trainer.nix;
    };
  };
}
