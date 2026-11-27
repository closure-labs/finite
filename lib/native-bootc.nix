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
    buildInputs = with pkgs; [libz zstd openssl glib ostree-full fuse3 libselinux];
    # selinux-sys exposes raw bindings without adding the native library to
    # bootc's final link command; keep this explicit in the portable tool build.
    NIX_LDFLAGS = "-lselinux";
    cargoBuildFlags = ["-p" "bootc"];
    # Keep the executable reproducible across separate signing and verification
    # runners. Parallel crate/codegen scheduling yielded several ELF digests.
    enableParallelBuilding = false;
    CARGO_INCREMENTAL = "0";
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS = "1";
    # Full upstream tests exercise mounts/installers. Validate this tool against
    # the Fedora importer and final signed OCI fixtures in the sealing checks.
    doCheck = false;
    meta.mainProgram = "bootc";
  }
