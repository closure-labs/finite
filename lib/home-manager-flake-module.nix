# Compatibility adapter for consumers of Finite's former Home Manager module.
{foundation}: {
  config,
  lib,
  ...
}: {
  options.finite.homeProfile = lib.mkOption {
    type = lib.types.attrs;
    description = "Foundation profile; validated by Foundation's constructor.";
  };
  options.flake = lib.mkOption {
    type = lib.types.lazyAttrsOf lib.types.raw;
    default = {};
  };
  config.flake.homeConfigurations.${config.finite.homeProfile.identity.username} =
    foundation.lib.mkHomeConfiguration {profile = config.finite.homeProfile;};
}
