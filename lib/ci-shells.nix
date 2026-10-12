{pkgs}: {
  ci = pkgs.mkShell {
    packages =
      (with pkgs; [bash coreutils cosign file git gh jq ripgrep skopeo])
      ++ [(pkgs.python3.withPackages (packages: [packages.pyyaml]))];
  };
  release = pkgs.mkShell {
    packages = with pkgs; [bash coreutils cosign gh jq python3 skopeo syft grype umoci];
  };
}
