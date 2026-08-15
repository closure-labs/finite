{inputs, ...}: {
  imports = [inputs.den.flakeModule];

  den.classes.bootc.description = "Purplefin bootc image composition";

  den.aspects.features = {
    base = import ../aspects/base;
    hardware-generic-x86_64 = import ../aspects/hardware-generic-x86_64;
    hardware-dell-xps-9350-intel = import ../aspects/hardware-dell-xps-9350-intel;
    developer = import ../aspects/developer;
    executive = import ../aspects/executive;
    it = import ../aspects/it;
    sales = import ../aspects/sales;
    support = import ../aspects/support;
    trainer = import ../aspects/trainer;
  };
}
