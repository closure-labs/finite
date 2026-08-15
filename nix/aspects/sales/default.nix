{
  bootc = {lib, ...}: {
    purplefin.roles = lib.mkAfter ["sales"];
  };
  homeManager.home.sessionVariables.PURPLEFIN_ROLE_SALES = "1";
}
