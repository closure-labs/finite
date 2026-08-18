{inputs, ...}: {
  imports = [inputs.den.flakeModule];

  den.classes.bootc.description = "Purplefin bootc image composition";
}
