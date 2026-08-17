{den, ...}: let
  inherit (den.aspects) features operations profiles sources;
in {
  # Operational aspects make the repository control plane part of the same
  # namespace graph as the images it validates and delivers.
  den.aspects.operations = {
    checks = {
      shell.includes = [operations.source];
      "repository-contracts".includes = [operations.source];
      documentation.includes = [operations.source];
      automation.includes = [operations.source];
      "bootc-engine".includes = [operations.source features.base];
      aspects.includes = [
        operations.source
        features.base
        features.capabilities.devops
        features.hardware.dell-xps-9350-intel
        features.roles.support
      ];
      workflows.includes = [operations.source];
      upstream.includes = [operations.source sources.bluefin];
      all.includes = [
        operations.checks.shell
        operations.checks."repository-contracts"
        operations.checks.documentation
        operations.checks.automation
        operations.checks."bootc-engine"
        operations.checks.aspects
        operations.checks.workflows
        operations.checks.upstream
      ];
    };

    delivery = {
      images.includes = [sources.bluefin] ++ builtins.attrValues profiles;
      installer.includes = [operations.delivery.images];
      release.includes = [
        operations.delivery.images
        operations.delivery.installer
      ];
    };

    github = {
      build.includes = [
        operations.checks.all
        operations.delivery.images
        operations.delivery.installer
      ];
      installer.includes = [operations.delivery.installer];
      release.includes = [operations.delivery.release];
      bluefin-update.includes = [
        operations.updates.bluefin
        operations.delivery.images
      ];
    };

    updates.bluefin.includes = [
      operations.source
      sources.bluefin
      operations.checks.upstream
    ];

    source = {};
  };
}
