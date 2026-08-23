{
  config,
  den,
  ...
}: {
  den.aspects.features.upstreams.bluefin-dx = {
    includes = [den.aspects.sources.bluefin-dx];
    bootc.finite = {
      foundation = "bluefin-dx";
      upstream = config.finite.sources.bluefinDx // {preserve = true;};
    };
  };
}
