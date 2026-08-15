{
  lib,
  den,
}: let
  profileNames = [
    "base"
    "base-generic"
    "base-dell-xps-9350-intel"
    "sales-generic"
    "sales-dell-xps-9350-intel"
    "support-generic"
    "support-dell-xps-9350-intel"
    "dale"
    "developer-generic"
    "trainer-generic"
    "executive-generic"
    "it-generic"
  ];

  evalProfile = name:
    lib.evalModules {
      modules = [
        ../profile-options.nix
        (den.lib.aspects.resolve "bootc" den.aspects.profiles.${name})
      ];
    };

  rawProfiles = lib.genAttrs profileNames (name: (evalProfile name).config.purplefin);

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

  ensure = condition: message:
    if condition
    then true
    else throw "Purplefin profile error: ${message}";

  profiles =
    lib.mapAttrs (
      name: profile:
        assert ensure profile.base.enable "${name} does not import the base module";
        assert ensure (profile.profileName == name) "${name} declares profileName=${profile.profileName}";
        assert ensure (name == "base" || profile.hardware != null) "${name} does not select hardware";
        assert ensure (
          name != "base" || profile.hardware == null
        ) "the common base must not select hardware";
        assert ensure profile.upstream.preserve "${name} must preserve the complete upstream Bluefin base";
        assert ensure (profile.tags != []) "${name} is missing a registry tag";
        assert ensure (
          lib.length profile.roles == lib.length (lib.unique profile.roles)
        ) "${name} repeats a role";
        assert ensure (
          lib.length profile.tags == lib.length (lib.unique profile.tags)
        ) "${name} repeats a tag";
        assert ensure (
          (profile.parent == null) == (name == "base")
        ) "only the common base may omit a parent";
        assert ensure (
          profile.roles == [] || profile.hardware != null
        ) "${name} has roles without a hardware selection"; let
          orderedRoles = sortRoles profile.roles;
        in
          profile
          // {
            roles = orderedRoles;
            homeModules = builtins.filter (role: builtins.elem role homeRoles) orderedRoles;
            modules = ["base"] ++ orderedRoles ++ lib.optional (profile.hardware != null) profile.hardware;
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
            or (throw "Purplefin profile error: ${name} has unknown parent ${profile.parent}");
    in
      assert ensure (
        parent.hardware == null || parent.hardware == profile.hardware
      ) "${name} hardware differs from parent ${profile.parent}";
      assert ensure (lib.all (
          module: builtins.elem module profile.modules
        )
        parent.modules) "${name} does not contain every module inherited from ${profile.parent}";
      assert ensure (
        parent.upstream == profile.upstream
      ) "${name} upstream differs from parent ${profile.parent}";
        profile
        // {
          deltaModules = builtins.filter (module: !(builtins.elem module parent.modules)) profile.modules;
          stage =
            if parent.hardware == null
            then "hardware"
            else "role";
        };

  validatedProfiles =
    lib.mapAttrs validateParent profiles
    // {
      base =
        profiles.base
        // {
          deltaModules = profiles.base.modules;
          stage = "root";
        };
    };
  allTags = lib.concatMap (name: validatedProfiles.${name}.tags) profileNames;
in
  assert ensure (
    lib.length allTags == lib.length (lib.unique allTags)
  ) "registry tags must be globally unique"; {
    order = profileNames;
    profiles = validatedProfiles;
  }
