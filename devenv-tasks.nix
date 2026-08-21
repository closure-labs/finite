{pkgs, ...}: let
  runLeaf = package: command: arguments: ''
    PURPLEFIN_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --accept-flake-config "path:$DEVENV_ROOT#${package}" \
        -c ${command} ${arguments}
  '';
in {
  packages = with pkgs; [actionlint git jq shellcheck zizmor];

  tasks = {
    "ci:prepare".exec = runLeaf "ci-prepare" "purplefin-ci-prepare" "";
    "ci:check:flake" = {
      exec = runLeaf "ci-check" "purplefin-ci-check" "--no-write-lock-file";
      execIfModified = ["."];
    };
    "ci:check".after = ["ci:check:flake"];
    "ci:gate".exec = runLeaf "ci-gate" "purplefin-ci-gate" "";
    "ci:image:validate".exec = runLeaf "ci-validate-image-shard" "purplefin-validate-image-shard" "";
    "ci:image:reuse".exec = runLeaf "ci-image-reuse" "purplefin-image-reuse" "";
    "ci:image:build".exec = runLeaf "ci-image-build" "purplefin-image-build" "";
    "ci:image:sign".exec = runLeaf "ci-image-sign" "purplefin-image-sign" "";
    "ci:image:sbom".exec = runLeaf "ci-image-sbom" "purplefin-image-sbom" "";
    "ci:image:promote".exec = runLeaf "ci-promote-images" "purplefin-promote-images" "";
    "ci:installer:build".exec = runLeaf "ci-installer-build" "purplefin-installer-build" "";

    "automation:update-locks".exec = runLeaf "ci-update-locks" "purplefin-update-locks" "";
    "automation:validate-locks".exec = runLeaf "ci-lock-validate" "purplefin-ci-validate-locks" "";
    "automation:trusted-update".exec = runLeaf "ci-trusted-update" "purplefin-trusted-update" "";
    "automation:queue".exec = runLeaf "ci-queue-dependabot" "purplefin-queue-dependabot" "";
    "automation:cleanup".exec = runLeaf "ci-package-cleanup" "purplefin-package-cleanup" "";

    "release:notes".exec = runLeaf "ci-release-notes" "purplefin-release-notes" "";
    "release:attest-sbom".exec = runLeaf "ci-sbom-attestation" "purplefin-sbom-attestation" "";
  };
}
