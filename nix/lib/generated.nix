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
    ".github/workflows/build-profile.yml"
    ".github/workflows/build.yml"
    "VERSION"
    "build_files/independently-managed-rpms.list"
    "build_files/select-ostree-linux.sh"
    "flake.lock"
    "flake.nix"
    "nix/flake-modules/den.nix"
    "nix/flake-modules/outputs.nix"
    "nix/home/common.nix"
    "nix/lib"
    "nix/modules/base.nix"
    "nix/modules/profile-options.nix"
  ];
  rootInputPaths = [
    "Containerfile"
    "build_files/bitwarden-cli.env"
    "build_files/bitwarden-cli.spec"
    "build_files/build.sh"
    "build_files/install-bitwarden-cli-rpm.sh"
    "build_files/lib"
    "manifests"
    "system_files"
  ];
  derivedInputPaths = [
    "Containerfile.derived"
    "build_files/build-derived.sh"
    "build_files/lib"
  ];
  moduleInputPaths = module:
    [
      "build_files/modules/${module}.sh"
      "nix/modules/roles/${module}.nix"
      "nix/home/roles/${module}.nix"
      "profile_files/modules/${module}"
    ]
    ++ lib.optionals (module == "developer") [
      "build_files/profiles/components/devops.sh"
      "build_files/profiles/lib/role-common.sh"
      "build_files/profiles/roles/development.sh"
      "profile_files/components/devops"
    ]
    ++ lib.optionals (module == "support") [
      "build_files/profiles/components/devops.sh"
      "build_files/profiles/lib/role-common.sh"
      "build_files/profiles/roles/support.sh"
      "profile_files/components/devops"
      "profile_files/roles/support"
    ]
    ++ lib.optionals (module == "hardware-dell-xps-9350-intel") [
      "build_files/install-libcamera-ov02c10-ipa.sh"
      "build_files/libcamera"
      "build_files/profiles/dell-xps-9350-intel.sh"
      "build_files/profiles/lib/authselect-features.sh"
      "build_files/profiles/lib/dell-xps-9350-common.sh"
      "build_files/profiles/lib/hardware-security.sh"
      "nix/modules/hardware/dell-xps-9350-intel.nix"
      "profile_files/dell-xps-9350-intel"
    ]
    ++ lib.optionals (lib.hasPrefix "hardware-" module && module != "hardware-dell-xps-9350-intel") [
      "build_files/profiles/lib/authselect-features.sh"
      "build_files/profiles/lib/hardware-security.sh"
      "nix/modules/hardware/${lib.removePrefix "hardware-" module}.nix"
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
    mkdir -p "$out/build_files" "$out/installer/config/profiles"
    cp ${matrixFile} "$out/build_files/image-matrix.json"
    cp ${catalogFile} "$out/build_files/profile-catalog.json"
    cp ${upstreamFile} "$out/build_files/upstream.json"
    ${lib.concatStringsSep "\n" (
      map (name: ''
        cp ${blueprintFiles.${name}} "$out/installer/config/profiles/${name}.toml"
      '')
      profileNames
    )}
  ''
