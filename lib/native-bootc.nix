{pkgs}: let
  pin = builtins.fromJSON (builtins.readFile ../sources/native-bootc.json);
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
    # Full upstream tests exercise mounts/installers. Validate this tool against
    # the Fedora importer and final signed OCI fixtures in the sealing checks.
    doCheck = false;
    meta.mainProgram = "bootc";
  }
