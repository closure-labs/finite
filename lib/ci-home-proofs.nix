# Compare the complete public aggregate while changing only proof scheduling.
{
  strategy ? "serial",
  preflight ? false,
  flake ? builtins.getFlake ("git+file://" + toString ../. + "?shallow=1"),
}: let
  inputs = flake.inputs // {self = flake;};
  lib = inputs.nixpkgs.lib;
  base = lib.evalModules {
    specialArgs = {inherit inputs;};
    modules = [(inputs.import-tree ../modules)];
  };
  evaluated = base.extendModules {
    specialArgs.outputDependencies =
      base._module.args.outputDependencies
      // {
        homeProofScheduler =
          if strategy == "serial"
          then _: result: result
          else builtins.parallel or (throw "Paired evaluation requires Determinate parallel-eval");
      };
  };
  system = (import ./project-policy.nix).platform.system;
  checks = evaluated.config.flake.packages.${system}.ci-checks;
in
  assert builtins.elem strategy ["serial" "paired"];
    if preflight
    then {
      revision = flake.rev;
      checkNames = checks.checkNames;
      proofCount = builtins.length checks.homeProofCases;
    }
    else
      builtins.deepSeq checks.drvPath {
        aggregateDrvPath = checks.drvPath;
        checkNames = checks.checkNames;
        cases = checks.homeProofCases;
        paths = checks.homeProofPaths;
      }
