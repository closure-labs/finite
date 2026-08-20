{
  buildCiPlan,
  classifyCi,
  pkgs,
  validateCiPlan,
}:
pkgs.writeShellApplication {
  name = "purplefin-ci-prepare";
  runtimeInputs = [pkgs.coreutils pkgs.jq classifyCi buildCiPlan validateCiPlan];
  text = ''
    set -euo pipefail
    runner_temp="''${RUNNER_TEMP:-''${TMPDIR:-/tmp}}"
    plan_file="$(mktemp "''${runner_temp}/purplefin-ci-plan.XXXXXX.json")"
    trap 'rm -f -- "''${plan_file}"' EXIT

    classification="$(purplefin-classify-ci)"
    plan="$(CLASSIFICATION="''${classification}" purplefin-ci-build-plan)"
    printf '%s\n' "''${plan}" >"''${plan_file}"
    purplefin-ci-validate-plan "''${plan_file}"

    if [[ -n "''${GITHUB_OUTPUT:-}" ]]; then
      printf 'plan=%s\n' "''${plan}" >>"''${GITHUB_OUTPUT}"
    else
      printf '%s\n' "''${plan}"
    fi
  '';
}
