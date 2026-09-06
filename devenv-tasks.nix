{pkgs, ...}: let
  runLeaf = package: command: arguments: ''
    FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --accept-flake-config "path:$DEVENV_ROOT#${package}" \
        -c ${command} ${arguments}
  '';
in {
  packages = with pkgs; [actionlint git jq shellcheck zizmor];

  tasks = {
    "ci:check:flake" = {
      exec = runLeaf "ci-check" "finite-ci-check" "--no-write-lock-file";
      execIfModified = ["."];
    };
    "ci:check".after = ["ci:check:flake"];

    "automation:update-locks".exec = runLeaf "ci-update-locks" "finite-update-locks" "";
    "automation:validate-locks".exec = runLeaf "ci-lock-validate" "finite-ci-validate-locks" "";
    "automation:fix-hashes".exec = runLeaf "ci-fix-nix-hashes" "finite-fix-nix-hashes" "";
    "automation:trusted-update".exec = runLeaf "ci-trusted-update" "finite-trusted-update" "";
    "automation:queue".exec = runLeaf "ci-queue-dependabot" "finite-queue-dependabot" "";
  };
}
