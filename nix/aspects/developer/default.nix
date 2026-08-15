{
  bootc = {lib, ...}: {
    purplefin.roles = lib.mkAfter ["developer"];
  };
}
