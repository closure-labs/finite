# Lightweight CI entry point: reuse the root lock without evaluating Den or
# Home Manager merely to run registry, publication, or GitHub maintenance tools.
let
  lock = builtins.fromJSON (builtins.readFile ../flake.lock);
  lockedInput = name: builtins.fetchTree lock.nodes.${lock.nodes.${lock.root}.inputs.${name}}.locked;
  project = import ./project-policy.nix;
  system = project.platform.system;
  pkgs = import ./mk-pkgs.nix {nixpkgs = lockedInput "nixpkgs";} system;
  weeklyPkgs = import ./mk-pkgs.nix {nixpkgs = lockedInput "nixpkgs-weekly";} system;
  repository = import ./ci-applications/repository-operations.nix {
    inherit pkgs;
    cacheName = project.cache.name;
    secretspec = weeklyPkgs.secretspec;
    devenv = throw "The CI tools entry point does not provide the developer environment";
  };
  updates = import ./ci-applications/dependency-operations.nix {inherit pkgs;};
  shells = import ./ci-shells.nix {inherit pkgs;};
in {
  shell = shells.ci;
  release = shells.release;
  ci-github-actions-secrets = repository.githubActionsSecrets;
  ci-trusted-update = updates.trustedUpdate;
  ci-queue-dependabot = updates.queueDependabot;
}
