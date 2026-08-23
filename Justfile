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

# Build a named profile into a local OCI image.
build profile tag:
    nix shell --accept-flake-config .#ci-image-build -c finite-image-build {{ profile }} {{ tag }}
