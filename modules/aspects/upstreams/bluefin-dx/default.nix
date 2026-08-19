{
  config,
  den,
  ...
}: {
  den.aspects.features.upstreams.bluefin-dx = {
    includes = [den.aspects.sources.bluefin-dx];
    bootc.purplefin.upstream = config.purplefin.sources.bluefinDx // {preserve = true;};
  };
}
