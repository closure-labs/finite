# Match devenv's SecretSpec 0.19 interface without compiling the full devenv
# toolchain merely to resolve a scoped credential on an ephemeral CI runner.
{pkgs}: let
  pin = builtins.fromJSON (builtins.readFile ../sources/secretspec.json);
in
  pkgs.stdenvNoCC.mkDerivation {
    pname = "finite-secretspec";
    inherit (pin) version;
    src = pkgs.fetchurl {inherit (pin) url sha256;};
    nativeBuildInputs = [pkgs.autoPatchelfHook];
    buildInputs = [pkgs.dbus pkgs.openssl pkgs.stdenv.cc.cc.lib];
    installPhase = ''
      runHook preInstall
      install -Dm755 secretspec "$out/bin/secretspec"
      runHook postInstall
    '';
  }
