{pkgs, ...}: let
  runLeaf = package: command: arguments: ''
    FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --accept-flake-config "path:$DEVENV_ROOT#${package}" \
        -c ${command} ${arguments}
  '';
in {
  packages = with pkgs; [actionlint git jq shellcheck zizmor];

  tasks = {
    "ci:prepare".exec = runLeaf "ci-prepare" "finite-ci-prepare" "";
    "ci:check:flake" = {
      exec = runLeaf "ci-check" "finite-ci-check" "--no-write-lock-file";
      execIfModified = ["."];
    };
    "ci:check".after = ["ci:check:flake"];
    "ci:gate".exec = runLeaf "ci-gate" "finite-ci-gate" "";
    "ci:image:validate".exec = runLeaf "ci-validate-image-shard" "finite-validate-image-shard" "";
    "ci:image:reuse".exec = runLeaf "ci-image-reuse" "finite-image-reuse" "";
    "ci:image:build".exec = runLeaf "ci-image-build" "finite-image-build" "";
    "ci:image:rechunk".exec = runLeaf "ci-rechunk-image" "finite-rechunk-image" "";
    "ci:image:sign".exec = runLeaf "ci-image-sign" "finite-image-sign" "";
    "ci:image:sbom".exec = runLeaf "ci-image-sbom" "finite-image-sbom" "";
    "ci:image:promote".exec = runLeaf "ci-promote-images" "finite-promote-images" "";
    "ci:installer:build".exec = runLeaf "ci-installer-build" "finite-installer-build" "";

    "automation:update-locks".exec = runLeaf "ci-update-locks" "finite-update-locks" "";
    "automation:validate-locks".exec = runLeaf "ci-lock-validate" "finite-ci-validate-locks" "";
    "automation:trusted-update".exec = runLeaf "ci-trusted-update" "finite-trusted-update" "";
    "automation:queue".exec = runLeaf "ci-queue-dependabot" "finite-queue-dependabot" "";
    "automation:cleanup".exec = runLeaf "ci-package-cleanup" "finite-package-cleanup" "";

    "release:notes".exec = runLeaf "ci-release-notes" "finite-release-notes" "";
    "release:attest-sbom".exec = runLeaf "ci-sbom-attestation" "finite-sbom-attestation" "";
  };
}
