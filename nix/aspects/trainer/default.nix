{
  bootc = {lib, ...}: {
    purplefin.roles = lib.mkAfter ["trainer"];
  };
  homeManager.home.sessionVariables.PURPLEFIN_ROLE_TRAINER = "1";
}
