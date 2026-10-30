{
  applications,
  homeScaffold,
  homeCatalog,
  foundation,
  lib,
  pkgs,
}: let
  sources = import ./check-sources.nix {inherit lib;};
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
      ../scripts/home
      ../scripts/workstation
      ../tests
      ../modules/outputs.nix
      ../lib
      ../sources
      ../cosign.pub
      ../VERSION
      ../CHANGELOG.md
      ../flake.nix
      ../flake.lock
      ../devenv.lock
      ../docs
      ../secretspec.toml
      ../devenv.yaml
      ../devenv.nix
      ../devenv-tasks.nix
    ];
  };
  check = name: tools: commands: let
    inputs = sources.${name} or source;
  in
    pkgs.runCommand "finite-${name}" {
      nativeBuildInputs = [pkgs.bash pkgs.coreutils] ++ tools;
    } ''
      export HOME="$TMPDIR/home"
      mkdir -p "$HOME" source
      cp -R ${inputs}/. source/
      chmod -R u+w source
      cd source
      export FINITE_HERMETIC_CHECK=true FINITE_SOURCE_ROOT="$PWD"
      ${commands}
      touch "$out"
    '';
in {
  home = check "home-contracts" (with pkgs; [gawk getent gnugrep jq just nix python3 ripgrep shellcheck xorriso yq-go]) ''
    export FINITE_HOME_CATALOG_PATH=${homeCatalog}
    export FINITE_TEST_PROFILE_EXPORT_COMMAND=${lib.getExe applications.profileExport}
    export FINITE_TEST_FOUNDATION_SOURCE=${foundation}
    shellcheck -s bash files/system/usr/libexec/finite/lib/update-shell-env
    bash tests/home/contracts.sh \
      ${lib.getExe applications.homeProfile} \
      ${lib.getExe applications.homeInit} \
      ${applications.cloudInit}/bin/finite-cloud-init \
      ${homeScaffold}
    python3 tests/home/maintenance.py
    python3 tests/home/foundation-integration.py
    python3 tests/home/first-login.py
  '';
  nix-lifecycle = check "nix-lifecycle" (with pkgs; [diffutils gawk gnugrep jq python3 systemd util-linux]) ''
    bash tests/bluebuild/nix-readiness.sh
    bash tests/nix/determinate-version.sh
    bash tests/nix/nix-lifecycle.sh
    bash tests/nix/nix-systemd.sh
    python3 tests/bluebuild/wifi-power.py
    bash tests/nix/home-selinux-contexts.sh
    bash tests/nix/nix-selinux.sh
    bash tests/bluebuild/vm-predecessor-home.sh
  '';
  bluebuild = check "bluebuild-contracts" [pkgs.gawk pkgs.git pkgs.glib pkgs.jq pkgs.openssl pkgs.sqlite applications.ciSecretsRun (import ./secretspec.nix {inherit pkgs;}) pkgs.yq-go (pkgs.python3.withPackages (p: [p.pyyaml]))] ''
    export PYTHONDONTWRITEBYTECODE=1
    python3 tests/automation/bluefin-upstream.py
    python3 tests/ci/foundation-update.py
    python3 tests/ci/github-api.py
    python3 tests/ci/publisher-health.py
    python3 tests/ci/release-readiness.py
    python3 tests/ci/release-cycle.py
    python3 tests/ci/premerge-vm.py
    python3 tests/ci/vm-tools.py
    python3 tests/ci/vm-host.py
    python3 tests/ci/selection.py
    python3 tests/ci/active-variants.py
    python3 tests/ci/release-selection.py
    python3 tests/ci/release-request.py
    python3 tests/ci/security-decisions.py
    python3 tests/ci/decision-authority.py
    python3 tests/ci/dependency-update.py
    python3 tests/ci/ci-run-admission.py
    python3 tests/ci/decision-revocation.py
    python3 tests/ci/validation-preflight.py
    python3 tests/ci/foundation-diagnostics.py
    python3 tests/ci/workflow-costs.py
    python3 tests/ci/decision-check.py
    python3 tests/ci/decision-controller.py
    python3 tests/ci/decision-packets.py
    python3 tests/ci/decision-health.py
    python3 tests/ci/legacy-release-boundary.py
    python3 tests/ci/security-admission.py
    python3 tests/ci/security-integrations.py
    python3 tests/ci/publication-authority.py
    python3 tests/ci/release-set.py
    python3 tests/ci/prepare-release-set.py
    python3 tests/ci/recovery-completion.py
    python3 tests/ci/reconcile-decisions.py
    python3 tests/workstation/cleanup-brew.py
    python3 tests/ci/verify-attestation-subject.py
    python3 tests/ci/release-handoff.py
    python3 tests/ci/ci-savings.py
    python3 tests/ci/release-origin.py
    python3 tests/ci/release-transport-benchmark.py
    python3 tests/ci/execute-release-set.py
    python3 tests/ci/release-recovery.py
    python3 tests/ci/image-identity.py
    python3 tests/ci/qualification-dependencies.py
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
    python3 tests/ci/nix-resources.py
    python3 tests/ci/nix-cache.py
    python3 tests/ci/cache-sqlite.py
    python3 tests/ci/secretspec.py
    python3 tests/ci/devenv-cache.py
    python3 tests/ci/cache-publish.py
    python3 tests/ci/benchmark-cache-writer.py
    python3 tests/ci/prune-ci-caches.py
    python3 tests/ci/ci-cache-benchmark.py
    python3 tests/ci/delivery-policy.py
    python3 tests/ci/installer-benchmark.py
    python3 tests/bluebuild/installer-provenance.py
    python3 tests/ci/image-tools-benchmark.py
    python3 tests/ci/image-verification-benchmark.py
    python3 tests/ci/image-transfer-benchmark.py
    python3 tests/ci/security-reuse-benchmark.py
    python3 tests/ci/database-overlap-benchmark.py
    python3 tests/ci/qualification-reuse-benchmark.py
    python3 tests/ci/remediation-preflight.py
    python3 tests/ci/security-ownership.py
    python3 tests/ci/security-remediation-diff.py
    python3 tests/ci/go-desktop-evidence.py
    python3 tests/ci/cosign-runtime.py
    python3 tests/ci/approved-baseline.py
    python3 tests/ci/local-candidate-evidence.py
    python3 tests/bluebuild/contracts.py
    python3 tests/bluebuild/desktop-integration.py
    python3 tests/workstation/password-manager-setup.py
    python3 tests/bluebuild/build.py
    python3 tests/bluebuild/inspect-built.py
    python3 tests/bluebuild/upstream-kernel.py
    python3 tests/bluebuild/authselect.py
    python3 tests/bluebuild/local-vm.py
    python3 tests/bluebuild/iso.py
    python3 tests/bluebuild/initramfs.py
    python3 tests/bluebuild/vm-mok.py
    python3 tests/bluebuild/vm-signature-rejection.py
    python3 tests/bluebuild/vm-upgrade.py
    python3 tests/bluebuild/unlock-vm.py
    python3 tests/bluebuild/installer.py
    python3 tests/bluebuild/installer-certificate.py
    python3 tests/bluebuild/qualification.py
    python3 tests/bluebuild/qualification-collection.py
    python3 tests/bluebuild/provisioning.py
    python3 tests/bluebuild/security-policy.py
    python3 tests/bluebuild/security-database-overlap.py
    python3 tests/bluebuild/security-remediation.py
    python3 tests/bluebuild/tailscale-security.py
    python3 tests/bluebuild/desktop-qualification.py
    python3 tests/bluebuild/reliability.py
    python3 tests/bluebuild/publication-current.py
    python3 tests/ci/reuse-candidate-security.py
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
    ]) ''
      bash tests/automation/fix-nix-hashes.sh
      bash tests/automation/trusted-update.sh
        bash tests/automation/source-update.sh
      bash tests/automation/update-locks.sh
      python3 tests/automation/http-get.py
    '';
  dependency-locks = check "dependency-locks" [applications.validateLocks] ''
    ${lib.getExe applications.validateLocks}
  '';
  workflows = check "workflow-lint" (with pkgs; [actionlint shellcheck zizmor curl (python3.withPackages (p: [p.pyyaml]))]) ''
    python3 tests/ci/workflow-lint.py
    python3 tests/ci/cosign-download.py
    python3 scripts/ci/lint-workflows.py
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
