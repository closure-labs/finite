{pkgs}: let
  inherit (pkgs) lib;
  executables = {
    qemu-system-x86_64 = pkgs.qemu_test;
    qemu-img = pkgs.qemu_test;
    xorriso = pkgs.libisoburn;
    mcopy = pkgs.mtools;
    openssl = pkgs.openssl;
    ssh = pkgs.openssh;
    ssh-keygen = pkgs.openssh;
    skopeo = pkgs.skopeo;
    virt-fw-vars = pkgs.python3Packages.virt-firmware;
    python3 = pkgs.python3.withPackages (p: [p.pyyaml]);
  };
  firmware = pkgs.OVMFFull.fd;
  manifest = pkgs.writeText "finite-vm-toolchain.json" (builtins.toJSON {
    schema = 1;
    provider = "nix";
    executables =
      lib.mapAttrs (name: package: {
        path = "${lib.getBin package}/bin/${name}";
        version = lib.getVersion package;
      })
      executables;
    firmware = {
      secureBoot = true;
      code = "${firmware}/FV/OVMF_CODE.fd";
      variables = "${firmware}/FV/OVMF_VARS.ms.fd";
    };
  });
in
  pkgs.buildEnv {
    name = "finite-ci-vm-tools";
    paths = lib.unique (map lib.getBin (builtins.attrValues executables));
    pathsToLink = ["/bin"];
    postBuild = ''
      mkdir -p "$out/share/finite-vm/firmware"
      cp ${manifest} "$out/share/finite-vm/toolchain.json"
      ln -s ${firmware}/FV/OVMF_CODE.fd "$out/share/finite-vm/firmware/OVMF_CODE_4M.fd"
      ln -s ${firmware}/FV/OVMF_CODE.fd "$out/share/finite-vm/firmware/OVMF_CODE_4M.secboot.fd"
      ln -s ${firmware}/FV/OVMF_VARS.fd "$out/share/finite-vm/firmware/OVMF_VARS_4M.fd"
      ln -s ${firmware}/FV/OVMF_VARS.ms.fd "$out/share/finite-vm/firmware/OVMF_VARS_4M.ms.fd"
    '';
  }
