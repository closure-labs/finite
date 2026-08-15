{
  bootc = {lib, ...}: {
    purplefin.roles = lib.mkAfter ["support"];
  };
  homeManager.home.sessionVariables.PURPLEFIN_ROLE_SUPPORT = "1";
}
