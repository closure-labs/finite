{
  lib,
  profileEntities,
  profileHosts,
}: let
  profileNames = builtins.attrNames profileEntities;

  evalProfile = name: let
    entity = profileEntities.${name};
    host = profileHosts.${name};
  in
    lib.evalModules {
      modules = [
        ../modules/profiles/bootc-class.nix
        host.mainModule
        {
          finite = {
            profileName = name;
            inherit (entity) parent tags;
          };
        }
      ];
    };

  rawProfiles = lib.genAttrs profileNames (name: (evalProfile name).config.finite);
  orderResult =
    lib.lists.toposort (
      parentName: childName: rawProfiles.${childName}.parent == parentName
    )
    profileNames;
  profileOrder =
    orderResult.result or (throw "Finite profile error: parent cycle: ${
      lib.concatStringsSep " -> " orderResult.cycle
    }");

  roleOrder = [
    "developer"
    "sales"
    "trainer"
    "support"
    "executive"
    "it"
  ];
  roleIndex = role: lib.lists.findFirstIndex (candidate: candidate == role) 999 roleOrder;
  sortRoles = roles: lib.sort (left: right: roleIndex left < roleIndex right) roles;
  homeRoles = [
    "sales"
    "support"
    "trainer"
  ];
  sortSteps = lib.sort (
    left: right:
      if left.order == right.order
      then left.name < right.name
      else left.order < right.order
  );

  ensure = condition: message:
    if condition
    then true
    else throw "Finite profile error: ${message}";

  profiles =
    lib.mapAttrs (
      name: profile: let
        roles = sortRoles profile.roles;
        steps = sortSteps profile.build.steps;
        modules = map (step: step.name) steps;
      in
        assert ensure profile.base.enable "${name} does not include the base aspect";
        assert ensure (builtins.elem profile.foundation ["bluefin" "bluefin-dx"]) "${name} has an invalid foundation";
        assert ensure (profile.profileName == name) "${name} declares profileName=${profile.profileName}";
        assert ensure (profile.hardware != null) "${name} does not select hardware";
        assert ensure profile.upstream.preserve "${name} must preserve the complete upstream Bluefin base";
        assert ensure (profile.tags != []) "${name} is missing a registry tag";
        assert ensure (lib.length roles == lib.length (lib.unique roles)) "${name} repeats a role";
        assert ensure (lib.length modules == lib.length (lib.unique modules)) "${name} repeats a build step";
        assert ensure (lib.length profile.tags == lib.length (lib.unique profile.tags)) "${name} repeats a tag";
        assert ensure (roles == [] || profile.hardware != null) "${name} has roles without a hardware selection";
          profile
          // {
            inherit modules roles steps;
            sourcePaths = lib.unique profile.build.sourcePaths;
            homeModules = builtins.filter (role: builtins.elem role homeRoles) roles;
            tagsString = lib.concatStringsSep " " profile.tags;
          }
    )
    rawProfiles;

  validateParent = name: profile:
    if profile.parent == null
    then profile
    else let
      parent =
        profiles.${profile.parent}
            or (throw "Finite profile error: ${name} has unknown parent ${profile.parent}");
      deltaSteps =
        builtins.filter (
          step: !(builtins.elem step.name parent.modules)
        )
        profile.steps;
    in
      assert ensure (
        parent.hardware == null || parent.hardware == profile.hardware
      ) "${name} hardware differs from parent ${profile.parent}";
      assert ensure (
        lib.all (module: builtins.elem module profile.modules) parent.modules
      ) "${name} does not contain every build step inherited from ${profile.parent}";
      assert ensure (parent.upstream == profile.upstream) "${name} upstream differs from parent ${profile.parent}";
        profile
        // {
          inherit deltaSteps;
          deltaModules = map (step: step.name) deltaSteps;
          stage =
            if parent.hardware == null
            then "hardware"
            else "role";
        };

  validatedProfiles =
    lib.mapAttrs (
      name: profile:
        if profile.parent == null
        then
          profile
          // {
            deltaSteps = profile.steps;
            deltaModules = profile.modules;
            stage = "root";
          }
        else validateParent name profile
    )
    profiles;
  allTags = lib.concatMap (name: validatedProfiles.${name}.tags) profileOrder;
in
  assert ensure (
    lib.length allTags == lib.length (lib.unique allTags)
  ) "registry tags must be globally unique"; {
    order = profileOrder;
    profiles = validatedProfiles;
  }
