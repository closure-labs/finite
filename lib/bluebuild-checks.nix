{
  applications,
  homeScaffold,
  homeCatalog,
  lib,
  pkgs,
}: let
  source = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../.github
      ../automation
      ../recipes
      ../files/scripts
      ../files/installer
      ../files/system
      ../files/dnf
      ../scripts/bluebuild
      ../scripts/ci
      ../tests
      ../modules/aspects
      ../templates
      ../lib
      ../sources
      ../VERSION
      ../flake.nix
      ../flake.lock
      ../devenv.lock
      ../docs
    ];
  };
  check = name: tools: commands:
    pkgs.runCommand "finite-${name}" {
      nativeBuildInputs = [pkgs.bash pkgs.coreutils] ++ tools;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${source}/. source/
      chmod -R u+w source
      cd source
      export FINITE_HERMETIC_CHECK=true FINITE_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
in {
  home = check "home-contracts" (with pkgs; [gawk getent gnugrep jq ripgrep yq-go]) ''
    export FINITE_HOME_CATALOG_PATH=${homeCatalog}
    bash tests/home/contracts.sh \
      ${applications.homeProfile}/bin/finite-home-profile \
      ${applications.homeInit}/bin/finite-home-init \
      ${applications.cloudInit}/bin/finite-cloud-init \
      ${homeScaffold}
    bash tests/home/dell-panel-policy.sh
  '';
  nix-lifecycle = check "nix-lifecycle" (with pkgs; [gnugrep jq systemd util-linux]) ''
    bash tests/bluebuild/nix-readiness.sh
    bash tests/nix/determinate-version.sh
    bash tests/nix/nix-lifecycle.sh
    bash tests/nix/nix-systemd.sh
  '';
  bluebuild = check "bluebuild-contracts" [pkgs.git pkgs.jq (pkgs.python3.withPackages (p: [p.pyyaml]))] ''
    python3 tests/ci/selection.py
    python3 tests/bluebuild/contracts.py
    python3 tests/bluebuild/iso.py
    python3 tests/bluebuild/kernel.py
    python3 tests/bluebuild/installer.py
  '';
  vm-iso = check "vm-iso-layout" (with pkgs; [diffutils gnugrep gnused libisoburn mtools]) ''
    bash tests/bluebuild/vm-iso.sh
  '';
  dependency-updates =
    check "dependency-update-contracts" (with pkgs; [
      gnugrep
      gnused
      diffutils
      python3
      jq
      applications.fixNixHashes
      applications.trustedUpdate
      applications.sourceUpdate
      applications.updateLocks
      applications.updateHomeRelease
    ]) ''
      bash tests/automation/fix-nix-hashes.sh
      bash tests/automation/trusted-update.sh
      bash tests/automation/update-home-release.sh
      bash tests/automation/source-update.sh
      bash tests/automation/update-locks.sh
      python3 tests/automation/http-get.py
    '';
  dependency-locks = check "dependency-locks" [applications.validateLocks] ''
    ${lib.getExe applications.validateLocks}
  '';
  workflows = check "workflow-lint" (with pkgs; [actionlint shellcheck zizmor]) ''
    actionlint .github/workflows/*.yml
    zizmor --offline --no-config --collect=all .github
    shellcheck --exclude=SC1091 files/scripts/*.sh scripts/bluebuild/*.sh
    shellcheck -s bash files/installer/install_finite_fstab
  '';
  repository-security = check "repository-security" (with pkgs; [jq applications.repositorySecurityAudit]) ''
    bash tests/automation/repository-security.sh \
      ${lib.getExe applications.repositorySecurityAudit} \
      automation/github/repository-security.json tests/fixtures/repository-security
  '';
}
