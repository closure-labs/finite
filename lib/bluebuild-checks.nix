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
      ../files/security
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
      ../cosign.pub
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
  home = check "home-contracts" (with pkgs; [gawk getent gnugrep jq python3 ripgrep yq-go]) ''
    export FINITE_HOME_CATALOG_PATH=${homeCatalog}
    bash tests/home/contracts.sh \
      ${applications.homeProfile}/bin/finite-home-profile \
      ${applications.homeInit}/bin/finite-home-init \
      ${applications.cloudInit}/bin/finite-cloud-init \
      ${homeScaffold}
    bash tests/home/dell-panel-policy.sh
    python3 tests/home/maintenance.py
    bash modules/aspects/capabilities/devops/tests/contracts.sh
    bash modules/aspects/roles/developer/tests/contracts.sh
    bash modules/aspects/roles/support/tests/contracts.sh
  '';
  nix-lifecycle = check "nix-lifecycle" (with pkgs; [diffutils gawk gnugrep jq systemd util-linux]) ''
    bash tests/bluebuild/nix-readiness.sh
    bash tests/nix/determinate-version.sh
    bash tests/nix/nix-lifecycle.sh
    bash tests/nix/nix-systemd.sh
    bash tests/nix/home-selinux-contexts.sh
    bash tests/nix/nix-selinux.sh
    bash tests/bluebuild/vm-predecessor-home.sh
  '';
  bluebuild = check "bluebuild-contracts" [pkgs.gawk pkgs.git pkgs.jq pkgs.yq-go (pkgs.python3.withPackages (p: [p.pyyaml]))] ''
    python3 tests/automation/bluefin-upstream.py
    python3 tests/ci/selection.py
    python3 tests/ci/release-selection.py
    python3 tests/ci/applicability-evidence.py
    python3 tests/ci/native-evidence-summary.py
    python3 tests/ci/diagnose-built-candidate.py
    python3 tests/ci/rpm-file-evidence.py
    python3 tests/ci/freerdp-reference-evidence.py
    python3 tests/ci/podman-reference-evidence.py
    python3 tests/ci/httpd-reference-evidence.py
    python3 tests/ci/go-consumer-reference.py
    python3 tests/ci/rclone-compatibility.py
    python3 tests/ci/nix-checks.py
    python3 tests/ci/toolchain.py
    python3 tests/ci/delivery-policy.py
    python3 tests/ci/image-tools-benchmark.py
    python3 tests/ci/remediation-preflight.py
    python3 tests/ci/security-ownership.py
    python3 tests/ci/security-remediation-diff.py
    python3 tests/ci/go-desktop-evidence.py
    python3 tests/ci/cosign-runtime.py
    python3 tests/ci/approved-baseline.py
    python3 tests/ci/kernel-update.py
    python3 tests/ci/local-candidate-evidence.py
    python3 tests/bluebuild/contracts.py
    python3 tests/bluebuild/build.py
    python3 tests/bluebuild/inspect-built.py
    python3 tests/bluebuild/iso.py
    python3 tests/bluebuild/kernel.py
    python3 tests/bluebuild/kernel-generic-security.py
    python3 tests/bluebuild/initramfs.py
    python3 tests/bluebuild/vm-mok.py
    python3 tests/bluebuild/installer.py
    python3 tests/bluebuild/provisioning.py
    python3 tests/bluebuild/security-policy.py
    python3 tests/bluebuild/security-remediation.py
    python3 tests/bluebuild/tailscale-security.py
    python3 tests/bluebuild/desktop-qualification.py
    python3 tests/bluebuild/reliability.py
    python3 tests/bluebuild/resume.py
    python3 tests/bluebuild/extraction-layout.py
  '';
  vm-iso = check "vm-iso-layout" (with pkgs; [diffutils gnugrep gnused libisoburn mtools]) ''
    bash tests/bluebuild/vm-iso.sh
  '';
  vm-firmware = check "vm-firmware" (with pkgs; [libisoburn openssl python3 python3Packages.virt-firmware]) ''
    bash tests/bluebuild/vm-firmware.sh ${pkgs.OVMF.fd}/FV/OVMF_VARS.fd
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
    shellcheck files/system/usr/libexec/finite/check-initramfs
  '';
  repository-security = check "repository-security" (with pkgs; [jq python3 applications.repositorySecurityAudit]) ''
    bash tests/automation/repository-security.sh \
      ${lib.getExe applications.repositorySecurityAudit} \
      automation/github/repository-security.json tests/fixtures/repository-security
  '';
}
