{
  determinateNixInstaller,
  determinateNixSelinuxFileContexts,
  determinateNixSelinuxPolicy,
  home,
  lib,
  pkgs,
  profileOrder,
  profiles,
  version,
}: let
  sourceRoot = ./..;
  relativePath = path:
    lib.removePrefix "${toString sourceRoot}/" (toString path);
  pathKind = path: let
    directory = builtins.dirOf (toString path);
    name = builtins.baseNameOf (toString path);
    entries = builtins.readDir directory;
  in
    entries.${name} or null;
  expandPath = path:
    if !(builtins.pathExists path)
    then []
    else if pathKind path == "directory"
    then lib.filesystem.listFilesRecursive path
    else [path];
  commonSourcePaths = [
    (sourceRoot + "/.containerignore")
    (sourceRoot + "/VERSION")
    (sourceRoot + "/bootc/builder")
  ];
  buildInput = name: let
    profile = profiles.${name};
    containerfile =
      if profile.stage == "root"
      then sourceRoot + "/bootc/Containerfile"
      else sourceRoot + "/bootc/Containerfile.derived";
    paths = lib.unique (commonSourcePaths ++ [containerfile] ++ profile.sourcePaths);
    files = lib.unique (lib.concatMap expandPath paths);
    evaluatedProfile = builtins.toJSON {
      inherit
        (profile)
        deltaModules
        foundation
        hardware
        modules
        parent
        profileName
        roles
        stage
        tags
        upstream
        ;
      buildSteps =
        map (step: {
          inherit (step) name order;
          script = relativePath step.script;
        })
        profile.steps;
    };
    fileHashes =
      map (
        path: "${relativePath path}:${builtins.hashFile "sha256" path}"
      )
      files;
  in
    builtins.hashString "sha256" (lib.concatStringsSep "\n" ([evaluatedProfile] ++ fileHashes));
  matrix =
    map (name: {
      inherit (profiles.${name}) foundation hardware stage;
      build_input = buildInput name;
      profile = name;
      parent = profiles.${name}.parent;
      tags = profiles.${name}.tagsString;
      upstream = profiles.${name}.upstream;
    })
    profileOrder;
  catalog = {
    schema = 4;
    inherit version;
    upstreams = lib.mapAttrs (_: profile: profile.upstream) profiles;
    profiles =
      lib.mapAttrs (_: profile: {
        inherit
          (profile)
          deltaModules
          foundation
          hardware
          modules
          parent
          roles
          stage
          tags
          ;
        buildSteps =
          map (step: {
            inherit (step) name order;
            script = relativePath step.script;
          })
          profile.steps;
        deltaBuildSteps =
          map (step: {
            inherit (step) name order;
            script = relativePath step.script;
          })
          profile.deltaSteps;
        inherit (profile) homeModules;
        imageBuilder = {
          blueprint = "installer/config/profiles/${profile.profileName}.toml";
          inherit (profile.imageBuilder) filesystems rootFilesystem;
        };
      })
      profiles;
  };
  roleNames = lib.sort (left: right: home.roles.${left}.order < home.roles.${right}.order) (builtins.attrNames home.roles);
  homeCatalog = {
    schema = 2;
    inherit version;
    foundations =
      lib.mapAttrs (_: foundation: {
        inherit (foundation) name profiles template;
        hardware = builtins.attrNames foundation.profiles;
        roles = roleNames;
      })
      home.foundations;
    hardware =
      lib.mapAttrs (_: hardware: {
        inherit (hardware) label name;
      })
      home.hardware;
    roles =
      lib.mapAttrs (_: role: {
        inherit (role) label name order;
        foundations = builtins.attrNames home.foundations;
      })
      home.roles;
    compatibility =
      lib.mapAttrs (_: foundation: {
        hardware = builtins.attrNames foundation.profiles;
        roles = roleNames;
      })
      home.foundations;
  };
  matrixFile = pkgs.writeText "image-matrix.json" (builtins.toJSON matrix + "\n");
  catalogFile = pkgs.writeText "profile-catalog.json" (builtins.toJSON catalog + "\n");
  homeCatalogFile = pkgs.writeText "home-profile-catalog.json" (builtins.toJSON homeCatalog + "\n");
  upstreamFile = pkgs.writeText "upstreams.json" (builtins.toJSON catalog.upstreams + "\n");
  toml = pkgs.formats.toml {};
  blueprintFiles =
    lib.mapAttrs (
      name: profile:
        toml.generate "${name}.toml" {
          customizations.filesystem = profile.imageBuilder.filesystems;
        }
    )
    profiles;
in
  pkgs.runCommand "finite-generated-${version}" {} ''
    mkdir -p "$out/bootc/generated" "$out/installer/config/profiles"
    cp ${matrixFile} "$out/bootc/generated/image-matrix.json"
    cp ${catalogFile} "$out/bootc/generated/profile-catalog.json"
    cp ${homeCatalogFile} "$out/bootc/generated/home-profile-catalog.json"
    cp ${upstreamFile} "$out/bootc/generated/upstreams.json"
    cp ${../sources/determinate-nix.json} "$out/bootc/generated/determinate-nix.json"
    cp ${determinateNixInstaller} "$out/bootc/generated/determinate-nix-installer"
    cp ${determinateNixSelinuxPolicy} "$out/bootc/generated/determinate-nix.pp"
    cp ${determinateNixSelinuxFileContexts} "$out/bootc/generated/nix.fc"
    chmod 0555 "$out/bootc/generated/determinate-nix-installer"
    chmod 0444 "$out/bootc/generated/determinate-nix.pp"
    chmod 0444 "$out/bootc/generated/nix.fc"
    ${lib.concatStringsSep "\n" (
      lib.concatMap (
        name:
          map (installerName: ''
            cp ${blueprintFiles.${name}} "$out/installer/config/profiles/${installerName}.toml"
          '')
          (lib.unique ([name] ++ profiles.${name}.tags))
      )
      profileOrder
    )}
  ''
