# Lightweight CI entry point: reuse the root lock without evaluating Den or
# Home Manager merely to run registry, publication, or GitHub maintenance tools.
let
  lock = builtins.fromJSON (builtins.readFile ../flake.lock);
  lockedInput = name: builtins.fetchTree lock.nodes.${lock.nodes.${lock.root}.inputs.${name}}.locked;
  project = import ./project-policy.nix;
  system = project.platform.system;
  pkgs = import ./mk-pkgs.nix {nixpkgs = lockedInput "nixpkgs";} system;
  secretspec = import ./secretspec.nix {inherit pkgs;};
  repository = import ./ci-applications/repository-operations.nix {
    inherit pkgs secretspec;
    cacheName = project.cache.name;
  };
  updates = import ./ci-applications/dependency-operations.nix {inherit pkgs;};
  shells = import ./ci-shells.nix {inherit pkgs;};
in {
  shell = shells.ci;
  image-tools = shells.imageTools;
  scanner-tools = shells.scannerTools;
  cache-tools = pkgs.buildEnv {
    name = "finite-ci-cache-tools";
    paths = [pkgs.cachix];
    pathsToLink = ["/bin"];
  };
  secretspec-tools = secretspec;
  ci-secrets-run = repository.ciSecretsRun;
  ci-secrets-options = repository.ciSecretsOptions;
  release = shells.release;
  ci-github-actions-secrets = repository.githubActionsSecrets;
  ci-repository-security-audit = import ./ci-applications/repository-security-audit.nix {
    inherit pkgs;
    policy = ../automation/github/repository-security.json;
  };
  ci-source-update = import ./ci-applications/update-determinate-nix.nix {inherit pkgs;};
  ci-lock-validate = import ./ci-applications/validate-locks.nix {inherit pkgs;};
  ci-trusted-update = updates.trustedUpdate;
  ci-queue-dependabot = updates.queueDependabot;
}
