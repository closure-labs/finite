{
  buildCiPlan,
  classifyCi,
  pkgs,
  validateCiPlan,
}:
pkgs.writeShellApplication {
  name = "finite-ci-prepare";
  runtimeInputs = [pkgs.coreutils pkgs.jq classifyCi buildCiPlan validateCiPlan];
  text = ''
    set -euo pipefail
    runner_temp="''${RUNNER_TEMP:-''${TMPDIR:-/tmp}}"
    plan_file="$(mktemp "''${runner_temp}/finite-ci-plan.XXXXXX.json")"
    trap 'rm -f -- "''${plan_file}"' EXIT

    classification="$(finite-classify-ci)"
    plan="$(CLASSIFICATION="''${classification}" finite-ci-build-plan)"
    printf '%s\n' "''${plan}" >"''${plan_file}"
    finite-ci-validate-plan "''${plan_file}"

    if [[ -n "''${GITHUB_OUTPUT:-}" ]]; then
      printf 'plan=%s\n' "''${plan}" >>"''${GITHUB_OUTPUT}"
    else
      printf '%s\n' "''${plan}"
    fi
  '';
}
