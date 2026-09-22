{pkgs}: {
  ci = pkgs.mkShell {
    packages =
      (with pkgs; [bash coreutils cosign file git gh jq ripgrep skopeo])
      ++ [(pkgs.python3.withPackages (packages: [packages.pyyaml]))];
  };
  release = pkgs.mkShell {
    packages = with pkgs; [bash coreutils cosign gh jq skopeo syft grype];
  };
}
