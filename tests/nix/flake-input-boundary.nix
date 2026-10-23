# Reading the input graph must not force Den's module composition. Accessing a
# real export must still evaluate it, and future module exports must not vanish.
let
  outputs = (import ../../flake.nix).outputs;
  names = ["apps" "checks" "denful" "devShells" "flakeModules" "formatter" "lib" "packages" "templates"];
  deferred = outputs {nixpkgs.lib.evalModules = throw "Unexpected Den evaluation";};
  mock = extra:
    outputs {
      nixpkgs.lib.evalModules = _: {
        config.flake =
          builtins.listToAttrs (map (name: {
              inherit name;
              value = true;
            })
            names)
          // extra;
      };
    };
in
  assert builtins.attrNames deferred == names;
  assert !(builtins.tryEval deferred.packages).success;
  assert (mock {}).packages;
  assert !(builtins.tryEval (mock {newExport = true;}).packages).success; true
