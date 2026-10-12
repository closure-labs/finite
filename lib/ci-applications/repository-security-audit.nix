{
  pkgs,
  policy,
}:
pkgs.writeShellApplication {
  name = "finite-repository-security-audit";
  runtimeInputs = with pkgs; [gh python3];
  text = ''
    export FINITE_SECURITY_POLICY=${policy}
    export FINITE_SECURITY_RULESET=${../../automation/github/policies/main-merge-queue.json}
    exec python3 ${../../scripts/ci/repository-security-audit.py} "$@"
  '';
}
