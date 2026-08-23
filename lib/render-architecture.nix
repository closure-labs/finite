{
  den,
  diagram,
  lib,
  pkgs,
}: let
  renderContext = diagram.renderContext {inherit pkgs;};
  aspectCandidates =
    [den.aspects.features.base]
    ++ builtins.attrValues den.aspects.features.capabilities
    ++ builtins.attrValues den.aspects.features.hardware
    ++ builtins.attrValues den.aspects.features.roles
    ++ builtins.attrValues den.aspects.profiles
    ++ builtins.attrValues den.aspects.sources
    ++ [den.aspects.operations.source]
    ++ builtins.attrValues den.aspects.operations.checks
    ++ builtins.attrValues den.aspects.operations.delivery
    ++ builtins.attrValues den.aspects.operations.github
    ++ builtins.attrValues den.aspects.operations.updates;
  declaredAspects =
    builtins.filter (
      value:
        builtins.isAttrs value
        && value ? __provider
        && value.__provider != []
    )
    aspectCandidates;
  qualifiedName = aspect:
    lib.concatStringsSep "." aspect.__provider;
  qualifyReference = reference:
    if builtins.isAttrs reference && reference ? __provider
    then {
      name = qualifiedName reference;
      meta = {};
      includes = [];
    }
    else reference;
  flattenedAspects = builtins.listToAttrs (
    map (
      aspect: let
        name = qualifiedName aspect;
      in {
        inherit name;
        value = {
          inherit name;
          meta = {};
          includes = map qualifyReference (aspect.includes or []);
        };
      }
    )
    declaredAspects
  );
  namespace = diagram.graph.ofNamespace {aspects = flattenedAspects;};
  rendered = renderContext.renderDense.toMermaid namespace;
  mermaid = lib.concatStringsSep "\n" (
    builtins.filter
    (line: !(lib.hasPrefix "%%{init:" line))
    (lib.splitString "\n" rendered)
  );
  markdown = pkgs.writeText "architecture.md" ''
    # Finite Den aspect namespace

    This view is rendered from the evaluated `den.aspects` registry. Edges are
    aspect `includes` relationships, so the diagram is the architecture rather
    than a separately maintained description of it.

    ```mermaid
    ${mermaid}
    ```
  '';
  source = pkgs.writeText "namespace.mmd" mermaid;
in
  pkgs.runCommand "finite-architecture" {} ''
    mkdir -p "$out"
    cp ${markdown} "$out/architecture.md"
    cp ${source} "$out/namespace.mmd"
  ''
