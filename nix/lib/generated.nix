{
  lib,
  pkgs,
  profileOrder,
  profiles,
  version,
}: let
  profileNames = profileOrder;
  upstream = profiles.base.upstream;
  sourceRoot = ../..;
  pathKind = relativePath: let
    directory = builtins.dirOf relativePath;
    name = builtins.baseNameOf relativePath;
    entries = builtins.readDir (sourceRoot + "/${directory}");
  in
    entries.${name} or null;
  expandPath = relativePath:
    if !(builtins.pathExists (sourceRoot + "/${relativePath}"))
    then []
    else if pathKind relativePath == "directory"
    then
      map (path: lib.removePrefix "${toString sourceRoot}/" (toString path)) (
        lib.filesystem.listFilesRecursive (sourceRoot + "/${relativePath}")
      )
    else [relativePath];
  commonInputPaths = [
    ".containerignore"
    "VERSION"
    "bootc/config/independently-managed-rpms.list"
    "flake.lock"
    "flake.nix"
    "nix/flake-modules/outputs.nix"
    "nix/lib"
    "nix/profile-options.nix"
  ];
  rootInputPaths = [
    "Containerfile"
    "bootc/build/full.sh"
    "bootc/lib"
    "bootc/modules/base.sh"
    "bootc/overlays/base"
    "bootc/packages"
  ];
  derivedInputPaths = [
    "Containerfile.derived"
    "bootc/build/derived.sh"
    "bootc/lib"
  ];
  moduleInputPaths = module:
    [
      "bootc/modules/${module}.sh"
      "bootc/overlays/roles/${module}"
    ]
    ++ lib.optionals (module == "developer") [
      "bootc/components/devops"
      "bootc/lib/overlay.sh"
    ]
    ++ lib.optionals (module == "support") [
      "bootc/components/devops"
      "bootc/lib/overlay.sh"
      "bootc/overlays/roles/support"
    ]
    ++ lib.optionals (module == "hardware-dell-xps-9350-intel") [
      "bootc/lib/authselect-features.sh"
      "bootc/lib/dell-xps-9350-common.sh"
      "bootc/lib/hardware-security.sh"
      "bootc/overlays/hardware/dell-xps-9350-intel"
    ]
    ++ lib.optionals (lib.hasPrefix "hardware-" module && module != "hardware-dell-xps-9350-intel") [
      "bootc/lib/authselect-features.sh"
      "bootc/lib/hardware-security.sh"
    ];
  buildInput = name: let
    profile = profiles.${name};
    paths = lib.unique (
      commonInputPaths
      ++ (
        if profile.stage == "root"
        then rootInputPaths
        else derivedInputPaths
      )
      ++ lib.concatMap moduleInputPaths profile.deltaModules
    );
    files = lib.unique (lib.concatMap expandPath paths);
    evaluatedProfile = builtins.toJSON {
      inherit
        (profile)
        deltaModules
        hardware
        modules
        parent
        roles
        stage
        tags
        upstream
        ;
    };
    fileHashes =
      map (
        relativePath: "${relativePath}:${builtins.hashFile "sha256" (sourceRoot + "/${relativePath}")}"
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
    profileNames;
  catalog = {
    schema = 1;
    inherit upstream;
    inherit version;
    profiles =
      lib.mapAttrs (name: profile: {
        inherit
          (profile)
          hardware
          deltaModules
          modules
          parent
          roles
          stage
          tags
          ;
        inherit (profile) homeModules;
        imageBuilder = {
          blueprint = "installer/config/profiles/${name}.toml";
          inherit (profile.imageBuilder) filesystems rootFilesystem;
        };
      })
      profiles;
  };
  matrixFile = pkgs.writeText "image-matrix.json" (builtins.toJSON matrix + "\n");
  catalogFile = pkgs.writeText "profile-catalog.json" (builtins.toJSON catalog + "\n");
  upstreamFile = pkgs.writeText "upstream.json" (builtins.toJSON upstream + "\n");
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
    ${lib.concatStringsSep "\n" (
      map (name: ''
        cp ${blueprintFiles.${name}} "$out/installer/config/profiles/${name}.toml"
      '')
      profileNames
    )}
  ''
