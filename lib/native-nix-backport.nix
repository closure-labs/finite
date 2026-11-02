{
  inputs,
  system,
}: let
  upstream = inputs.native-nix;
  pkgs = import upstream.inputs.nixpkgs {inherit system;};
  patch = ../patches/nix/completed-resume-416.patch;
  components = (upstream.lib.makeComponents {inherit pkgs;}).overrideScope (
    _: previous: {
      nix-store = previous.nix-store.overrideAttrs (old: {
        postPatch =
          (old.postPatch or "")
          + ''
            echo '92865d00ce339532f7e15ed952479e1985500e02446c1497dd0523699aa0753d  filetransfer.cc' | sha256sum -c -
            patch -p3 < ${patch}
            echo '0f7106c425f195a69f31a602670231b14fc0fa2c0b31bc89506004764e276432  filetransfer.cc' | sha256sum -c -
          '';
      });
    }
  );
in
  assert (builtins.fromJSON (builtins.readFile ../sources/determinate-nix.json)).version == "3.24.1";
  assert upstream.rev == "240bbbcb10d3fc4bce957fafc1000b85ffb004d0"; {
    runtime = components.nix-cli;
    library = components.nix-store;
    closure = pkgs.closureInfo {rootPaths = [components.nix-cli];};
    inherit patch;
  }
