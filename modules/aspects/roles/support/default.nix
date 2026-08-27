{den, ...}: {
  den.aspects.features.roles.support = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager.imports = [../../../../templates/home-manager/modules/aspects/roles/support/home.nix];
  };
}
