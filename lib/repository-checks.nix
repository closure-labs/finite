{
  applications,
  architecture,
  generated,
  lib,
  pkgs,
}: let
  root = ../.;
  inherit (lib) fileset;
  sourceFor = selected:
    fileset.toSource {
      inherit root;
      fileset = fileset.unions selected;
    };
  shellFiles = fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".sh" file.name) root;
  nixFiles = fileset.fileFilter (file: file.type == "regular" && lib.hasSuffix ".nix" file.name) root;
  textFiles =
    fileset.fileFilter (
      file:
        file.type
        == "regular"
        && (
          builtins.elem file.name [".editorconfig" ".gitignore" "Containerfile" "Containerfile.derived" "Justfile" "LICENSE" "VERSION"]
          || builtins.any (suffix: lib.hasSuffix suffix file.name) [
            ".conf"
            ".css"
            ".json"
            ".md"
            ".nix"
            ".sh"
            ".toml"
            ".xml"
            ".yaml"
            ".yml"
            ".zsh"
          ]
        )
    )
    root;
  shellSource = sourceFor [shellFiles];
  nixSource = sourceFor [nixFiles ../tests/repository/nix.sh];
  repositorySource = sourceFor [
    ../VERSION
    ../bootc/Containerfile
    ../bootc/Containerfile.derived
    ../bootc/builder
    ../modules/aspects
    ../sources
    ../secretspec.toml
    ../tests/repository/contracts.sh
    ../tests/repository/architecture.sh
  ];
  documentationSource = sourceFor [textFiles];
  automationSource = sourceFor [
    ../automation/github
    ../flake.nix
    ../tests/automation
    ../tests/repository/automation.sh
  ];
  bootcSource = sourceFor [
    ../.github/syft.yaml
    ../bootc/builder
    ../modules/aspects
    ../tests/bootc
    ../tests/repository/bootc.sh
  ];
  aspectsSource = sourceFor [
    ../modules/aspects
    ../tests/repository/aspects.sh
  ];
  releaseSource = sourceFor [
    ../CHANGELOG.md
    ../VERSION
    ../automation/release
    ../flake.nix
    ../tests/repository/release.sh
  ];
  upstreamSource = sourceFor [
    ../automation/sources
    ../automation/nix
    ../bootc/Containerfile
    ../flake.nix
    ../lib/flake-applications.nix
    ../modules/outputs.nix
    ../sources
    ../secretspec.toml
    ../tests/repository/upstream.sh
  ];
  workflowSource = sourceFor [
    ../.github
    ../automation/github/policies
    ../automation/installer/build.sh
    ../bootc/Containerfile
    ../bootc/builder/sbom.sh
    ../flake.nix
    ../lib/installer-application.nix
    ../modules/outputs.nix
    ../installer/Containerfile
    ../installer/rootfs/usr/share/anaconda/interactive-defaults.ks
    ../tests/repository/workflows.sh
  ];
  mkSourceCheck = {
    commands,
    generatedRoot ? null,
    name,
    source,
    tools ? [],
  }:
    pkgs.runCommand "purplefin-${name}" {
      nativeBuildInputs = [pkgs.bash pkgs.coreutils] ++ tools;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${source}/. source/
      chmod -R u+w source
      cd source
      ${lib.optionalString (generatedRoot != null) ''
        export PURPLEFIN_GENERATED_ROOT=${generatedRoot}
      ''}
      export PURPLEFIN_HERMETIC_CHECK=true
      export PURPLEFIN_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
in {
  shell = mkSourceCheck {
    name = "shell-checks";
    source = shellSource;
    tools = with pkgs; [findutils shellcheck];
    commands = "bash tests/repository/shell.sh";
  };

  repository = mkSourceCheck {
    name = "repository-contracts";
    source = repositorySource;
    generatedRoot = generated;
    tools = with pkgs; [gnugrep jq];
    commands = ''
      bash tests/repository/contracts.sh
      bash tests/repository/architecture.sh ${architecture}
    '';
  };

  upstream = mkSourceCheck {
    name = "upstream-contracts";
    source = upstreamSource;
    tools = with pkgs; [gnugrep jq secretspec];
    commands = "bash tests/repository/upstream.sh";
  };

  documentation = mkSourceCheck {
    name = "documentation-checks";
    source = documentationSource;
    tools = with pkgs; [file findutils gawk gnugrep ripgrep];
    commands = "bash tests/repository/documentation.sh";
  };

  automation = mkSourceCheck {
    name = "automation-checks";
    source = automationSource;
    tools = with pkgs; [
      applications.classifyChanges
      applications.classifyCi
      applications.ciGate
      applications.promoteImages
      applications.trustedUpdate
      git
      gnugrep
      jq
    ];
    commands = "bash tests/repository/automation.sh";
  };

  bootc = mkSourceCheck {
    name = "bootc-checks";
    source = bootcSource;
    generatedRoot = generated;
    tools = with pkgs; [
      applications.imagePlan
      applications.shardPlan
      applications.validateImageShard
      diffutils
      findutils
      gnugrep
      jq
    ];
    commands = "bash tests/repository/bootc.sh";
  };

  aspects = mkSourceCheck {
    name = "aspect-contracts";
    source = aspectsSource;
    tools = with pkgs; [gnugrep systemd util-linux];
    commands = "bash tests/repository/aspects.sh";
  };

  release = mkSourceCheck {
    name = "release-contracts";
    source = releaseSource;
    tools = with pkgs; [applications.releaseNotes gawk gnugrep gnused];
    commands = "bash tests/repository/release.sh";
  };

  workflows = mkSourceCheck {
    name = "workflow-checks";
    source = workflowSource;
    tools = with pkgs; [actionlint gnugrep jq yq-go zizmor];
    commands = "bash tests/repository/workflows.sh";
  };

  nix = mkSourceCheck {
    name = "nix-checks";
    source = nixSource;
    tools = [pkgs.statix];
    commands = "bash tests/repository/nix.sh";
  };
}
