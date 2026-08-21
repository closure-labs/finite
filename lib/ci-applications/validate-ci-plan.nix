{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-ci-validate-plan";
  runtimeInputs = [pkgs.check-jsonschema];
  text = ''
    set -euo pipefail
    plan="''${1:?usage: purplefin-ci-validate-plan PLAN.json}"
    check-jsonschema --quiet --schemafile ${./ci-plan.schema.json} "''${plan}"
  '';
}
