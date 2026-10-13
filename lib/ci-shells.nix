{pkgs}: let
  # One package list keeps the interactive shell and hosted image tools aligned.
  # Neither entry installs a Nix client: use the host's Determinate client.
  ciPackages =
    (with pkgs; [bash coreutils cosign file git gh jq ripgrep skopeo])
    ++ [(pkgs.python3.withPackages (packages: [packages.pyyaml]))];
  scannerPackages =
    (with pkgs; [bash coreutils cosign gh jq skopeo syft grype umoci])
    ++ [(pkgs.python3.withPackages (packages: [packages.pyyaml]))];
in {
  ci = pkgs.mkShell {packages = ciPackages;};
  imageTools = pkgs.buildEnv {
    name = "finite-ci-image-tools";
    paths = ciPackages;
    pathsToLink = ["/bin"];
  };
  scannerTools = pkgs.buildEnv {
    name = "finite-ci-scanner-tools";
    paths = scannerPackages;
    pathsToLink = ["/bin"];
  };
  release = pkgs.mkShell {
    packages = scannerPackages;
  };
}
