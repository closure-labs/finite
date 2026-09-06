{
  cacheName,
  devenv,
  pkgs,
  secretspec,
}: let
  repository = import ./ci-applications/repository-operations.nix {
    inherit cacheName devenv pkgs secretspec;
  };
  updates = import ./ci-applications/dependency-operations.nix {inherit pkgs;};
in
  repository
  // updates
  // {
    sourceUpdate = import ./ci-applications/update-determinate-nix.nix {inherit pkgs;};
    updateLocks = import ./ci-applications/update-locks.nix {inherit devenv pkgs;};
    updateHomeRelease = import ./ci-applications/update-home-release.nix {inherit pkgs;};
    validateLocks = import ./ci-applications/validate-locks.nix {inherit pkgs;};
    repositorySecurityAudit = import ./ci-applications/repository-security-audit.nix {
      inherit pkgs;
      policy = ../automation/github/repository-security.json;
    };
  }
