{
  catalog,
  config,
  homeDependencies,
  lib,
  mkPkgs,
  outputDependencies,
  project,
  ...
}: let
  system = project.platform.system;
  pkgs = mkPkgs system;
  treefmtEval = outputDependencies.treefmt.evalModule pkgs ../treefmt.nix;
  repositoryToolchain =
    (with pkgs; [
      actionlint
      bash
      cachix
      coreutils
      diffutils
      file
      findutils
      gawk
      git
      glib
      gnugrep
      gnused
      jq
      just
      pipewire
      ripgrep
      secretspec
      shellcheck
      statix
      systemd
      util-linux
      zizmor
      zsh
    ])
    ++ [
      (pkgs.python3.withPackages (p: [p.pyyaml]))
      treefmtEval.config.build.wrapper
    ];
  home = config.finite.home;
  inherit (project) cache;
  version = lib.removeSuffix "\n" (builtins.readFile ../VERSION);
  homeScaffold = import ../lib/render-home-scaffold.nix {
    inherit pkgs version;
  };
  imagePayload = import ../lib/image-payload.nix {
    inherit pkgs lib catalog homeScaffold version;
  };
  baseApplications = import ../lib/flake-applications.nix {
    devenv = outputDependencies.devenvPackage;
    inherit pkgs;
    cacheName = cache.name;
    secretspec = outputDependencies.weeklySecretspec;
  };
  homeApplications = import ../lib/home-profile-applications.nix {
    inherit homeScaffold pkgs;
    inherit (imagePayload) homeCatalog;
  };
  applications = baseApplications // homeApplications;
  roleModules = map (name: ../modules/aspects/roles + "/${name}/default.nix") catalog.roleNames;
  hardwareModules = map (name: ../modules/aspects/hardware + "/${name}/default.nix") catalog.homeHardwareNames;
  homeFlakeModule = {
    imports =
      [
        outputDependencies.denFlakeModule
        ../modules/aspects/base/default.nix
        ../modules/aspects/capabilities/devops/default.nix
      ]
      ++ roleModules
      ++ hardwareModules
      ++ [
        (import ../lib/home-manager-flake-module.nix {
          inherit catalog homeDependencies mkPkgs project;
          homeInputs = outputDependencies.homeModuleInputs;
          inherit (outputDependencies) homeManagerLib;
          inherit (applications) homeBootstrap homeProfile;
        })
      ];
  };
  allRoles = catalog.roleNames;
  mkHomeProof = foundation: hardware: packages: roles: let
    username = "finite-check-${foundation}-${hardware}-${lib.concatStringsSep "-" packages}-${lib.concatStringsSep "-" roles}";
    evaluated = lib.evalModules {
      # Den resolves its generated module imports from these Flake inputs.
      specialArgs.inputs = outputDependencies.homeModuleInputs;
      modules = [
        homeFlakeModule
        {
          finite.homeProfile = {
            schema = 2;
            inherit foundation hardware packages roles;
            identity = {
              inherit username;
              homeDirectory = "/var/home/${username}";
            };
          };
        }
      ];
    };
  in
    evaluated.config.flake.homeConfigurations.${username}.activationPackage;
  foundationHardwareProofs =
    lib.concatMap (
      foundation:
        map (hardware: mkHomeProof foundation hardware [] []) catalog.homeHardwareNames
    )
    catalog.foundationNames;
  roleProofs =
    map (
      role:
        mkHomeProof
        (builtins.head catalog.foundationNames)
        (builtins.head catalog.homeHardwareNames)
        []
        [role]
    )
    allRoles;
  allRolesProof =
    mkHomeProof
    (lib.last catalog.foundationNames)
    (lib.last catalog.homeHardwareNames)
    []
    allRoles;
  allPackagesProof =
    mkHomeProof
    (builtins.head catalog.foundationNames)
    (builtins.head catalog.homeHardwareNames)
    catalog.packageNames
    [];
  homeProofsEvaluated =
    builtins.deepSeq (
      map (activation: activation.drvPath) (foundationHardwareProofs ++ roleProofs ++ [allRolesProof allPackagesProof])
    )
    true;
  homeCheck = assert homeProofsEvaluated;
    pkgs.runCommand "finite-home-configurations-proof" {} ''
      touch "$out"
    '';
  repositoryChecks = import ../lib/bluebuild-checks.nix {
    inherit applications homeScaffold lib pkgs;
    inherit (imagePayload) homeCatalog;
  };
  formattingSource = lib.cleanSourceWith {
    src = outputDependencies.self;
    filter = path: _type: let
      relative = lib.removePrefix "${toString outputDependencies.self}/" (toString path);
    in
      relative
      != ".git"
      && !(lib.hasPrefix ".git/" relative)
      && relative != ".devenv"
      && !(lib.hasPrefix ".devenv/" relative)
      && relative != ".direnv"
      && !(lib.hasPrefix ".direnv/" relative);
  };
  formattingValidation = treefmtEval.config.build.check formattingSource;
  formattingCheck = pkgs.runCommand "finite-formatting-proof" {} ''
    test -e ${formattingValidation}
    touch "$out"
  '';
  checks =
    repositoryChecks
    // {
      formatting = formattingCheck;
      home-configurations = homeCheck;
      cache-configuration = assert lib.assertMsg ((import ../flake.nix).nixConfig == project.nixConfig)
      "Keep the concrete flake cache configuration synchronized with project-policy.nix";
        pkgs.runCommand "finite-cache-configuration" {} ''
          touch "$out"
        '';
    };
  ciChecks = pkgs.runCommand "finite-ci-checks" {} ''
    mkdir "$out"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: check: ''
        ln -s ${check} "$out/${name}"
      '')
      checks
    )}
  '';
  ciCheck = applications.mkCheck checks;
  localCache = applications.mkLocalCache ciCheck;
  exportTable = {
    ci-check.package = ciCheck;
    ci-checks.package = ciChecks;
    ci-fix-nix-hashes.package = applications.fixNixHashes;
    ci-update-locks.package = applications.updateLocks;
    ci-home-release-update.package = applications.updateHomeRelease;
    ci-source-update.package = applications.sourceUpdate;
    ci-trusted-update.package = applications.trustedUpdate;
    ci-queue-dependabot.package = applications.queueDependabot;
    ci-repository-security-audit.package = applications.repositorySecurityAudit;
    ci-github-actions-secrets.package = applications.githubActionsSecrets;
    ci-lock-validate.package = applications.validateLocks;
    ci-cosign.package = pkgs.cosign;
    ci-skopeo.package = pkgs.skopeo;
    devenv = {
      package = outputDependencies.devenvPackage;
      appProgram = lib.getExe outputDependencies.devenvPackage;
    };
    default.package = imagePayload.payload;
    image-payload.package = imagePayload.payload;
    image-payload-next.package = imagePayload.next;
    home-profile-catalog.package = imagePayload.homeCatalog;
    home-manager-template.package = homeScaffold;
    home-profile = {
      package = applications.homeProfile;
      appProgram = "${applications.homeProfile}/bin/finite-home-profile";
    };
    home-bootstrap = {
      package = applications.homeBootstrap;
      appProgram = "${applications.homeBootstrap}/bin/finite-home-bootstrap";
    };
    home-init = {
      package = applications.homeInit;
      appProgram = "${applications.homeInit}/bin/finite-home-init";
    };
    cloud-init.appProgram = "${applications.cloudInit}/bin/finite-cloud-init";
    local-cache.appProgram = "${localCache}/bin/finite-local-cache";
    repository-security-audit.appProgram = lib.getExe applications.repositorySecurityAudit;
  };
  packageExports = lib.mapAttrs (_: export: export.package) (
    lib.filterAttrs (_: export: export ? package) exportTable
  );
  appExports = lib.mapAttrs (
    _: export: {
      type = "app";
      program = export.appProgram;
    }
  ) (lib.filterAttrs (_: export: export ? appProgram) exportTable);
in {
  flake = {
    lib.finite = {
      inherit home;
      inherit cache catalog;
    };
    flakeModules.home = homeFlakeModule;
    templates = {
      home-manager = {
        path = ../templates/home-manager;
        description = "Canonical self-contained Finite Home Manager configuration";
      };
      home-bluefin = {
        path = ../templates/home-manager;
        description = "Finite Home Manager template; bootstrap sets the Bluefin profile variables";
      };
      home-bluefin-dx = {
        path = ../templates/home-manager;
        description = "Finite Home Manager template; bootstrap sets the Bluefin DX profile variables";
      };
    };
    packages.${system} = packageExports;

    apps.${system} = appExports;

    checks.${system} = checks;

    devShells.${system} = {
      default = pkgs.mkShell {
        packages = repositoryToolchain;
      };
    };

    formatter.${system} = treefmtEval.config.build.wrapper;
  };
}
