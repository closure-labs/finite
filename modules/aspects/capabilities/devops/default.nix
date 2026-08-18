_: {
  den.aspects.features.capabilities.devops.bootc.purplefin.build = {
    steps = [
      {
        name = "devops";
        order = 200;
        script = ./apply.sh;
      }
    ];
    sourcePaths = [
      ./apply.sh
      ./manifests
      ./rootfs
    ];
  };
}
