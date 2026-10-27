{
  description = "Finite BlueBuild payload and Home Manager configuration";

  # Consumers derive the Finite cache name from this centralized URL.
  # Flake configuration rejects imported values as thunks. Project evaluation
  # consumes lib/project-policy.nix directly, and repository checks keep this
  # required concrete copy synchronized with that policy.
  nixConfig = {
    extra-substituters = [
      "https://finite-os.cachix.org"
      "https://devenv.cachix.org"
      "https://cachix.cachix.org"
    ];
    extra-trusted-public-keys = [
      "finite-os.cachix.org-1:iwOc148wD1hSWnyNwhP3DsMxBv8WcL+ppMwcRIvx4Ko="
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
      "cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM="
    ];
  };

  inputs = {
    # Foundation owns the Home Manager dependency graph; do not add follows here.
    foundation.url = "github:closure-labs/foundation/214e62aa594fc51a7416d69a01ab345edf036f77";
    # Update Den and the gen hub together: newer Den APIs may require a newer schema.
    den.url = "github:denful/den/90c303be407632d3983fb619e714c53b2349b8e6";

    # Use Den's tested gen hub through flake inputs, so sibling libraries share
    # revisions via follows instead of recursively fetching standalone roots.
    gen.url = "github:sini/gen/0004f3c9dfd5634f47ee72575e56c54883450bcf";
    gen.inputs.nixpkgs.follows = "nixpkgs";
    gen.inputs.import-tree.follows = "import-tree";

    devenv.url = "github:cachix/devenv";

    import-tree.url = "github:vic/import-tree";

    nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-26.05-chilled/0.1";
    nixpkgs-weekly.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0.1";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # Den composes Home Manager aspects; BlueBuild owns image configuration.
  outputs = inputs: let
    flake =
      (inputs.nixpkgs.lib.evalModules {
        specialArgs = {inherit inputs;};
        modules = [(inputs.import-tree ./modules)];
      }).config.flake;
    # getFlake needs the output attribute names even when a caller only reads
    # inputs. Keep that boundary lazy; forcing a public export still evaluates
    # the original module result and rejects any unlisted new export.
    names = ["apps" "checks" "denful" "devShells" "flakeModules" "formatter" "lib" "packages" "templates"];
  in
    builtins.listToAttrs (map (name: {
        inherit name;
        value = assert builtins.attrNames flake == names;
          flake.${name};
      })
      names);
}
