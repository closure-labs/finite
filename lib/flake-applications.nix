{
  devenv,
  pkgs,
  secretspec,
}: let
  repository = import ./ci-applications/repository-operations.nix {
    inherit devenv pkgs secretspec;
  };
  updates = import ./ci-applications/dependency-operations.nix {inherit pkgs;};
in
  repository
  // updates
  // {
    sourceUpdate = import ./ci-applications/update-determinate-nix.nix {inherit pkgs;};
    updateLocks = import ./ci-applications/update-locks.nix {inherit devenv pkgs;};
    updateFoundation = import ./ci-applications/update-foundation.nix {inherit pkgs;};
    validateLocks = import ./ci-applications/validate-locks.nix {inherit pkgs;};
    repositorySecurityAudit = import ./ci-applications/repository-security-audit.nix {
      inherit pkgs;
      policy = ../automation/github/repository-security.json;
    };
  }
