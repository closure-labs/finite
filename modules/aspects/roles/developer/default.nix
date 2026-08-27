{den, ...}: {
  den.aspects.features.roles.developer = {
    includes = [den.aspects.features.capabilities.devops];
    homeManager.imports = [../../../../templates/home-manager/modules/aspects/roles/developer/home.nix];
  };
}
