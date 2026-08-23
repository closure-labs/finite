{
  config,
  den,
  ...
}: {
  den.aspects.features.upstreams.bluefin = {
    includes = [den.aspects.sources.bluefin];
    bootc.finite = {
      foundation = "bluefin";
      upstream = config.finite.sources.bluefin // {preserve = true;};
    };
  };
}
