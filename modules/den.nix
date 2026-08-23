{inputs, ...}: {
  imports = [inputs.den.flakeModule];

  den.classes.bootc.description = "Finite bootc image composition";
}
