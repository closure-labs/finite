{system}: let
  pin = builtins.fromJSON (builtins.readFile ../sources/native-bootc.json);
  # The verifier authenticates the output bytes, including linked Nix store
  # paths. The project's weekly input updates must not change those bytes.
  pkgs = import (builtins.fetchTree pin.nixpkgs) {inherit system;};
in
  pkgs.rustPlatform.buildRustPackage {
    pname = "finite-native-bootc-importer";
    inherit (pin) version cargoHash;
    src = pkgs.fetchFromGitHub {
      owner = "bootc-dev";
      repo = "bootc";
      rev = pin.revision;
      hash = pin.sourceHash;
    };
    nativeBuildInputs = [pkgs.pkg-config pkgs.rustPlatform.bindgenHook];
    buildInputs = with pkgs; [libz zstd openssl glib ostree-full fuse3 libselinux pcre2];
    # selinux-sys exposes raw bindings without adding the native library to
    # bootc's final link command; keep this explicit in the portable tool build.
    NIX_LDFLAGS = "-lselinux";
    cargoBuildFlags = ["-p" "bootc"];
    # Preserve the crate and codegen settings used for the reviewed binary.
    enableParallelBuilding = false;
    CARGO_INCREMENTAL = "0";
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS = "1";
    # Bundled PCRE2 passes an unsorted read_dir to its static archive builder.
    # Use the shared library from the same pinned Nix package set.
    PCRE2_SYS_STATIC = "0";
    preBuild = ''
      pkg-config --exists libpcre2-8
    '';
    postInstall = ''
      readelf -Wd "$out/bin/bootc" | grep -F 'Shared library: [libpcre2-8.so.0]' >/dev/null
    '';
    # zlink-macros 0.7.0 emits the Varlink stream enum by iterating a seeded
    # HashMap. Sort the items before generating Rust tokens. The separately
    # built Fedora runtime and its OCI import path do not use this patch.
    postPatch = ''
      zlink_codegen=("$cargoDepsCopy"/source-registry-*/zlink-macros-0.7.0/src/service/codegen.rs)
      test "''${#zlink_codegen[@]}" -eq 1
      substituteInPlace "''${zlink_codegen[0]}" --replace-fail \
        '    for (type_str, variant_name) in &type_map {' \
        $'    let mut type_variant_pairs: Vec<_> = type_map.iter().collect();\n    type_variant_pairs.sort_unstable_by_key(|(type_str, _)| *type_str);\n    for (type_str, variant_name) in type_variant_pairs {'
    '';
    # Full upstream tests exercise mounts/installers. Validate this tool against
    # the Fedora importer and final signed OCI fixtures in the sealing checks.
    doCheck = false;
    meta.mainProgram = "bootc";
  }
