{
  determinateNixInstaller,
  determinateNixSelinuxPolicy,
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
      inherit (profiles.${name}) stage;
      build_input = buildInput name;
      profile = name;
      parent = profiles.${name}.parent;
      tags = profiles.${name}.tagsString;
    })
    profileOrder;
  catalog = {
    schema = 3;
    inherit version;
    inherit (profiles.base) upstream;
    profiles =
      lib.mapAttrs (_: profile: {
        inherit
          (profile)
          deltaModules
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
  matrixFile = pkgs.writeText "image-matrix.json" (builtins.toJSON matrix + "\n");
  catalogFile = pkgs.writeText "profile-catalog.json" (builtins.toJSON catalog + "\n");
  upstreamFile = pkgs.writeText "upstream.json" (builtins.toJSON profiles.base.upstream + "\n");
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
  pkgs.runCommand "purplefin-generated-${version}" {} ''
    mkdir -p "$out/bootc/generated" "$out/installer/config/profiles"
    cp ${matrixFile} "$out/bootc/generated/image-matrix.json"
    cp ${catalogFile} "$out/bootc/generated/profile-catalog.json"
    cp ${upstreamFile} "$out/bootc/generated/upstream.json"
    cp ${../sources/determinate-nix.json} "$out/bootc/generated/determinate-nix.json"
    cp ${determinateNixInstaller} "$out/bootc/generated/determinate-nix-installer"
    cp ${determinateNixSelinuxPolicy} "$out/bootc/generated/determinate-nix.pp"
    chmod 0555 "$out/bootc/generated/determinate-nix-installer"
    chmod 0444 "$out/bootc/generated/determinate-nix.pp"
    ${lib.concatStringsSep "\n" (
      map (name: ''
        cp ${blueprintFiles.${name}} "$out/installer/config/profiles/${name}.toml"
      '')
      profileOrder
    )}
  ''
