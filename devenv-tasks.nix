{pkgs, ...}: let
  # Realization happens before resolving task credentials. SecretSpec scopes
  # then remove inherited manifest-declared values from the launched child.
  cleanEnvironment = "env -u CACHIX_AUTH_TOKEN -u FINITE_CACHIX_TOKEN -u COSIGN_PRIVATE_KEY -u COSIGN_PASSWORD -u GH_TOKEN -u MERGE_QUEUE_TOKEN -u REGISTRY_TOKEN -u SECAUDIT_PEM -u SECAUDIT_CLIENTID";
  scopedTools = tools: profile: command: ''
    ${cleanEnvironment} FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --accept-flake-config --file "$DEVENV_ROOT/lib/ci-tools.nix" \
        ci-secrets-run ${tools} -c finite-ci-secrets-run ${profile} -- ${command}
  '';
  scopedLeaf = package: profile: command: arguments: ''
    leaf=$(${cleanEnvironment} nix build --accept-flake-config \
      "path:$DEVENV_ROOT#${package}" --no-link --print-out-paths)
    [[ $leaf == /nix/store/* && $leaf != *$'\n'* ]]
    ${cleanEnvironment} FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --file "$DEVENV_ROOT/lib/ci-tools.nix" ci-secrets-run \
        -c finite-ci-secrets-run ${profile} -- "$leaf/bin/${command}" ${arguments}
  '';
  runLeaf = package: command: arguments: ''
    FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
      nix shell --accept-flake-config "path:$DEVENV_ROOT#${package}" \
        -c ${command} ${arguments}
  '';
in {
  packages = (with pkgs; [actionlint git jq pass python3 shellcheck zizmor]) ++ [(import ./lib/secretspec.nix {inherit pkgs;})];

  tasks = {
    "ci:check:flake" = {
      exec = runLeaf "ci-check" "finite-ci-check" "--no-write-lock-file";
      execIfModified = ["."];
    };
    "ci:check".after = ["ci:check:flake"];

    "ci:cache:options".exec = ''
      ${cleanEnvironment} FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
        nix shell --file "$DEVENV_ROOT/lib/ci-tools.nix" ci-secrets-options \
          -c finite-ci-secrets-options
    '';
    "ci:cache:benchmark".exec = ''
      # Summarize downloaded hosted measurements; do not turn local disk/cache
      # state into a purported hosted baseline or invoke a remote workflow.
      ${cleanEnvironment} python3 "$DEVENV_ROOT/scripts/ci/benchmark-ci-cache.py" summarize \
        "''${FINITE_CACHE_BENCHMARK_DIR:-$DEVENV_ROOT/.bluebuild/cache-benchmarks}" \
        "''${FINITE_CACHE_BENCHMARK_SUMMARY:-$DEVENV_ROOT/.bluebuild/cache-benchmark-summary.md}"
    '';
    "ci:cache:writer:prepare".exec = ''
      ${cleanEnvironment} ${runLeaf "ci-check" "finite-ci-check" "--no-write-lock-file"}
    '';
    "ci:cache:check".exec = ''
      ${cleanEnvironment} FINITE_SOURCE_ROOT="$DEVENV_ROOT" \
        nix run --accept-flake-config "path:$DEVENV_ROOT#local-cache" -- --no-write-lock-file
    '';
    "ci:cache:writer:push".after = ["ci:cache:check"];
    "repository:audit".exec = scopedTools "ci-repository-security-audit" "repository-read" ''
      finite-repository-security-audit --repository "''${GH_REPOSITORY:-closure-labs/finite}" --read-only-app
    '';
    "image:verify".exec = ''
      image="''${IMAGE_REFERENCE:?set IMAGE_REFERENCE to the immutable image to verify}"
      [[ $image =~ ^ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
      ${cleanEnvironment} nix shell --file "$DEVENV_ROOT/lib/ci-tools.nix" scanner-tools \
        -c cosign verify --new-bundle-format=false --key "$DEVENV_ROOT/cosign.pub" "$image"
    '';
    "image:sign".exec = ''
      image="''${IMAGE_REFERENCE:?set IMAGE_REFERENCE to the immutable image to sign}"
      [[ $image =~ ^ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}$ ]]
      # Uses existing registry login; keys are fetched only for this child.
      ${scopedTools "scanner-tools" "image-signing" ''
        cosign sign --yes --new-bundle-format=false --use-signing-config=false \
          --key env://COSIGN_PRIVATE_KEY "$image"
      ''}
    '';
    "release:sign".exec = scopedTools "scanner-tools" "release-signing" ''
      bash "$DEVENV_ROOT/scripts/bluebuild/sign-release.sh"
    '';

    "automation:update-locks".exec = runLeaf "ci-update-locks" "finite-update-locks" "";
    "automation:validate-locks".exec = runLeaf "ci-lock-validate" "finite-ci-validate-locks" "";
    "automation:fix-hashes".exec = scopedLeaf "ci-fix-nix-hashes" "updater" "finite-fix-nix-hashes" "";
    "automation:trusted-update".exec = scopedLeaf "ci-trusted-update" "updater" "finite-trusted-update" "";
    "automation:queue".exec = scopedLeaf "ci-queue-dependabot" "updater" "finite-queue-dependabot" "";
  };
}
