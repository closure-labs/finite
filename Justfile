default:
    @just --list

# Format all repository sources with the pinned Flake formatter.
format:
    nix fmt

# Run the complete hermetic validation graph.
check:
    nix shell --accept-flake-config .#ci-check -c finite-ci-check

# Run repository checks interactively with the pinned toolchain.
ci:
    just check

# Stage and validate a handwritten recipe without building an OS image.
validate profile:
    bash scripts/bluebuild/stage.sh {{ profile }}
    bluebuild validate recipes/{{ profile }}.yml

# Build a named recipe locally (requires substantial storage).
build profile:
    bash scripts/bluebuild/stage.sh {{ profile }}
    bluebuild build --build-driver docker --run-driver docker --registry ghcr.io --registry-namespace closure-labs recipes/{{ profile }}.yml
