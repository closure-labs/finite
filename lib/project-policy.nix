let
  caches = [
    {
      name = "finite-os";
      url = "https://finite-os.cachix.org";
      publicKey = "finite-os.cachix.org-1:iwOc148wD1hSWnyNwhP3DsMxBv8WcL+ppMwcRIvx4Ko=";
    }
    {
      name = "devenv";
      url = "https://devenv.cachix.org";
      publicKey = "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw=";
    }
    {
      name = "cachix";
      url = "https://cachix.cachix.org";
      publicKey = "cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM=";
    }
  ];
in {
  platform = {
    system = "x86_64-linux";
    ociArchitecture = "amd64";
  };
  cache = builtins.head caches;
  inherit caches;
  nixConfig = {
    extra-substituters = map (cache: cache.url) caches;
    extra-trusted-public-keys = map (cache: cache.publicKey) caches;
  };
}
