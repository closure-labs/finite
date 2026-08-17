{inputs, ...}: {
  imports = [inputs.den.flakeModule];

  den.classes.bootc.description = "Purplefin bootc image composition";
  den.classes.repository.description = "Purplefin repository tooling and validation";
}
