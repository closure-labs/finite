{
  bootc = {lib, ...}: {
    purplefin.roles = lib.mkAfter ["executive"];
  };
}
