# Each check receives its declared inputs. The aggregate still requires every
# check; a controller edit no longer changes firmware or home test derivations.
{lib}: let
  source = paths:
    lib.fileset.toSource {
      root = ../.;
      fileset = lib.fileset.unions paths;
    };
  system = [../files/system ../files/scripts ../files/dnf ../recipes ../sources];
  nixInputs = [../flake.nix ../flake.lock ../devenv.lock ../sources];
in {
  home-contracts = source [../tests/home ../scripts/home ../files/system];
  nix-lifecycle = source ([../tests/nix ../scripts/bluebuild ../tests/bluebuild/nix-readiness.sh ../tests/bluebuild/wifi-power.py ../tests/bluebuild/vm-predecessor-home.sh] ++ system);
  vm-iso-layout = source [../tests/bluebuild/vm-iso.sh ../scripts/bluebuild/prepare-vm-iso.sh];
  vm-firmware = source [../tests/bluebuild/vm-firmware.sh ../scripts/bluebuild/prepare-vm-firmware.sh];
  dependency-update-contracts = source ([../tests/automation ../scripts/ci/http-get.py] ++ nixInputs);
  dependency-locks = source nixInputs;
  workflow-lint = source [../.github ../lib/bluebuild-checks.nix ../scripts/ci/lint-workflows.py ../tests/ci/workflow-lint.py ../files/scripts ../files/installer ../files/system/usr/libexec/finite/check-initramfs ../scripts/bluebuild];
  repository-security = source [../automation/github ../tests/automation/repository-security.sh ../tests/fixtures/repository-security ../scripts/ci/repository-security-audit.py];
}
