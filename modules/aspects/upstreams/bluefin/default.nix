{
  config,
  den,
  ...
}: {
  den.aspects.features.upstreams.bluefin = {
    includes = [den.aspects.sources.bluefin];
    bootc.purplefin.upstream = config.purplefin.sources.bluefin // {preserve = true;};
  };
}
