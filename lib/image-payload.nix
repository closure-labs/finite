{
  pkgs,
  lib,
  catalog,
  homeScaffold,
  version,
  foundation,
  inputs,
}:
let
  native = import ./native-nix-backport.nix {
    inherit inputs;
    system = pkgs.stdenv.hostPlatform.system;
  };
  determinate = builtins.fromJSON (builtins.readFile ../sources/determinate-nix.json);
  fetch = asset: pkgs.fetchurl { inherit (asset) url sha256; };
  homeCatalog = pkgs.writeText "home-profile-catalog.json" (
    builtins.toJSON (
      import ./home-catalog.nix {
        domainCatalog = catalog;
        inherit lib version foundation;
      }
    )
  );
  payload = pkgs.runCommand "finite-image-payload-${version}" { } ''
    mkdir -p "$out/home-manager-template"
    cp -R ${homeScaffold}/. "$out/home-manager-template/"
    cp ${homeCatalog} "$out/home-profile-catalog.json"
    cp -R ${foundation}/. "$out/foundation/"
    cp ${pkgs.writeText "foundation-source.json" (builtins.toJSON foundation.lib.sourceInfo)} "$out/foundation-source.json"
    cp ${../VERSION} "$out/version"
    cp ${../sources/determinate-nix.json} "$out/determinate-nix.json"
    cp ${fetch determinate.installer} "$out/determinate-nix-installer"
    cp ${fetch determinate.selinuxPolicy} "$out/determinate-nix.pp"
    cp ${fetch determinate.selinuxFileContexts} "$out/nix.fc"
    chmod 0555 "$out/determinate-nix-installer"
    mkdir -p "$out/nix-runtime/store"
    cp ${native.closure}/registration "$out/nix-runtime/registration"
    cp ${native.closure}/store-paths "$out/nix-runtime/store-paths"
    while IFS= read -r path; do
      cp -a "$path" "$out/nix-runtime/store/"
    done < ${native.closure}/store-paths
    ${pkgs.python3}/bin/python3 - "$out/nix-runtime/runtime.json" <<'PY'
    import hashlib, json, pathlib, sys
    digest = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
    pathlib.Path(sys.argv[1]).write_text(json.dumps({
      "schema": 1, "runtime": "${native.runtime}",
      "binarySha256": digest("${native.runtime}/bin/nix"),
      "library": "${native.library}/lib/libnixstore.so",
      "librarySha256": digest("${native.library}/lib/libnixstore.so"),
      "sourceRevision": "240bbbcb10d3fc4bce957fafc1000b85ffb004d0",
      "patchedSourceSha256": "0f7106c425f195a69f31a602670231b14fc0fa2c0b31bc89506004764e276432",
      "patchSha256": digest("${native.patch}")
    }, indent=2) + "\n")
    PY
  '';
in
{
  inherit payload homeCatalog;
}
